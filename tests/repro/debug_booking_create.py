"""Debug: reproduce the browser-suite fixture chain and print exact API errors."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'samana_erp.settings')
os.environ.setdefault('DJANGO_DEBUG', 'True')

import django  # noqa: E402
django.setup()

import requests  # noqa: E402

BASE = 'http://127.0.0.1:8000'


def login(s):
    s.get(BASE + '/api/auth/csrf/')
    tok = s.cookies.get('csrftoken', '')
    r = s.post(BASE + '/api/auth/login/', data={'username': 'admin', 'password': 'admin123'},
               headers={'X-CSRFToken': tok})
    # re-read csrf after login (rotate)
    tok = s.cookies.get('csrftoken', '')
    print('login', r.status_code)
    return tok


def main():
    s = requests.Session()
    tok = login(s)
    H = {'X-CSRFToken': tok, 'Content-Type': 'application/json'}
    import json
    import time
    ts = str(int(time.time()))[-6:]

    r = s.post(BASE + '/api/projects/', json={'name': f'QA Debug {ts}', 'location': 'Karachi'}, headers=H)
    print('project', r.status_code, r.text[:200])
    proj = r.json().get('id')

    r = s.post(BASE + '/api/plots/', json={
        'plot_number': f'DBG-{ts}', 'project': proj, 'size_marla': '5.00',
        'price': '108000.00', 'holding_deposit': '10000.00', 'status': 'available',
    }, headers=H)
    print('plot', r.status_code, r.text[:400])
    plot = r.json().get('id')

    r = s.post(BASE + '/api/customers/', json={
        'first_name': 'QA', 'last_name': f'Buyer{ts}', 'email': f'qa{ts}@example.com',
        'phone': f'+92-3{ts}', 'cnic': f'35202-{ts + "0"}-0',
    }, headers=H)
    print('customer', r.status_code, r.text[:300])
    cust = r.json().get('id')

    r = s.post(BASE + '/api/bookings/', json={
        'customer': cust, 'plot': plot, 'total_amount': '108000.00',
        'advance_paid': '10000.00', 'source': 'walk_in',
    }, headers=H)
    print('booking', r.status_code, r.text[:500])


if __name__ == '__main__':
    main()
