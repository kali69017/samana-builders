"""Per-page audits: one run_code_unsafe call per page, each under 5s.

Relies on the persistent browser profile (no --isolated) so the login
cookie survives across calls.
"""
import json
import subprocess
import sys
import time

sys.path.insert(0, 'research')
from pw_client import new_session, curl_rpc

PAGES = [
    ('Corporate Home', 'http://127.0.0.1:8000/'),
    ('Login Page', 'http://127.0.0.1:8000/login/'),
    ('Dashboard', 'http://127.0.0.1:8000/dashboard/'),
    ('Customers', 'http://127.0.0.1:8000/customers/'),
    ('Properties', 'http://127.0.0.1:8000/properties/'),
    ('Bookings', 'http://127.0.0.1:8000/bookings/'),
    ('Payments', 'http://127.0.0.1:8000/payments/'),
    ('Installment Plans', 'http://127.0.0.1:8000/installment-plans/'),
    ('Leads', 'http://127.0.0.1:8000/leads/'),
    ('Agents', 'http://127.0.0.1:8000/agents/'),
    ('Financial Reports', 'http://127.0.0.1:8000/reports/financial/'),
    ('Expenses', 'http://127.0.0.1:8000/expenses/'),
    ('Finance Ledger', 'http://127.0.0.1:8000/finance/ledger/'),
    ('HR Overview', 'http://127.0.0.1:8000/hr/'),
    ('Employees', 'http://127.0.0.1:8000/hr/employees/'),
    ('Payroll', 'http://127.0.0.1:8000/hr/payroll/'),
    ('AI Assistant', 'http://127.0.0.1:8000/ai/'),
    ('AI Insights', 'http://127.0.0.1:8000/ai/insights/'),
    ('AI HR', 'http://127.0.0.1:8000/ai/hr/'),
    ('Users', 'http://127.0.0.1:8000/users/'),
    ('Audit Logs', 'http://127.0.0.1:8000/audit-logs/'),
    ('Notifications', 'http://127.0.0.1:8000/notifications/'),
    ('Backup', 'http://127.0.0.1:8000/backup/'),
    ('Company Settings', 'http://127.0.0.1:8000/settings/company/'),
    ('Profile', 'http://127.0.0.1:8000/profile/'),
    ('Customer Create', 'http://127.0.0.1:8000/customers/create/'),
    ('Plot Create', 'http://127.0.0.1:8000/properties/plot/create/'),
    ('Booking Create', 'http://127.0.0.1:8000/bookings/create/'),
    ('Payment Create', 'http://127.0.0.1:8000/payments/create/'),
    ('Receivables', 'http://127.0.0.1:8000/reports/receivables/'),
    ('Sales Report', 'http://127.0.0.1:8000/reports/sales/'),
    ('Attendance', 'http://127.0.0.1:8000/hr/attendance/'),
    ('Leaves', 'http://127.0.0.1:8000/hr/leaves/'),
    ('Milestones', 'http://127.0.0.1:8000/projects/milestones/'),
    ('Refunds', 'http://127.0.0.1:8000/refunds/'),
]

AUDIT_CODE = '''async (page) => {
  const errors = [];
  page.on('pageerror', e => errors.push(String(e).slice(0, 100)));
  await page.goto(URL, {waitUntil: 'domcontentloaded', timeout: 15000});
  await page.waitForTimeout(400);
  const r = await page.evaluate(() => {
    const o = {};
    o.url = location.href;
    o.title = document.title;
    o.bodyLen = document.body ? document.body.innerText.length : 0;
    o.brokenImgs = [...document.images].filter(i => !i.complete || i.naturalWidth === 0).length;
    o.errorBanner = !!document.querySelector('.alert-error, .errorlist');
    o.redirectedToLogin = location.href.includes('/login/');
    return o;
  });
  return JSON.stringify({audit: r, errors});
}'''


def run():
    results = []
    for name, url in PAGES:
        sid = new_session()  # fresh session per page — sessions die after ~4 calls
        code = AUDIT_CODE.replace('URL', json.dumps(url))
        t0 = time.time()
        resp = curl_rpc('tools/call', {
            'name': 'browser_run_code_unsafe', 'arguments': {'code': code}}, sid, timeout=30)
        dt = round(time.time() - t0, 1)
        result = resp.get('result', resp)
        text = ''
        if isinstance(result, dict) and 'content' in result:
            text = '\n'.join(c.get('text', '') for c in result['content'] if c.get('type') == 'text')
        else:
            text = json.dumps(result, default=str)
        # extract JSON result if present
        parsed = None
        try:
            start = text.index('{')
            parsed = json.loads(text[start:text.rindex('}') + 1])
        except (ValueError, json.JSONDecodeError):
            parsed = {'raw': text[:120]}
        status = 'OK'
        if parsed.get('audit', {}).get('redirectedToLogin'):
            status = 'AUTH'
        if parsed.get('raw', '').startswith('Session') or 'Error' in text[:60]:
            status = 'ERR'
        results.append((name, url, status, dt, parsed))
        print(f'{status:4s} {dt:5.1f}s {name}')
    return results


if __name__ == '__main__':
    run()
