"""Shared helpers for Samana ERP UI test cases (Playwright MCP driver).

Every test case uses ONE fresh MCP session per browser interaction because
the streamable-HTTP MCP server drops sessions after ~4 tool calls. All
browser logic runs through browser_run_code_unsafe, which must complete in
under ~5 seconds (server-side cap).
"""
import json
import os
import subprocess
import sys

TC_DIR = os.path.dirname(os.path.abspath(__file__))          # .../ui-test/testcases
UI_TEST_DIR = os.path.dirname(TC_DIR)                        # .../ui-test
RESEARCH = os.path.dirname(UI_TEST_DIR)                      # .../research
PROJ = os.path.dirname(RESEARCH)                             # D:/ERP/samana
for p in (RESEARCH, UI_TEST_DIR, TC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)
from pw_client import new_session, curl_rpc  # noqa: E402

ERP = 'http://127.0.0.1:8000'
SHOT_DIR = os.path.join(os.path.dirname(__file__), '..', 'screenshots')


class CaseResult:
    def __init__(self, name):
        self.name = name
        self.checks = []

    def ok(self, check_name, cond, detail=''):
        self.checks.append((check_name, bool(cond), detail))
        print(f'  {"PASS" if cond else "FAIL"}  {check_name} {detail}'.rstrip())

    def bad(self, check_name, detail=''):
        self.checks.append((check_name, False, detail))
        print(f'  FAIL  {check_name} {detail}'.rstrip())

    @property
    def passed(self):
        return all(ok for _, ok, _ in self.checks)


def run_code(code, timeout=40):
    """Open a fresh session and run a browser_run_code_unsafe block.

    Returns the parsed JSON payload the page.evaluate returned (or raw text).
    """
    sid = new_session()
    resp = curl_rpc('tools/call', {
        'name': 'browser_run_code_unsafe',
        'arguments': {'code': code},
    }, sid, timeout=timeout)
    result = resp.get('result', resp)
    if isinstance(result, dict) and 'content' in result:
        text = '\n'.join(c.get('text', '')
                         for c in result['content'] if c.get('type') == 'text')
    else:
        text = json.dumps(result, default=str)
    # The tool returns a quoted JSON string after "### Result"
    try:
        idx = text.index('### Result')
        after = text[idx + len('### Result'):].strip()
        if after.startswith('"'):
            return json.loads(json.loads(after.split('\n')[0]))
        if after.startswith('{'):
            return json.loads(after.split('\n')[0])
    except (ValueError, json.JSONDecodeError, IndexError):
        pass
    return {'raw': text[:300]}


def goto_audit_code(url, checks_js):
    """Build a run_code_unsafe block: goto URL, wait, run checks_js.

    checks_js is a JS expression evaluated in the page that must return an
    object (e.g. {title: ..., ok: true}).
    """
    return f'''async (page) => {{
  await page.goto({json.dumps(url)}, {{waitUntil: 'domcontentloaded', timeout: 15000}});
  await page.waitForTimeout(450);
  return JSON.stringify(await page.evaluate(() => ({checks_js})));
}}'''


def login_sessionid(username='admin', password='admin123'):
    """Login via the Django API and return the sessionid cookie value."""
    import http.cookiejar
    import urllib.request
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    req = urllib.request.Request(ERP + '/api/auth/csrf/', method='GET')
    opener.open(req, timeout=15)
    csrf = next((c.value for c in cj if c.name == 'csrftoken'), '')
    req = urllib.request.Request(
        ERP + '/api/auth/login/',
        data=json.dumps({'username': username, 'password': password}).encode(),
        headers={'Content-Type': 'application/json', 'X-CSRFToken': csrf,
                 'Referer': ERP + '/'},
        method='POST')
    opener.open(req, timeout=15)
    return next((c.value for c in cj if c.name == 'sessionid'), '')


def auth_code(url, checks_js):
    """Like goto_audit_code but injects an admin session cookie first.

    Needed because each MCP session starts from the shared browser profile,
    whose auth state is not guaranteed (e.g. after a logout test).
    """
    sid = login_sessionid()
    return f'''async (page) => {{
  await page.goto({json.dumps(ERP + '/login/')}, {{waitUntil: 'domcontentloaded', timeout: 15000}});
  await page.waitForTimeout(300);
  await page.evaluate('document.cookie = "sessionid={sid}; path=/"; 1');
  await page.goto({json.dumps(url)}, {{waitUntil: 'domcontentloaded', timeout: 15000}});
  await page.waitForTimeout(450);
  return JSON.stringify(await page.evaluate(() => ({checks_js})));
}}'''


def main_runner(test_cases):
    """test_cases: list of callables taking no args and returning CaseResult."""
    print(f'\n===== SAMANA ERP UI TEST SUITE =====\n')
    results = []
    for tc in test_cases:
        print(f'\n--- {tc.__name__} ---')
        try:
            res = tc()
        except Exception as e:  # noqa: BLE001
            res = CaseResult(tc.__name__)
            res.bad('unhandled exception', str(e)[:150])
        results.append(res)
    print('\n===== SUMMARY =====')
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f'Test cases passed: {passed}/{total}')
    for r in results:
        print(f'  {"PASS" if r.passed else "FAIL"}  {r.name}  ({sum(1 for _, ok, _ in r.checks if ok)} checks)')
    return 0 if passed == total else 1
