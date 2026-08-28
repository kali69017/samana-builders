"""One-shot: navigate + snapshot in a single session to verify persistence."""
import json
import sys

sys.path.insert(0, 'research')
from pw_flow import new_session, call_tool

sid = new_session()
print('session:', sid[:8], file=sys.stderr)

nav = call_tool(sid, 'browser_navigate', {'url': 'http://127.0.0.1:8000/'})
print('NAV RESULT:', json.dumps(nav, default=str)[:300])

import time
time.sleep(2)

snap = call_tool(sid, 'browser_snapshot', {})
print('SNAP LEN:', len(snap))
print(snap[:2000])
