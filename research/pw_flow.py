"""Single-process Playwright MCP driver: keeps one session alive for the
whole test flow. Run: python research/pw_flow.py <command> [json args]

Commands: navigate <url>, snapshot, click <ref>, type <ref> <text>,
screenshot <path>, console, eval <js>, wait <ms>, select <ref> <value>
"""
import json
import subprocess
import sys
import time

MCP_URL = 'http://localhost:8931/mcp'


def rpc(method, params, session_id, timeout=90):
    import urllib.request
    payload = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
    req = urllib.request.Request(
        MCP_URL, data=payload.encode(),
        headers={'Content-Type': 'application/json',
                 'Accept': 'application/json, text/event-stream',
                 'Mcp-Session-Id': session_id})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode('utf-8', 'ignore')
    data_lines = [l[6:] for l in raw.splitlines() if l.startswith('data: ')]
    if data_lines:
        return json.loads(data_lines[-1])
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {'raw': raw}


def new_session():
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
    rpc('notifications/initialized', {}, sid)
    return sid


def call_tool(sid, name, args):
    resp = rpc('tools/call', {'name': name, 'arguments': args}, sid, timeout=120)
    result = resp.get('result', resp)
    if isinstance(result, dict) and 'structuredContent' in result:
        return result['structuredContent']
    if isinstance(result, dict) and 'content' in result:
        texts = [c.get('text', '') for c in result['content'] if c.get('type') == 'text']
        return '\n'.join(texts)
    return result


def main():
    sid = new_session()
    cmd = sys.argv[1]

    if cmd == 'navigate':
        out = call_tool(sid, 'browser_navigate', {'url': sys.argv[2]})
        print('NAVIGATED' if out is None or out == '' else out)
    elif cmd == 'snapshot':
        out = call_tool(sid, 'browser_snapshot', {})
        print(out)
    elif cmd == 'click':
        out = call_tool(sid, 'browser_click', {'element': sys.argv[2]})
        print(json.dumps(out, default=str)[:2000])
    elif cmd == 'type':
        out = call_tool(sid, 'browser_type', {'element': sys.argv[2], 'text': sys.argv[3]})
        print(json.dumps(out, default=str)[:2000])
    elif cmd == 'select':
        out = call_tool(sid, 'browser_select_option', {'element': sys.argv[2], 'value': sys.argv[3]})
        print(json.dumps(out, default=str)[:2000])
    elif cmd == 'press':
        out = call_tool(sid, 'browser_press_key', {'key': sys.argv[2]})
        print(json.dumps(out, default=str)[:2000])
    elif cmd == 'screenshot':
        out = call_tool(sid, 'browser_take_screenshot', {'filename': sys.argv[2]})
        print(json.dumps(out, default=str)[:1000])
    elif cmd == 'console':
        out = call_tool(sid, 'browser_console_messages', {})
        print(json.dumps(out, default=str)[:4000])
    elif cmd == 'eval':
        out = call_tool(sid, 'browser_evaluate', {'function': sys.argv[2]})
        print(json.dumps(out, default=str)[:4000])
    elif cmd == 'wait':
        time.sleep(float(sys.argv[2]) / 1000.0)
        print('waited')
    elif cmd == 'find':
        out = call_tool(sid, 'browser_find', {'query': sys.argv[2]})
        print(json.dumps(out, default=str)[:2000])
    else:
        print('unknown cmd', cmd)


if __name__ == '__main__':
    main()
