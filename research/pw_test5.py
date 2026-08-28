"""With --isolated: navigate ERP then snapshot, same session."""
import json
import sys
import time

sys.path.insert(0, 'research')
from pw_test3 import new_session, curl_rpc

sid = new_session()
print('session:', sid[:8], file=sys.stderr)

print('--- navigate ERP ---')
nav = curl_rpc('tools/call', {'name': 'browser_navigate',
                              'arguments': {'url': 'http://127.0.0.1:8000/'}},
               sid, timeout=60)
print('nav:', json.dumps(nav, default=str)[:300])

time.sleep(3)

print('--- snapshot ---')
snap = curl_rpc('tools/call', {'name': 'browser_snapshot', 'arguments': {}},
                sid, timeout=40)
print('snap:', json.dumps(snap, default=str)[:1200])
