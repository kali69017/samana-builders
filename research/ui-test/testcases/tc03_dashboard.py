"""TC-03 Dashboard: KPIs, charts, quick actions render after login."""
from tc_utils import CaseResult, ERP, run_code, auth_code


def tc03_dashboard():
    res = CaseResult('TC-03 Dashboard')
    data = run_code(auth_code(ERP + '/dashboard/', '''
        ({
          title: document.title,
          bodyLen: document.body ? document.body.innerText.length : 0,
          hasSidebar: !!document.querySelector('.sidebar, aside, nav'),
          statCards: document.querySelectorAll('.stat-card, .kpi-card, .card').length,
          hasChart: !!document.querySelector('canvas, [id*="chart"], [class*="chart"]'),
          bodyText: document.body ? document.body.innerText.slice(0, 600) : ''
        })
    '''))
    res.ok('dashboard title', 'Dashboard' in str(data.get('title', '')))
    res.ok('sidebar present', data.get('hasSidebar') is True)
    res.ok('stat/KPI cards present', (data.get('statCards') or 0) >= 3,
           f'cards={data.get("statCards")}')
    res.ok('chart canvas present', data.get('hasChart') is True)
    body = str(data.get('bodyText', ''))
    res.ok('body has content', (data.get('bodyLen') or 0) > 2000,
           f'len={data.get("bodyLen")}')
    return res


if __name__ == '__main__':
    import sys
    r = tc03_dashboard()
    print(f'\nTC-03 {"PASS" if r.passed else "FAIL"} ({sum(1 for _, ok, _ in r.checks if ok)}/{len(r.checks)})')
    sys.exit(0 if r.passed else 1)
