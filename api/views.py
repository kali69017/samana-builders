from django.contrib.auth import authenticate
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.models import User
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from customers.models import Customer
from payments.models import Payment


def _is_customer_user(user):
    return Customer.objects.filter(user=user).exists()


def _user_payload(user):
    is_customer = _is_customer_user(user)
    role = None
    if hasattr(user, 'profile') and user.profile:
        role = user.profile.role
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'full_name': user.get_full_name() or user.username,
        'is_staff': user.is_staff,
        'is_superuser': user.is_superuser,
        'is_customer': is_customer,
        'role': role or ('customer' if is_customer else None),
    }


@ensure_csrf_cookie
@api_view(['GET'])
@permission_classes([AllowAny])
def csrf_token(request):
    """Sets the csrftoken cookie so the SPA can send X-CSRFToken on unsafe calls."""
    return Response({'detail': 'CSRF cookie set'})


@api_view(['POST'])
@permission_classes([AllowAny])
def api_login(request):
    username = request.data.get('username', '')
    password = request.data.get('password', '')
    user = authenticate(request, username=username, password=password)

    if user is None:
        # Distinguish a deactivated account from bad credentials. ``authenticate``
        # returns None for inactive users, so check explicitly.
        existing = User.objects.filter(username=username).first()
        if existing is not None and not existing.is_active:
            return Response({'detail': 'Your account has been deactivated. Contact an administrator.'},
                            status=status.HTTP_403_FORBIDDEN)
        return Response({'detail': 'Invalid username or password.'},
                        status=status.HTTP_400_BAD_REQUEST)

    auth_login(request, user)
    from core.models import AuditLog
    AuditLog.objects.create(
        user=user, action='login', model_name='User',
        description=f'{user.username} logged in',
        ip_address=request.META.get('REMOTE_ADDR'),
    )
    return Response(_user_payload(user))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_logout(request):
    from core.models import AuditLog
    AuditLog.objects.create(
        user=request.user, action='logout', model_name='User',
        description=f'{request.user.username} logged out',
        ip_address=request.META.get('REMOTE_ADDR'),
    )
    auth_logout(request)
    return Response({'detail': 'Logged out.'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def current_user(request):
    return Response(_user_payload(request.user))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def portal_dashboard(request):
    """Customer-only dashboard summary: their bookings, payments, installments."""
    customer = Customer.objects.filter(user=request.user).first()
    if customer is None:
        return Response({'detail': 'No customer profile linked to this account.'},
                        status=status.HTTP_403_FORBIDDEN)

    active_statuses = ['pending', 'confirmed', 'active']
    bookings = customer.bookings.select_related('plot', 'plot__project').all()

    active_bookings = [b for b in bookings if b.status in active_statuses]
    total_amount = sum((b.total_amount for b in active_bookings), 0)
    total_paid = sum(
        (p.amount for p in Payment.objects.filter(booking__customer=customer, status='verified')), 0
    )

    payments = (
        Payment.objects.filter(booking__customer=customer)
        .select_related('booking')
        .order_by('-payment_date', '-created_at')
    )

    booking_payload = []
    installments = []
    for b in bookings:
        plan = getattr(b, 'installment_plan', None)
        plan_installments = list(plan.installments.all().order_by('installment_number')) if plan else []
        installments.extend(plan_installments)
        booking_payload.append({
            'id': b.id,
            'booking_id': b.booking_id,
            'plot_number': b.plot.plot_number,
            'project': b.plot.project.name if b.plot.project else None,
            'total_amount': float(b.total_amount),
            'advance_paid': float(b.advance_paid),
            'remaining_balance': float(b.remaining_balance),
            'status': b.status,
            'booking_date': b.booking_date,
            'payment_progress': b.payment_progress,
        })

    installment_payload = [{
        'id': ins.id,
        'booking_id': ins.plan.booking.booking_id,
        'installment_number': ins.installment_number,
        'due_date': ins.due_date,
        'amount': float(ins.amount),
        'late_fee': float(ins.late_fee),
        'paid_amount': float(ins.paid_amount),
        'remaining_amount': float(ins.remaining_amount),
        'status': ins.status,
    } for ins in installments]

    pending_installments = [i for i in installment_payload if i['status'] == 'pending']
    overdue_installments = [i for i in installment_payload if i['status'] == 'overdue']
    next_due = min(pending_installments + overdue_installments, key=lambda i: i['due_date']) \
        if (pending_installments or overdue_installments) else None

    return Response({
        'customer': {
            'customer_id': customer.customer_id,
            'full_name': customer.full_name,
            'email': customer.email,
            'phone': customer.phone,
            'city': customer.city,
        },
        'summary': {
            'total_bookings': bookings.count(),
            'total_amount': float(total_amount),
            'total_paid': float(total_paid),
            'remaining_balance': float(total_amount - total_paid),
            'pending_installments': len(pending_installments),
            'overdue_installments': len(overdue_installments),
            'next_due': next_due,
        },
        'bookings': booking_payload,
        'payments': [
            {
                'id': p.id,
                'payment_id': p.payment_id,
                'booking_id': p.booking.booking_id,
                'amount': float(p.amount),
                'payment_date': p.payment_date,
                'payment_method': p.get_payment_method_display(),
                'status': p.status,
            }
            for p in payments
        ],
        'installments': installment_payload,
    })