"""Installment plan management views.

Provides visibility and manual control over installment schedules: list plans,
drill into a plan, mark an installment paid (manual adjustment) and reschedule a
due date.
"""
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum, Count, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from core.models import AuditLog
from core.permissions import management_or_above, finance_or_above
from .models import InstallmentPlan, Installment, InstallmentReschedule, InstallmentPlanTemplate


def _log(request, action, model, object_id, description):
    AuditLog.objects.create(
        user=request.user, action=action, model_name=model,
        object_id=str(object_id), description=description,
        ip_address=request.META.get('REMOTE_ADDR'),
    )


@login_required
@finance_or_above
def installment_plans_view(request):
    plans = InstallmentPlan.objects.select_related(
        'booking', 'booking__customer', 'booking__plot', 'booking__plot__project'
    ).all()

    search = request.GET.get('search', '').strip()
    if search:
        plans = plans.filter(
            Q(booking__booking_id__icontains=search) |
            Q(booking__customer__first_name__icontains=search) |
            Q(booking__customer__last_name__icontains=search)
        )

    for plan in plans:
        plan.paid_count = plan.installments.filter(status='paid').count()
        plan.overdue_count = plan.installments.filter(status='overdue').count()

    # Available plan templates (the preset schedules shown in dropdowns)
    templates = InstallmentPlanTemplate.objects.select_related('project').all()

    context = {
        'plans': plans,
        'search': search,
        'templates': templates,
        'total_count': InstallmentPlan.objects.count(),
        'active_count': InstallmentPlan.objects.filter(is_active=True).count(),
    }
    return render(request, 'installment_plans.html', context)


@login_required
@finance_or_above
def installment_plan_detail_view(request, pk):
    plan = get_object_or_404(
        InstallmentPlan.objects.select_related(
            'booking', 'booking__customer', 'booking__plot', 'booking__plot__project', 'template'
        ),
        pk=pk,
    )
    installments = plan.installments.select_related('plan').all().order_by('installment_number')
    reschedules = plan.reschedules.all().order_by('-rescheduled_at')

    total_amount = sum((i.amount + i.late_fee for i in installments), 0)
    total_paid = sum((i.paid_amount for i in installments), 0)

    return render(request, 'installment_plan_detail.html', {
        'plan': plan,
        'installments': installments,
        'reschedules': reschedules,
        'total_amount': total_amount,
        'total_paid': total_paid,
    })


@login_required
@finance_or_above
def installment_mark_paid_view(request, pk):
    """Manually mark an installment as paid and adjust the booking advance."""
    installment = get_object_or_404(Installment.objects.select_related('plan__booking'), pk=pk)
    booking = installment.plan.booking

    if request.method == 'POST':
        with transaction.atomic():
            remaining = installment.remaining_amount
            installment.paid_amount = installment.amount + installment.late_fee
            installment.status = 'paid'
            installment.paid_date = timezone.localdate()
            installment.save()

            # Keep revenue (booking.advance_paid) consistent with the adjustment.
            new_advance = booking.advance_paid + remaining
            booking.advance_paid = min(new_advance, booking.total_amount)
            if booking.remaining_balance <= 0:
                booking.status = 'completed'
            booking.save()

            # Recalculate the plan: this installment is now settled, so the
            # remaining balance shrinks and later installments must adjust.
            if hasattr(booking, 'installment_plan') and booking.installment_plan:
                booking.installment_plan.recalculate()

        _log(request, 'update', 'Installment', pk,
             f'Marked installment {installment.installment_number} of {booking.booking_id} as paid')
        messages.success(request, f'Installment #{installment.installment_number} marked as paid.')
    return redirect('installment_plan_detail', pk=installment.plan_id)


@login_required
@finance_or_above
def installment_reschedule_view(request, pk):
    installment = get_object_or_404(Installment.objects.select_related('plan'), pk=pk)

    if request.method == 'POST':
        new_due_date = request.POST.get('new_due_date', '')
        reason = request.POST.get('reason', 'customer_request')
        valid_reasons = dict(InstallmentReschedule.REASONS)
        if reason not in valid_reasons:
            reason = 'customer_request'

        if not new_due_date:
            messages.error(request, 'A new due date is required.')
            return redirect('installment_plan_detail', pk=installment.plan_id)

        original = installment.due_date
        installment.due_date = new_due_date
        if installment.status == 'overdue':
            installment.status = 'pending'
        installment.save()

        InstallmentReschedule.objects.create(
            plan=installment.plan,
            installment=installment,
            original_due_date=original,
            new_due_date=new_due_date,
            reason=reason,
            approved_by=request.user,
        )

        _log(request, 'update', 'Installment', pk,
             f'Rescheduled installment {installment.installment_number} from {original} to {new_due_date}')
        messages.success(request, f'Installment #{installment.installment_number} rescheduled.')
    return redirect('installment_plan_detail', pk=installment.plan_id)
