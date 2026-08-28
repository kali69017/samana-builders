"""Run the complete Samana ERP UI test suite (TC-01..TC-08).

Prereqs:
  1. Django server running:  python manage.py runserver 127.0.0.1:8000
  2. Playwright MCP running on :8931 with:
     npx @playwright/mcp --port 8931 --snapshot-mode none --allowed-hosts "*" \
       --allowed-origins "*" --blocked-origins "<external CDNs>"

Run:  python run_all.py
"""
import subprocess
import sys
import time

TESTS = [
    'tc01_corporate_site',
    'tc02_login_logout',
    'tc03_dashboard',
    'tc04_customer_form_validation',
    'tc05_booking_create_form',
    'tc06_ai_pages',
    'tc07_module_pages_audit',
    'tc08_evidence_screenshots',
]


def main():
    print('Samana ERP UI Test Suite\n' + '=' * 40)
    results = []
    for name in TESTS:
        t0 = time.time()
        r = subprocess.run([sys.executable, f'{name}.py'],
                           capture_output=True, text=True, timeout=600)
        dt = time.time() - t0
        passed = r.returncode == 0
        results.append((name, passed, dt))
        print(f'\n--- {name} ({dt:.1f}s) ---')
        print(r.stdout.strip()[-400:] if r.stdout else r.stderr.strip()[-400:])

    print('\n' + '=' * 40)
    print('SUITE SUMMARY')
    total_ok = sum(1 for _, p, _ in results if p)
    print(f'Passed: {total_ok}/{len(results)}')
    for name, passed, dt in results:
        print(f'  {"PASS" if passed else "FAIL"}  {name}  ({dt:.1f}s)')
    return 0 if total_ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
