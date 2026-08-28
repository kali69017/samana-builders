"""Minimal Playwright MCP client (streamable HTTP) for UI testing.

Handles initialize handshake, session-id persistence, and tools/call.
Usage:
    python pw_mcp.py tools/list
    python pw_mcp.py browser_navigate '{"url": "http://127.0.0.1:8000/"}'
    python pw_mcp.py browser_snapshot '{}'
"""
import json
import os
import subprocess
import sys
import time

MCP_URL = 'http://localhost:8931/mcp'
SID_CACHE = os.path.join(os.path.dirname(__file__), '.pw_session_id')


def rpc(method, params, session_id=None, timeout=60):
    headers = ['-H', 'Content-Type: application/json',
               '-H', 'Accept: application/json, text/event-stream']
    if session_id:
        headers += ['-H', f'Mcp-Session-Id: {session_id}']
    payload = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
    out = subprocess.run(
        ['curl', '-s', '-X', 'POST', MCP_URL] + headers +
        ['-d', payload, '--max-time', str(timeout)],
        capture_output=True, text=True, timeout=timeout + 10).stdout
    # Parse SSE or JSON response
    data_lines = [l[6:] for l in out.splitlines() if l.startswith('data: ')]
    if data_lines:
        return json.loads(data_lines[-1])
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {'raw': out}


def _new_session():
    import urllib.request
    req = urllib.request.Request(
        MCP_URL, data=json.dumps({
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                       'clientInfo': {'name': 'hermes-qa', 'version': '1.0'}},
        }).encode(),
        headers={'Content-Type': 'application/json',
                 'Accept': 'application/json, text/event-stream'})
    with urllib.request.urlopen(req, timeout=30) as r:
        sid = r.headers.get('mcp-session-id')
    rpc('notifications/initialized', {}, session_id=sid)
    with open(SID_CACHE, 'w') as f:
        f.write(sid)
    return sid


def get_session():
    if os.path.exists(SID_CACHE):
        sid = open(SID_CACHE).read().strip()
        if sid:
            return sid
    return _new_session()


def reset_session():
    if os.path.exists(SID_CACHE):
        os.remove(SID_CACHE)
    return _new_session()


def main():
    cmd = sys.argv[1]
    params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    sid = get_session()
    if cmd == 'tools/list':
        resp = rpc('tools/list', {}, session_id=sid, timeout=30)
        result = resp.get('result', resp)
        tools = result.get('tools', []) if isinstance(result, dict) else []
        for t in tools:
            print(t['name'], '|', (t.get('description') or '')[:100])
        return
    resp = rpc('tools/call', {'name': cmd, 'arguments': params}, session_id=sid, timeout=90)
    result = resp.get('result', resp)
    # Print structured content if present
    if isinstance(result, dict):
        sc = result.get('structuredContent')
        if sc is not None:
            print(json.dumps(sc, indent=2, default=str)[:6000])
        else:
            print(json.dumps(result, indent=2, default=str)[:6000])
    else:
        print(result)


if __name__ == '__main__':
    main()
