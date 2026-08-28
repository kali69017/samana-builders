"""Capture screenshots of key pages for evidence."""
import json
import sys
import time

sys.path.insert(0, 'research')
from pw_client import new_session, curl_rpc

SHOTS = [
    ('dashboard', 'http://127.0.0.1:8000/dashboard/', 'dashboard.png'),
    ('customers', 'http://127.0.0.1:8000/customers/', 'customers.png'),
    ('bookings', 'http://127.0.0.1:8000/bookings/', 'bookings.png'),
    ('payments', 'http://127.0.0.1:8000/payments/', 'payments.png'),
    ('ai_assistant', 'http://127.0.0.1:8000/ai/', 'ai_assistant.png'),
    ('ai_insights', 'http://127.0.0.1:8000/ai/insights/', 'ai_insights.png'),
    ('ai_hr', 'http://127.0.0.1:8000/ai/hr/', 'ai_hr.png'),
]

BASE = 'D:/ERP/samana/research/ui-test/screenshots/'

for name, url, fname in SHOTS:
    sid = new_session()
    code = f'''async (page) => {{
      await page.goto('{url}', {{waitUntil: 'domcontentloaded', timeout: 15000}});
      await page.waitForTimeout(900);
      await page.screenshot({{path: '{BASE}{fname}', type: 'png'}});
      return 'saved ' + page.url();
    }}'''
    resp = curl_rpc('tools/call', {'name': 'browser_run_code_unsafe', 'arguments': {'code': code}}, sid, timeout=30)
    result = resp.get('result', resp)
    text = '\n'.join(c.get('text', '') for c in result.get('content', []) if c.get('type') == 'text') if isinstance(result, dict) else str(result)
    print(f'{name}: {text[:80]}')
