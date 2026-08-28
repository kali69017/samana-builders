"""Single-process Playwright MCP driver using curl subprocess (handles SSE).

Keeps one session alive for the whole run and executes a script of commands.
Usage: python research/pw_run.py <script.json>
Script format: JSON array of [command, args_dict] steps.
Commands: navigate, snapshot, click, type, select, press, screenshot,
console, eval, wait, find, url, tabs
"""
import json
import subprocess
import sys
import time

MCP_URL = 'http://localhost:8931/mcp'


def curl_rpc(method, params, sid, timeout=90):
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
        return {'raw': out}


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


def call_tool(sid, name, args):
    resp = curl_rpc('tools/call', {'name': name, 'arguments': args}, sid, timeout=120)
    result = resp.get('result', resp)
    if isinstance(result, dict) and 'structuredContent' in result:
        return result['structuredContent']
    if isinstance(result, dict) and 'content' in result:
        texts = [c.get('text', '') for c in result['content'] if c.get('type') == 'text']
        return '\n'.join(texts)
    return result


def run_step(sid, step):
    cmd = step[0]
    args = step[1] if len(step) > 1 else {}
    if cmd == 'navigate':
        return ('NAV', call_tool(sid, 'browser_navigate', {'url': args['url']}))
    if cmd == 'snapshot':
        return ('SNAP', call_tool(sid, 'browser_snapshot', {}))
    if cmd == 'click':
        return ('CLICK', call_tool(sid, 'browser_click', {'element': args['ref']}))
    if cmd == 'type':
        return ('TYPE', call_tool(sid, 'browser_type', {'element': args['ref'], 'text': args['text']}))
    if cmd == 'select':
        return ('SELECT', call_tool(sid, 'browser_select_option', {'element': args['ref'], 'value': args['value']}))
    if cmd == 'press':
        return ('PRESS', call_tool(sid, 'browser_press_key', {'key': args['key']}))
    if cmd == 'screenshot':
        return ('SHOT', call_tool(sid, 'browser_take_screenshot', {'filename': args['path']}))
    if cmd == 'console':
        return ('CONSOLE', call_tool(sid, 'browser_console_messages', {}))
    if cmd == 'eval':
        return ('EVAL', call_tool(sid, 'browser_evaluate', {'function': args['js']}))
    if cmd == 'wait':
        time.sleep(float(args['ms']) / 1000.0)
        return ('WAIT', 'ok')
    if cmd == 'find':
        return ('FIND', call_tool(sid, 'browser_find', {'query': args['query']}))
    if cmd == 'url':
        return ('URL', call_tool(sid, 'browser_evaluate', {'function': '() => window.location.href'}))
    return ('UNKNOWN', cmd)


def main():
    script_path = sys.argv[1]
    with open(script_path, encoding='utf-8') as f:
        script = json.load(f)
    sid = new_session()
    print(f'# session {sid[:8]}', file=sys.stderr)
    for i, step in enumerate(script):
        name, out = run_step(sid, step)
        print(f'--- step {i}: {name} ---')
        if isinstance(out, str):
            print(out[:4000])
        else:
            print(json.dumps(out, default=str)[:4000])
        sys.stdout.flush()


if __name__ == '__main__':
    main()
