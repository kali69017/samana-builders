"""Diagnose: capture curl exit code + headers for ERP navigate."""
import json
import subprocess
import sys

sys.path.insert(0, 'research')
from pw_test3 import new_session

sid = new_session()
print('session:', sid[:8], file=sys.stderr)

payload = json.dumps({'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call',
                      'params': {'name': 'browser_navigate',
                                 'arguments': {'url': 'http://127.0.0.1:8000/'}}})
cmd = ['curl', '-s', '-N', '-D', '-', '-o', '-', '-X', 'POST', 'http://localhost:8931/mcp',
       '-H', 'Content-Type: application/json',
       '-H', 'Accept: application/json, text/event-stream',
       '-H', f'Mcp-Session-Id: {sid}',
       '-d', payload, '--max-time', '45', '-w', '\nCURL_EXIT_MARKER %{exitcode}\n']
proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
print('rc:', proc.returncode)
print('STDOUT (first 2500 chars):')
print(proc.stdout[:2500])
print('STDERR:', proc.stderr[:500])
