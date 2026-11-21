from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


MOJIBAKE_ICONS = (
    'ðŸ””',
    'âœ“',
    'â³',
    'â­',
    'âœ•',
    'ðŸ“§',
    'ðŸ“±',
    'ðŸ’¬',
)


class NotificationCenterIconTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            'notificons', 'notificons@example.com', 'pw12345!')
        self.client.force_login(self.user)

    def test_notification_center_does_not_render_mojibake_icons(self):
        response = self.client.get(reverse('notifications'))
        html = response.content.decode('utf-8')

        for icon in MOJIBAKE_ICONS:
            with self.subTest(icon=icon):
                self.assertNotIn(icon, html)
