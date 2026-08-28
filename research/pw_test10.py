"""Test: do 5 plain navigations survive in one session?"""
import json
import sys
import time

sys.path.insert(0, 'research')
from pw_client import new_session, curl_rpc

sid = new_session()
print('session:', sid[:8])

for i, url in enumerate(['http://127.0.0.1:8000/login/',
                         'http://127.0.0.1:8000/',
                         'http://127.0.0.1:8000/login/',
                         'http://127.0.0.1:8000/',
                         'http://127.0.0.1:8000/login/']):
    r = curl_rpc('tools/call', {'name': 'browser_navigate',
                                'arguments': {'url': url}}, sid, timeout=30)
    txt = json.dumps(r, default=str)[:100]
    print(f'nav {i}: {txt}')
    time.sleep(1.2)
