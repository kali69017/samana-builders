"""ORM-only fixture helper for the properties Playwright spec.

The plot charge fields (development_charge / lease_charge / other_charges) and
holding_deposit cannot be set through the web form, the Django admin, or the DRF
serializer (PROP-EC-07). This script performs those ORM operations and prints a
single line of JSON on stdout so the Playwright spec can assert exact values.

Run (from repo root, shared venv):
    env -u PYTHONPATH DJANGO_DEBUG=True /d/samana/.venv312/Scripts/python.exe \\
        tests/fixtures/properties_orm.py <subcommand> [args...]

Subcommands:
    set_charges <plot_pk> <dev> <lease> <other> [holding_deposit]
    get_plot    <plot_pk>
    plot_financials <plot_pk>      # status + booking/payment/receipt counts
    get_milestone <milestone_pk>
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'samana_erp.settings')
os.environ.setdefault('DJANGO_DEBUG', 'True')

import django  # noqa: E402

django.setup()

from decimal import Decimal  # noqa: E402
from properties.models import Plot, ProjectMilestone  # noqa: E402


def _d(value):
    """Decimal -> canonical 2dp string, or None."""
    if value is None:
        return None
    return format(Decimal(str(value)), '.2f')


def _date(value):
    if value is None:
        return None
    return value.isoformat()


def set_charges(argv):
    pk = int(argv[0])
    dev, lease, other = argv[1], argv[2], argv[3]
    holding = argv[4] if len(argv) > 4 else None
    p = Plot.objects.get(pk=pk)
    p.development_charge = Decimal(dev)
    p.lease_charge = Decimal(lease)
    p.other_charges = Decimal(other)
    if holding is not None:
        p.holding_deposit = Decimal(holding)
    p.save()
    print(json.dumps({
        'price': _d(p.price),
        'total_charges': _d(p.total_charges),
        'total_cost': _d(p.total_cost),
        'status': p.status,
        'holding_deposit': _d(p.holding_deposit),
        'development_charge': _d(p.development_charge),
        'lease_charge': _d(p.lease_charge),
        'other_charges': _d(p.other_charges),
    }))


def get_plot(argv):
    p = Plot.objects.get(pk=int(argv[0]))
    print(json.dumps({
        'price': _d(p.price),
        'total_charges': _d(p.total_charges),
        'total_cost': _d(p.total_cost),
        'status': p.status,
        'holding_deposit': _d(p.holding_deposit),
        'development_charge': _d(p.development_charge),
        'lease_charge': _d(p.lease_charge),
        'other_charges': _d(p.other_charges),
    }))


def plot_financials(argv):
    p = Plot.objects.get(pk=int(argv[0]))
    print(json.dumps({
        'status': p.status,
        'booking_count': p.bookings.count(),
        'payment_count': sum(b.payments.count() for b in p.bookings.all()),
        'receipt_count': sum(b.payments.filter(receipt_generated=True).count() for b in p.bookings.all()),
    }))


def get_milestone(argv):
    m = ProjectMilestone.objects.get(pk=int(argv[0]))
    print(json.dumps({
        'title': m.title,
        'status': m.status,
        'completion_percent': _d(m.completion_percent),
        'start_date': _date(m.start_date),
        'milestone_type': m.milestone_type,
        'progress_date': _date(m.progress_date),
        'target_date': _date(m.target_date),
        'completed_date': _date(m.completed_date),
        'order': m.order,
    }))


COMMANDS = {
    'set_charges': set_charges,
    'get_plot': get_plot,
    'plot_financials': plot_financials,
    'get_milestone': get_milestone,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(json.dumps({'error': 'usage: properties_orm.py <' + '|'.join(COMMANDS) + '> ...'}))
        sys.exit(2)
    COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == '__main__':
    main()
