"""Test navigation to different ERP URLs to isolate the hang."""
import json
import subprocess
import sys
import time

sys.path.insert(0, 'research')
from pw_test3 import new_session, curl_rpc

for url in ['http://127.0.0.1:8000/login/',
            'http://127.0.0.1:8000/',
            'http://127.0.0.1:8000/dashboard/']:
    sid = new_session()
    t0 = time.time()
    nav = curl_rpc('tools/call', {'name': 'browser_navigate',
                                  'arguments': {'url': url}},
                   sid, timeout=30)
    dt = round(time.time() - t0, 1)
    txt = json.dumps(nav, default=str)[:150]
    print(f'{url} -> {dt}s {txt}')
    # cleanup: close browser to free the profile
    curl_rpc('tools/call', {'name': 'browser_close', 'arguments': {}}, sid, timeout=15)
    time.sleep(1)
