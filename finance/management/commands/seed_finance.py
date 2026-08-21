"""Seed default offices and expense categories."""
from django.core.management.base import BaseCommand
from finance.models import Office, ExpenseCategory


class Command(BaseCommand):
    help = 'Seed default offices and expense categories.'

    def handle(self, *args, **options):
        Office.objects.get_or_create(name='Head Office', defaults={'office_type': 'head_office'})

        categories = [
            ('Rent', 'rent'), ('Utilities', 'utilities'), ('Internet', 'internet'),
            ('Maintenance', 'maintenance'), ('Stationery', 'stationery'),
            ('Salaries', 'salaries'), ('Miscellaneous', 'misc'),
        ]
        for name, ctype in categories:
            ExpenseCategory.objects.get_or_create(name=name, defaults={'category_type': ctype})

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {Office.objects.count()} offices, {ExpenseCategory.objects.count()} categories.'
        ))
