"""TC-05 Booking Create Form: customers, plots, installment templates load."""
from tc_utils import CaseResult, ERP, run_code, login_sessionid


def tc05_booking_create_form():
    res = CaseResult('TC-05 Booking Create Form')
    sid = login_sessionid()
    data = run_code(f'''async (page) => {{
      await page.goto('{ERP}/login/', {{waitUntil: 'domcontentloaded', timeout: 15000}});
      await page.waitForTimeout(300);
      await page.evaluate('document.cookie = "sessionid={sid}; path=/"; 1');
      await page.goto('{ERP}/bookings/create/', {{waitUntil: 'domcontentloaded', timeout: 15000}});
      await page.waitForTimeout(500);
      return JSON.stringify(await page.evaluate(() => ({{
        title: document.title,
        customers: document.querySelectorAll('#id_customer option').length,
        plots: document.querySelectorAll('#id_plot option').length,
        templates: document.querySelectorAll('#id_installment_template option, [name="installment_template"] option').length
      }})));
    }}''')
    res.ok('booking create title', 'Booking' in str(data.get('title', '')))
    res.ok('customers populate dropdown', (data.get('customers') or 0) > 0,
           f'customers={data.get("customers")}')
    res.ok('plots populate dropdown', (data.get('plots') or 0) > 0,
           f'plots={data.get("plots")}')
    res.ok('installment templates populate', (data.get('templates') or 0) > 0,
           f'templates={data.get("templates")}')
    return res


if __name__ == '__main__':
    import sys
    r = tc05_booking_create_form()
    print(f'\nTC-05 {"PASS" if r.passed else "FAIL"} ({sum(1 for _, ok, _ in r.checks if ok)}/{len(r.checks)})')
    sys.exit(0 if r.passed else 1)
