import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from core.models import UserProfile
from properties.models import Plot, Project, ProjectPhase


XSS_NAME = "x');alert(document.domain);//<script>alert(1)</script>"


class PropertiesXSSRegressionTests(TestCase):
    """Project/phase/plot names must never render as raw HTML or raw JS."""

    def setUp(self):
        self.user = User.objects.create_user('xss-admin', 'xss@example.com', 'pass123456')
        UserProfile.objects.create(user=self.user, role='admin')
        self.client.login(username='xss-admin', password='pass123456')
        self.project = Project.objects.create(
            name=XSS_NAME, location=XSS_NAME, total_plots=10, status='booking_open',
        )
        self.phase = ProjectPhase.objects.create(
            project=self.project, phase_number=1, name=XSS_NAME, total_plots=10,
            status='booking_open', price_per_marla=Decimal('100'),
        )
        self.plot = Plot.objects.create(
            plot_number=XSS_NAME, project=self.project, phase=self.phase, block=XSS_NAME,
            plot_type='residential', size_marla=Decimal('5'), size_sqft=Decimal('1361.25'),
            price=Decimal('500'), holding_deposit=Decimal('50'), status='available',
        )

    def assert_escaped(self, response, label):
        self.assertEqual(response.status_code, 200, label)
        html = response.content.decode()
        self.assertNotIn(XSS_NAME, html, f'{label} rendered the raw XSS payload')
        self.assertIn('&lt;script&gt;', html, f'{label} did not render an escaped payload')

    def test_properties_list_escapes_project_and_plot_names(self):
        self.assert_escaped(self.client.get('/properties/'), 'properties list')

    def test_project_detail_context_escapes_project_name(self):
        # There is no standalone project detail route; the filtered properties
        # page is the project-scoped list/detail view.
        self.assert_escaped(
            self.client.get('/properties/', {'project': self.project.pk}),
            'project detail context',
        )

    def test_project_edit_escapes_project_and_phase_names(self):
        self.assert_escaped(
            self.client.get(f'/properties/project/{self.project.pk}/edit/'),
            'project edit',
        )

    def test_plot_detail_escapes_project_phase_and_plot_names(self):
        self.assert_escaped(
            self.client.get(f'/properties/plot/{self.plot.pk}/'),
            'plot detail',
        )

    def test_plot_create_form_escapes_dropdown_labels(self):
        self.assert_escaped(self.client.get('/properties/plot/create/'), 'plot create form')

    def test_booking_create_form_escapes_plot_dropdown_labels(self):
        self.assert_escaped(self.client.get('/bookings/create/'), 'booking create form')


class TemplateXSSPolicyTests(TestCase):
    """No template or hand-written JS may bypass autoescaping for injected data."""

    def test_templates_and_js_have_no_unsafe_escapes(self):
        roots = [Path(settings.BASE_DIR) / 'templates', Path(settings.BASE_DIR) / 'static' / 'js']
        pattern = re.compile(r'\|safe\b|mark_safe|autoescape\s+off')
        hits = []
        for root in roots:
            for path in root.rglob('*'):
                if path.suffix not in {'.html', '.js'}:
                    continue
                text = path.read_text(encoding='utf-8')
                for number, line in enumerate(text.splitlines(), 1):
                    if pattern.search(line):
                        hits.append(f'{path.relative_to(settings.BASE_DIR)}:{number}')
        self.assertEqual(hits, [], 'Unsafe template/JS escaping: ' + ', '.join(hits))
