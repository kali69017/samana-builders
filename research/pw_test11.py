"""Test: urllib-based SSE client — does the session survive 5 navigations?"""
import json
import sys
import time
import urllib.request

MCP_URL = 'http://localhost:8931/mcp'


def rpc(method, params, sid, timeout=30):
    payload = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
    req = urllib.request.Request(
        MCP_URL, data=payload.encode(),
        headers={'Content-Type': 'application/json',
                 'Accept': 'application/json, text/event-stream',
                 'Mcp-Session-Id': sid})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode('utf-8', 'ignore')
    data_lines = [l[6:] for l in raw.splitlines() if l.startswith('data: ')]
    if data_lines:
        return json.loads(data_lines[-1])
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {'raw': raw[:200]}


def new_session():
    req = urllib.request.Request(
        MCP_URL, data=json.dumps({
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                       'clientInfo': {'name': 'hermes-qa', 'version': '1.0'}}}).encode(),
        headers={'Content-Type': 'application/json',
                 'Accept': 'application/json, text/event-stream'})
    with urllib.request.urlopen(req, timeout=30) as r:
        sid = r.headers.get('mcp-session-id')
    rpc('notifications/initialized', {}, sid, timeout=20)
    return sid


sid = new_session()
print('session:', sid[:8])

for i, url in enumerate(['http://127.0.0.1:8000/login/',
                         'http://127.0.0.1:8000/',
                         'http://127.0.0.1:8000/login/',
                         'http://127.0.0.1:8000/',
                         'http://127.0.0.1:8000/login/']):
    try:
        r = rpc('tools/call', {'name': 'browser_navigate',
                               'arguments': {'url': url}}, sid, timeout=30)
        txt = json.dumps(r, default=str)[:100]
    except Exception as e:
        txt = f'EXC {e}'
    print(f'nav {i}: {txt}')
    time.sleep(1.2)
