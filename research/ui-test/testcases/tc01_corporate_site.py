"""TC-01 Corporate Site: public home page renders hero, nav, lead form."""
from tc_utils import CaseResult, ERP, run_code, goto_audit_code


def tc01_corporate_site():
    res = CaseResult('TC-01 Corporate Site')
    data = run_code(goto_audit_code(ERP + '/', '''
        ({
          title: document.title,
          h1: document.querySelector('h1') ? document.querySelector('h1').textContent.trim() : null,
          loginLink: !!document.querySelector('a[href="/login/"]'),
          heroImg: !!document.querySelector('main img, .hero img'),
          navLinks: [...document.querySelectorAll('header a, nav a')].map(a => a.textContent.trim()).filter(Boolean),
          leadForm: !!document.querySelector('form[action*="lead"], form[action*="enquiry"]'),
          brokenImgs: [...document.images].filter(i => !i.complete || i.naturalWidth === 0).length
        })
    '''))
    res.ok('title is corporate', 'Samana Builders' in str(data.get('title', '')))
    res.ok('h1 hero present', bool(data.get('h1')))
    res.ok('login link present', data.get('loginLink') is True)
    res.ok('hero image present', data.get('heroImg') is True)
    nav = ' '.join(data.get('navLinks', []))
    for item in ['Home', 'Projects', 'Contact', 'Staff Login', 'Book Now']:
        res.ok(f'nav item: {item}', item in nav)
    res.ok('lead/enquiry form present', data.get('leadForm') is True)
    return res


if __name__ == '__main__':
    import sys
    r = tc01_corporate_site()
    print(f'\nTC-01 {"PASS" if r.passed else "FAIL"} ({sum(1 for _, ok, _ in r.checks if ok)}/{len(r.checks)})')
    sys.exit(0 if r.passed else 1)
