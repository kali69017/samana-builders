"""Idempotent seed of QA role users + a portal customer (non-staff, no UserProfile).

Run from the repo root:
    env -u PYTHONPATH DJANGO_DEBUG=True /d/samana/.venv312/Scripts/python.exe tests/fixtures/seed_roles.py

Creates (password 'admin123' for all):
  qa_management (role management), qa_accounts (accounts), qa_sales (sales),
  qa_hr (hr)  — all is_staff=True, with UserProfile.
  qa_customer  — is_staff=False, linked to a Customer, NO UserProfile (matches the
                 privilege-escalation "customer with no profile" scenario).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'samana_erp.settings')
os.environ.setdefault('DJANGO_DEBUG', 'True')

import django  # noqa: E402

django.setup()

from django.contrib.auth.models import User  # noqa: E402
from core.models import UserProfile  # noqa: E402
from customers.models import Customer  # noqa: E402

PWD = 'admin123'

for uname, role in [
    ('qa_management', 'management'),
    ('qa_accounts', 'accounts'),
    ('qa_sales', 'sales'),
    ('qa_hr', 'hr'),
]:
    u, created = User.objects.get_or_create(username=uname, defaults={'is_staff': True})
    if created:
        u.set_password(PWD)
        u.is_staff = True
        u.is_superuser = False
        u.save()
    UserProfile.objects.update_or_create(user=u, defaults={'role': role})
    print(f'role user {uname}: {role} ({ "created" if created else "exists" })')

cu, created = User.objects.get_or_create(username='qa_customer', defaults={'is_staff': False})
if created:
    cu.set_password(PWD)
    cu.is_staff = False
    cu.is_superuser = False
    cu.save()
UserProfile.objects.filter(user=cu).delete()
c, ccreated = Customer.objects.get_or_create(
    user=cu,
    defaults=dict(
        first_name='QA', last_name='Customer', email='qa.customer.qa@example.com',
        phone='+92-300-8888888', cnic='35202-8888888-8',
        address='QA Address', city='Lahore',
    ),
)
print(f'portal customer {cu.username} ({ "new" if created else "exists" }) '
      f'-> customer {c.customer_id} ({ "new" if ccreated else "exists" }), is_staff={cu.is_staff}')
print('DONE')
