"""Management command: ai_daily_insights

Generates a DeepSeek-powered business insights summary for the current ERP
state and writes it into an AiInteractionLog row (feature='insights').

Designed to run on a cron schedule (e.g. daily at 09:00 PKT):

    python manage.py ai_daily_insights

Exits 0 even when AI is disabled so cron does not page on config gaps.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate daily AI business insights from live ERP data'

    def handle(self, *args, **options):
        from ai import services
        from ai.models import AiInteractionLog

        try:
            text = services.generate_insights(user=None)
        except services.AiDisabledError as exc:
            self.stdout.write(self.style.WARNING(f'AI disabled: {exc}'))
            return
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f'AI insights failed: {exc}'))
            return

        log = AiInteractionLog.objects.filter(feature='insights', status='success').first()
        self.stdout.write(self.style.SUCCESS('AI insights generated:'))
        self.stdout.write(text)
