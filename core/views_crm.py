"""CRM views: Leads and Agents.

Kept separate from the monolithic ``core/views.py`` for maintainability. All of
these views are role-aware and log to ``AuditLog`` like the rest of the ERP.
"""
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Q, Sum, Count
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.http import url_has_allowed_host_and_scheme

from .models import AuditLog, Lead, LeadNote, Agent
from .forms import LeadForm, LeadNoteForm, AgentForm
from .permissions import management_or_above, get_user_role
from customers.models import Customer
from bookings.models import Booking


def _log(request, action, model, object_id, description):
    AuditLog.objects.create(
        user=request.user, action=action, model_name=model,
        object_id=str(object_id), description=description,
        ip_address=request.META.get('REMOTE_ADDR'),
    )


# ─── LEADS ─────────────────────────────────────────────────────────────────────

@login_required
def leads_view(request):
    status_filter = request.GET.get('status', '')
    source_filter = request.GET.get('source', '')
    search = request.GET.get('search', '').strip()

    leads = Lead.objects.select_related('assigned_to', 'interest_project', 'converted_customer').all()

    if status_filter:
        leads = leads.filter(status=status_filter)
    if source_filter:
        leads = leads.filter(source=source_filter)
    if search:
        leads = leads.filter(
            Q(name__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search)
        )

    status_counts = {key: Lead.objects.filter(status=key).count() for key, _ in Lead.LEAD_STATUS_CHOICES}

    context = {
        'leads': leads,
        'status_filter': status_filter,
        'source_filter': source_filter,
        'search': search,
        'status_choices': Lead.LEAD_STATUS_CHOICES,
        'source_choices': Lead.LEAD_SOURCE_CHOICES,
        'status_counts': status_counts,
        'total_count': Lead.objects.count(),
    }
    return render(request, 'leads.html', context)


@login_required
def lead_create_view(request):
    if request.method == 'POST':
        form = LeadForm(request.POST)
        if form.is_valid():
            lead = form.save()
            _log(request, 'create', 'Lead', lead.pk, f'Created lead {lead.display_name}')
            messages.success(request, f'Lead created successfully!')
            return redirect('leads')
    else:
        form = LeadForm()
    return render(request, 'lead_form.html', {'form': form, 'title': 'Add New Lead'})


@login_required
def lead_detail_view(request, pk):
    lead = get_object_or_404(Lead.objects.select_related(
        'assigned_to', 'interest_project', 'converted_customer'), pk=pk)
    notes = lead.lead_notes.select_related('created_by').all()
    note_form = LeadNoteForm()
    return render(request, 'lead_detail.html', {
        'lead': lead,
        'notes': notes,
        'note_form': note_form,
    })


@login_required
def lead_edit_view(request, pk):
    lead = get_object_or_404(Lead, pk=pk)
    if request.method == 'POST':
        form = LeadForm(request.POST, instance=lead)
        if form.is_valid():
            form.save()
            _log(request, 'update', 'Lead', lead.pk, f'Updated lead {lead.display_name}')
            messages.success(request, 'Lead updated successfully!')
            return redirect('lead_detail', pk=pk)
    else:
        form = LeadForm(instance=lead)
    return render(request, 'lead_form.html', {'form': form, 'title': f'Edit Lead', 'lead': lead})


@login_required
@management_or_above
def lead_delete_view(request, pk):
    lead = get_object_or_404(Lead, pk=pk)
    if request.method == 'POST':
        name = lead.display_name
        lead.delete()
        _log(request, 'delete', 'Lead', pk, f'Deleted lead {name}')
        messages.success(request, 'Lead deleted successfully!')
        return redirect('leads')
    return render(request, 'confirm_delete.html', {'object': lead, 'title': 'Delete Lead', 'cancel_url': 'leads'})


@login_required
def lead_status_update_view(request, pk):
    """Inline status change from the leads list / detail."""
    lead = get_object_or_404(Lead, pk=pk)
    if request.method == 'POST':
        status = request.POST.get('status', '')
        valid = dict(Lead.LEAD_STATUS_CHOICES)
        if status not in valid:
            messages.error(request, 'Invalid status selected.')
        else:
            old = lead.get_status_display()
            lead.status = status
            if status == 'contacted':
                lead.is_contacted = True
            lead.save()
            _log(request, 'update', 'Lead', lead.pk,
                 f'Changed lead {lead.display_name} status from {old} to {valid[status]}')
            messages.success(request, f'Lead status updated to {valid[status]}.')
    next_url = request.POST.get('next') or ''
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = 'leads'
    return redirect(next_url)


@login_required
def lead_note_add_view(request, pk):
    lead = get_object_or_404(Lead, pk=pk)
    if request.method == 'POST':
        form = LeadNoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.lead = lead
            note.created_by = request.user
            note.save()
            messages.success(request, 'Note added.')
    return redirect('lead_detail', pk=pk)


@login_required
def lead_convert_view(request, pk):
    """Convert a lead into a Customer record (and optionally a portal login)."""
    lead = get_object_or_404(Lead, pk=pk)

    if lead.converted_customer_id:
        messages.info(request, f'This lead is already converted to {lead.converted_customer.customer_id}.')
        return redirect('customer_detail', pk=lead.converted_customer.pk)

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        phone = request.POST.get('phone', lead.phone or '').strip()
        cnic = request.POST.get('cnic', '').strip()
        email = request.POST.get('email', lead.email or '').strip()
        city = request.POST.get('city', '').strip()

        # Reuse the lead's name if no explicit first name supplied.
        if not first_name and lead.name:
            parts = lead.name.split(' ', 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else last_name

        # Guard: CNIC must be unique if provided.
        if cnic and Customer.objects.filter(cnic=cnic).exists():
            messages.error(request, 'A customer with this CNIC already exists.')
            return render(request, 'lead_convert.html', {'lead': lead})

        with transaction.atomic():
            customer = Customer.objects.create(
                first_name=first_name or lead.name or 'Lead',
                last_name=last_name,
                email=email or None,
                phone=phone,
                cnic=cnic,
                city=city,
                created_by=request.user,
            )
            lead.status = 'converted'
            lead.converted_customer = customer
            lead.save()

        from notifications.services import NotificationService
        NotificationService.send_customer_welcome(customer, user=request.user)

        _log(request, 'update', 'Lead', lead.pk,
             f'Converted lead {lead.display_name} to customer {customer.customer_id}')
        messages.success(request, f'Lead converted to customer {customer.customer_id}!')
        return redirect('customer_detail', pk=customer.pk)

    return render(request, 'lead_convert.html', {'lead': lead})


# ─── AGENTS ────────────────────────────────────────────────────────────────────

@login_required
def agents_view(request):
    agents = Agent.objects.annotate(
        booking_count=Count('bookings'),
        commission_earned=Sum('bookings__total_amount'),
    ).all()

    # Compute commission in Python to keep the aggregation simple.
    for agent in agents:
        agent.total_commission = (agent.commission_earned or 0) * (agent.commission_rate or 0) / 100

    context = {
        'agents': agents,
        'total_count': Agent.objects.count(),
        'active_count': Agent.objects.filter(is_active=True).count(),
    }
    return render(request, 'agents.html', context)


@login_required
@management_or_above
def agent_create_view(request):
    if request.method == 'POST':
        form = AgentForm(request.POST)
        if form.is_valid():
            agent = form.save()
            _log(request, 'create', 'Agent', agent.agent_id, f'Created agent {agent.name}')
            messages.success(request, f'Agent {agent.agent_id} created successfully!')
            return redirect('agents')
    else:
        form = AgentForm()
    return render(request, 'agent_form.html', {'form': form, 'title': 'Add New Agent'})


@login_required
def agent_detail_view(request, pk):
    agent = get_object_or_404(Agent, pk=pk)
    bookings = Booking.objects.filter(agent=agent).select_related('customer', 'plot', 'plot__project').all()
    total_commission = sum((b.agent_commission for b in bookings), 0)
    payments = agent.commission_payments.all()
    return render(request, 'agent_detail.html', {
        'agent': agent,
        'bookings': bookings,
        'total_commission': total_commission,
        'payments': payments,
    })


@login_required
@management_or_above
def agent_commission_payment_view(request, pk):
    """Record a commission payment made to an agent."""
    agent = get_object_or_404(Agent, pk=pk)
    from .forms import AgentCommissionPaymentForm
    if request.method == 'POST':
        form = AgentCommissionPaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.agent = agent
            payment.paid_by = request.user
            payment.save()
            _log(request, 'create', 'AgentCommissionPayment', payment.pk,
                 f'Recorded Rs. {payment.amount} commission payment to {agent.name}')
            messages.success(request, f'Commission payment of Rs. {payment.amount} recorded for {agent.name}.')
            return redirect('agent_detail', pk=agent.pk)
    else:
        from django.utils import timezone
        form = AgentCommissionPaymentForm(initial={'payment_date': timezone.localdate()})
    return render(request, 'agent_commission_form.html', {
        'form': form, 'agent': agent, 'title': f'Record Commission Payment — {agent.name}',
    })


@login_required
@management_or_above
def agent_edit_view(request, pk):
    agent = get_object_or_404(Agent, pk=pk)
    if request.method == 'POST':
        form = AgentForm(request.POST, instance=agent)
        if form.is_valid():
            form.save()
            _log(request, 'update', 'Agent', agent.agent_id, f'Updated agent {agent.name}')
            messages.success(request, 'Agent updated successfully!')
            return redirect('agents')
    else:
        form = AgentForm(instance=agent)
    return render(request, 'agent_form.html', {'form': form, 'title': f'Edit Agent', 'agent': agent})


@login_required
@management_or_above
def agent_delete_view(request, pk):
    agent = get_object_or_404(Agent, pk=pk)
    if request.method == 'POST':
        name = agent.name
        agent.delete()
        _log(request, 'delete', 'Agent', pk, f'Deleted agent {name}')
        messages.success(request, 'Agent deleted successfully!')
        return redirect('agents')
    return render(request, 'confirm_delete.html', {'object': agent, 'title': 'Delete Agent', 'cancel_url': 'agents'})
