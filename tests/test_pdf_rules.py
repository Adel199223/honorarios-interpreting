"""PDF generation acceptance with fictional input and actual rendered output."""
from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from pypdf import PdfReader

from scripts.generate_pdf import (
    DEFAULT_TEMPLATE, IntakeError, build_rendered_request, generate_pdf,
    main as generate_main, render_html,
)

ROOT = Path(__file__).resolve().parents[1]


class PdfRulesTests(unittest.TestCase):
    def setUp(self):
        self.intake = json.loads((ROOT / 'examples/intake.synthetic.example.json').read_text(encoding='utf-8'))
        self.profile = json.loads((ROOT / 'config/profile.example.json').read_text(encoding='utf-8'))
        temporary = tempfile.TemporaryDirectory(prefix='honorarios-pdf-rules-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_actual_pdf_has_case_service_date_place_payment_and_signature(self):
        rendered = build_rendered_request(self.intake, self.profile)
        target = self.root / 'request.pdf'
        generate_pdf(rendered, target)
        reader = PdfReader(target)
        self.assertEqual(len(reader.pages), 1)
        text = reader.pages[0].extract_text()
        for expected in ('100/26.0TSTXX', '15/01/2026', 'Example Police Station', '12 km',
                         'EXAMPLE_IBAN', '16 de janeiro de 2026', 'Example Interpreter'):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_html_preview_escapes_user_text_without_changing_visible_pdf_text(self):
        self.intake['case_number'] = '100/26.0TSTXX <script>alert(1)</script>'
        self.profile['applicant_name'] = 'Example <Interpreter>'
        rendered = build_rendered_request(self.intake, self.profile)
        target = self.root / 'preview.html'
        render_html(DEFAULT_TEMPLATE, rendered, target)
        html = target.read_text(encoding='utf-8')
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('Example &lt;Interpreter&gt;', html)

    def test_transport_is_optional_and_service_period_is_explicit(self):
        self.intake.update(claim_transport=False, service_period_label='manhã', service_start_time='09:00', service_end_time='11:00')
        rendered = build_rendered_request(self.intake, self.profile)
        self.assertIsNone(rendered.transport_paragraph)
        self.assertIn('das 09:00 às 11:00', rendered.service_paragraph)

    def test_one_sided_time_is_rejected(self):
        self.intake.update(service_start_time='09:00')
        with self.assertRaisesRegex(IntakeError, 'provided together'):
            build_rendered_request(self.intake, self.profile)

    def test_translation_source_cannot_generate_an_interpreting_request(self):
        self.intake['source_text'] = 'Tradução de documento traduzido, número de palavras: 100.'
        with self.assertRaisesRegex(IntakeError, 'not an in-person interpreting request'):
            build_rendered_request(self.intake, self.profile)

    def test_duplicate_cli_stops_before_pdf_and_html_artifacts(self):
        source = self.root / 'intake.json'
        source.write_text(json.dumps(self.intake), encoding='utf-8')
        index = self.root / 'duplicates.json'
        index.write_text(json.dumps([{'case_number': self.intake['case_number'], 'service_date': self.intake['service_date'], 'status': 'drafted'}]), encoding='utf-8')
        pdf, html = self.root / 'blocked.pdf', self.root / 'blocked.html'
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            code = generate_main([str(source), '--profile', str(ROOT / 'config/profile.example.json'),
                                  '--duplicate-index', str(index), '--output', str(pdf), '--html-preview', str(html)])
        self.assertEqual(code, 3)
        self.assertFalse(pdf.exists())
        self.assertFalse(html.exists())


if __name__ == '__main__':
    unittest.main()
