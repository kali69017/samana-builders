from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.contrib import messages
import re
from django.db.models import Sum, Count, Q
from django.db import transaction
from django.db.models.functions import TruncMonth, TruncWeek, TruncYear
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from .models import UserProfile, AuditLog
from .forms import UserForm, UserProfileForm, CreateUserForm, UserEditForm, RestoreBackupForm
from .permissions import (
    role_required, super_admin_required, admin_or_above,
    management_or_above, finance_or_above, payments_access, get_user_role,
)
from customers.models import Customer, CustomerNominee
from properties.models import Project, Plot
from bookings.models import Booking, Installment
from payments.models import Payment
from expenses.models import Expense


def _post_login_target(user):
    """Employees go straight to their Leave portal; customers (non-staff) go
    to the React customer portal; staff go to the ERP dashboard."""
    if getattr(user, 'employee', None):
        return 'hr_my_leave'
    if user.is_staff or hasattr(user, 'profile'):
        return 'dashboard'
    if Customer.objects.filter(user=user).exists():
        return '/portal'
    return 'dashboard'


def login_view(request):
    if request.user.is_authenticated:
        return redirect(_post_login_target(request.user))
    
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        username = request.POST.get('username', '')
        ip = request.META.get('REMOTE_ADDR')

        # Brute-force guard: 5 failed attempts per 15 minutes locks the account.
        from api.views import _login_locked_out, _record_login_attempt
        if _login_locked_out(username, ip):
            _record_login_attempt(username, ip, False)
            messages.error(request, 'Too many failed attempts. Try again after 15 minutes.')
            return render(request, 'login.html', {'form': form})

        if form.is_valid():
            user = form.get_user()
            
            # Deactivated users cannot log in
            if not user.is_active:
                messages.error(request, 'Your account has been deactivated. Contact an administrator.')
                return render(request, 'login.html', {'form': form})
            
            _record_login_attempt(username, ip, True)
            login(request, user)
            AuditLog.objects.create(
                user=user, action='login', model_name='User',
                description=f'{user.username} logged in',
                ip_address=request.META.get('REMOTE_ADDR')
            )
            messages.success(request, f'Welcome back, {user.get_full_name() or user.username}!')
            return redirect(_post_login_target(user))
        else:
            _record_login_attempt(username, ip, False)
            messages.error(request, 'Invalid username or password.')
    else:
        form = AuthenticationForm()
    
    return render(request, 'login.html', {'form': form})


def logout_view(request):
    if request.user.is_authenticated:
        AuditLog.objects.create(
            user=request.user, action='logout', model_name='User',
            description=f'{request.user.username} logged out',
            ip_address=request.META.get('REMOTE_ADDR')
        )
    logout(request)
    return redirect('login')


def password_reset_request_view(request):
    """Step 1: accept an email, generate a 6-digit code, email it, and store
    the pending user id in the session for step 2 verification."""
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        user = User.objects.filter(email__iexact=email).first()
        if user and user.is_active:
            from .models import PasswordResetCode
            PasswordResetCode.objects.filter(user=user, used=False).update(used=True, used_at=timezone.now())

            code = '{:06d}'.format(__import__('random').SystemRandom().randrange(0, 1000000))
            expiry = timezone.now() + timedelta(minutes=15)
            PasswordResetCode.objects.create(user=user, code=code, expires_at=expiry)

            from notifications.services import EmailService
            EmailService.send(
                to_email=user.email,
                subject='Your Samana ERP Password Reset Code',
                message=(
                    'Hi ' + (user.get_full_name() or user.username) + ',\n\n'
                    'Your password reset verification code is:\n\n'
                    '      ' + code + '\n\n'
                    'This code is valid for 15 minutes. If you did not request a '
                    'password reset, you can safely ignore this email.\n\n'
                    'Regards,\nSamana Builders & Developers'
                ),
            )

            request.session['reset_user_id'] = user.pk
            request.session['reset_email'] = user.email
        messages.success(request, 'If an account exists for that email, a password reset code has been sent. Please check your inbox.')
        return redirect('password_reset_verify')

    return render(request, 'password_reset_request.html')


def password_reset_verify_view(request):
    """Step 2: verify the emailed code and set a new password."""
    reset_user_id = request.session.get('reset_user_id')
    user = User.objects.filter(pk=reset_user_id).first() if reset_user_id else None

    if request.method == 'POST':
        if user is None:
            messages.error(request, 'Your reset session has expired. Please start again.')
            return redirect('password_reset_request')

        code = request.POST.get('code', '').strip()
        new_password = request.POST.get('new_password', '')
        confirm = request.POST.get('confirm_password', '')

        if new_password != confirm:
            messages.error(request, 'Passwords do not match.')
        elif len(new_password) < 6:
            messages.error(request, 'Password must be at least 6 characters.')
        else:
            from .models import PasswordResetCode
            reset = PasswordResetCode.objects.filter(
                user=user, code=code, used=False
            ).order_by('-created_at').first()
            if reset and not reset.is_expired:
                reset.used = True
                reset.used_at = timezone.now()
                reset.save()
                user.set_password(new_password)
                user.save()
                AuditLog.objects.create(
                    user=user, action='update', model_name='User',
                    description=f'Password reset for {user.username} via email code',
                    ip_address=request.META.get('REMOTE_ADDR'),
                )
                request.session.pop('reset_user_id', None)
                request.session.pop('reset_email', None)
                messages.success(request, 'Your password has been reset successfully. Please log in.')
                return redirect('login')
            else:
                messages.error(request, 'Invalid or expired verification code.')

    context = {'user': user}
    return render(request, 'password_reset_verify.html', context)


@login_required
def dashboard_view(request):
    # Employees use their own self-service Leave portal — never show them
    # the admin dashboard or its menus.
    if getattr(request.user, 'employee', None):
        return redirect('hr_my_leave')

    today = timezone.now().date()
    month_start = today.replace(day=1)
    
    verified_payments_qs = Payment.objects.filter(status='verified')
    
    # Revenue = total advance_paid across all bookings (single source of truth)
    # This captures both recorded payments AND any historical advances
    total_revenue = Booking.objects.aggregate(total=Sum('advance_paid'))['total'] or 0
    
    # Monthly revenue = advance_paid from bookings made this month + verified payments this month not yet in advance_paid
    monthly_advance = Booking.objects.filter(
        booking_date__gte=month_start
    ).aggregate(total=Sum('advance_paid'))['total'] or 0
    monthly_revenue = monthly_advance
    
    # Monthly revenue trend (last 12 months) — use advance_paid by booking month
    twelve_months_ago = today - timedelta(days=365)
    
    monthly_revenue_data_raw = (
        Booking.objects.filter(booking_date__gte=twelve_months_ago)
        .annotate(month=TruncMonth('booking_date'))
        .values('month')
        .annotate(total=Sum('advance_paid'))
        .order_by('month')
    )
    
    monthly_revenue_data = [
        {'label': entry['month'].strftime('%b %Y'), 'amount': float(entry['total'])}
        for entry in monthly_revenue_data_raw
    ]
    
    max_amount = max([item['amount'] for item in monthly_revenue_data]) if monthly_revenue_data else 1
    for item in monthly_revenue_data:
        item['pct'] = round((item['amount'] / max_amount) * 100, 1)
    
    # Revenue by payment type
    type_data = (
        verified_payments_qs.values('payment_type')
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )
    type_labels = dict(Payment.PAYMENT_TYPE_CHOICES)
    payment_type_data = [
        {'type': type_labels.get(t['payment_type'], t['payment_type']), 'total': float(t['total'])}
        for t in type_data
    ]

    # Collection rate trend (last 12 months)
    collection_trend = []
    for i in range(11, -1, -1):
        target_date = today - timedelta(days=30 * i)
        m_start = target_date.replace(day=1)
        if m_start.month == 12:
            m_end = m_start.replace(year=m_start.year + 1, month=1, day=1)
        else:
            m_end = m_start.replace(month=m_start.month + 1, day=1)

        month_total = Installment.objects.filter(
            due_date__gte=m_start, due_date__lt=m_end
        ).aggregate(total=Sum('amount'))['total'] or 0

        month_paid = Installment.objects.filter(
            due_date__gte=m_start, due_date__lt=m_end
        ).aggregate(total=Sum('paid_amount'))['total'] or 0

        rate = round((month_paid / month_total) * 100, 1) if month_total > 0 else 0
        if rate > 100:
            rate = 100

        collection_trend.append({
            'label': m_start.strftime('%b %Y'),
            'rate': rate
        })

    # Project-wise revenue
    project_revenue = (
        verified_payments_qs
        .values('booking__plot__project__name')
        .annotate(revenue=Sum('amount'), count=Count('id'))
        .order_by('-revenue')
    )
    project_revenue_data = [
        {
            'project': p['booking__plot__project__name'] or 'Unknown',
            'revenue': float(p['revenue']),
            'count': p['count']
        }
        for p in project_revenue
    ]
    
    # Top defaulters (customers with overdue installments)
    overdue_installments_qs = Installment.objects.filter(
        status='overdue'
    ).select_related('plan__booking__customer')
    
    defaulter_map = {}
    for inst in overdue_installments_qs:
        customer = inst.plan.booking.customer
        if customer.pk not in defaulter_map:
            defaulter_map[customer.pk] = {
                'name': customer.full_name,
                'customer_id': customer.customer_id,
                'overdue_count': 0,
                'overdue_amount': 0,
            }
        defaulter_map[customer.pk]['overdue_count'] += 1
        defaulter_map[customer.pk]['overdue_amount'] += float(inst.amount + inst.late_fee - inst.paid_amount)
    
    top_defaulters_data = sorted(
        defaulter_map.values(),
        key=lambda x: x['overdue_amount'],
        reverse=True
    )[:10]

    # Booking stats
    pending_bookings = Booking.objects.filter(status='pending').count()
    active_bookings = Booking.objects.filter(status='active').count()
    confirmed_bookings = Booking.objects.filter(status='confirmed').count()
    completed_bookings = Booking.objects.filter(status='completed').count()
    cancelled_bookings = Booking.objects.filter(status='cancelled').count()
    
    # Payment stats
    pending_payments = Payment.objects.filter(status='pending').count()
    verified_payments = verified_payments_qs.count()
    
    # Property stats
    available_plots = Plot.objects.filter(status='available').count()
    booked_plots = Plot.objects.filter(status='booked').count()
    sold_plots = Plot.objects.filter(status='sold').count()
    
    plot_status_data = [
        {'label': 'Available', 'count': available_plots, 'color': '#0ca30c'},
        {'label': 'Booked', 'count': booked_plots, 'color': '#2a78d6'},
        {'label': 'Sold', 'count': sold_plots, 'color': '#fab219'},
    ]
    
    # Installment stats
    overdue_installments = Installment.objects.filter(status='overdue').count()
    paid_installments = Installment.objects.filter(status='paid').count()
    pending_installments = Installment.objects.filter(status='pending').count()
    partial_installments = Installment.objects.filter(status='partial').count()
    
    installment_status_data = [
        {'label': 'Paid', 'count': paid_installments, 'color': '#0ca30c'},
        {'label': 'Overdue', 'count': overdue_installments, 'color': '#d03b3b'},
        {'label': 'Pending', 'count': pending_installments, 'color': '#fab219'},
        {'label': 'Partial', 'count': partial_installments, 'color': '#2a78d6'},
    ]
    
    # Collection rate
    total_installment_amount = Installment.objects.aggregate(total=Sum('amount'))['total'] or 1
    total_paid_amount = Installment.objects.aggregate(total=Sum('paid_amount'))['total'] or 0
    collection_rate = round((total_paid_amount / total_installment_amount) * 100, 1)
    if collection_rate > 100:
        collection_rate = 100
    
    # Payment method breakdown
    method_data = (
        verified_payments_qs.values('payment_method')
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )
    method_labels = dict(Payment.METHOD_CHOICES)
    payment_method_data = [
        {'method': method_labels.get(m['payment_method'], m['payment_method']), 'total': float(m['total'])}
        for m in method_data
    ]
    
    # Plots by project
    plots_by_project = (
        Plot.objects.values('project__name')
        .annotate(count=Count('id'))
        .order_by('-count')
    )
    plots_by_project_data = [
        {'project': p['project__name'], 'count': p['count']}
        for p in plots_by_project
    ]
    
    # Booking status for doughnut
    booking_status_data = [
        {'label': 'Completed', 'count': completed_bookings, 'color': '#0ca30c'},
        {'label': 'Active', 'count': active_bookings, 'color': '#2a78d6'},
        {'label': 'Confirmed', 'count': confirmed_bookings, 'color': '#7a5af8'},
        {'label': 'Pending', 'count': pending_bookings, 'color': '#fab219'},
        {'label': 'Cancelled', 'count': cancelled_bookings, 'color': '#d03b3b'},
    ]
    
    # Booking sources
    source_data = (
        Booking.objects.values('source')
        .annotate(count=Count('id'))
        .order_by('-count')
    )
    source_labels = dict(Booking.SOURCE_CHOICES)
    booking_source_data = [
        {'source': source_labels.get(s['source'], s['source']), 'count': s['count']}
        for s in source_data
    ]
    
    # Payment status breakdown (ERP verification workflow)
    payment_status_qs = (
        Payment.objects.values('status')
        .annotate(count=Count('id'))
        .order_by('-count')
    )
    payment_status_labels = dict(Payment.STATUS_CHOICES)
    payment_status_data = [
        {'status': payment_status_labels.get(p['status'], p['status']), 'count': p['count']}
        for p in payment_status_qs
    ]
    
    # Monthly target (20% above average monthly revenue)
    months_with_data = len(monthly_revenue_data) or 1
    monthly_target = round((float(total_revenue) / max(months_with_data, 1)) * 1.2, -4)
    target_remaining = max(monthly_target - float(monthly_revenue), 0)
    
    # Staff vs admin dashboard
    user_role = None
    if hasattr(request.user, 'profile'):
        user_role = request.user.profile.role
    
    context = {
        # Customers
        'total_customers': Customer.objects.count(),
        'active_customers': Customer.objects.filter(is_active=True).count(),
        
        # Projects / Properties
        'total_projects': Project.objects.exclude(status='inactive').count(),
        'total_plots': Plot.objects.count(),
        'available_plots': available_plots,
        'booked_plots': booked_plots,
        'sold_plots': sold_plots,
        'plots_sold': sold_plots,
        
        # Bookings
        'total_bookings': Booking.objects.count(),
        'pending_bookings': pending_bookings,
        'active_bookings': active_bookings,
        'confirmed_bookings': confirmed_bookings,
        'completed_bookings': completed_bookings,
        'cancelled_bookings': cancelled_bookings,
        
        # Payments
        'total_payments': Payment.objects.count(),
        'pending_payments': pending_payments,
        'verified_payments': verified_payments,
        'total_revenue': total_revenue,
        'monthly_revenue': monthly_revenue,
        'monthly_target': monthly_target,
        'target_remaining': target_remaining,
        
        # Installments
        'overdue_installments': overdue_installments,
        'paid_installments': paid_installments,
        'collection_rate': collection_rate,
        
        # Chart data
        'monthly_revenue_data': monthly_revenue_data,
        'booking_status_data': booking_status_data,
        'payment_method_data': payment_method_data,
        'payment_type_data': payment_type_data,
        'collection_trend': collection_trend,
        'plots_by_project_data': plots_by_project_data,
        'installment_status_data': installment_status_data,
        'plot_status_data': plot_status_data,
        'booking_source_data': booking_source_data,
        'payment_status_data': payment_status_data,
        'project_revenue_data': project_revenue_data,
        'top_defaulters_data': top_defaulters_data,
        
        # Recent records
        'recent_bookings': Booking.objects.select_related('customer', 'plot').order_by('-created_at')[:5],
        'recent_payments': Payment.objects.select_related('booking', 'booking__customer').order_by('-created_at')[:5],
        
        # User role for template
        'user_role': user_role,
    }
    return render(request, 'dashboard.html', context)


@login_required
@finance_or_above
def revenue_trend_view(request):
    """JSON endpoint for the revenue trend chart (week / month / year)."""
    period = request.GET.get('period', 'month')
    today = timezone.now().date()

    qs = Payment.objects.filter(status='verified')

    labels = []
    amounts = []

    if period == 'week':
        start = today - timedelta(days=49)
        data = (
            qs.filter(payment_date__gte=start)
            .annotate(bucket=TruncWeek('payment_date'))
            .values('bucket')
            .annotate(total=Sum('amount'))
            .order_by('bucket')
        )
        for entry in data:
            labels.append(entry['bucket'].strftime('%d %b'))
            amounts.append(float(entry['total']))
    elif period == 'year':
        data = (
            qs.annotate(bucket=TruncYear('payment_date'))
            .values('bucket')
            .annotate(total=Sum('amount'))
            .order_by('bucket')
        )
        for entry in data:
            labels.append(entry['bucket'].strftime('%Y'))
            amounts.append(float(entry['total']))
    else:
        start = today - timedelta(days=180)
        data = (
            qs.filter(payment_date__gte=start)
            .annotate(bucket=TruncMonth('payment_date'))
            .values('bucket')
            .annotate(total=Sum('amount'))
            .order_by('bucket')
        )
        for entry in data:
            labels.append(entry['bucket'].strftime('%b %Y'))
            amounts.append(float(entry['total']))

    return JsonResponse({'labels': labels, 'amounts': amounts})


@login_required
@finance_or_above
def financial_reports_view(request):
    """Project-wise revenue and financial reports."""
    from payments.models import Receipt
    from django.db.models.functions import TruncMonth
    
    today = timezone.now().date()
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)
    
    # Project-wise revenue
    projects = Project.objects.exclude(status='inactive')
    project_revenue = []
    for project in projects:
        verified_payments = Payment.objects.filter(
            status='verified',
            booking__plot__project=project
        )
        total_revenue = verified_payments.aggregate(total=Sum('amount'))['total'] or 0
        year_revenue = verified_payments.filter(payment_date__gte=year_start).aggregate(total=Sum('amount'))['total'] or 0
        month_revenue = verified_payments.filter(payment_date__gte=month_start).aggregate(total=Sum('amount'))['total'] or 0
        total_bookings = Booking.objects.filter(plot__project=project).count()
        active_bookings = Booking.objects.filter(plot__project=project, status__in=['active', 'confirmed', 'pending']).count()
        total_plots = project.plots.count()
        sold_plots = project.plots.filter(status='sold').count()
        
        expenses = Expense.objects.filter(project=project).aggregate(total=Sum('amount'))['total'] or 0
        profit = float(total_revenue) - float(expenses)
        
        project_revenue.append({
            'project': project,
            'total_revenue': total_revenue,
            'year_revenue': year_revenue,
            'month_revenue': month_revenue,
            'total_bookings': total_bookings,
            'active_bookings': active_bookings,
            'total_plots': total_plots,
            'sold_plots': sold_plots,
            'expenses': expenses,
            'profit': profit,
        })
    
    # Overall stats
    total_revenue = Payment.objects.filter(status='verified').aggregate(total=Sum('amount'))['total'] or 0
    total_expenses = Expense.objects.aggregate(total=Sum('amount'))['total'] or 0
    year_revenue = Payment.objects.filter(status='verified', payment_date__gte=year_start).aggregate(total=Sum('amount'))['total'] or 0
    month_revenue = Payment.objects.filter(status='verified', payment_date__gte=month_start).aggregate(total=Sum('amount'))['total'] or 0
    
    # Monthly revenue trend for chart
    six_months_ago = today - timedelta(days=180)
    monthly_data = (
        Payment.objects.filter(status='verified', payment_date__gte=six_months_ago)
        .annotate(month=TruncMonth('payment_date'))
        .values('month')
        .annotate(total=Sum('amount'))
        .order_by('month')
    )
    monthly_chart_data = [{'label': entry['month'].strftime('%b %Y'), 'amount': float(entry['total'])} for entry in monthly_data]
    
    # Payment method breakdown
    method_data = (
        Payment.objects.filter(status='verified')
        .values('payment_method')
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )
    method_labels = dict(Payment.METHOD_CHOICES)
    payment_method_data = [{'method': method_labels.get(m['payment_method'], m['payment_method']), 'total': float(m['total'])} for m in method_data]
    
    # Collection rate
    total_installment_amount = Installment.objects.aggregate(total=Sum('amount'))['total'] or 1
    total_paid_amount = Installment.objects.aggregate(total=Sum('paid_amount'))['total'] or 0
    collection_rate = round((float(total_paid_amount) / float(total_installment_amount)) * 100, 1)
    
    context = {
        'project_revenue': project_revenue,
        'total_revenue': total_revenue,
        'total_expenses': total_expenses,
        'year_revenue': year_revenue,
        'month_revenue': month_revenue,
        'net_profit': float(total_revenue) - float(total_expenses),
        'monthly_chart_data': monthly_chart_data,
        'payment_method_data': payment_method_data,
        'collection_rate': min(collection_rate, 100),
    }
    return render(request, 'financial_reports.html', context)


# ─── CUSTOMERS ───────────────────────────────────────────────────────────────────

@login_required
def customers_view(request):
    search = request.GET.get('search', '')
    customers = Customer.objects.all()
    
    if search:
        customers = customers.filter(
            Q(customer_id__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(phone__icontains=search) |
            Q(cnic__icontains=search)
        )
    
    context = {
        'customers': customers,
        'search': search,
        'total_count': Customer.objects.count(),
        'active_count': Customer.objects.filter(is_active=True).count(),
        'customers_with_bookings': Customer.objects.filter(bookings__isnull=False).distinct().count(),
    }
    return render(request, 'customers.html', context)


@login_required
def customer_create_view(request):
    from customers.forms import CustomerForm, CustomerNomineeForm
    
    if request.method == 'POST':
        form = CustomerForm(request.POST, request.FILES)
        nominee_form = CustomerNomineeForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                customer = form.save(commit=False)
                customer.created_by = request.user
                customer.save()
                if nominee_form.is_valid() and nominee_form.cleaned_data.get('nominee_name'):
                    nominee = nominee_form.save(commit=False)
                    nominee.customer = customer
                    nominee.save()
            AuditLog.objects.create(
                user=request.user, action='create', model_name='Customer',
                object_id=customer.customer_id,
                description=f'Created customer {customer.full_name}'
            )
            messages.success(request, f'Customer {customer.customer_id} created successfully!')
            return redirect('customers')
    else:
        form = CustomerForm()
        nominee_form = CustomerNomineeForm()
    
    return render(request, 'customer_form.html', {
        'form': form,
        'nominee_form': nominee_form,
        'title': 'Add New Customer',
    })


@login_required
@admin_or_above
def customer_profile_create_view(request):
    """Create a customer portal login linked to an existing Customer."""
    from customers.forms import CustomerProfileForm

    if request.method == 'POST':
        form = CustomerProfileForm(request.POST)
        if form.is_valid():
            user = form.save()
            customer = form.cleaned_data['customer']
            AuditLog.objects.create(
                user=request.user, action='create', model_name='CustomerProfile',
                object_id=customer.customer_id,
                description=f'Created customer profile for {customer.customer_id} ({user.username})'
            )
            messages.success(request, f'Portal login created for {customer.full_name} (username: {user.username}).')
            return redirect('customers')
    else:
        form = CustomerProfileForm()

    return render(request, 'customer_profile_form.html', {
        'form': form,
        'title': 'Create Customer Profile',
    })


@login_required
def customer_edit_view(request, pk):
    from customers.forms import CustomerForm, CustomerNomineeForm
    
    customer = get_object_or_404(Customer, pk=pk)
    nominee_instance = getattr(customer, 'nominee', None)
    if request.method == 'POST':
        form = CustomerForm(request.POST, request.FILES, instance=customer)
        nominee_form = CustomerNomineeForm(request.POST, instance=nominee_instance)
        if form.is_valid():
            with transaction.atomic():
                form.save()
                if nominee_form.is_valid() and nominee_form.cleaned_data.get('nominee_name'):
                    nominee = nominee_form.save(commit=False)
                    nominee.customer = customer
                    nominee.save()
                elif nominee_instance and not nominee_form.cleaned_data.get('nominee_name'):
                    nominee_instance.delete()
            AuditLog.objects.create(
                user=request.user, action='update', model_name='Customer',
                object_id=customer.customer_id,
                description=f'Updated customer {customer.full_name}'
            )
            messages.success(request, f'Customer {customer.customer_id} updated successfully!')
            return redirect('customers')
    else:
        form = CustomerForm(instance=customer)
        # Pre-fill CNIC as plain digits (input field only accepts digits now)
        if form.initial.get('cnic'):
            form.initial['cnic'] = re.sub(r'\D', '', str(form.initial['cnic']))
        nominee_form = CustomerNomineeForm(instance=nominee_instance)
    
    return render(request, 'customer_form.html', {
        'form': form,
        'nominee_form': nominee_form,
        'title': f'Edit Customer {customer.customer_id}',
        'customer': customer,
    })


@login_required
@management_or_above
def customer_delete_view(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    # Data protection: a customer with bookings or ledger history cannot be
    # deleted (matches the API guard). Deactivate instead.
    if customer.bookings.exists() or customer.ledger_entries.exists():
        messages.error(
            request,
            'Cannot delete a customer with bookings or ledger history. Deactivate them instead.'
        )
        return redirect('customer_detail', pk=customer.pk)
    if request.method == 'POST':
        customer_id = customer.customer_id
        customer.delete()
        AuditLog.objects.create(
            user=request.user, action='delete', model_name='Customer',
            object_id=customer_id,
            description=f'Deleted customer {customer_id}'
        )
        messages.success(request, f'Customer {customer_id} deleted successfully!')
        return redirect('customers')
    
    return render(request, 'confirm_delete.html', {'object': customer, 'title': 'Delete Customer', 'cancel_url': 'customers'})


@login_required
def customer_detail_view(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    bookings = customer.bookings.select_related('plot', 'plot__project').all()
    payments = (
        Payment.objects.filter(booking__customer=customer)
        .select_related('booking', 'booking__plot')
        .order_by('-payment_date', '-created_at')
    )
    nominee = getattr(customer, 'nominee', None)
    context = {
        'customer': customer,
        'bookings': bookings,
        'payments': payments,
        'latest_payment': payments.first(),
        'nominee': nominee,
    }
    return render(request, 'customer_detail.html', context)


# ─── PROPERTIES / PROJECTS / PLOTS ───────────────────────────────────────────────

@login_required
def properties_view(request):
    projects = Project.objects.all()
    plots = Plot.objects.select_related('project').all()
    
    project_filter = request.GET.get('project', '')
    status_filter = request.GET.get('status', '')
    
    if project_filter:
        plots = plots.filter(project_id=project_filter)
        projects = projects.filter(pk=project_filter)
    if status_filter:
        plots = plots.filter(status=status_filter)
    
    context = {
        'projects': projects,
        'plots': plots,
        'project_filter': project_filter,
        'status_filter': status_filter,
        'available_plots_count': plots.filter(status='available').count(),
    }
    return render(request, 'properties.html', context)


@login_required
def project_create_view(request):
    from properties.forms import ProjectForm
    
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save()
            AuditLog.objects.create(
                user=request.user, action='create', model_name='Project',
                object_id=str(project.id),
                description=f'Created project {project.name}'
            )
            messages.success(request, f'Project "{project.name}" created successfully!')
            return redirect('properties')
    else:
        form = ProjectForm()
    
    return render(request, 'project_form.html', {'form': form, 'title': 'Add New Project'})


@login_required
def project_edit_view(request, pk):
    from properties.forms import ProjectForm
    
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            form.save()
            AuditLog.objects.create(
                user=request.user, action='update', model_name='Project',
                object_id=str(project.id),
                description=f'Updated project {project.name}'
            )
            messages.success(request, f'Project "{project.name}" updated successfully!')
            return redirect('properties')
    else:
        form = ProjectForm(instance=project)
    
    return render(request, 'project_form.html', {'form': form, 'title': f'Edit Project', 'project': project})


@login_required
@management_or_above
def project_delete_view(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        project_name = project.name
        project.delete()
        AuditLog.objects.create(
            user=request.user, action='delete', model_name='Project',
            object_id=str(pk),
            description=f'Deleted project {project_name}'
        )
        messages.success(request, f'Project "{project_name}" deleted successfully!')
        return redirect('properties')
    
    return render(request, 'confirm_delete.html', {'object': project, 'title': 'Delete Project', 'cancel_url': 'properties'})


@login_required
def plot_create_view(request):
    from properties.forms import PlotForm
    
    if request.method == 'POST':
        form = PlotForm(request.POST)
        if form.is_valid():
            plot = form.save()
            AuditLog.objects.create(
                user=request.user, action='create', model_name='Plot',
                object_id=str(plot.id),
                description=f'Created plot {plot.plot_number} in {plot.project.name}'
            )
            messages.success(request, f'Plot {plot.plot_number} created successfully!')
            return redirect('properties')
    else:
        form = PlotForm()
    
    return render(request, 'plot_form.html', {'form': form, 'title': 'Add New Plot'})


@login_required
def plot_edit_view(request, pk):
    from properties.forms import PlotForm
    
    plot = get_object_or_404(Plot, pk=pk)
    if request.method == 'POST':
        form = PlotForm(request.POST, instance=plot)
        if form.is_valid():
            form.save()
            AuditLog.objects.create(
                user=request.user, action='update', model_name='Plot',
                object_id=str(plot.id),
                description=f'Updated plot {plot.plot_number}'
            )
            messages.success(request, f'Plot {plot.plot_number} updated successfully!')
            return redirect('properties')
    else:
        form = PlotForm(instance=plot)
    
    return render(request, 'plot_form.html', {'form': form, 'title': f'Edit Plot', 'plot': plot})


@login_required
@management_or_above
def plot_delete_view(request, pk):
    plot = get_object_or_404(Plot, pk=pk)
    # Data protection: a plot with bookings or reservations cannot be deleted
    # (deleting it would cascade away payment history).
    if plot.bookings.exists() or plot.reservations.exists():
        messages.error(
            request,
            'Cannot delete a plot that has bookings or reservations. Mark it inactive instead.'
        )
        return redirect('properties')
    if request.method == 'POST':
        plot_info = f'{plot.plot_number} ({plot.project.name})'
        plot.delete()
        AuditLog.objects.create(
            user=request.user, action='delete', model_name='Plot',
            object_id=str(pk),
            description=f'Deleted plot {plot_info}'
        )
        messages.success(request, f'Plot deleted successfully!')
        return redirect('properties')
    
    return render(request, 'confirm_delete.html', {'object': plot, 'title': 'Delete Plot', 'cancel_url': 'properties'})

@login_required
def plot_detail_view(request, pk):
    plot = get_object_or_404(
        Plot.objects.select_related('project', 'phase'),
        pk=pk,
    )
    price_history = plot.price_history.select_related('changed_by').all()
    booking = plot.bookings.select_related('customer').order_by('-id').first()
    return render(request, 'plot_detail.html', {
        'plot': plot,
        'bookings': plot.bookings.select_related('customer').all(),
        'reservations': plot.reservations.select_related('customer').all(),
        'documents': plot.documents.all(),
        'price_history': price_history,
        'current_booking': booking,
    })

# ─── BOOKINGS ────────────────────────────────────────────────────────────────────

@login_required
def bookings_view(request):
    bookings = Booking.objects.select_related('customer', 'plot', 'plot__project').all()
    status_filter = request.GET.get('status', '')
    search = request.GET.get('search', '').strip()
    
    if status_filter:
        bookings = bookings.filter(status=status_filter)
    if search:
        bookings = bookings.filter(
            Q(booking_id__icontains=search) |
            Q(customer__first_name__icontains=search) |
            Q(customer__last_name__icontains=search) |
            Q(plot__plot_number__icontains=search)
        )
    
    context = {
        'bookings': bookings,
        'status_filter': status_filter,
        'search': search,
        'confirmed_count': bookings.filter(status='confirmed').count(),
        'pending_count': bookings.filter(status='pending').count(),
        'total_amount': bookings.aggregate(total=Sum('total_amount'))['total'] or 0,
    }
    return render(request, 'bookings.html', context)


@login_required
def booking_create_view(request):
    from bookings.forms import BookingForm
    from bookings.models import InstallmentPlanTemplate
    
    customer_id = request.GET.get('customer_id')
    plot_id = request.GET.get('plot_id')
    initial = {}
    if customer_id:
        initial['customer'] = customer_id
    if plot_id:
        initial['plot'] = plot_id
    
    if request.method == 'POST':
        form = BookingForm(request.POST)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.created_by = request.user
            booking.save()
            
            # Update plot status
            plot = booking.plot
            plot.status = 'booked'
            plot.save()
            
            # Auto-generate installment plan from template if selected
            template_id = request.POST.get('installment_template')
            if template_id:
                from bookings.models import InstallmentPlanTemplate, InstallmentPlan
                try:
                    template = InstallmentPlanTemplate.objects.get(pk=template_id, project=booking.plot.project)
                    # Down payment = what the customer actually paid at booking
                    # time (falling back to the template's expected percentage).
                    down_payment = booking.advance_paid if booking.advance_paid > 0 else (
                        booking.total_amount * template.down_payment_percentage / 100
                    )
                    plan = InstallmentPlan.objects.create(
                        booking=booking,
                        template=template,
                        total_installments=template.total_installments,
                        installment_amount=(booking.total_amount - down_payment) / template.total_installments,
                        down_payment_amount=down_payment,
                        start_date=booking.booking_date,
                        frequency=template.frequency,
                        late_fee_per_day=template.late_fee_per_day,
                        grace_period_days=template.grace_period_days,
                    )
                    plan.auto_generate()
                    messages.success(request, f'Installment plan generated: {template.total_installments} {template.frequency} installments.')
                except InstallmentPlanTemplate.DoesNotExist:
                    pass
            
            # Record the upfront advance as a real verified Payment so the
            # payment ledger, receipts, and customer payment history stay
            # consistent with booking.advance_paid.
            if booking.advance_paid > 0:
                from payments.models import Payment, Receipt
                payment = Payment.objects.create(
                    booking=booking,
                    amount=booking.advance_paid,
                    payment_date=booking.booking_date,
                    payment_method='cash',
                    payment_type='down_payment',
                    status='verified',
                    verified_by=request.user,
                    verified_at=timezone.now(),
                    created_by=request.user,
                    notes='Upfront advance collected at booking',
                )
                Receipt.objects.create(
                    payment=payment,
                    receipt_date=payment.payment_date,
                    generated_by=request.user,
                )
                payment.receipt_generated = True
                payment.save(update_fields=['receipt_generated'])
            
            AuditLog.objects.create(
                user=request.user, action='create', model_name='Booking',
                object_id=booking.booking_id,
                description=f'Created booking {booking.booking_id} for {booking.customer.full_name}'
            )

            # AUTO-SEND BOOKING NOTIFICATION
            try:
                from notifications.services import NotificationService
                NotificationService.send_booking_notification(booking)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f'Booking notification failed: {e}')

            messages.success(request, f'Booking {booking.booking_id} created successfully!')
            return redirect('bookings')
    else:
        form = BookingForm(initial=initial)
    
    projects = Project.objects.exclude(status='inactive')
    templates = InstallmentPlanTemplate.objects.filter(project__in=projects, is_active=True).select_related('project')
    
    return render(request, 'booking_form.html', {
        'form': form, 
        'title': 'Create New Booking',
        'plan_templates': templates,
        'projects': projects,
    })


@login_required
def plan_templates_api_view(request):
    """JSON endpoint: return installment plan templates for a given project."""
    from bookings.models import InstallmentPlanTemplate
    project_id = request.GET.get('project_id') or request.GET.get('plot_id')
    templates = InstallmentPlanTemplate.objects.filter(is_active=True)
    if project_id:
        try:
            from properties.models import Plot
            plot = Plot.objects.filter(pk=project_id).first()
            if plot:
                templates = templates.filter(project=plot.project)
            else:
                templates = templates.filter(project_id=project_id)
        except (ValueError, TypeError):
            templates = templates.filter(project_id=project_id)
    data = [{
        'id': t.id,
        'name': t.name,
        'total_installments': t.total_installments,
        'frequency': t.frequency,
        'down_payment_percentage': float(t.down_payment_percentage),
        'late_fee_per_day': float(t.late_fee_per_day),
        'grace_period_days': t.grace_period_days,
    } for t in templates]
    return JsonResponse({'templates': data})


@login_required
def booking_detail_view(request, pk):
    booking = get_object_or_404(
        Booking.objects.select_related('customer', 'plot', 'plot__project'),
        pk=pk
    )
    installments = booking.installment_plan.installments.all() if hasattr(booking, 'installment_plan') else []
    payments = booking.payments.select_related('verified_by').prefetch_related('receipts').all()
    
    context = {
        'booking': booking,
        'installments': installments,
        'payments': payments,
    }
    return render(request, 'booking_detail.html', context)


@login_required
def booking_edit_view(request, pk):
    from bookings.forms import BookingForm
    
    booking = get_object_or_404(Booking, pk=pk)
    if request.method == 'POST':
        form = BookingForm(request.POST, instance=booking)
        if form.is_valid():
            form.save()
            AuditLog.objects.create(
                user=request.user, action='update', model_name='Booking',
                object_id=booking.booking_id,
                description=f'Updated booking {booking.booking_id}'
            )
            messages.success(request, f'Booking {booking.booking_id} updated successfully!')
            return redirect('bookings')
    else:
        form = BookingForm(instance=booking)
    
    return render(request, 'booking_form.html', {'form': form, 'title': f'Edit Booking', 'booking': booking})


@login_required
@management_or_above
def booking_delete_view(request, pk):
    booking = get_object_or_404(Booking, pk=pk)
    # Data protection: a booking with payments cannot be hard-deleted
    # (payments and receipts would vanish from the ledger).
    if booking.payments.exists():
        messages.error(
            request,
            'Cannot delete a booking that has payments. Cancel it and process a refund instead.'
        )
        return redirect('booking_detail', pk=booking.pk)
    if request.method == 'POST':
        booking_id = booking.booking_id
        # Reset plot status
        plot = booking.plot
        plot.status = 'available'
        plot.save()
        booking.delete()
        AuditLog.objects.create(
            user=request.user, action='delete', model_name='Booking',
            object_id=booking_id,
            description=f'Deleted booking {booking_id}'
        )
        messages.success(request, f'Booking {booking_id} deleted successfully!')
        return redirect('bookings')
    
    return render(request, 'confirm_delete.html', {'object': booking, 'title': 'Delete Booking', 'cancel_url': 'bookings'})


@login_required
@management_or_above
def booking_confirm_view(request, pk):
    """Confirm a pending booking status"""
    booking = get_object_or_404(Booking, pk=pk)
    
    # Only allow confirming pending bookings
    if booking.status != 'pending':
        messages.error(request, f'Only pending bookings can be confirmed. Current status: {booking.get_status_display()}')
        return redirect('booking_detail', pk=pk)
    
    if request.method == 'POST':
        booking.status = 'confirmed'
        booking.save()
        AuditLog.objects.create(
            user=request.user, action='update', model_name='Booking',
            object_id=booking.booking_id,
            description=f'Confirmed booking {booking.booking_id}'
        )

        # AUTO-SEND BOOKING APPROVAL NOTIFICATION
        try:
            from notifications.services import NotificationService
            customer = booking.customer
            msg = (
                f"Dear {customer.full_name},\n\n"
                f"Your booking {booking.booking_id} has been CONFIRMED.\n\n"
                f"Plot: {booking.plot.plot_number}\n"
                f"Project: {booking.plot.project.name}\n"
                f"Total Amount: Rs. {booking.total_amount:,.0f}\n\n"
                f"Please proceed with the down payment as per your payment plan.\n\n"
                f"Samana Builders & Developers"
            )
            channels = ['email']
            if customer.phone:
                channels.append('whatsapp')
            for ch in channels:
                contact = customer.email if ch == 'email' else customer.phone
                if contact:
                    NotificationService.send_notification(
                        recipient_name=customer.full_name,
                        recipient_contact=contact,
                        channel=ch,
                        notification_type='booking_approval',
                        subject=f'Booking Approved - {booking.booking_id}',
                        message=msg,
                        customer_id=customer.customer_id,
                        booking_id=booking.booking_id,
                    )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f'Booking approval notification failed: {e}')

        messages.success(request, f'Booking {booking.booking_id} confirmed successfully!')
        return redirect('booking_detail', pk=pk)
    
    return render(request, 'booking_confirm.html', {'booking': booking})


# ─── BOOKING TRANSFER ──────────────────────────────────────────────────────────

@login_required
@management_or_above
def booking_transfer_view(request, pk):
    from bookings.models import BookingTransfer
    
    booking = get_object_or_404(Booking, pk=pk)
    
    if request.method == 'POST':
        to_customer_id = request.POST.get('to_customer')
        transfer_fee = Decimal(request.POST.get('transfer_fee', '0'))
        handling = request.POST.get('payment_handling', 'transfer')
        notes = request.POST.get('notes', '')
        
        try:
            to_customer = Customer.objects.get(pk=to_customer_id)
            transfer = BookingTransfer.objects.create(
                booking=booking,
                from_customer=booking.customer,
                to_customer=to_customer,
                transfer_fee=transfer_fee,
                previous_payments_handling=handling,
                approved_by=request.user,
                notes=notes,
            )
            # Update booking customer
            old_customer = booking.customer
            booking.customer = to_customer
            booking.save()
            
            AuditLog.objects.create(
                user=request.user, action='transfer', model_name='Booking',
                object_id=booking.booking_id,
                description=f'Transferred booking {booking.booking_id} from {old_customer.full_name} to {to_customer.full_name}'
            )
            messages.success(request, f'Booking transferred successfully!')
            return redirect('booking_detail', pk=booking.pk)
        except Customer.DoesNotExist:
            messages.error(request, 'Customer not found.')
    
    customers = Customer.objects.filter(is_active=True).exclude(pk=booking.customer.pk)
    return render(request, 'booking_transfer.html', {
        'booking': booking,
        'customers': customers,
    })


# ─── RESERVATION ──────────────────────────────────────────────────────────────

@login_required
def reservation_create_view(request):
    from bookings.models import Reservation
    from bookings.forms import ReservationForm
    
    if request.method == 'POST':
        form = ReservationForm(request.POST)
        if form.is_valid():
            reservation = form.save(commit=False)
            reservation.created_by = request.user
            reservation.save()
            
            # Reserve the plot
            plot = reservation.plot
            plot.status = 'reserved'
            plot.save()
            
            AuditLog.objects.create(
                user=request.user, action='create', model_name='Reservation',
                object_id=str(reservation.id),
                description=f'Created reservation for {reservation.customer.full_name} on plot {plot.plot_number}'
            )
            messages.success(request, 'Plot reserved successfully!')
            return redirect('properties')
    else:
        form = ReservationForm()
    
    return render(request, 'reservation_form.html', {'form': form, 'title': 'Create Reservation'})


# ─── PAYMENTS ────────────────────────────────────────────────────────────────────

@login_required
@payments_access  # sales has no access to payment details; staff keeps legacy view access
def payments_view(request):
    payments = Payment.objects.select_related('booking', 'booking__customer').all()
    status_filter = request.GET.get('status', '')
    method_filter = request.GET.get('method', '')
    search = request.GET.get('search', '')
    customer_id = request.GET.get('customer', '')
    
    if status_filter:
        payments = payments.filter(status=status_filter)
    if method_filter:
        payments = payments.filter(payment_method=method_filter)
    type_filter = request.GET.get('type', '')
    if type_filter:
        if type_filter == 'other':
            payments = payments.exclude(payment_type__in=['down_payment', 'installment', 'full_payment', 'late_fee'])
        else:
            payments = payments.filter(payment_type=type_filter)
    if customer_id:
        payments = payments.filter(booking__customer_id=customer_id)
    if search:
        payments = payments.filter(
            Q(payment_id__icontains=search) |
            Q(booking__booking_id__icontains=search) |
            Q(booking__customer__first_name__icontains=search) |
            Q(booking__customer__last_name__icontains=search)
        )
    
    payments = payments.select_related('booking', 'booking__customer', 'booking__plot', 'verified_by').prefetch_related('receipts')

    today = timezone.localdate()
    month_start = today.replace(day=1)
    total_amount = payments.aggregate(total=Sum('amount'))['total'] or 0
    month_amount = payments.filter(payment_date__gte=month_start).aggregate(total=Sum('amount'))['total'] or 0

    all_payments = Payment.objects.all()
    type_counts = {
        'all': all_payments.count(),
        'down_payment': all_payments.filter(payment_type='down_payment').count(),
        'installment': all_payments.filter(payment_type='installment').count(),
        'full_payment': all_payments.filter(payment_type='full_payment').count(),
        'late_fee': all_payments.filter(payment_type='late_fee').count(),
        'other': all_payments.exclude(payment_type__in=['down_payment', 'installment', 'full_payment', 'late_fee']).count(),
    }

    context = {
        'payments': payments,
        'status_filter': status_filter,
        'method_filter': method_filter,
        'type_filter': type_filter,
        'search': search,
        'customer_filter': Customer.objects.filter(pk=customer_id).first() if customer_id else None,
        'total_count': payments.count(),
        'total_amount': total_amount,
        'month_amount': month_amount,
        'type_counts': type_counts,
    }
    return render(request, 'payments.html', context)


@login_required
@payments_access
def payment_create_view(request):
    from payments.forms import PaymentForm
    from payments.models import Receipt, PaymentAttachment
    from django.db import transaction
    
    booking_id = request.GET.get('booking_id')
    pre_filled_booking = None
    
    if booking_id:
        pre_filled_booking = get_object_or_404(Booking, pk=booking_id)
    
    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.created_by = request.user
            payment.status = 'verified'
            payment.verified_by = request.user
            payment.verified_at = timezone.now()

            # ── VALIDATION: installment must belong to this booking ──────────
            if payment.installment:
                if payment.installment.plan.booking_id != payment.booking_id:
                    form.add_error('installment', 'Selected installment does not belong to this booking.')
                    return render(request, 'payment_form.html', {
                        'form': form, 'title': 'Record New Payment',
                        'projects': Project.objects.exclude(status='inactive'),
                        'plots': Plot.objects.all(),
                        'bookings': Booking.objects.filter(status__in=['pending', 'confirmed', 'active']).select_related('customer', 'plot', 'plot__project'),
                        'pre_filled_booking': pre_filled_booking,
                    })

            # ── DUPLICATE CHECK: same booking + amount + date within 60s ─────
            recent_cutoff = timezone.now() - timedelta(seconds=60)
            duplicate = Payment.objects.filter(
                booking=payment.booking,
                amount=payment.amount,
                payment_date=payment.payment_date,
                payment_method=payment.payment_method,
                created_at__gte=recent_cutoff,
            ).exists()
            if duplicate:
                messages.error(request, 'Possible duplicate payment detected. This payment was already recorded. Please check the payment list.')
                return redirect('payments')

            # ── ATOMIC TRANSACTION: all-or-nothing ──────────────────────────
            with transaction.atomic():
                payment.save()

                # Update installment if linked
                if payment.installment:
                    installment = payment.installment
                    installment_total = installment.amount + installment.late_fee
                    remaining_before = installment_total - installment.paid_amount
                    
                    # Track overpayment
                    overpayment = 0
                    if payment.amount > remaining_before:
                        overpayment = payment.amount - remaining_before
                        payment.unallocated_amount = overpayment
                        payment.save(update_fields=['unallocated_amount'])
                        installment.paid_amount = installment_total
                    else:
                        installment.paid_amount += payment.amount
                    
                    if installment.paid_amount >= installment_total:
                        installment.status = 'paid'
                        installment.paid_date = payment.payment_date
                    elif installment.paid_amount > 0:
                        installment.status = 'partial'
                    installment.save()

                # Update booking advance (capped at total_amount)
                booking = payment.booking
                new_advance = booking.advance_paid + payment.amount
                if new_advance > booking.total_amount:
                    new_advance = booking.total_amount
                booking.advance_paid = new_advance
                if booking.remaining_balance <= 0:
                    booking.status = 'completed'
                booking.save()

                # Recalculate the installment plan so unpaid installments
                # reflect the new remaining balance.
                if hasattr(booking, 'installment_plan') and booking.installment_plan:
                    booking.installment_plan.recalculate()

                # Auto-generate receipt
                receipt = Receipt.objects.create(
                    payment=payment,
                    receipt_date=payment.payment_date,
                    generated_by=request.user,
                )
                payment.receipt_generated = True
                payment.save(update_fields=['receipt_generated'])
            
            # Handle file attachments (outside transaction - non-critical)
            method_type_map = {
                'cash': 'receipt_image',
                'cheque': 'cheque_image',
                'bank_transfer': 'payment_screenshot',
                'jazzcash': 'payment_screenshot',
                'easypaisa': 'payment_screenshot',
                'raast': 'payment_screenshot',
                'online': 'payment_screenshot',
            }
            files = request.FILES.getlist('attachments')
            for f in files:
                PaymentAttachment.objects.create(
                    payment=payment,
                    file=f,
                    attachment_type=method_type_map.get(payment.payment_method, 'other'),
                    filename=f.name,
                    uploaded_by=request.user,
                )
            
            AuditLog.objects.create(
                user=request.user, action='create', model_name='Payment',
                object_id=payment.payment_id,
                description=f'Created payment {payment.payment_id} for booking {payment.booking.booking_id}'
            )

            # AUTO-SEND NOTIFICATIONS
            try:
                from notifications.services import NotificationService
                NotificationService.send_payment_confirmation(payment)
                NotificationService.send_receipt_notification(receipt)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f'Notification send failed: {e}')

            messages.success(request, f'Payment {payment.payment_id} recorded successfully! Receipt {receipt.receipt_number} generated.')
            return redirect('payments')
    else:
        form = PaymentForm()
        if pre_filled_booking:
            form.fields['booking'].initial = pre_filled_booking.id
            form.fields['booking'].widget.attrs['disabled'] = True
    
    projects = Project.objects.exclude(status='inactive')
    plots = Plot.objects.all()
    bookings = Booking.objects.filter(status__in=['pending', 'confirmed', 'active']).select_related('customer', 'plot', 'plot__project')
    
    return render(request, 'payment_form.html', {
        'form': form,
        'title': 'Receive Payment' if pre_filled_booking else 'Record New Payment',
        'projects': projects,
        'plots': plots,
        'bookings': bookings,
        'pre_filled_booking': pre_filled_booking,
    })


@login_required
@payments_access
def payment_detail_view(request, pk):
    payment = get_object_or_404(Payment.objects.select_related(
        'booking', 'booking__customer', 'booking__plot', 'booking__plot__project',
        'installment', 'created_by', 'verified_by'
    ).prefetch_related('receipts'), pk=pk)
    
    installments = []
    payment_summary = None
    plan = getattr(payment.booking, 'installment_plan', None)
    
    if plan:
        installments = plan.installments.all().order_by('installment_number')
        total_paid = float(payment.booking.advance_paid)
        progress = payment.booking.payment_progress
        paid_count = installments.filter(status='paid').count()
        payment_summary = {
            'property_price': float(payment.booking.total_amount),
            'down_payment': float(plan.down_payment_amount),
            'total_paid': total_paid,
            'remaining': float(payment.booking.remaining_balance),
            'total_installments': plan.total_installments,
            'installment_amount': float(plan.installment_amount),
            'paid_installments': paid_count,
            'remaining_installments': plan.total_installments - paid_count,
            'progress': progress,
            'is_fully_paid': payment.booking.remaining_balance <= 0,
        }
    
    all_attachments = payment.attachments.all()
    
    customer_payments = (
        Payment.objects.filter(booking__customer=payment.booking.customer)
        .select_related('booking')
        .order_by('-payment_date', '-created_at')
    )
    
    return render(request, 'payment_detail.html', {
        'payment': payment,
        'installments': installments,
        'payment_summary': payment_summary,
        'attachments': all_attachments,
        'customer_payments': customer_payments,
    })


# ─── RECEIPTS ─────────────────────────────────────────────────────────────────────

@login_required
@payments_access
def receipt_detail_view(request, pk):
    from payments.models import Receipt
    from payments.utils import amount_in_words
    
    receipt = get_object_or_404(
        Receipt.objects.select_related(
            'payment', 'payment__booking', 'payment__booking__customer',
            'payment__booking__plot', 'payment__booking__plot__project',
            'generated_by'
        ),
        pk=pk
    )
    
    payment = receipt.payment
    booking = payment.booking
    amount_words = amount_in_words(payment.amount)
    
    return render(request, 'receipt_detail.html', {
        'receipt': receipt,
        'payment': payment,
        'booking': booking,
        'amount_words': amount_words,
    })


@login_required
@payments_access
def receipt_pdf_view(request, pk):
    from payments.models import Receipt
    from payments.pdf_utils import generate_receipt_pdf

    receipt = get_object_or_404(Receipt, pk=pk)

    pdf_content = generate_receipt_pdf(receipt)
    if pdf_content:
        response = HttpResponse(pdf_content, content_type='application/pdf')
        filename = f"receipt_{receipt.receipt_number.replace('/', '-')}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['Cache-Control'] = 'no-store'
        return response

    messages.error(request, 'Failed to generate PDF. Please try again.')
    return redirect('receipt_detail', pk=pk)


@login_required
@payments_access
def invoice_pdf_view(request, pk):
    from payments.pdf_utils import generate_invoice_pdf

    booking = get_object_or_404(Booking, pk=pk)
    pdf_content = generate_invoice_pdf(booking)

    if pdf_content:
        response = HttpResponse(pdf_content, content_type='application/pdf')
        filename = f"invoice_{booking.booking_id}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['Cache-Control'] = 'no-store'
        return response

    messages.error(request, 'Failed to generate invoice PDF.')
    return redirect('booking_detail', pk=pk)


@login_required
def customer_profile_pdf_view(request, pk):
    from payments.pdf_utils import generate_customer_profile_pdf

    customer = get_object_or_404(Customer, pk=pk)
    pdf_content = generate_customer_profile_pdf(customer)

    if pdf_content:
        response = HttpResponse(pdf_content, content_type='application/pdf')
        filename = f"customer_profile_{customer.customer_id}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    messages.error(request, 'Failed to generate customer profile PDF.')
    return redirect('customer_detail', pk=pk)


# ─── USERS (admin/super_admin only; management read-only) ──────────────────────────

@login_required
@management_or_above
def users_view(request):
    users = User.objects.select_related('profile').order_by('-date_joined')
    role_choices = [(k, v) for k, v in UserProfile.ROLE_CHOICES if k != 'super_admin']
    return render(request, 'users.html', {
        'users': users,
        'role_choices': role_choices,
        'active_count': User.objects.filter(is_active=True).count(),
        'admin_count': User.objects.filter(profile__role__in=['super_admin', 'admin']).count(),
    })


@login_required
@admin_or_above
def user_create_view(request):
    from .forms import CreateUserForm

    if request.method == 'POST':
        form = CreateUserForm(request.POST, actor=request.user)
        if form.is_valid():
            user = User.objects.create_user(
                username=form.cleaned_data['username'],
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password'],
                first_name=form.cleaned_data['first_name'],
                last_name=form.cleaned_data['last_name'],
            )
            UserProfile.objects.create(
                user=user,
                role=form.cleaned_data['role'],
                phone=form.cleaned_data.get('phone', ''),
                cnic=form.cleaned_data.get('cnic', ''),
            )
            AuditLog.objects.create(
                user=request.user, action='create', model_name='User',
                object_id=user.username,
                description=f'Created user {user.username} with role {form.cleaned_data["role"]}'
            )
            messages.success(request, f'User {user.username} created successfully!')
            return redirect('users')
    else:
        form = CreateUserForm()

    return render(request, 'user_form.html', {'form': form, 'title': 'Create New User'})


@login_required
@admin_or_above
def user_edit_view(request, pk):
    user = get_object_or_404(User.objects.select_related('profile'), pk=pk)
    actor_role = get_user_role(request)
    target_role = getattr(getattr(user, 'profile', None), 'role', None)

    if target_role == 'super_admin' and actor_role != 'super_admin':
        messages.error(request, 'Only a Super Admin can edit a Super Admin account.')
        return redirect('users')

    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=user)
        if form.is_valid():
            new_role = form.cleaned_data['role']

            if user == request.user and new_role != target_role:
                form.add_error('role', 'You cannot change your own role.')
            elif (
                target_role == 'super_admin'
                and new_role != 'super_admin'
                and User.objects.filter(is_active=True, profile__role='super_admin').count() <= 1
            ):
                form.add_error('role', 'Cannot change the role of the last active Super Admin.')
            else:
                password_changed = bool(form.cleaned_data.get('new_password'))
                form.save()
                AuditLog.objects.create(
                    user=request.user, action='update', model_name='User',
                    object_id=user.username,
                    description=f'Updated user {user.username}' + (' and changed password' if password_changed else '')
                )
                messages.success(request, f'User {user.username} updated successfully!')
                return redirect('users')
    else:
        form = UserEditForm(instance=user)

    return render(request, 'user_form.html', {'form': form, 'title': f'Edit User: {user.username}', 'user': user})


@login_required
@admin_or_above
def user_role_update_view(request, pk):
    """Inline role dropdown update from the Manage Users list."""
    user = get_object_or_404(User.objects.select_related('profile'), pk=pk)
    allowed = [k for k, _ in UserProfile.ROLE_CHOICES if k != 'super_admin']

    if request.method == 'POST':
        role = request.POST.get('role', '')
        if user == request.user:
            messages.error(request, 'You cannot change your own role.')
        elif not hasattr(user, 'profile'):
            messages.error(request, f'User {user.username} has no profile.')
        elif getattr(user.profile, 'role', None) == 'super_admin':
            messages.error(request, 'Super Admin roles cannot be changed.')
        elif role not in allowed:
            messages.error(request, 'Invalid role selected.')
        else:
            old_role = user.profile.get_role_display()
            user.profile.role = role
            user.profile.save()
            AuditLog.objects.create(
                user=request.user, action='update', model_name='User',
                object_id=user.username,
                description=f'Changed role of {user.username} from {old_role} to {user.profile.get_role_display()}'
            )
            messages.success(request, f'Role updated for {user.username}.')
    return redirect('users')


@login_required
@admin_or_above
def user_deactivate_view(request, pk):
    user = get_object_or_404(User, pk=pk)
    actor_role = get_user_role(request)
    target_role = getattr(getattr(user, 'profile', None), 'role', None)

    # Prevent self-deactivation
    if user == request.user:
        messages.error(request, 'You cannot deactivate your own account.')
        return redirect('users')

    # Only a super admin may deactivate another super admin
    if target_role == 'super_admin' and actor_role != 'super_admin':
        messages.error(request, 'Only a Super Admin can deactivate another Super Admin.')
        return redirect('users')

    # Never lock out the last active super admin
    if (
        target_role == 'super_admin' and user.is_active
        and User.objects.filter(is_active=True, profile__role='super_admin').count() <= 1
    ):
        messages.error(request, 'Cannot deactivate the last active Super Admin.')
        return redirect('users')

    if request.method == 'POST':
        user.is_active = not user.is_active
        user.save()
        status = 'activated' if user.is_active else 'deactivated'
        AuditLog.objects.create(
            user=request.user, action='update', model_name='User',
            object_id=user.username,
            description=f'{status.title()} user {user.username}'
        )
        messages.success(request, f'User {user.username} {status} successfully!')
        return redirect('users')

    return render(request, 'confirm_delete.html', {
        'object': user,
        'title': f'{"Deactivate" if user.is_active else "Activate"} User',
        'message': f'Are you sure you want to {"deactivate" if user.is_active else "activate"} user "{user.username}"?',
        'cancel_url': 'users',
    })


# ─── AUDIT LOGS ──────────────────────────────────────────────────────────────────

@login_required
@management_or_above
def audit_logs_view(request):
    logs = AuditLog.objects.select_related('user').all()[:100]
    return render(request, 'audit_logs.html', {'logs': logs})


# ─── PROFILE (self-service) ──────────────────────────────────────────────────────

@login_required
def profile_view(request):
    user = request.user
    
    if request.method == 'POST':
        user_form = UserForm(request.POST, instance=user)
        # Build profile form manually
        profile = getattr(user, 'profile', None)
        if profile:
            profile_form = UserProfileForm(request.POST, instance=profile)
        else:
            profile_form = UserProfileForm(request.POST)
        
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile = profile_form.save(commit=False)
            profile.user = user
            profile.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('profile')
    else:
        user_form = UserForm(instance=user)
        profile = getattr(user, 'profile', None)
        profile_form = UserProfileForm(instance=profile) if profile else UserProfileForm()
    
    context = {
        'user_form': user_form,
        'profile_form': profile_form,
    }
    return render(request, 'profile.html', context)


@login_required
def save_theme_view(request):
    """AJAX endpoint to persist theme preference."""
    if request.method == 'POST':
        import json
        try:
            body = json.loads(request.body)
            theme = body.get('theme', 'professional-blue')
        except (json.JSONDecodeError, AttributeError):
            theme = request.POST.get('theme', 'professional-blue')
        
        valid_themes = ['professional-blue', 'modern-green', 'elegant-dark', 'warm-earth', 'minimalist-purple']
        if theme in valid_themes:
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            profile.theme = theme
            profile.save()
            return JsonResponse({'status': 'ok', 'theme': theme})
    
    return JsonResponse({'status': 'error'}, status=400)


# ─── DB BACKUP (admin/super_admin only) ──────────────────────────────────────────

@login_required
@admin_or_above
def backup_view(request):
    from pathlib import Path
    from datetime import datetime
    from django.conf import settings

    backup_dir = Path(settings.BASE_DIR) / 'backups'
    last_backups = []
    if backup_dir.exists():
        files = sorted(backup_dir.glob('samana_backup_*.zip'), reverse=True)[:5]
        for f in files:
            last_backups.append({
                'name': f.name,
                'size': f.stat().st_size,
                'time': datetime.fromtimestamp(f.stat().st_mtime),
            })

    restore_form = RestoreBackupForm()
    return render(request, 'backup.html', {
        'last_backups': last_backups,
        'restore_form': restore_form,
    })


@login_required
@admin_or_above
def backup_download_view(request):
    import io
    from pathlib import Path
    from django.conf import settings
    from django.http import FileResponse
    from .backup import build_backup_zip

    data = build_backup_zip()
    filename = f"samana_backup_{timezone.now().strftime('%Y%m%d_%H%M%S')}.zip"

    backup_dir = Path(settings.BASE_DIR) / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / filename).write_bytes(data)

    AuditLog.objects.create(
        user=request.user, action='backup', model_name='Database',
        object_id=filename,
        description=f'Database backup downloaded: {filename}'
    )
    messages.success(request, f'Backup created successfully: {filename}')

    response = FileResponse(io.BytesIO(data), as_attachment=True, filename=filename)
    response['Cache-Control'] = 'no-store'
    return response


def _perform_restore(request, data, name):
    from .backup import restore_from_backup
    try:
        summary = restore_from_backup(data)
    except Exception as exc:
        try:
            AuditLog.objects.create(
                user=request.user, action='restore', model_name='Database',
                object_id=name, description=f'Restore FAILED: {exc}',
            )
        except Exception:
            pass
        messages.error(request, f'Restore failed: {exc}')
        return False

    AuditLog.objects.create(
        user=request.user, action='restore', model_name='Database',
        object_id=name,
        description='Database restored: {} rows across {} tables, {} media files'.format(
            summary['total_rows'], len(summary['tables']), summary['media_files']),
    )
    messages.success(
        request,
        'Database restored successfully: {} rows across {} tables, {} media files.'.format(
            summary['total_rows'], len(summary['tables']), summary['media_files']),
    )
    return True


def _restore_blocked(request, name):
    """Basic guard against duplicate restores in quick succession (non-DEBUG)."""
    from django.conf import settings
    if settings.DEBUG:
        return False
    user_ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR'))
    return AuditLog.objects.filter(
        user=request.user, action='restore', object_id=name,
        description__icontains=(user_ip or ''),
        created_at__gte=timezone.now() - timedelta(seconds=60),
    ).exists()


@login_required
@admin_or_above
def backup_restore_latest_view(request):
    from pathlib import Path
    from django.conf import settings

    if request.method != 'POST':
        return redirect('backup')

    backup_dir = Path(settings.BASE_DIR) / 'backups'
    if not backup_dir.exists():
        messages.error(request, 'No backups found in the backups folder. Create a backup first.')
        return redirect('backup')

    files = sorted(backup_dir.glob('samana_backup_*.zip'), reverse=True)
    if not files:
        messages.error(request, 'No backups found in the backups folder. Create a backup first.')
        return redirect('backup')

    latest = files[0]
    name = latest.name

    if _restore_blocked(request, name):
        messages.error(request, 'Restore already in progress. Please wait and try again shortly.')
        return redirect('backup')

    with latest.open('rb') as fh:
        data = fh.read()
    _perform_restore(request, data, name)
    return redirect('backup')


@login_required
@admin_or_above
def backup_restore_upload_view(request):
    from django.core.files.uploadedfile import InMemoryUploadedFile

    if request.method != 'POST':
        return redirect('backup')

    form = RestoreBackupForm(request.POST, request.FILES)
    if not form.is_valid():
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, error)
        return redirect('backup')

    upload = form.cleaned_data['backup_file']
    if isinstance(upload, InMemoryUploadedFile):
        data = upload.read()
    else:
        data = upload.file.read()

    name = getattr(upload, 'name', 'uploaded_backup.zip')
    if _restore_blocked(request, name):
        messages.error(request, 'Restore already in progress. Please wait and try again shortly.')
        return redirect('backup')

    _perform_restore(request, data, name)
    return redirect('backup')


# ─── CORPORATE SITE + CUSTOMER PORTAL (Django templates) ─────────────────────

def corporate_home_view(request):
    return render(request, 'corporate/home.html', {})


def lead_submit_view(request):
    from .models import Lead
    if request.method != 'POST':
        return redirect('corporate_home')

    name = request.POST.get('name', '').strip()
    email = request.POST.get('email', '').strip()
    phone = request.POST.get('phone', '').strip()
    source = request.POST.get('lead_type', 'hero')
    if source not in dict(Lead.LEAD_SOURCE_CHOICES):
        source = 'hero'

    if not name and not email and not phone:
        messages.error(request, 'Please provide at least your name or email.')
        return redirect('corporate_home')

    # Create Lead record
    interest = request.POST.get('interest', '').strip()
    message = request.POST.get('message', '').strip()
    notes_parts = []
    if interest:
        notes_parts.append(f'Interest: {interest}')
    if message:
        notes_parts.append(f'Message: {message}')
    lead = Lead.objects.create(name=name, email=email, phone=phone, source=source,
                               notes='\n'.join(notes_parts))

    messages.success(request, 'Thank you! Your enquiry has been received. Our team will contact you soon.')
    return redirect('corporate_home')


@login_required
def portal_view(request):
    from django.db.models import Sum
    customer = Customer.objects.filter(user=request.user).first()
    if customer is None:
        messages.error(request, 'No customer profile is linked to this account.')
        return redirect('dashboard')

    active_statuses = ['pending', 'confirmed', 'active']
    bookings_qs = customer.bookings.select_related('plot', 'plot__project').all()
    active_bookings = [b for b in bookings_qs if b.status in active_statuses]
    total_amount = sum((b.total_amount for b in active_bookings), 0)
    total_paid = Payment.objects.filter(booking__customer=customer, status='verified').aggregate(
        total=Sum('amount'))['total'] or 0

    payments = (
        Payment.objects.filter(booking__customer=customer)
        .select_related('booking')
        .order_by('-payment_date', '-created_at')
    )

    bookings_payload = []
    installments = []
    for b in bookings_qs:
        plan = getattr(b, 'installment_plan', None)
        plan_installments = list(plan.installments.all().order_by('installment_number')) if plan else []
        installments.extend(plan_installments)
        bookings_payload.append({
            'booking_id': b.booking_id,
            'plot_number': b.plot.plot_number,
            'project': b.plot.project.name if b.plot.project else None,
            'total_amount': float(b.total_amount),
            'advance_paid': float(b.advance_paid),
            'remaining_balance': float(b.remaining_balance),
            'status': b.status,
        })

    installment_payload = [{
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

    payments_payload = [{
        'payment_id': p.payment_id,
        'booking_id': p.booking.booking_id,
        'amount': float(p.amount),
        'payment_date': p.payment_date,
        'payment_method': p.get_payment_method_display(),
        'status': p.status,
    } for p in payments]

    context = {
        'customer': customer,
        'summary': {
            'total_bookings': bookings_qs.count(),
            'total_paid': float(total_paid),
            'remaining_balance': float(total_amount - total_paid),
            'pending_installments': len(pending_installments),
            'overdue_installments': len(overdue_installments),
            'next_due': next_due,
        },
        'bookings': bookings_payload,
        'payments': payments_payload,
        'installments': installment_payload,
    }
    return render(request, 'portal/dashboard.html', context)


# ─── AI ASSISTANT (LangChain + DeepSeek) ─────────────────────────────────────

@login_required
def ai_assistant_page_view(request):
    """ERP AI chat assistant page (staff only)."""
    from django.conf import settings
    from core.models import CompanySettings
    from core.permissions import get_user_role, ADMIN_ROLES
    settings_obj = CompanySettings.load()
    role = get_user_role(request)
    context = {
        'ai_enabled': bool(getattr(settings, 'AI_ENABLED', False)),
        'ai_configured': bool(getattr(settings, 'DEEPSEEK_API_KEY', '')),
        'ai_language': settings_obj.ai_language,
        'can_manage_ai_language': request.user.is_superuser or role in ADMIN_ROLES,
    }
    return render(request, 'ai/assistant.html', context)


@login_required
@finance_or_above
def ai_insights_page_view(request):
    """AI business insights page (finance/management only)."""
    from django.conf import settings
    from django.db.models import Sum
    from bookings.models import Booking, Installment
    from payments.models import Payment
    from properties.models import Plot
    from ai.models import AiInteractionLog

    today = timezone.now().date()
    month_start = today.replace(day=1)
    total_revenue = Booking.objects.aggregate(total=Sum('advance_paid'))['total'] or 0
    monthly_revenue = Booking.objects.filter(
        booking_date__gte=month_start
    ).aggregate(total=Sum('advance_paid'))['total'] or 0
    pending_payments = Payment.objects.filter(status='pending').count()
    overdue_count = Installment.objects.filter(status='overdue').count()
    overdue_amount = Installment.objects.filter(status='overdue').aggregate(
        total=Sum('amount'))['total'] or 0
    available_plots = Plot.objects.filter(status='available').count()
    active_bookings = Booking.objects.filter(status__in=['active', 'confirmed']).count()

    history = list(
        AiInteractionLog.objects.filter(feature='insights', status='success')
        .order_by('-created_at')[:6]
    )

    context = {
        'ai_enabled': bool(getattr(settings, 'AI_ENABLED', False)),
        'ai_configured': bool(getattr(settings, 'DEEPSEEK_API_KEY', '')),
        'total_revenue': total_revenue,
        'monthly_revenue': monthly_revenue,
        'pending_payments': pending_payments,
        'overdue_count': overdue_count,
        'overdue_amount': overdue_amount,
        'available_plots': available_plots,
        'active_bookings': active_bookings,
        'insights_history': history,
    }
    return render(request, 'ai/insights.html', context)


@login_required
def ai_hr_page_view(request):
    """AI HR tools page (HR/management roles)."""
    from django.conf import settings
    from .permissions import get_user_role

    role = get_user_role(request)
    if not (request.user.is_superuser or role in ('super_admin', 'admin', 'management', 'hr')):
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('dashboard')

    from hr.models import Department, Designation, Leave, PayrollRun
    context = {
        'ai_enabled': bool(getattr(settings, 'AI_ENABLED', False)),
        'ai_configured': bool(getattr(settings, 'DEEPSEEK_API_KEY', '')),
        'departments': Department.objects.filter(is_active=True),
        'designations': Designation.objects.filter(is_active=True),
        'pending_leaves': Leave.objects.filter(status='pending').select_related('employee')[:10],
        'payroll_runs': PayrollRun.objects.all()[:10],
    }
    return render(request, 'ai/hr.html', context)