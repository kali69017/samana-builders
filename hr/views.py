"""HR and Payroll ERP views."""
from datetime import date

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum, Count, Q
from django.shortcuts import render, redirect, get_object_or_404

from core.models import AuditLog
from core.permissions import hr_required, payroll_access
from .models import (
    Department, Designation, SalaryComponent, Employee, EmployeeDocument,
    EmployeeSalary, PayrollRun, SalarySlip, SalarySlipItem, SalaryPayment,
    Attendance, Leave, LEAVE_POLICY_ALLOWANCES,
)
from .forms import (
    DepartmentForm, DesignationForm, SalaryComponentForm, EmployeeForm,
    EmployeeSalaryForm, PayrollRunForm, AttendanceForm, LeaveForm,
    EmployeeProfileForm,
)


def _log(request, action, model, object_id, description):
    AuditLog.objects.create(
        user=request.user, action=action, model_name=model,
        object_id=str(object_id), description=description,
        ip_address=request.META.get('REMOTE_ADDR'),
    )


# ─── HR HOME ─────────────────────────────────────────────────────────────────
@login_required
@payroll_access
def hr_home_view(request):
    today = date.today()
    context = {
        'total_employees': Employee.objects.count(),
        'active_employees': Employee.objects.filter(status='active').count(),
        'departments': Department.objects.count(),
        'pending_leaves': Leave.objects.filter(status='pending').count(),
        'current_month': today.month,
        'current_year': today.year,
        'recent_runs': PayrollRun.objects.order_by('-year', '-month')[:5],
        'pending_leave_list': Leave.objects.filter(status='pending').select_related('employee')[:10],
    }
    return render(request, 'hr/hr_home.html', context)


# ─── DEPARTMENTS ─────────────────────────────────────────────────────────────
@login_required
@hr_required
def departments_view(request):
    departments = Department.objects.annotate(employee_count=Count('employees')).all()
    return render(request, 'hr/departments.html', {'departments': departments})


@login_required
@hr_required
def department_create_view(request):
    if request.method == 'POST':
        form = DepartmentForm(request.POST)
        if form.is_valid():
            dept = form.save()
            _log(request, 'create', 'Department', dept.pk, f'Created department {dept.name}')
            messages.success(request, 'Department created successfully!')
            return redirect('hr_departments')
    else:
        form = DepartmentForm()
    return render(request, 'hr/department_form.html', {'form': form, 'title': 'Add Department'})


@login_required
@hr_required
def department_edit_view(request, pk):
    dept = get_object_or_404(Department, pk=pk)
    if request.method == 'POST':
        form = DepartmentForm(request.POST, instance=dept)
        if form.is_valid():
            form.save()
            _log(request, 'update', 'Department', pk, f'Updated department {dept.name}')
            messages.success(request, 'Department updated successfully!')
            return redirect('hr_departments')
    else:
        form = DepartmentForm(instance=dept)
    return render(request, 'hr/department_form.html', {'form': form, 'title': 'Edit Department', 'department': dept})


@login_required
@hr_required
def department_delete_view(request, pk):
    dept = get_object_or_404(Department, pk=pk)
    if request.method == 'POST':
        dept.delete()
        _log(request, 'delete', 'Department', pk, f'Deleted department {dept.name}')
        messages.success(request, 'Department deleted successfully!')
        return redirect('hr_departments')
    return render(request, 'confirm_delete.html', {'object': dept, 'title': 'Delete Department', 'cancel_url': 'hr_departments'})


# ─── DESIGNATIONS ────────────────────────────────────────────────────────────
@login_required
@hr_required
def designations_view(request):
    designations = Designation.objects.annotate(employee_count=Count('employees')).all()
    return render(request, 'hr/designations.html', {'designations': designations})


@login_required
@hr_required
def designation_create_view(request):
    if request.method == 'POST':
        form = DesignationForm(request.POST)
        if form.is_valid():
            des = form.save()
            _log(request, 'create', 'Designation', des.pk, f'Created designation {des.title}')
            messages.success(request, 'Designation created successfully!')
            return redirect('hr_designations')
    else:
        form = DesignationForm()
    return render(request, 'hr/designation_form.html', {'form': form, 'title': 'Add Designation'})


@login_required
@hr_required
def designation_edit_view(request, pk):
    des = get_object_or_404(Designation, pk=pk)
    if request.method == 'POST':
        form = DesignationForm(request.POST, instance=des)
        if form.is_valid():
            form.save()
            _log(request, 'update', 'Designation', pk, f'Updated designation {des.title}')
            messages.success(request, 'Designation updated successfully!')
            return redirect('hr_designations')
    else:
        form = DesignationForm(instance=des)
    return render(request, 'hr/designation_form.html', {'form': form, 'title': 'Edit Designation', 'designation': des})


@login_required
@hr_required
def designation_delete_view(request, pk):
    des = get_object_or_404(Designation, pk=pk)
    if request.method == 'POST':
        des.delete()
        _log(request, 'delete', 'Designation', pk, f'Deleted designation {des.title}')
        messages.success(request, 'Designation deleted successfully!')
        return redirect('hr_designations')
    return render(request, 'confirm_delete.html', {'object': des, 'title': 'Delete Designation', 'cancel_url': 'hr_designations'})


# ─── SALARY COMPONENTS ───────────────────────────────────────────────────────
@login_required
@hr_required
def salary_components_view(request):
    components = SalaryComponent.objects.all()
    return render(request, 'hr/salary_components.html', {'components': components})


@login_required
@hr_required
def salary_component_create_view(request):
    if request.method == 'POST':
        form = SalaryComponentForm(request.POST)
        if form.is_valid():
            comp = form.save()
            _log(request, 'create', 'SalaryComponent', comp.pk, f'Created salary component {comp.name}')
            messages.success(request, 'Salary component created successfully!')
            return redirect('hr_salary_components')
    else:
        form = SalaryComponentForm()
    return render(request, 'hr/salary_component_form.html', {'form': form, 'title': 'Add Salary Component'})


@login_required
@hr_required
def salary_component_edit_view(request, pk):
    comp = get_object_or_404(SalaryComponent, pk=pk)
    if request.method == 'POST':
        form = SalaryComponentForm(request.POST, instance=comp)
        if form.is_valid():
            form.save()
            _log(request, 'update', 'SalaryComponent', pk, f'Updated salary component {comp.name}')
            messages.success(request, 'Salary component updated successfully!')
            return redirect('hr_salary_components')
    else:
        form = SalaryComponentForm(instance=comp)
    return render(request, 'hr/salary_component_form.html', {'form': form, 'title': 'Edit Salary Component', 'component': comp})


@login_required
@hr_required
def salary_component_delete_view(request, pk):
    comp = get_object_or_404(SalaryComponent, pk=pk)
    if request.method == 'POST':
        comp.delete()
        _log(request, 'delete', 'SalaryComponent', pk, f'Deleted salary component {comp.name}')
        messages.success(request, 'Salary component deleted successfully!')
        return redirect('hr_salary_components')
    return render(request, 'confirm_delete.html', {'object': comp, 'title': 'Delete Salary Component', 'cancel_url': 'hr_salary_components'})


# ─── EMPLOYEES ───────────────────────────────────────────────────────────────
@login_required
@payroll_access
def employees_view(request):
    search = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '')
    employees = Employee.objects.select_related('department', 'designation').all()
    if search:
        employees = employees.filter(
            Q(employee_id__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(cnic__icontains=search) |
            Q(phone__icontains=search)
        )
    if status_filter:
        employees = employees.filter(status=status_filter)
    context = {
        'employees': employees,
        'search': search,
        'status_filter': status_filter,
        'total_count': Employee.objects.count(),
        'active_count': Employee.objects.filter(status='active').count(),
    }
    return render(request, 'hr/employees.html', context)


@login_required
@hr_required
def employee_create_view(request):
    if request.method == 'POST':
        form = EmployeeForm(request.POST)
        if form.is_valid():
            emp = form.save(commit=False)
            emp.created_by = request.user
            emp.save()
            _log(request, 'create', 'Employee', emp.employee_id, f'Created employee {emp.full_name}')
            messages.success(request, f'Employee {emp.employee_id} created successfully!')
            return redirect('hr_employee_detail', pk=emp.pk)
    else:
        form = EmployeeForm()
    return render(request, 'hr/employee_form.html', {'form': form, 'title': 'Add Employee'})


@login_required
@payroll_access
def employee_detail_view(request, pk):
    employee = get_object_or_404(
        Employee.objects.select_related('department', 'designation'), pk=pk)
    salaries = employee.salaries.select_related('component').all()
    documents = employee.documents.all()
    slips = employee.salary_slips.select_related('run').all()
    leaves = employee.leaves.all()[:10]
    return render(request, 'hr/employee_detail.html', {
        'employee': employee,
        'salaries': salaries,
        'documents': documents,
        'slips': slips,
        'leaves': leaves,
        'monthly_gross': employee.monthly_gross,
    })


@login_required
@hr_required
def employee_edit_view(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == 'POST':
        form = EmployeeForm(request.POST, instance=employee)
        if form.is_valid():
            form.save()
            _log(request, 'update', 'Employee', employee.employee_id, f'Updated employee {employee.full_name}')
            messages.success(request, 'Employee updated successfully!')
            return redirect('hr_employee_detail', pk=pk)
    else:
        form = EmployeeForm(instance=employee)
    return render(request, 'hr/employee_form.html', {'form': form, 'title': f'Edit Employee {employee.employee_id}', 'employee': employee})


@login_required
@hr_required
def employee_delete_view(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == 'POST':
        emp_id = employee.employee_id
        employee.delete()
        _log(request, 'delete', 'Employee', emp_id, f'Deleted employee {emp_id}')
        messages.success(request, 'Employee deleted successfully!')
        return redirect('hr_employees')
    return render(request, 'confirm_delete.html', {'object': employee, 'title': 'Delete Employee', 'cancel_url': 'hr_employees'})


# ─── EMPLOYEE SALARY ─────────────────────────────────────────────────────────
@login_required
@hr_required
def employee_salary_add_view(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == 'POST':
        form = EmployeeSalaryForm(request.POST)
        if form.is_valid():
            es = form.save(commit=False)
            es.employee = employee
            es.save()
            _log(request, 'create', 'EmployeeSalary', es.pk, f'Added {es.component.name} to {employee.full_name}')
            messages.success(request, 'Salary component added.')
            return redirect('hr_employee_detail', pk=pk)
    else:
        form = EmployeeSalaryForm()
    return render(request, 'hr/salary_form.html', {'form': form, 'employee': employee, 'title': f'Add Salary Component - {employee.full_name}'})


@login_required
@hr_required
def employee_salary_delete_view(request, pk):
    es = get_object_or_404(EmployeeSalary, pk=pk)
    emp_pk = es.employee.pk
    if request.method == 'POST':
        es.delete()
        messages.success(request, 'Salary component removed.')
    return redirect('hr_employee_detail', pk=emp_pk)


# ─── PAYROLL RUNS ────────────────────────────────────────────────────────────
@login_required
@payroll_access
def payroll_runs_view(request):
    runs = PayrollRun.objects.annotate(count=Count('slips')).all()
    return render(request, 'hr/payroll_runs.html', {'runs': runs})


@login_required
@hr_required
def payroll_run_create_view(request):
    if request.method == 'POST':
        form = PayrollRunForm(request.POST)
        if form.is_valid():
            run = form.save(commit=False)
            run.created_by = request.user
            run.save()
            _log(request, 'create', 'PayrollRun', run.pk, f'Created payroll run {run.period_label}')
            messages.success(request, f'Payroll run {run.period_label} created. Now generate slips.')
            return redirect('hr_payroll_run_detail', pk=run.pk)
    else:
        form = PayrollRunForm(initial={'month': date.today().month, 'year': date.today().year})
    return render(request, 'hr/payroll_run_form.html', {'form': form, 'title': 'New Payroll Run'})


@login_required
@payroll_access
def payroll_run_detail_view(request, pk):
    run = get_object_or_404(PayrollRun.objects.prefetch_related('slips__employee'), pk=pk)
    slips = run.slips.select_related('employee', 'employee__department', 'employee__designation').all()
    context = {
        'run': run,
        'slips': slips,
        'total_net': run.total_net,
        'total_gross': sum((s.gross for s in slips), 0),
    }
    return render(request, 'hr/payroll_run_detail.html', context)


@login_required
@hr_required
def payroll_run_generate_view(request, pk):
    run = get_object_or_404(PayrollRun, pk=pk)
    if request.method == 'POST':
        count = run.generate_slips()
        _log(request, 'create', 'PayrollRun', run.pk, f'Generated {count} slips for {run.period_label}')
        messages.success(request, f'Generated {count} salary slips.')
    return redirect('hr_payroll_run_detail', pk=pk)


@login_required
@hr_required
def payroll_run_process_view(request, pk):
    run = get_object_or_404(PayrollRun, pk=pk)
    if request.method == 'POST':
        with transaction.atomic():
            for slip in run.slips.all():
                slip.recalculate()
                slip.status = 'approved'
                slip.save(update_fields=['status'])
            run.status = 'processed'
            run.save(update_fields=['status'])
        _log(request, 'update', 'PayrollRun', run.pk, f'Processed payroll run {run.period_label}')
        messages.success(request, 'Payroll processed. Slips approved.')
    return redirect('hr_payroll_run_detail', pk=pk)


@login_required
@payroll_access
def payroll_run_pay_view(request, pk):
    run = get_object_or_404(PayrollRun, pk=pk)
    if request.method == 'POST':
        with transaction.atomic():
            paid = 0
            for slip in run.slips.filter(status='approved'):
                payment, created = SalaryPayment.objects.get_or_create(
                    slip=slip,
                    defaults={'amount': slip.net, 'payment_date': date.today(),
                              'method': 'bank_transfer', 'created_by': request.user},
                )
                if created:
                    payment.post_to_ledger()
                slip.status = 'paid'
                slip.save(update_fields=['status'])
                paid += 1
            run.status = 'paid'
            run.save(update_fields=['status'])
        _log(request, 'update', 'PayrollRun', run.pk, f'Paid {paid} salaries for {run.period_label}')
        messages.success(request, f'Paid {paid} salaries and posted to ledger.')
    return redirect('hr_payroll_run_detail', pk=pk)


# ─── SALARY SLIPS ────────────────────────────────────────────────────────────
@login_required
@payroll_access
def salary_slip_detail_view(request, pk):
    slip = get_object_or_404(SalarySlip.objects.select_related('employee', 'run'), pk=pk)
    items = slip.items.select_related('component').all()
    components = SalaryComponent.objects.filter(is_active=True)
    return render(request, 'hr/salary_slip_detail.html', {
        'slip': slip, 'items': items, 'components': components,
    })


@login_required
@hr_required
def salary_slip_add_item_view(request, pk):
    slip = get_object_or_404(SalarySlip, pk=pk)
    if request.method == 'POST':
        component_id = request.POST.get('component')
        amount = request.POST.get('amount', '0')
        try:
            component = SalaryComponent.objects.get(pk=component_id)
            item, created = SalarySlipItem.objects.get_or_create(
                slip=slip, component=component, defaults={'amount': amount})
            if not created:
                item.amount = amount
                item.save()
            slip.recalculate()
            messages.success(request, f'Item {component.name} added/updated.')
        except (SalaryComponent.DoesNotExist, ValueError):
            messages.error(request, 'Invalid component or amount.')
    return redirect('hr_salary_slip_detail', pk=pk)


@login_required
@hr_required
def salary_slip_remove_item_view(request, pk):
    item = get_object_or_404(SalarySlipItem, pk=pk)
    slip_pk = item.slip.pk
    if request.method == 'POST':
        item.delete()
        item.slip.recalculate()
        messages.success(request, 'Item removed.')
    return redirect('hr_salary_slip_detail', pk=slip_pk)


# ─── ATTENDANCE ──────────────────────────────────────────────────────────────
@login_required
@payroll_access
def attendance_view(request):
    date_filter = request.GET.get('date', date.today().isoformat())
    records = Attendance.objects.filter(date=date_filter).select_related('employee').all()
    return render(request, 'hr/attendance.html', {
        'records': records,
        'date_filter': date_filter,
    })


@login_required
@hr_required
def attendance_create_view(request):
    """Bulk attendance marking: all employees on one screen.

    HR sees every employee with a status dropdown (Present / Absent / Leave,
    defaulting to Present). Changing only the exceptions and clicking
    'Mark Attendance' records attendance for the chosen date for everyone.
    Re-marking the same date updates existing records instead of duplicating.
    """
    STATUS_OPTIONS = ['present', 'absent', 'leave']
    employees = (
        Employee.objects
        .filter(status__in=['active', 'on_leave'])
        .select_related('department', 'designation')
        .order_by('first_name', 'last_name')
    )

    if request.method == 'POST':
        att_date_str = request.POST.get('date', '')
        try:
            att_date = date.fromisoformat(att_date_str)
        except ValueError:
            att_date = date.today()

        # Re-marking the same date updates existing rows (no duplicates).
        created = updated = 0
        with transaction.atomic():
            for emp in employees:
                status_value = request.POST.get(f'status_{emp.pk}', 'present')
                if status_value not in STATUS_OPTIONS:
                    status_value = 'present'
                # Employees already on Leave default to 'leave' unless HR
                # explicitly picks something else.
                if status_value == 'present' and emp.status == 'on_leave':
                    status_value = 'leave'
                _, was_created = Attendance.objects.update_or_create(
                    employee=emp,
                    date=att_date,
                    defaults={'status': status_value},
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        _log(request, 'bulk_create', 'Attendance', att_date.isoformat(),
             f'Marked attendance for {att_date}: {created} created, {updated} updated '
             f'across {employees.count()} employees')
        messages.success(
            request,
            f'Attendance marked for {att_date.isoformat()}: '
            f'{created} created, {updated} updated, {employees.count()} employees total.'
        )
        return redirect('hr_attendance')

    # GET: pre-fill today's date and any existing attendance for that date.
    att_date = date.today()
    existing = {
        a.employee_id: a
        for a in Attendance.objects.filter(date=att_date)
    }
    employee_rows = []
    for emp in employees:
        att = existing.get(emp.pk)
        employee_rows.append({
            'employee': emp,
            'status': att.status if att else 'present',
        })

    status_labels = [
        (v, label)
        for v, label in Attendance.STATUS_CHOICES
        if v in STATUS_OPTIONS
    ]

    return render(request, 'hr/attendance_form.html', {
        'title': 'Mark Attendance',
        'employee_rows': employee_rows,
        'att_date': att_date,
        'status_labels': status_labels,
        'employee_count': employees.count(),
    })


# ─── LEAVE ───────────────────────────────────────────────────────────────────
@login_required
@payroll_access
def leaves_view(request):
    status_filter = request.GET.get('status', '')
    leaves = Leave.objects.select_related('employee', 'approved_by').all()
    if status_filter:
        leaves = leaves.filter(status=status_filter)
    context = {
        'leaves': leaves,
        'status_filter': status_filter,
        'pending_count': Leave.objects.filter(status='pending').count(),
    }
    return render(request, 'hr/leaves.html', context)


@login_required
@hr_required
def leave_create_view(request):
    if request.method == 'POST':
        form = LeaveForm(request.POST)
        if form.is_valid():
            leave = form.save()
            _log(request, 'create', 'Leave', leave.pk, f'Leave applied for {leave.employee.full_name}')
            messages.success(request, 'Leave application recorded.')
            return redirect('hr_leaves')
    else:
        form = LeaveForm()
    return render(request, 'hr/leave_form.html', {'form': form, 'title': 'Apply Leave'})


@login_required
@hr_required
def leave_approve_view(request, pk):
    leave = get_object_or_404(Leave, pk=pk)
    if request.method == 'POST':
        action = request.POST.get('action', 'approve')
        leave.status = 'approved' if action == 'approve' else 'rejected'
        leave.approved_by = request.user
        leave.save()
        _log(request, 'update', 'Leave', leave.pk, f'{leave.get_status_display()} leave for {leave.employee.full_name}')
        messages.success(request, f'Leave {leave.get_status_display()}.')
    return redirect('hr_leaves')


@hr_required
def employee_profile_create_view(request):
    """Create an ERP login (username/password) linked to an existing Employee."""
    if request.method == 'POST':
        form = EmployeeProfileForm(request.POST)
        if form.is_valid():
            user = form.save()
            employee = form.cleaned_data['employee']
            _log(request, 'create', 'EmployeeProfile', employee.employee_id,
                 f'Created employee login for {employee.full_name} ({user.username})')
            messages.success(request,
                             f'Employee login created for {employee.full_name} (username: {user.username}).')
            return redirect('hr_employees')
    else:
        form = EmployeeProfileForm()

    return render(request, 'hr/employee_profile_form.html', {
        'form': form,
        'title': 'Create Employee Profile',
    })


@login_required
def my_leave_view(request):
    """Employee-facing Leave portal: their balance and own requests only."""
    employee = getattr(request.user, 'employee', None)
    if employee is None:
        messages.error(request, 'You do not have an employee profile.')
        return redirect('dashboard')

    status_filter = request.GET.get('status', '')
    leaves_qs = Leave.objects.filter(employee=employee).select_related('approved_by')
    leaves = leaves_qs.all()
    if status_filter:
        leaves = leaves.filter(status=status_filter)

    # Balance per leave type: annual allowance minus approved days taken.
    used_by_type = {
        row['leave_type']: row['total']
        for row in leaves_qs.filter(status='approved')
        .values('leave_type').annotate(total=Sum('days'))
    }
    balance_rows = []
    for value, label in Leave.LEAVE_TYPE_CHOICES:
        allowance = LEAVE_POLICY_ALLOWANCES.get(value, 0)
        used = used_by_type.get(value, 0)
        balance_rows.append({
            'value': value,
            'label': label,
            'allowance': allowance,
            'used': used,
            'remaining': max(allowance - used, 0),
        })

    context = {
        'employee': employee,
        'balance_rows': balance_rows,
        'leaves': leaves,
        'status_filter': status_filter,
        'total_requests': leaves_qs.count(),
        'pending_count': leaves_qs.filter(status='pending').count(),
        'approved_count': leaves_qs.filter(status='approved').count(),
        'rejected_count': leaves_qs.filter(status='rejected').count(),
        'annual_remaining': next(
            (row['remaining'] for row in balance_rows if row['value'] == 'annual'), 0),
    }
    return render(request, 'hr/my_leave.html', context)


@login_required
def my_leave_apply_view(request):
    """Employee-facing leave application.

    Employees apply only for their own profile: the employee selector is never
    shown and any posted employee value is ignored — the leave is always bound
    to the logged-in employee. All other fields, validation, styling and
    submission logic are identical to the admin Apply Leave form, and requests
    flow into the same workflow for admin review/approval.
    """
    employee = getattr(request.user, 'employee', None)
    if employee is None:
        messages.error(request, 'You do not have an employee profile.')
        return redirect('hr_my_leave')

    form = LeaveForm(request.POST if request.method == 'POST' else None)
    # Employees apply for themselves; drop the employee picker entirely.
    form.fields.pop('employee')
    # Custom grid layout: Days | Leave Type on row 1, then End date | Start
    # date on row 2, then the Reason field.
    form.fields = {name: form.fields[name]
                   for name in ('days', 'leave_type', 'end_date', 'start_date', 'reason')}
    form.fields['leave_type'].widget.input_type = 'float-select'
    form.fields['leave_type'].label = 'Leave Type'

    if request.method == 'POST':
        if form.is_valid():
            leave = form.save(commit=False)
            leave.employee = employee
            leave.save()
            _log(request, 'create', 'Leave', leave.pk, f'Leave applied for {leave.employee.full_name}')
            messages.success(request, 'Leave application submitted for review.')
            return redirect('hr_my_leave')

    return render(request, 'hr/leave_form.html', {'form': form, 'title': 'Apply Leave'})


# ─── REPORTS ─────────────────────────────────────────────────────────────────
@login_required
@payroll_access
def payroll_report_view(request):
    runs = PayrollRun.objects.order_by('-year', '-month')
    return render(request, 'hr/payroll_report.html', {'runs': runs})
