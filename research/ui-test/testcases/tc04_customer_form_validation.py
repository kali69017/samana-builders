"""TC-04 Customer Form: fields render, empty submit shows validation,
invalid phone/CNIC shows field errors."""
from tc_utils import CaseResult, ERP, run_code, login_sessionid


def tc04_customer_form_validation():
    res = CaseResult('TC-04 Customer Form Validation')
    sid = login_sessionid()
    data = run_code(f'''async (page) => {{
      await page.goto('{ERP}/login/', {{waitUntil: 'domcontentloaded', timeout: 15000}});
      await page.waitForTimeout(300);
      await page.evaluate('document.cookie = "sessionid={sid}; path=/"; 1');
      await page.goto('{ERP}/customers/create/', {{waitUntil: 'domcontentloaded', timeout: 15000}});
      await page.waitForTimeout(400);
      const fields = await page.locator('input[name], select[name], textarea[name]').count();
      await page.click('button[type="submit"]');
      await page.waitForTimeout(800);
      const errsEmpty = await page.locator('.errorlist, .form-error, .alert-error').count();
      await page.fill('#id_first_name, input[name="first_name"]', 'Test');
      await page.fill('#id_last_name, input[name="last_name"]', 'User');
      await page.fill('#id_phone, input[name="phone"]', 'abc');
      await page.fill('#id_cnic, input[name="cnic"]', '123');
      await page.click('button[type="submit"]');
      await page.waitForTimeout(800);
      const errsInvalid = await page.locator('.errorlist, .form-error, .alert-error').count();
      return JSON.stringify({{fields, errsEmpty, errsInvalid}});
    }}''')
    res.ok('form has fields', (data.get('fields') or 0) >= 10, f'fields={data.get("fields")}')
    res.ok('empty submit shows validation errors', (data.get('errsEmpty') or 0) >= 3,
           f'errs={data.get("errsEmpty")}')
    res.ok('invalid phone/CNIC shows errors', (data.get('errsInvalid') or 0) >= 1,
           f'errs={data.get("errsInvalid")}')
    return res


if __name__ == '__main__':
    import sys
    r = tc04_customer_form_validation()
    print(f'\nTC-04 {"PASS" if r.passed else "FAIL"} ({sum(1 for _, ok, _ in r.checks if ok)}/{len(r.checks)})')
    sys.exit(0 if r.passed else 1)
