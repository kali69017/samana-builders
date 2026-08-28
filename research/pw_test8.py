"""Pinpoint: does browser_evaluate (async fetch) followed by navigate kill the session?"""
import json
import sys
import time

sys.path.insert(0, 'research')
from pw_client import new_session, curl_rpc

sid = new_session()
print('session:', sid[:8])

curl_rpc('tools/call', {'name': 'browser_navigate',
                        'arguments': {'url': 'http://127.0.0.1:8000/login/'}}, sid, timeout=30)
time.sleep(1.5)

ev = curl_rpc('tools/call', {'name': 'browser_evaluate', 'arguments': {'function': '''
    async () => {
        const csrf = document.cookie.split('; ').find(c => c.startsWith('csrftoken='));
        const token = csrf ? csrf.split('=')[1] : '';
        const resp = await fetch('/api/auth/login/', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': token},
            body: JSON.stringify({username: 'admin', password: 'admin123'})
        });
        return {status: resp.status};
    }
    '''}}, sid, timeout=30)
print('EVAL:', json.dumps(ev, default=str)[:120])
time.sleep(2)

# Sync call: completing the previous tool's SSE lifecycle prevents the
# next navigate from hitting a "Session not found" race.
sync = curl_rpc('tools/call', {'name': 'browser_tabs', 'arguments': {'action': 'list'}}, sid, timeout=30)
print('SYNC TABS:', json.dumps(sync, default=str)[:120])

nav = curl_rpc('tools/call', {'name': 'browser_navigate',
                              'arguments': {'url': 'http://127.0.0.1:8000/dashboard/'}}, sid, timeout=30)
print('NAV DASH:', json.dumps(nav, default=str)[:200])
