"""Seed default HR lookups: departments, designations and salary components."""
from django.core.management.base import BaseCommand
from hr.models import Department, Designation, SalaryComponent


class Command(BaseCommand):
    help = 'Seed default HR departments, designations and salary components.'

    def handle(self, *args, **options):
        departments = ['Administration', 'Sales & Marketing', 'Accounts & Finance',
                       'Human Resources', 'Engineering', 'Project Management']
        designations = ['General Manager', 'Accountant', 'Sales Executive', 'HR Officer',
                        'Project Manager', 'Site Engineer', 'Office Assistant']

        components = [
            ('Basic Salary', 'earning'),
            ('House Rent Allowance', 'earning'),
            ('Medical Allowance', 'earning'),
            ('Transport Allowance', 'earning'),
            ('Other Allowance', 'earning'),
            ('Overtime', 'earning'),
            ('Bonus', 'earning'),
            ('Income Tax', 'deduction'),
            ('Advance Deduction', 'deduction'),
            ('Loan Deduction', 'deduction'),
        ]

        for name in departments:
            Department.objects.get_or_create(name=name)
        for title in designations:
            Designation.objects.get_or_create(title=title)
        for name, ctype in components:
            SalaryComponent.objects.get_or_create(name=name, defaults={'component_type': ctype})

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {Department.objects.count()} departments, '
            f'{Designation.objects.count()} designations, '
            f'{SalaryComponent.objects.count()} salary components.'
        ))
