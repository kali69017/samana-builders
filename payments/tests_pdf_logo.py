from django.test import TestCase, override_settings

from payments.pdf_utils import render_to_pdf


PDF_LOGO_TEMPLATE = (
    '<html><body>'
    '<img src="{{ pdf_logo_uri }}" style="height:44px; width:44px;">'
    '</body></html>'
)


@override_settings(TEMPLATES=[{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'OPTIONS': {
        'loaders': [
            ('django.template.loaders.locmem.Loader', {
                'pdf_logo_test.html': PDF_LOGO_TEMPLATE,
            }),
        ],
    },
}])
class PdfLogoEmbeddingTest(TestCase):
    def test_render_to_pdf_embeds_logo_without_relative_path(self):
        pdf = render_to_pdf('pdf_logo_test.html')

        self.assertIsNotNone(pdf)
        self.assertIn(b'/Subtype /Image', pdf)
