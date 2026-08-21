"""Administrative settings and reporting views.

Covers Company Settings (singleton), Project Milestones, Receivables Aging and
the Sales / Commission report. These are management-facing views.
"""
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from datetime import timedelta

from .models import AuditLog, CompanySettings
from .forms import CompanySettingsForm
from .permissions import management_or_above, admin_or_above, finance_or_above
from properties.models import Project, ProjectMilestone
from properties.forms import ProjectMilestoneForm
from customers.models import Customer
from bookings.models import Booking, Installment
from payments.models import Payment
from core.models import Agent


def _log(request, action, model, object_id, description):
    AuditLog.objects.create(
        user=request.user, action=action, model_name=model,
        object_id=str(object_id), description=description,
        ip_address=request.META.get('REMOTE_ADDR'),
    )


# ─── COMPANY SETTINGS ──────────────────────────────────────────────────────────

@login_required
@admin_or_above
def company_settings_view(request):
    settings_obj = CompanySettings.load()
    if request.method == 'POST':
        form = CompanySettingsForm(request.POST, request.FILES, instance=settings_obj)
        if form.is_valid():
            form.save()
            _log(request, 'update', 'CompanySettings', 1, 'Updated company settings')
            messages.success(request, 'Company settings updated successfully!')
            return redirect('company_settings')
    else:
        form = CompanySettingsForm(instance=settings_obj)
    return render(request, 'company_settings.html', {'form': form})


# ─── PROJECT MILESTONES ────────────────────────────────────────────────────────

@login_required
def milestones_view(request):
    project_filter = request.GET.get('project', '')
    milestones = ProjectMilestone.objects.select_related('project').all()
    projects = Project.objects.exclude(status='inactive')
    if project_filter:
        milestones = milestones.filter(project_id=project_filter)

    context = {
        'milestones': milestones,
        'projects': projects,
        'project_filter': project_filter,
        'status_choices': ProjectMilestone.STATUS_CHOICES,
    }
    return render(request, 'milestones.html', context)


@login_required
@management_or_above
def milestone_create_view(request):
    if request.method == 'POST':
        form = ProjectMilestoneForm(request.POST)
        if form.is_valid():
            milestone = form.save()
            _log(request, 'create', 'ProjectMilestone', milestone.pk, f'Created milestone {milestone.title}')
            messages.success(request, 'Milestone created successfully!')
            return redirect('milestones')
    else:
        form = ProjectMilestoneForm()
    return render(request, 'milestone_form.html', {'form': form, 'title': 'Add Milestone'})


@login_required
@management_or_above
def milestone_edit_view(request, pk):
    milestone = get_object_or_404(ProjectMilestone, pk=pk)
    if request.method == 'POST':
        form = ProjectMilestoneForm(request.POST, instance=milestone)
        if form.is_valid():
            form.save()
            _log(request, 'update', 'ProjectMilestone', pk, f'Updated milestone {milestone.title}')
            messages.success(request, 'Milestone updated successfully!')
            return redirect('milestones')
    else:
        form = ProjectMilestoneForm(instance=milestone)
    return render(request, 'milestone_form.html', {'form': form, 'title': 'Edit Milestone', 'milestone': milestone})


@login_required
@management_or_above
def milestone_delete_view(request, pk):
    milestone = get_object_or_404(ProjectMilestone, pk=pk)
    if request.method == 'POST':
        title = milestone.title
        milestone.delete()
        _log(request, 'delete', 'ProjectMilestone', pk, f'Deleted milestone {title}')
        messages.success(request, 'Milestone deleted successfully!')
        return redirect('milestones')
    return render(request, 'confirm_delete.html', {'object': milestone, 'title': 'Delete Milestone', 'cancel_url': 'milestones'})


# ─── RECEIVABLES AGING ─────────────────────────────────────────────────────────

@login_required
@finance_or_above
def receivables_aging_view(request):
    today = timezone.localdate()

    buckets = {
        'current': {'label': 'Current (0-30)', 'min': 0, 'max': 30, 'customers': [], 'total': 0},
        '31_60': {'label': '31-60 Days', 'min': 31, 'max': 60, 'customers': [], 'total': 0},
        '61_90': {'label': '61-90 Days', 'min': 61, 'max': 90, 'customers': [], 'total': 0},
        '90_plus': {'label': '90+ Days', 'min': 91, 'max': None, 'customers': [], 'total': 0},
    }

    # All bookings with outstanding balances
    bookings = Booking.objects.select_related('customer', 'plot', 'plot__project').filter(
        Q(status__in=['confirmed', 'active', 'pending'])
    ).all()

    for booking in bookings:
        balance = booking.remaining_balance
        if balance <= 0:
            continue

        # Days overdue derived from the earliest overdue installment if present.
        overdue_inst = booking.installment_plan.installments.filter(
            status='overdue', due_date__lt=today
        ).order_by('due_date').first() if hasattr(booking, 'installment_plan') else None

        if overdue_inst:
            days = (today - overdue_inst.due_date).days
        else:
            days = 0

        if days <= 30:
            bucket = 'current'
        elif days <= 60:
            bucket = '31_60'
        elif days <= 90:
            bucket = '61_90'
        else:
            bucket = '90_plus'

        buckets[bucket]['customers'].append({
            'customer': booking.customer,
            'booking': booking,
            'balance': balance,
            'days': days,
        })
        buckets[bucket]['total'] += float(balance)

    total_receivables = sum((b['total'] for b in buckets.values()), 0)
    total_overdue = sum((b['total'] for k, b in buckets.items() if k != 'current'), 0)

    context = {
        'buckets': buckets,
        'total_receivables': total_receivables,
        'total_overdue': total_overdue,
    }
    return render(request, 'receivables_aging.html', context)


# ─── SALES / COMMISSION REPORT ─────────────────────────────────────────────────

@login_required
@finance_or_above
def sales_report_view(request):
    agents = Agent.objects.annotate(
        booking_count=Count('bookings'),
        total_sales=Sum('bookings__total_amount'),
    ).all()

    agent_rows = []
    for agent in agents:
        commission = (agent.total_sales or 0) * (agent.commission_rate or 0) / 100
        agent_rows.append({
            'agent': agent,
            'booking_count': agent.booking_count,
            'total_sales': agent.total_sales or 0,
            'commission': commission,
        })

    by_source = Booking.objects.values('source').annotate(
        count=Count('id'), total=Sum('total_amount')
    ).order_by('-total')
    source_labels = dict(Booking.SOURCE_CHOICES)

    context = {
        'agent_rows': agent_rows,
        'by_source': [
            {'source': source_labels.get(s['source'], s['source']), 'count': s['count'], 'total': s['total'] or 0}
            for s in by_source
        ],
        'total_sales': Booking.objects.aggregate(t=Sum('total_amount'))['t'] or 0,
    }
    return render(request, 'sales_report.html', context)
