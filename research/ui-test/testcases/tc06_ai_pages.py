"""TC-06 AI Pages: Assistant chat UI, Insights controls, HR tool forms render."""
from tc_utils import CaseResult, ERP, run_code, login_sessionid

_SID = None


def _sid():
    global _SID
    if _SID is None:
        _SID = login_sessionid()
    return _SID


def tc06_ai_pages():
    res = CaseResult('TC-06 AI Pages')
    sid = _sid()

    # AI Assistant
    data = run_code(f'''async (page) => {{
      await page.goto('{ERP}/login/', {{waitUntil: 'domcontentloaded', timeout: 15000}});
      await page.waitForTimeout(300);
      await page.evaluate('document.cookie = "sessionid={sid}; path=/"; 1');
      await page.goto('{ERP}/ai/', {{waitUntil: 'domcontentloaded', timeout: 15000}});
      await page.waitForTimeout(450);
      return JSON.stringify(await page.evaluate(() => ({{
        title: document.title,
        hasInput: !!document.querySelector('#chatInput, textarea'),
        hasSend: !!document.querySelector('#chatSendBtn, button[type="submit"]'),
        suggestions: document.querySelectorAll('[data-q]').length
      }})));
    }}''')
    res.ok('AI assistant page renders', 'AI' in str(data.get('title', '')))
    res.ok('chat input present', data.get('hasInput') is True)
    res.ok('send button present', data.get('hasSend') is True)
    res.ok('suggested questions shown', (data.get('suggestions') or 0) >= 3,
           f'suggestions={data.get("suggestions")}')

    # AI Insights
    data = run_code(f'''async (page) => {{
      await page.goto('{ERP}/login/', {{waitUntil: 'domcontentloaded', timeout: 15000}});
      await page.waitForTimeout(300);
      await page.evaluate('document.cookie = "sessionid={sid}; path=/"; 1');
      await page.goto('{ERP}/ai/insights/', {{waitUntil: 'domcontentloaded', timeout: 15000}});
      await page.waitForTimeout(450);
      return JSON.stringify(await page.evaluate(() => ({{
        title: document.title,
        hasGenerate: !!document.querySelector('button, [onclick*="generate"], [id*="generate"], [id*="Insights"]'),
        hasCard: !!document.querySelector('.card, .insights-box, #insightsBox')
      }})));
    }}''')
    res.ok('AI insights page renders', 'Insights' in str(data.get('title', '')))
    res.ok('insights generate control present', data.get('hasGenerate') is True)

    # AI HR
    data = run_code(f'''async (page) => {{
      await page.goto('{ERP}/login/', {{waitUntil: 'domcontentloaded', timeout: 15000}});
      await page.waitForTimeout(300);
      await page.evaluate('document.cookie = "sessionid={sid}; path=/"; 1');
      await page.goto('{ERP}/ai/hr/', {{waitUntil: 'domcontentloaded', timeout: 15000}});
      await page.waitForTimeout(450);
      return JSON.stringify(await page.evaluate(() => ({{
        title: document.title,
        forms: document.querySelectorAll('form, select').length
      }})));
    }}''')
    res.ok('AI HR page renders', 'HR' in str(data.get('title', '')))
    res.ok('AI HR tool controls present', (data.get('forms') or 0) >= 2,
           f'controls={data.get("forms")}')
    return res


if __name__ == '__main__':
    import sys
    r = tc06_ai_pages()
    print(f'\nTC-06 {"PASS" if r.passed else "FAIL"} ({sum(1 for _, ok, _ in r.checks if ok)}/{len(r.checks)})')
    sys.exit(0 if r.passed else 1)
