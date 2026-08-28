"""Run full UI test via browser_run_code_unsafe, capture response directly."""
import json
import sys

sys.path.insert(0, 'research')
from pw_client import new_session, curl_rpc

with open('research/ui_full_test.js', encoding='utf-8') as f:
    code = f.read()

sid = new_session()
print('session:', sid[:8], file=sys.stderr)

resp = curl_rpc('tools/call', {
    'name': 'browser_run_code_unsafe',
    'arguments': {'code': code},
}, sid, timeout=400)

result = resp.get('result', resp)
if isinstance(result, dict) and 'content' in result:
    texts = [c.get('text', '') for c in result['content'] if c.get('type') == 'text']
    out = '\n'.join(texts)
else:
    out = json.dumps(result, default=str)

print(out[:15000])
