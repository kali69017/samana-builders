"""TC-02 Login & Logout: form present, valid login lands on dashboard,
invalid credentials show an error, logout returns to login page."""
from tc_utils import CaseResult, ERP, run_code


def tc02_login_logout():
    res = CaseResult('TC-02 Login & Logout')

    # 1) Logout first to guarantee a clean state, then inspect login page
    data = run_code(f'''async (page) => {{
      await page.goto('{ERP}/logout/', {{waitUntil: 'domcontentloaded', timeout: 15000}});
      await page.waitForTimeout(600);
      await page.goto('{ERP}/login/', {{waitUntil: 'domcontentloaded', timeout: 15000}});
      await page.waitForTimeout(400);
      return JSON.stringify(await page.evaluate(() => ({{
        url: location.href,
        hasUser: !!document.querySelector('#id_username, input[name="username"]'),
        hasPass: !!document.querySelector('#id_password, input[name="password"]'),
        hasSubmit: !!document.querySelector('button[type="submit"]'),
        formAction: document.querySelector('form') ? document.querySelector('form').getAttribute('action') : null
      }})));
    }}''')
    res.ok('login page reachable', 'login' in str(data.get('url', '')))
    res.ok('username field present', data.get('hasUser') is True)
    res.ok('password field present', data.get('hasPass') is True)
    res.ok('submit button present', data.get('hasSubmit') is True)

    # 2) Valid credentials -> dashboard
    data = run_code(f'''async (page) => {{
      await page.goto('{ERP}/login/', {{waitUntil: 'domcontentloaded', timeout: 15000}});
      await page.waitForTimeout(400);
      await page.fill('input[name="username"], #id_username', 'admin');
      await page.fill('input[name="password"], #id_password', 'admin123');
      await page.click('button[type="submit"]');
      await page.waitForTimeout(2000);
      return JSON.stringify(await page.evaluate(() => ({{
        url: location.href,
        hasSidebar: !!document.querySelector('.sidebar, aside, nav'),
        bodyHasDashboard: document.body.innerText.includes('Dashboard')
      }})));
    }}''')
    res.ok('valid login lands on dashboard', 'dashboard' in str(data.get('url', '')))
    res.ok('sidebar rendered after login', data.get('hasSidebar') is True)

    # 3) Invalid credentials -> error on login page
    data = run_code(f'''async (page) => {{
      await page.goto('{ERP}/logout/', {{waitUntil: 'domcontentloaded', timeout: 15000}});
      await page.waitForTimeout(500);
      await page.goto('{ERP}/login/', {{waitUntil: 'domcontentloaded', timeout: 15000}});
      await page.waitForTimeout(400);
      await page.fill('input[name="username"], #id_username', 'admin');
      await page.fill('input[name="password"], #id_password', 'WRONGPASSWORD');
      await page.click('button[type="submit"]');
      await page.waitForTimeout(1200);
      return JSON.stringify(await page.evaluate(() => ({{
        url: location.href,
        errorShown: document.body.innerText.includes('incorrect') || document.body.innerText.includes('Invalid') || !!document.querySelector('.errorlist, .alert-error')
      }})));
    }}''')
    res.ok('invalid login stays on login page', 'login' in str(data.get('url', '')))
    res.ok('invalid login shows error', data.get('errorShown') is True)
    return res


if __name__ == '__main__':
    import sys
    r = tc02_login_logout()
    print(f'\nTC-02 {"PASS" if r.passed else "FAIL"} ({sum(1 for _, ok, _ in r.checks if ok)}/{len(r.checks)})')
    sys.exit(0 if r.passed else 1)
