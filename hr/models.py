"""HR and Payroll models.

Salary is component-based (industry standard): a ``SalaryComponent`` is a named
earning or deduction; an ``EmployeeSalary`` assigns a monthly value per
component; a ``PayrollRun`` generates a ``SalarySlip`` per employee whose
``SalarySlipItem`` rows carry the actual amounts for that month.
"""
from django.db import models
from django.contrib.auth.models import User


# Annual per-type leave entitlements in days. HR can adjust these numbers;
# an employee's balance = allowance - approved leave days taken.
LEAVE_POLICY_ALLOWANCES = {
    'annual': 18,
    'sick': 10,
    'casual': 6,
}


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class Designation(models.Model):
    title = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['title']


class SalaryComponent(models.Model):
    COMPONENT_TYPE_CHOICES = [
        ('earning', 'Earning'),
        ('deduction', 'Deduction'),
    ]

    name = models.CharField(max_length=100, unique=True)
    component_type = models.CharField(max_length=20, choices=COMPONENT_TYPE_CHOICES, default='earning')
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.get_component_type_display()})"

    class Meta:
        ordering = ['component_type', 'name']


class Employee(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('on_leave', 'On Leave'),
        ('resigned', 'Resigned'),
        ('terminated', 'Terminated'),
    ]

    employee_id = models.CharField(max_length=20, unique=True, editable=False)
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='employee')
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')
    designation = models.ForeignKey(Designation, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')
    joining_date = models.DateField()
    cnic = models.CharField(max_length=15, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='employees_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.employee_id:
            from django.db import transaction
            with transaction.atomic():
                last = Employee.objects.select_for_update().order_by('-id').first()
                num = int(last.employee_id.split('-')[1]) + 1 if last else 1
                self.employee_id = f'EMP-{str(num).zfill(5)}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employee_id} - {self.full_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def monthly_gross(self):
        return sum((es.amount for es in self.salaries.filter(component__component_type='earning')), 0)

    class Meta:
        ordering = ['employee_id']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['department']),
        ]


class EmployeeDocument(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='documents')
    title = models.CharField(max_length=100)
    file = models.FileField(upload_to='employee_documents/%Y/%m/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} - {self.employee.full_name}"


class EmployeeSalary(models.Model):
    """A recurring monthly salary component for an employee."""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='salaries')
    component = models.ForeignKey(SalaryComponent, on_delete=models.CASCADE, related_name='employee_salaries')
    amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    effective_from = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.employee.full_name} - {self.component.name}: {self.amount}"

    class Meta:
        ordering = ['employee', 'component']
        unique_together = ['employee', 'component']
        verbose_name_plural = 'Employee Salaries'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gte=0),
                name='employee_salary_amount_non_negative',
            ),
        ]


class PayrollRun(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('processed', 'Processed'),
        ('paid', 'Paid'),
    ]

    month = models.PositiveIntegerField(choices=[(i, f'{i:02d}') for i in range(1, 13)])
    year = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payroll {self.month:02d}/{self.year}"

    @property
    def period_label(self):
        return f"{self.month:02d}/{self.year}"

    @property
    def total_net(self):
        return sum((s.net for s in self.slips.all()), 0)

    @property
    def total_gross(self):
        return sum((s.gross for s in self.slips.all()), 0)

    @property
    def slip_count(self):
        return self.slips.count()

    def generate_slips(self):
        """Create a salary slip for every active employee from their structure."""
        from django.db import transaction
        active = Employee.objects.filter(status='active').select_related('department', 'designation')
        with transaction.atomic():
            for emp in active:
                slip, created = SalarySlip.objects.get_or_create(employee=emp, run=self)
                if created:
                    for es in emp.salaries.select_related('component'):
                        SalarySlipItem.objects.create(slip=slip, component=es.component, amount=es.amount)
                slip.recalculate()
        return self.slips.count()

    class Meta:
        ordering = ['-year', '-month']
        unique_together = ['month', 'year']


class SalarySlip(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='salary_slips')
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name='slips')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    gross = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_earnings = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    net = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.employee.full_name} - {self.run.period_label}"

    def recalculate(self):
        earnings = sum((i.amount for i in self.items.filter(component__component_type='earning')), 0)
        deductions = sum((i.amount for i in self.items.filter(component__component_type='deduction')), 0)
        self.gross = earnings
        self.total_earnings = earnings
        self.total_deductions = deductions
        self.net = earnings - deductions
        self.save(update_fields=['gross', 'total_earnings', 'total_deductions', 'net'])
        return self.net

    class Meta:
        ordering = ['employee__employee_id']
        unique_together = ['employee', 'run']


class SalarySlipItem(models.Model):
    slip = models.ForeignKey(SalarySlip, on_delete=models.CASCADE, related_name='items')
    component = models.ForeignKey(SalaryComponent, on_delete=models.CASCADE, related_name='slip_items')
    amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.slip.employee.full_name} - {self.component.name}: {self.amount}"

    class Meta:
        ordering = ['component__component_type', 'component__name']
        unique_together = ['slip', 'component']


class SalaryPayment(models.Model):
    METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('online', 'Online'),
    ]

    slip = models.OneToOneField(SalarySlip, on_delete=models.CASCADE, related_name='payment')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_date = models.DateField()
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='bank_transfer')
    reference_number = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment for {self.slip.employee.full_name} - {self.amount}"

    def post_to_ledger(self):
        """Idempotently post a Cash/Bank Payment voucher for this salary payment.

        Spec §3.17: posts against the Salaries head (5200), keyed on
        ``reference_type='SalaryPayment'`` + ``reference_id=self.pk``.
        """
        from decimal import Decimal
        from finance.accounting import (
            cash_bank_head, post_source_voucher, salaries_head, voucher_type_for,
        )
        employee = self.slip.employee
        return post_source_voucher(
            reference_type='SalaryPayment', reference_id=self.pk,
            voucher_type=voucher_type_for(self.method, 'payment'),
            date=self.payment_date,
            narration=f'Salary payment for {employee.full_name} '
                      f'({self.slip.run.period_label})',
            lines=[
                (salaries_head(), self.amount, Decimal('0.00')),
                (cash_bank_head(self.method), Decimal('0.00'), self.amount),
            ],
            user=self.created_by,
        )

    class Meta:
        ordering = ['-payment_date']


class Attendance(models.Model):
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('half_day', 'Half Day'),
        ('leave', 'Leave'),
        ('holiday', 'Holiday'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendance')
    date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='present')
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.employee.full_name} - {self.date} ({self.get_status_display()})"

    class Meta:
        ordering = ['-date']
        unique_together = ['employee', 'date']
        indexes = [models.Index(fields=['date', 'status'])]


class Leave(models.Model):
    LEAVE_TYPE_CHOICES = [
        ('annual', 'Annual'),
        ('sick', 'Sick'),
        ('casual', 'Casual'),
        ('unpaid', 'Unpaid'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leaves')
    leave_type = models.CharField(max_length=20, choices=LEAVE_TYPE_CHOICES, default='annual')
    start_date = models.DateField()
    end_date = models.DateField()
    days = models.PositiveIntegerField(default=1)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='leaves_approved')
    applied_on = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.employee.full_name} - {self.get_leave_type_display()} ({self.start_date} → {self.end_date})"

    class Meta:
        ordering = ['-applied_on']
        indexes = [models.Index(fields=['status'])]
