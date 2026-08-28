async (page) => {
  const results = [];
  const consoleErrors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 150));
  });
  page.on('pageerror', err => consoleErrors.push('PAGEERROR: ' + String(err).slice(0, 150)));

  const login = async () => {
    await page.goto('http://127.0.0.1:8000/login/', {waitUntil: 'domcontentloaded', timeout: 20000});
    await page.fill('input[name="username"], #id_username', 'admin');
    await page.fill('input[name="password"], #id_password', 'admin123');
    await Promise.all([
      page.waitForNavigation({waitUntil: 'domcontentloaded', timeout: 20000}).catch(() => {}),
      page.click('button[type="submit"]')
    ]);
    await page.waitForTimeout(1500);
  };

  const audit = async (name, url) => {
    try {
      await page.goto(url, {waitUntil: 'domcontentloaded', timeout: 20000});
      await page.waitForTimeout(1200);
      const data = await page.evaluate(() => {
        const r = {};
        r.url = location.href;
        r.title = document.title;
        r.bodyLen = document.body ? document.body.innerText.length : 0;
        r.brokenImgs = [...document.images].filter(i => !i.complete || i.naturalWidth === 0).length;
        r.errorBanner = !!document.querySelector('.alert-error, .errorlist');
        r.redirectedToLogin = location.href.includes('/login/');
        return r;
      });
      results.push({name, ...data});
      return `OK ${name}`;
    } catch (e) {
      results.push({name, error: String(e).slice(0, 120)});
      return `ERR ${name}: ${String(e).slice(0, 80)}`;
    }
  };

  // Corporate site
  await audit('Corporate Home', 'http://127.0.0.1:8000/');
  await audit('Login Page', 'http://127.0.0.1:8000/login/');

  // Authenticated walk
  await login();
  const pages = [
    ['Dashboard', 'http://127.0.0.1:8000/dashboard/'],
    ['Customers', 'http://127.0.0.1:8000/customers/'],
    ['Customer Create', 'http://127.0.0.1:8000/customers/create/'],
    ['Properties', 'http://127.0.0.1:8000/properties/'],
    ['Plot Create', 'http://127.0.0.1:8000/properties/plot/create/'],
    ['Bookings', 'http://127.0.0.1:8000/bookings/'],
    ['Booking Create', 'http://127.0.0.1:8000/bookings/create/'],
    ['Payments', 'http://127.0.0.1:8000/payments/'],
    ['Payment Create', 'http://127.0.0.1:8000/payments/create/'],
    ['Installment Plans', 'http://127.0.0.1:8000/installment-plans/'],
    ['Leads', 'http://127.0.0.1:8000/leads/'],
    ['Agents', 'http://127.0.0.1:8000/agents/'],
    ['Financial Reports', 'http://127.0.0.1:8000/reports/financial/'],
    ['Receivables', 'http://127.0.0.1:8000/reports/receivables/'],
    ['Sales Report', 'http://127.0.0.1:8000/reports/sales/'],
    ['Expenses', 'http://127.0.0.1:8000/expenses/'],
    ['Finance Ledger', 'http://127.0.0.1:8000/finance/ledger/'],
    ['HR Overview', 'http://127.0.0.1:8000/hr/'],
    ['Employees', 'http://127.0.0.1:8000/hr/employees/'],
    ['Payroll', 'http://127.0.0.1:8000/hr/payroll/'],
    ['Attendance', 'http://127.0.0.1:8000/hr/attendance/'],
    ['Leaves', 'http://127.0.0.1:8000/hr/leaves/'],
    ['Milestones', 'http://127.0.0.1:8000/projects/milestones/'],
    ['Refunds', 'http://127.0.0.1:8000/refunds/'],
    ['AI Assistant', 'http://127.0.0.1:8000/ai/'],
    ['AI Insights', 'http://127.0.0.1:8000/ai/insights/'],
    ['AI HR', 'http://127.0.0.1:8000/ai/hr/'],
    ['Users', 'http://127.0.0.1:8000/users/'],
    ['Audit Logs', 'http://127.0.0.1:8000/audit-logs/'],
    ['Notifications', 'http://127.0.0.1:8000/notifications/'],
    ['Backup', 'http://127.0.0.1:8000/backup/'],
    ['Company Settings', 'http://127.0.0.1:8000/settings/company/'],
    ['Profile', 'http://127.0.0.1:8000/profile/']
  ];
  const lines = [];
  for (const [name, url] of pages) {
    lines.push(await audit(name, url));
  }
  results.push({name: '__CONSOLE_ERRORS__', errors: consoleErrors.slice(0, 50)});
  return JSON.stringify(results, null, 1);
}
