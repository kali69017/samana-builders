import re
from django.db import models
from django.contrib.auth.models import User


def format_phone(value):
    digits = re.sub(r'\D', '', value or '')
    if not digits:
        return value
    if digits.startswith('92') and len(digits) == 12:
        local = digits[2:]
    elif digits.startswith('0') and len(digits) == 11:
        local = digits[1:]
    else:
        local = digits
    if len(local) == 10:
        return f"+92-{local[:3]}-{local[3:]}"
    return value


def format_cnic(value):
    digits = re.sub(r'\D', '', value or '')
    if len(digits) == 13:
        return f"{digits[:5]}-{digits[5:12]}-{digits[12:]}"
    return value


class Customer(models.Model):
    OCCUPATION_CHOICES = [
        ('business', 'Business'),
        ('salaried', 'Salaried'),
        ('other', 'Other'),
    ]
    customer_id = models.CharField(max_length=20, unique=True, editable=False)
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True, blank=True, null=True)
    phone = models.CharField(max_length=20)
    alternate_phone = models.CharField(max_length=20, blank=True)
    cnic = models.CharField(max_length=15, unique=True)
    occupation = models.CharField(max_length=20, choices=OCCUPATION_CHOICES, blank=True)
    occupation_other = models.CharField(max_length=100, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    document = models.FileField(upload_to='customers/documents/', blank=True, null=True)
    image = models.ImageField(upload_to='customers/images/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='customers_created')
    
    def save(self, *args, **kwargs):
        if not self.customer_id:
            from django.db import transaction
            with transaction.atomic():
                last_customer = Customer.objects.select_for_update().order_by('-id').first()
                if last_customer:
                    last_num = int(last_customer.customer_id.split('-')[1])
                    self.customer_id = f'CUS-{str(last_num + 1).zfill(5)}'
                else:
                    self.customer_id = 'CUS-00001'
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.customer_id} - {self.first_name} {self.last_name}"
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def formatted_phone(self):
        return format_phone(self.phone)

    @property
    def formatted_alternate_phone(self):
        return format_phone(self.alternate_phone)

    @property
    def formatted_cnic(self):
        return format_cnic(self.cnic)

    @property
    def occupation_display_value(self):
        if self.occupation == 'other':
            return self.occupation_other.strip() or 'Other'
        return dict(self.OCCUPATION_CHOICES).get(self.occupation, '')

    @property
    def total_bookings(self):
        return self.bookings.count()
    
    @property
    def total_paid(self):
        from django.db.models import Sum
        from payments.models import Payment
        result = Payment.objects.filter(booking__customer=self, status='verified').aggregate(total=Sum('amount'))
        return result['total'] or 0
    
    @property
    def current_balance(self):
        total_owed = self.bookings.aggregate(total=models.Sum('total_amount'))['total'] or 0
        return total_owed - self.total_paid
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['cnic']),
            models.Index(fields=['phone']),
        ]


class CustomerLedgerEntry(models.Model):
    TRANSACTION_TYPES = [
        ('booking', 'New Booking'),
        ('payment', 'Payment Received'),
        ('refund', 'Refund Issued'),
        ('late_fee', 'Late Fee Applied'),
        ('waiver', 'Late Fee Waived'),
        ('discount', 'Discount Applied'),
        ('transfer_in', 'Transfer In'),
        ('transfer_out', 'Transfer Out'),
        ('adjustment', 'Manual Adjustment'),
        ('reversal', 'Entry Reversal'),
    ]
    
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='ledger_entries')
    booking = models.ForeignKey('bookings.Booking', on_delete=models.CASCADE, related_name='ledger_entries', null=True, blank=True)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    reference_id = models.CharField(max_length=50, blank=True)
    debit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    running_balance = models.DecimalField(max_digits=15, decimal_places=2)
    description = models.TextField(blank=True)
    entry_date = models.DateField()
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['entry_date', 'created_at']
        verbose_name_plural = 'Customer Ledger Entries'
        indexes = [
            models.Index(fields=['customer', 'entry_date']),
            models.Index(fields=['booking', 'entry_date']),
        ]


class ReceivableAging(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    booking = models.ForeignKey('bookings.Booking', on_delete=models.CASCADE)
    current_balance = models.DecimalField(max_digits=15, decimal_places=2)
    days_overdue = models.IntegerField(default=0)
    aging_bucket = models.CharField(max_length=20, choices=[
        ('current', 'Current (0-30)'),
        ('1_30', '1-30 Days'),
        ('31_60', '31-60 Days'),
        ('61_90', '61-90 Days'),
        ('90_plus', '90+ Days'),
    ])
    computed_at = models.DateField(auto_now_add=True)


class CustomerNominee(models.Model):
    customer = models.OneToOneField(Customer, on_delete=models.CASCADE, related_name='nominee')
    nominee_name = models.CharField(max_length=200)
    nominee_cnic = models.CharField(max_length=15, blank=True)
    nominee_phone = models.CharField(max_length=20, blank=True)
    relationship = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Nominee for {self.customer.full_name}: {self.nominee_name}"

    class Meta:
        verbose_name = 'Customer Nominee'
        verbose_name_plural = 'Customer Nominees'