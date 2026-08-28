"""Isolate the navigate hang: try about:blank first, then the ERP."""
import json
import subprocess
import sys
import time

MCP_URL = 'http://localhost:8931/mcp'


def curl_rpc(method, params, sid, timeout=30):
    payload = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
    cmd = ['curl', '-s', '-N', '-X', 'POST', MCP_URL,
           '-H', 'Content-Type: application/json',
           '-H', 'Accept: application/json, text/event-stream',
           '-H', f'Mcp-Session-Id: {sid}',
           '-d', payload, '--max-time', str(timeout)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10).stdout
    data_lines = [l[6:] for l in out.splitlines() if l.startswith('data: ')]
    if data_lines:
        return json.loads(data_lines[-1])
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {'raw': out[:300]}


def new_session():
    payload = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                          'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                                     'clientInfo': {'name': 'hermes-qa', 'version': '1.0'}}})
    cmd = ['curl', '-s', '-D', '-', '-X', 'POST', MCP_URL,
           '-H', 'Content-Type: application/json',
           '-H', 'Accept: application/json, text/event-stream',
           '-d', payload, '--max-time', '20']
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    sid = ''
    for line in out.splitlines():
        if 'mcp-session-id' in line.lower():
            sid = line.split(':', 1)[1].strip()
    curl_rpc('notifications/initialized', {}, sid, timeout=20)
    return sid


sid = new_session()
print('session:', sid[:8])

# 1) tabs before
print('--- tabs (before) ---')
print(json.dumps(curl_rpc('tools/call', {'name': 'browser_tabs', 'arguments': {'action': 'list'}}, sid), default=str)[:300])

# 2) navigate to about:blank (trivial)
print('--- navigate about:blank ---')
t0 = time.time()
nav = curl_rpc('tools/call', {'name': 'browser_navigate', 'arguments': {'url': 'about:blank'}}, sid, timeout=25)
print('elapsed', round(time.time() - t0, 1), 's')
print(json.dumps(nav, default=str)[:300])

# 3) tabs after
print('--- tabs (after) ---')
print(json.dumps(curl_rpc('tools/call', {'name': 'browser_tabs', 'arguments': {'action': 'list'}}, sid), default=str)[:300])
