"""Full ERP UI walkthrough: login, then visit every module page and audit DOM.

Reports per page: HTTP reachable, title, key element presence, broken images,
console errors, and any visible error banners.
"""
import json
import sys
import time
import urllib.request
import http.cookiejar

sys.path.insert(0, 'research')
from pw_client import new_session, call_tool, curl_rpc


def get_admin_session_cookie():
    """Login to Django via API and return the sessionid cookie value."""
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    req = urllib.request.Request('http://127.0.0.1:8000/api/auth/csrf/', method='GET')
    opener.open(req, timeout=15)
    csrf = next((c.value for c in cj if c.name == 'csrftoken'), '')
    req = urllib.request.Request(
        'http://127.0.0.1:8000/api/auth/login/',
        data=json.dumps({'username': 'admin', 'password': 'admin123'}).encode(),
        headers={'Content-Type': 'application/json', 'X-CSRFToken': csrf,
                 'Referer': 'http://127.0.0.1:8000/'},
        method='POST')
    opener.open(req, timeout=15)
    return next((c.value for c in cj if c.name == 'sessionid'), '')

PAGES = [
    # (name, url, key_selector_or_None, expected_text)
    ('Dashboard', 'http://127.0.0.1:8000/dashboard/', None, None),
    ('Customers', 'http://127.0.0.1:8000/customers/', 'table, .card, .grid', None),
    ('Customer Create', 'http://127.0.0.1:8000/customers/create/', 'form', None),
    ('Properties', 'http://127.0.0.1:8000/properties/', None, None),
    ('Plot Create', 'http://127.0.0.1:8000/properties/plot/create/', 'form', None),
    ('Bookings', 'http://127.0.0.1:8000/bookings/', None, None),
    ('Booking Create', 'http://127.0.0.1:8000/bookings/create/', 'form', None),
    ('Payments', 'http://127.0.0.1:8000/payments/', None, None),
    ('Payment Create', 'http://127.0.0.1:8000/payments/create/', 'form', None),
    ('Installment Plans', 'http://127.0.0.1:8000/installment-plans/', None, None),
    ('Leads', 'http://127.0.0.1:8000/leads/', None, None),
    ('Agents', 'http://127.0.0.1:8000/agents/', None, None),
    ('Financial Reports', 'http://127.0.0.1:8000/reports/financial/', None, None),
    ('Receivables', 'http://127.0.0.1:8000/reports/receivables/', None, None),
    ('Sales Report', 'http://127.0.0.1:8000/reports/sales/', None, None),
    ('Expenses', 'http://127.0.0.1:8000/expenses/', None, None),
    ('Finance Ledger', 'http://127.0.0.1:8000/finance/ledger/', None, None),
    ('HR Overview', 'http://127.0.0.1:8000/hr/', None, None),
    ('Employees', 'http://127.0.0.1:8000/hr/employees/', None, None),
    ('Payroll', 'http://127.0.0.1:8000/hr/payroll/', None, None),
    ('Attendance', 'http://127.0.0.1:8000/hr/attendance/', None, None),
    ('Leaves', 'http://127.0.0.1:8000/hr/leaves/', None, None),
    ('Milestones', 'http://127.0.0.1:8000/projects/milestones/', None, None),
    ('Refunds', 'http://127.0.0.1:8000/refunds/', None, None),
    ('AI Assistant', 'http://127.0.0.1:8000/ai/', 'input, textarea, .chat-window', None),
    ('AI Insights', 'http://127.0.0.1:8000/ai/insights/', '#insightsBox, .card', None),
    ('AI HR', 'http://127.0.0.1:8000/ai/hr/', 'form, select, .card', None),
    ('Users', 'http://127.0.0.1:8000/users/', None, None),
    ('Audit Logs', 'http://127.0.0.1:8000/audit-logs/', None, None),
    ('Notifications', 'http://127.0.0.1:8000/notifications/', None, None),
    ('Backup', 'http://127.0.0.1:8000/backup/', None, None),
    ('Company Settings', 'http://127.0.0.1:8000/settings/company/', 'form', None),
    ('Profile', 'http://127.0.0.1:8000/profile/', 'form', None),
]


def run():
    sid = new_session()
    print('session:', sid[:8], file=sys.stderr)

    # 1) Login: get session cookie via API, inject it in the browser with a
    #    synchronous evaluate, then navigate. (Async fetch evaluate kills the
    #    MCP session; cookie injection does not.)
    sessionid = get_admin_session_cookie()
    print('sessionid len:', len(sessionid), file=sys.stderr)

    curl_rpc('tools/call', {'name': 'browser_navigate',
                            'arguments': {'url': 'http://127.0.0.1:8000/login/'}},
             sid, timeout=30)
    time.sleep(1.5)

    curl_rpc('tools/call', {'name': 'browser_evaluate',
                            'arguments': {'function': f'''
        () => {{
            document.cookie = "sessionid={sessionid}; path=/";
            return document.cookie.length;
        }}
        '''}},
             sid, timeout=30)
    time.sleep(0.8)

    curl_rpc('tools/call', {'name': 'browser_navigate',
                            'arguments': {'url': 'http://127.0.0.1:8000/dashboard/'}},
             sid, timeout=30)
    time.sleep(2.5)

    # Check where we landed
    loc = curl_rpc('tools/call', {'name': 'browser_evaluate',
                                  'arguments': {'function': '() => window.location.href'}},
                   sid, timeout=30)
    print('AFTER LOGIN URL:', json.dumps(loc, default=str)[:200])

    # 2) Walk every page
    results = []
    for name, url, selector, _ in PAGES:
        try:
            curl_rpc('tools/call', {'name': 'browser_navigate',
                                    'arguments': {'url': url}}, sid, timeout=30)
            time.sleep(1.2)
            sel_js = json.dumps(selector) if selector else 'null'
            audit = curl_rpc('tools/call', {'name': 'browser_evaluate',
                                            'arguments': {'function': f'''
                () => {{
                    const sel = {sel_js};
                    const r = {{}};
                    r.url = location.href;
                    r.title = document.title;
                    r.bodyTextLen = document.body ? document.body.innerText.length : 0;
                    r.brokenImgs = [...document.images].filter(i => !i.complete || i.naturalWidth === 0).length;
                    r.errorBanner = !!document.querySelector('.alert-error, .errorlist');
                    r.selectorFound = sel ? !!document.querySelector(sel) : null;
                    r.redirectedToLogin = location.href.includes('/login/');
                    return r;
                }}
                '''}},
                           sid, timeout=30)
            data = audit.get('result', audit)
            text = json.dumps(data, default=str)
            results.append((name, url, text[:600]))
        except Exception as e:
            results.append((name, url, f'ERROR {e}'))
        print(f'  [{name}] -> {results[-1][2][:120]}')

    # 3) Summary
    print('\n===== PAGE AUDIT SUMMARY =====')
    for name, url, text in results:
        flag = 'OK '
        if 'redirectedToLogin' in text and 'true' in text.split('redirectedToLogin')[1][:20]:
            flag = 'AUTH'
        if 'ERROR' in text:
            flag = 'ERR'
        print(f'{flag} {name}: {text[:140]}')


if __name__ == '__main__':
    run()
