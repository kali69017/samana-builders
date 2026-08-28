"""TC-08 Evidence Screenshots: capture key pages to research/ui-test/screenshots/."""
import os

from tc_utils import CaseResult, ERP, run_code, SHOT_DIR, login_sessionid

SHOTS = [
    ('Dashboard', ERP + '/dashboard/', 'dashboard.png'),
    ('Customers', ERP + '/customers/', 'customers.png'),
    ('Bookings', ERP + '/bookings/', 'bookings.png'),
    ('Payments', ERP + '/payments/', 'payments.png'),
    ('AI Assistant', ERP + '/ai/', 'ai_assistant.png'),
    ('AI Insights', ERP + '/ai/insights/', 'ai_insights.png'),
    ('AI HR', ERP + '/ai/hr/', 'ai_hr.png'),
]


def tc08_evidence_screenshots():
    res = CaseResult('TC-08 Evidence Screenshots')
    os.makedirs(SHOT_DIR, exist_ok=True)
    sid = login_sessionid()
    for name, url, fname in SHOTS:
        path = os.path.join(SHOT_DIR, fname).replace('\\', '/')
        data = run_code(f'''async (page) => {{
          await page.goto({repr(ERP + '/login/')}, {{waitUntil: 'domcontentloaded', timeout: 15000}});
          await page.waitForTimeout(300);
          await page.evaluate('document.cookie = "sessionid={sid}; path=/"; 1');
          await page.goto({repr(url)}, {{waitUntil: 'domcontentloaded', timeout: 15000}});
          await page.waitForTimeout(700);
          await page.screenshot({{path: {repr(path)}, type: 'png'}});
          return JSON.stringify({{saved: true, url: page.url()}});
        }}''')
        full = os.path.join(SHOT_DIR, fname)
        exists = os.path.exists(full)
        size = os.path.getsize(full) if exists else 0
        res.ok(f'{name} screenshot saved', exists and size > 20000, f'{size} bytes')
    return res


if __name__ == '__main__':
    import sys
    r = tc08_evidence_screenshots()
    print(f'\nTC-08 {"PASS" if r.passed else "FAIL"} ({sum(1 for _, ok, _ in r.checks if ok)}/{len(r.checks)})')
    sys.exit(0 if r.passed else 1)
