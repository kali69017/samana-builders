"""Payment verification workflow and refund management views.

Separates the finance-team workflow (verify / reject / bounce payments, and
manage refunds) from the monolithic ``core/views.py``.
"""
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from core.models import AuditLog
from core.permissions import finance_or_above, management_or_above, admin_or_above
from .models import Payment, Refund, Receipt
from .forms import RefundForm


def _log(request, action, model, object_id, description):
    AuditLog.objects.create(
        user=request.user, action=action, model_name=model,
        object_id=str(object_id), description=description,
        ip_address=request.META.get('REMOTE_ADDR'),
    )


def _apply_payment_effects(payment):
    """Reflect a verified payment on its installment and booking."""
    booking = payment.booking

    if payment.installment:
        installment = payment.installment
        installment_total = installment.amount + installment.late_fee
        remaining_before = installment_total - installment.paid_amount
        if payment.amount > remaining_before:
            payment.unallocated_amount = payment.amount - remaining_before
            installment.paid_amount = installment_total
        else:
            installment.paid_amount += payment.amount

        if installment.paid_amount >= installment_total:
            installment.status = 'paid'
            installment.paid_date = payment.payment_date
        elif installment.paid_amount > 0:
            installment.status = 'partial'
        installment.save()

    new_advance = booking.advance_paid + payment.amount
    booking.advance_paid = min(new_advance, booking.total_amount)
    if booking.remaining_balance <= 0:
        booking.status = 'completed'
    booking.save()

    # Recalculate the installment plan so unpaid installments reflect
    # the new remaining balance.
    if hasattr(booking, 'installment_plan') and booking.installment_plan:
        booking.installment_plan.recalculate()


@login_required
@admin_or_above
def payment_verify_view(request, pk):
    payment = get_object_or_404(Payment.objects.select_related('booking', 'installment'), pk=pk)
    if payment.status in ['verified', 'rejected', 'reversed']:
        messages.error(request, f'This payment is already {payment.get_status_display()}.')
        return redirect('payment_detail', pk=pk)

    if request.method == 'POST':
        with transaction.atomic():
            payment.status = 'verified'
            payment.verified_by = request.user
            payment.verified_at = timezone.now()
            payment.save()
            _apply_payment_effects(payment)
            payment.save(update_fields=['unallocated_amount'])

            # Ensure a receipt exists
            if not payment.receipts.exists():
                Receipt.objects.create(payment=payment, receipt_date=payment.payment_date, generated_by=request.user)
                payment.receipt_generated = True
                payment.save(update_fields=['receipt_generated'])

        _log(request, 'verify', 'Payment', payment.payment_id, f'Verified payment {payment.payment_id}')
        messages.success(request, f'Payment {payment.payment_id} verified successfully!')
    return redirect('payment_detail', pk=pk)


@login_required
@admin_or_above
def payment_reject_view(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    if payment.status in ['verified', 'rejected', 'reversed']:
        messages.error(request, f'This payment is already {payment.get_status_display()}.')
        return redirect('payment_detail', pk=pk)

    if request.method == 'POST':
        payment.status = 'rejected'
        payment.verified_by = request.user
        payment.verified_at = timezone.now()
        payment.notes = request.POST.get('notes', payment.notes)
        payment.save()
        _log(request, 'reject', 'Payment', payment.payment_id, f'Rejected payment {payment.payment_id}')
        messages.success(request, f'Payment {payment.payment_id} rejected.')
    return redirect('payment_detail', pk=pk)


@login_required
@admin_or_above
def payment_bounce_view(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    if payment.status in ['verified', 'rejected', 'reversed']:
        messages.error(request, f'This payment is already {payment.get_status_display()}.')
        return redirect('payment_detail', pk=pk)

    if request.method == 'POST':
        payment.status = 'bounced'
        payment.bounce_reason = request.POST.get('bounce_reason', '')
        payment.bounce_fee = request.POST.get('bounce_fee', 0)
        payment.save()
        _log(request, 'reject', 'Payment', payment.payment_id, f'Marked payment {payment.payment_id} as bounced')
        messages.success(request, f'Payment {payment.payment_id} marked as bounced.')
    return redirect('payment_detail', pk=pk)


@login_required
@admin_or_above
def payment_reverse_view(request, pk):
    payment = get_object_or_404(Payment.objects.select_related('booking', 'installment'), pk=pk)
    if request.method == 'POST':
        if payment.status != 'verified':
            messages.error(request, f'Only verified payments can be reversed.')
            return redirect('payment_detail', pk=pk)
        with transaction.atomic():
            payment.status = 'reversed'
            payment.save()

            # Reverse effects on installment and booking
            if payment.installment:
                installment = payment.installment
                installment.paid_amount = max(installment.paid_amount - payment.amount, 0)
                if installment.paid_amount <= 0:
                    installment.status = 'pending'
                    installment.paid_date = None
                else:
                    installment.status = 'partial'
                installment.save()

            booking = payment.booking
            booking.advance_paid = max(booking.advance_paid - payment.amount, 0)
            if booking.status == 'completed' and booking.remaining_balance > 0:
                booking.status = 'active'
            booking.save()

        _log(request, 'cancel', 'Payment', payment.payment_id, f'Reversed payment {payment.payment_id}')
        messages.success(request, f'Payment {payment.payment_id} reversed.')
    return redirect('payment_detail', pk=pk)


# ─── REFUNDS ───────────────────────────────────────────────────────────────────

@login_required
@finance_or_above
def refunds_view(request):
    refunds = Refund.objects.select_related('booking', 'booking__customer', 'approved_by').all()
    status_filter = request.GET.get('status', '')
    if status_filter:
        refunds = refunds.filter(status=status_filter)

    context = {
        'refunds': refunds,
        'status_filter': status_filter,
        'status_choices': Refund.STATUS_CHOICES,
        'total_count': Refund.objects.count(),
        'pending_count': Refund.objects.filter(status='pending').count(),
        'total_amount': Refund.objects.aggregate(t=Sum('amount'))['t'] or 0,
    }
    return render(request, 'refunds.html', context)


@login_required
@finance_or_above
def refund_create_view(request):
    if request.method == 'POST':
        form = RefundForm(request.POST, request.FILES)
        if form.is_valid():
            refund = form.save()
            _log(request, 'create', 'Refund', refund.pk,
                 f'Created refund of {refund.amount} for booking {refund.booking.booking_id}')
            messages.success(request, 'Refund request created successfully!')
            return redirect('refunds')
    else:
        form = RefundForm()
    return render(request, 'refund_form.html', {'form': form, 'title': 'New Refund'})


@login_required
@admin_or_above
def refund_approve_view(request, pk):
    refund = get_object_or_404(Refund.objects.select_related('booking'), pk=pk)
    if request.method == 'POST':
        if refund.status != 'pending':
            messages.error(request, f'Refund is already {refund.get_status_display()}; cannot approve/reject again.')
            return redirect('refunds')
        action = request.POST.get('action', 'approve')
        try:
            if action == 'reject':
                refund.reject(notes=request.POST.get('notes', ''), user=request.user)
            else:
                # Approval applies the financial effect: reduce the booking's
                # advance_paid so the balance reflects the money returned.
                refund.apply_approval(user=request.user)
        except Exception as exc:
            messages.error(request, f'Unable to {action} refund: {exc}')
            return redirect('refunds')
        _log(request, 'update', 'Refund', refund.pk,
             f'{refund.get_status_display()} refund of {refund.amount} for booking {refund.booking.booking_id}')
        messages.success(request, f'Refund {refund.get_status_display()}.')
    return redirect('refunds')


@login_required
@management_or_above
def refund_process_view(request, pk):
    """Mark an approved refund as processed and post it to the ledger exactly once."""
    refund = get_object_or_404(Refund.objects.select_related('booking'), pk=pk)
    if request.method == 'POST':
        try:
            refund.process(user=request.user)
        except Exception as exc:
            messages.error(request, f'Unable to process refund: {exc}')
            return redirect('refunds')
        _log(request, 'process', 'Refund', refund.pk,
             f'Processed refund of {refund.amount} for booking {refund.booking.booking_id}')
        messages.success(request, 'Refund processed and posted to the ledger.')
    return redirect('refunds')
