"""Create the six transactional WhatsApp templates on the WABA.

Reads notifications/wa_templates.json, validates it, then POSTs each entry to
POST /{Version}/{WABA-ID}/message_templates.

Requires WHATSAPP_WABA_ID (App Dashboard > WhatsApp > API Setup) and
WHATSAPP_API_TOKEN. Does NOT require WHATSAPP_ENABLED - provisioning while the
live send path is off is the intended workflow.

Usage:
    python manage.py create_wa_templates --dry-run    # print payloads, call nothing
    python manage.py create_wa_templates              # create all six
    python manage.py create_wa_templates --only samana_installment_due

Created templates land in PENDING and need Meta review. Follow up with:
    python manage.py check_wa_templates
"""
import json

from django.core.management.base import BaseCommand, CommandError

from notifications.services import WhatsAppService
from notifications import wa_templates


class Command(BaseCommand):
    help = 'Create the WhatsApp message templates described in notifications/wa_templates.json'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print the exact request bodies without calling Meta',
        )
        parser.add_argument(
            '--only',
            action='append',
            metavar='NAME',
            help='Only this template name; repeat for more (default: all six)',
        )

    def handle(self, *args, **options):
        if not options['dry_run'] and not WhatsAppService._templates_url():
            # Fail once with the fix, rather than six times with a template name.
            raise CommandError(
                "WhatsApp template provisioning not configured. Set WHATSAPP_WABA_ID "
                "and WHATSAPP_API_TOKEN in .env (App Dashboard > WhatsApp > API Setup)."
            )

        errors = wa_templates.validate_spec()
        if errors:
            raise CommandError(
                'notifications/wa_templates.json is invalid, refusing to send:\n  - '
                + '\n  - '.join(errors)
            )

        try:
            payloads = wa_templates.build_payloads(only=options['only'])
        except KeyError as e:
            raise CommandError(f"Template entry is missing field {e}.")

        if not payloads:
            raise CommandError(
                'No templates matched. Known names: '
                + ', '.join(e['suggested_name'] for e in wa_templates.templates())
            )

        if options['dry_run']:
            return self._preview(payloads)

        return self._create(payloads)

    def _preview(self, payloads):
        self.stdout.write(self.style.NOTICE(
            f"Dry run - {len(payloads)} template(s) would be created. No calls made.\n"))
        by_name = {t['suggested_name']: t for t in wa_templates.templates()}
        for payload in payloads:
            # One valid JSON object per line, so the block can be piped straight
            # into a file and re-read without hand-editing.
            self.stdout.write(json.dumps(payload, ensure_ascii=False))
            component = payload['components'][0]
            self.stdout.write(f"    body: {component['text']}")
            examples = (component.get('example') or {}).get('body_text') or [[]]
            names = [p['param_name'] for p in by_name[payload['name']]['parameters']]
            # Positional: show {{n}} -> param_name so a misaligned example is obvious.
            for i, (name, example) in enumerate(zip(names, examples[0]), start=1):
                self.stdout.write(f"      {{{{{i}}}}} {name} = {example}")
            self.stdout.write('')

    def _create(self, payloads):
        created, failed = [], []

        for payload in payloads:
            name = payload['name']
            ok, data, detail = WhatsAppService.create_template(payload)

            if ok:
                template_id = (data or {}).get('id', '?')
                status = (data or {}).get('status', '?')
                created.append(name)
                self.stdout.write(self.style.SUCCESS(f"  OK    {name}  id={template_id}  {status}"))
            else:
                failed.append(name)
                self.stdout.write(self.style.ERROR(f"  FAIL  {name}  {detail}"))

        self.stdout.write('')
        self.stdout.write(f"Created {len(created)}, failed {len(failed)} of {len(payloads)}.")
        self.stdout.write(self.style.NOTICE(
            'Templates are PENDING until Meta reviews them. Check with:\n'
            '    python manage.py check_wa_templates'))

        if failed:
            # Non-zero exit so a scheduled provisioning run can alert rather than pass silently.
            raise CommandError(f"{len(failed)} template(s) failed to create: {', '.join(failed)}")