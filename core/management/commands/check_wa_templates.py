"""Report the review status of every WhatsApp template on the WABA.

Answers the only question that matters after provisioning: did the six
transactional templates get APPROVED, and if not, why not?

Requires WHATSAPP_WABA_ID and WHATSAPP_API_TOKEN. Does NOT require
WHATSAPP_ENABLED.

Usage:
    python manage.py check_wa_templates

Then set each approved name in .env, e.g.
    WHATSAPP_TEMPLATE_INSTALLMENT_REMINDER=samana_installment_due
"""
from django.core.management.base import BaseCommand, CommandError

from notifications.services import WhatsAppService
from notifications import wa_templates


class Command(BaseCommand):
    help = 'Show status, quality score and rejection reason for every WhatsApp template'

    # Only these two outcomes need action from a human; the rest are progress.
    ACTIONABLE = ('REJECTED', 'PAUSED', 'DISABLED', 'LIMIT_EXCEEDED', 'ARCHIVED', 'PENDING_DELETION')

    STATUS_STYLE = {
        'APPROVED': 'SUCCESS',
        'REJECTED': 'ERROR',
        'IN_APPEAL': 'WARNING',
    }

    def handle(self, *args, **options):
        ok, rows, detail = WhatsAppService.list_templates()
        if not ok:
            raise CommandError(detail)

        if not rows:
            self.stdout.write(self.style.WARNING(
                'No templates on this WABA. Create them with:\n'
                '    python manage.py create_wa_templates'))
            return

        header = f"{'TEMPLATE':<30} {'LANG':<6} {'STATUS':<12} {'SUBCATEGORY':<16} {'QUALITY':<8} ID"
        self.stdout.write(header)
        self.stdout.write('-' * len(header))

        by_status = {}
        for row in rows:
            status = row.get('status', 'UNKNOWN')
            by_status.setdefault(status, []).append(row.get('name', '?'))
            self.stdout.write(
                f"{row.get('name', '?'):<30} "
                f"{row.get('language', '?'):<6} "
                f"{self._styled(status):<12} "
                f"{row.get('sub_category') or '-':<16} "
                f"{(row.get('quality_score') or {}).get('score', '-'):<8} "
                f"{row.get('id', '?')}"
            )
            self._explain(row)

        self.stdout.write('')
        self._coverage(rows)

    def _styled(self, status):
        style = getattr(self.style, self.STATUS_STYLE.get(status, 'WARNING'))
        # Padding is applied after styling so the escape codes do not skew columns.
        return f"{status:<12}" if style is self.style.WARNING else style(status)

    def _explain(self, row):
        """Print why a template is not APPROVED, if Meta told us."""
        status = row.get('status', '')
        reason = row.get('rejected_reason') or ''
        if status == 'REJECTED' and reason and reason != 'NONE':
            self.stdout.write(self.style.ERROR(f"        rejected_reason: {reason}"))
            self.stdout.write(self.style.NOTICE(f"        {self.ADVICE.get(reason, 'Review the body copy.')}\n"))
        elif status in self.ACTIONABLE and not reason:
            self.stdout.write(self.style.WARNING(f"        status is {status}; Meta gave no reason\n"))

    ADVICE = {
        'INCORRECT_CATEGORY': (
            'Not seen as transactional. Check the body has no promotional language.'),
        'TAG_CONTENT_MISMATCH': (
            'sub_category does not match the body. Drop sub_category and recreate.'),
        'INVALID_FORMAT': 'Body/placeholder syntax is wrong. Check {{param}} spelling and examples.',
        'PROMOTIONAL': (
            'Read as marketing, not a transaction. Rewrite the body as a plain '
            'statement of fact - no offers, no urgency, no calls to action.'),
        'CATEGORY_NOT_AVAILABLE': 'This sub_category is not offered on the account.',
        'SCAM': 'Templating pattern resembles a scam. Use different phrasing.',
        'ABUSIVE_CONTENT': 'Wording is unacceptable to Meta.',
    }

    def _coverage(self, rows):
        """Cross-check the WABA against what this app actually sends."""
        live = {r.get('name') for r in rows}
        configured = {t['suggested_name']: t for t in wa_templates.templates()}

        missing = [n for n in configured if n not in live]
        if missing:
            self.stdout.write(self.style.WARNING(
                f"{len(missing)} spec template(s) not on the WABA: {', '.join(sorted(missing))}"))
            return

        # Present, but does .env point at it? The name on the WABA is worthless
        # unless send_typed() can resolve it from the matching setting.
        from django.conf import settings

        unresolved = []
        for name, entry in configured.items():
            setting = entry['env_setting']
            if getattr(settings, setting, '') != name:
                unresolved.append(f"{setting} (expected {name})")

        if unresolved:
            self.stdout.write(self.style.WARNING(
                f"{len(unresolved)} template(s) created but not wired into .env:\n  - "
                + '\n  - '.join(sorted(unresolved))))
        else:
            self.stdout.write(self.style.SUCCESS(
                'All six templates exist on the WABA and are wired to .env.'))