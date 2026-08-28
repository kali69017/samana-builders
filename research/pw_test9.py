"""Login via curl cookie injection, then navigate. Avoids async evaluate."""
import json
import sys
import time
import urllib.request
import http.cookiejar

sys.path.insert(0, 'research')
from pw_client import new_session, curl_rpc

# 1) Get a session cookie from Django via curl (API login)
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
req = urllib.request.Request('http://127.0.0.1:8000/api/auth/csrf/', method='GET')
opener.open(req, timeout=15)
csrf = next((c.value for c in cj if c.name == 'csrftoken'), '')
req = urllib.request.Request(
    'http://127.0.0.1:8000/api/auth/login/',
    data=json.dumps({'username': 'admin', 'password': 'admin123'}).encode(),
    headers={'Content-Type': 'application/json', 'X-CSRFToken': csrf,
             'Referer': 'http://127.0.0.1:8000/api/auth/csrf/'},
    method='POST')
opener.open(req, timeout=15)
sessionid = next((c.value for c in cj if c.name == 'sessionid'), '')
print('sessionid len:', len(sessionid))

# 2) Open browser, inject cookie synchronously, navigate
sid = new_session()
curl_rpc('tools/call', {'name': 'browser_navigate',
                        'arguments': {'url': 'http://127.0.0.1:8000/login/'}}, sid, timeout=30)
time.sleep(1.5)

inject = curl_rpc('tools/call', {'name': 'browser_evaluate', 'arguments': {'function': f'''
    () => {{
        document.cookie = "sessionid={sessionid}; path=/";
        return document.cookie;
    }}
    '''}}, sid, timeout=30)
print('INJECT:', json.dumps(inject, default=str)[:150])

time.sleep(1)
nav = curl_rpc('tools/call', {'name': 'browser_navigate',
                              'arguments': {'url': 'http://127.0.0.1:8000/dashboard/'}}, sid, timeout=30)
print('NAV DASH:', json.dumps(nav, default=str)[:200])
