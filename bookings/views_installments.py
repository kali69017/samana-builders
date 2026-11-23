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
    """Record a pending payment for an installment.

    The installment becomes paid only when that payment is verified.
    """
    installment = get_object_or_404(Installment.objects.select_related('plan__booking'), pk=pk)
    booking = installment.plan.booking

    if request.method == 'POST':
        with transaction.atomic():
            installment = Installment.objects.select_for_update().get(pk=installment.pk)
            if installment.payments.filter(
                    status__in=['pending', 'under_clearing']).exists():
                messages.error(
                    request,
                    'A payment for this installment is already pending verification.',
                )
                return redirect('installment_plan_detail', pk=installment.plan_id)
            from finance.accounting import cash_bank_head
            from payments.models import Payment
            remaining = installment.remaining_amount
            if remaining <= 0:
                messages.error(request, 'This installment has no remaining amount.')
                return redirect('installment_plan_detail', pk=installment.plan_id)
            payment = Payment.objects.create(
                booking=booking,
                installment=installment,
                received_into=cash_bank_head('cash'),
                amount=remaining,
                payment_date=timezone.localdate(),
                payment_method='cash',
                payment_type='installment',
                status='pending',
                created_by=request.user,
                notes='Installment payment recorded, pending verification',
            )

        _log(request, 'update', 'Installment', pk,
             f'Recorded pending payment {payment.payment_id} for installment '
             f'{installment.installment_number} of {booking.booking_id}')
        messages.success(
            request,
            f'Payment {payment.payment_id} recorded for installment '
            f'#{installment.installment_number} and is pending verification.',
        )
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
