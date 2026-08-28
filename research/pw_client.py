"""Shared Playwright MCP client helpers (import-safe, no side effects)."""
import json
import subprocess

MCP_URL = 'http://localhost:8931/mcp'


def curl_rpc(method, params, sid, timeout=40):
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
        return {'raw': out[:500]}


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


def call_tool(sid, name, args, timeout=60):
    resp = curl_rpc('tools/call', {'name': name, 'arguments': args}, sid, timeout=timeout)
    result = resp.get('result', resp)
    if isinstance(result, dict) and 'content' in result:
        texts = [c.get('text', '') for c in result['content'] if c.get('type') == 'text']
        return '\n'.join(texts)
    if isinstance(result, dict) and 'structuredContent' in result:
        return result['structuredContent']
    return result
