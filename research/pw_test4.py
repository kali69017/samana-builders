"""Navigate to the ERP with generous timeout; report what comes back."""
import json
import sys
import time

sys.path.insert(0, 'research')
from pw_test3 import new_session, curl_rpc

sid = new_session()
print('session:', sid[:8], file=sys.stderr)

print('--- navigate ERP (60s timeout) ---')
t0 = time.time()
nav = curl_rpc('tools/call', {'name': 'browser_navigate',
                              'arguments': {'url': 'http://127.0.0.1:8000/'}},
               sid, timeout=60)
print('elapsed', round(time.time() - t0, 1), 's')
print(json.dumps(nav, default=str)[:600])
