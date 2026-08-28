"""Full UI audit: one fresh session per page, parse results, save JSON report."""
import json
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

CODE = '''async (page) => {
  const errors = [];
  page.on('pageerror', e => errors.push('PAGEERROR: ' + String(e).slice(0, 120)));
  await page.goto(URL, {waitUntil: 'domcontentloaded', timeout: 15000});
  await page.waitForTimeout(500);
  const r = await page.evaluate(() => {
    const o = {};
    o.url = location.href;
    o.title = document.title;
    o.bodyLen = document.body ? document.body.innerText.length : 0;
    o.brokenImgs = [...document.images].filter(i => !i.complete || i.naturalWidth === 0).length;
    o.errorBanner = !!document.querySelector('.alert-error, .errorlist');
    o.redirectedToLogin = location.href.includes('/login/');
    o.h1 = document.querySelector('h1') ? document.querySelector('h1').textContent.trim() : null;
    return o;
  });
  return JSON.stringify({audit: r, errors});
}'''


def main():
    results = []
    for name, url in PAGES:
        sid = new_session()
        code = CODE.replace('URL', json.dumps(url))
        t0 = time.time()
        resp = curl_rpc('tools/call', {'name': 'browser_run_code_unsafe',
                                       'arguments': {'code': code}}, sid, timeout=30)
        dt = round(time.time() - t0, 1)
        result = resp.get('result', resp)
        text = ''
        if isinstance(result, dict) and 'content' in result:
            text = '\n'.join(c.get('text', '') for c in result['content'] if c.get('type') == 'text')
        else:
            text = json.dumps(result, default=str)
        # find the JSON: it appears as a quoted string right after "### Result"
        parsed = {'raw': text[:100]}
        try:
            idx = text.index('### Result')
            after = text[idx + len('### Result'):].strip()
            if after.startswith('"'):
                # escaped JSON string
                parsed = json.loads(json.loads(after.split('\n')[0]))
            elif after.startswith('{'):
                parsed = json.loads(after.split('\n')[0])
        except (ValueError, json.JSONDecodeError, IndexError):
            pass
        audit = parsed.get('audit', {})
        status = 'ERR' if (parsed.get('raw', '').startswith('Session') or 'Error' in text[:80] and '### Result' not in text) else 'OK'
        if audit.get('redirectedToLogin'):
            status = 'AUTH'
        results.append({
            'name': name, 'url': url, 'status': status, 'seconds': dt,
            'title': audit.get('title'), 'bodyLen': audit.get('bodyLen'),
            'brokenImgs': audit.get('brokenImgs'), 'errorBanner': audit.get('errorBanner'),
            'redirectedToLogin': audit.get('redirectedToLogin'), 'h1': audit.get('h1'),
            'finalUrl': audit.get('url'), 'jsErrors': parsed.get('errors', []),
        })
        print(f"{status:4s} {dt:5.1f}s {name:22s} title={str(audit.get('title'))[:35]!r} bodyLen={audit.get('bodyLen')} brk={audit.get('brokenImgs')}")

    with open('research/ui-test/ui_audit_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=1, default=str)

    print('\n===== SUMMARY =====')
    ok = sum(1 for r in results if r['status'] == 'OK')
    auth = sum(1 for r in results if r['status'] == 'AUTH')
    err = sum(1 for r in results if r['status'] == 'ERR')
    print(f'OK: {ok}  AUTH-REDIRECT: {auth}  ERR: {err}  total: {len(results)}')
    print('Report saved to research/ui-test/ui_audit_results.json')


if __name__ == '__main__':
    main()
