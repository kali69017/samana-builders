import re

from django.contrib.auth.models import User
from django.test import TestCase

from ai.models import AiInteractionLog


class AiHistoryVisibleLimitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            'aihist', 'aihist@example.com', 'pw12345!')
        self.client.force_login(self.user)
        for index in range(4):
            AiInteractionLog.objects.create(
                user=self.user,
                feature='insights',
                status='success',
                response=f'Insight {index}',
            )

    def test_four_recent_analyses_are_visible_by_default(self):
        response = self.client.get('/ai/insights/')
        html = response.content.decode('utf-8')

        history_items = re.findall(r'<div class="history-item[^"]*"', html)
        visible = [item for item in history_items if 'history-hidden' not in item]

        self.assertEqual(len(visible), 4)
