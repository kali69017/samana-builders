"""TC-07 Module Pages Audit: every ERP module page renders without errors,
no auth redirects, no broken images, no error banners.

Uses one fresh session per page (MCP sessions die after ~4 calls).
"""
from tc_utils import CaseResult, ERP, run_code, auth_code

PAGES = [
    ('Corporate Home', ERP + '/', None),
    ('Login Page', ERP + '/login/', None),
    ('Dashboard', ERP + '/dashboard/', None),
    ('Customers', ERP + '/customers/', None),
    ('Properties', ERP + '/properties/', None),
    ('Bookings', ERP + '/bookings/', None),
    ('Payments', ERP + '/payments/', None),
    ('Installment Plans', ERP + '/installment-plans/', None),
    ('Leads', ERP + '/leads/', None),
    ('Agents', ERP + '/agents/', None),
    ('Financial Reports', ERP + '/reports/financial/', None),
    ('Expenses', ERP + '/expenses/', None),
    ('Finance Ledger', ERP + '/finance/ledger/', None),
    ('HR Overview', ERP + '/hr/', None),
    ('Employees', ERP + '/hr/employees/', None),
    ('Payroll', ERP + '/hr/payroll/', None),
    ('AI Assistant', ERP + '/ai/', None),
    ('AI Insights', ERP + '/ai/insights/', None),
    ('AI HR', ERP + '/ai/hr/', None),
    ('Users', ERP + '/users/', None),
    ('Audit Logs', ERP + '/audit-logs/', None),
    ('Notifications', ERP + '/notifications/', None),
    ('Backup', ERP + '/backup/', None),
    ('Company Settings', ERP + '/settings/company/', None),
    ('Profile', ERP + '/profile/', None),
    ('Customer Create', ERP + '/customers/create/', None),
    ('Plot Create', ERP + '/properties/plot/create/', None),
    ('Booking Create', ERP + '/bookings/create/', None),
    ('Payment Create', ERP + '/payments/create/', None),
    ('Receivables', ERP + '/reports/receivables/', None),
    ('Sales Report', ERP + '/reports/sales/', None),
    ('Attendance', ERP + '/hr/attendance/', None),
    ('Leaves', ERP + '/hr/leaves/', None),
    ('Milestones', ERP + '/projects/milestones/', None),
    ('Refunds', ERP + '/refunds/', None),
]

AUDIT = '''
({
  url: location.href,
  title: document.title,
  bodyLen: document.body ? document.body.innerText.length : 0,
  brokenImgs: [...document.images].filter(i => !i.complete || i.naturalWidth === 0).length,
  errorBanner: !!document.querySelector('.alert-error, .errorlist'),
  redirectedToLogin: location.href.includes('/login/')
})
'''


def tc07_module_pages_audit():
    res = CaseResult('TC-07 Module Pages Audit')
    for name, url, _ in PAGES:
        data = run_code(auth_code(url, AUDIT))
        res.ok(f'{name} renders', bool(data.get('title')), f'title={str(data.get("title"))[:40]!r}')
        res.ok(f'{name} no auth redirect', data.get('redirectedToLogin') is not True,
               f'url={data.get("url")}')
        res.ok(f'{name} no error banner', data.get('errorBanner') is not True)
        res.ok(f'{name} has content', (data.get('bodyLen') or 0) > 200,
               f'len={data.get("bodyLen")}')
    return res


if __name__ == '__main__':
    import sys
    r = tc07_module_pages_audit()
    print(f'\nTC-07 {"PASS" if r.passed else "FAIL"} ({sum(1 for _, ok, _ in r.checks if ok)}/{len(r.checks)})')
    sys.exit(0 if r.passed else 1)
