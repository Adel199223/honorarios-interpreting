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
from scripts.source_classification import classify_source_work
from scripts.entity_rules import build_service_place_clause, has_pj_host_building

ROOT = Path(__file__).resolve().parents[1]


class PdfRulesTests(unittest.TestCase):
    def setUp(self):
        self.intake = json.loads((ROOT / 'examples/intake.synthetic.example.json').read_text(encoding='utf-8'))
        self.profile = json.loads((ROOT / 'config/profile.example.json').read_text(encoding='utf-8'))
        temporary = tempfile.TemporaryDirectory(prefix='honorarios-pdf-rules-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_pj_building_only_rendered_clause_cannot_supply_a_missing_city(self):
        for host in ('Hospital', 'Posto', 'Esquadra', 'Hospital Central', 'Gabinete Médico-Legal'):
            with self.subTest(host=host):
                candidate = {**self.intake, 'service_entity': 'Polícia Judiciária',
                             'service_entity_type': 'police', 'service_place': host}
                candidate['service_place_phrase'] = build_service_place_clause(
                    {'service_place': host}, 'Polícia Judiciária')
                self.assertFalse(has_pj_host_building(candidate))
                with self.assertRaisesRegex(IntakeError, 'physical host building and city'):
                    build_rendered_request(candidate, self.profile)
        for host in ('Hospital de Faro', 'Hospital Central de Faro', 'Posto da GNR de Beja',
                     'Gabinete Médico-Legal de Example City'):
            with self.subTest(host=host):
                candidate = {'service_entity': 'Polícia Judiciária', 'service_place': host,
                             'service_place_phrase': build_service_place_clause({'service_place': host}, 'Polícia Judiciária')}
                self.assertTrue(has_pj_host_building(candidate))

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

    def test_actual_pdf_preserves_distinct_payment_host_and_confirmed_service_date_without_optional_phrase(self):
        self.intake.update(
            addressee='Exmo. Senhor Procurador da República\nFictional Payment Court',
            payment_entity='Fictional Payment Court',
            service_entity='Polícia Judiciária',
            service_entity_type='police', entities_differ=True,
            service_place='Posto da GNR de Beja', service_place_phrase='',
            service_date='2026-09-26', photo_metadata_date='2026-09-28',
            service_date_source='user_confirmed_exception', closing_date='2026-09-30',
            claim_transport=False,
        )
        rendered = build_rendered_request(self.intake, self.profile)
        target = self.root / 'distinct-payment-host.pdf'
        generate_pdf(rendered, target)
        reader = PdfReader(target)
        self.assertEqual(len(reader.pages), 1)
        text = ' '.join(reader.pages[0].extract_text().split())
        self.assertIn('Fictional Payment Court', text)
        self.assertIn('Posto da GNR de Beja', text)
        self.assertIn('no dia 26/09/2026', text)
        self.assertIn('30 de setembro de 2026', text)
        self.assertNotIn('28/09/2026', text, 'Capture date cannot replace the explicitly chosen service date.')
        self.assertNotIn('despesas de transporte', text)
        self.assertNotIn('12 km', text)
        self.assertIn('Posto da GNR de Beja', rendered.service_paragraph)
        self.assertNotIn('Fictional Payment Court', rendered.service_paragraph, 'Paying court is not the physical host.')

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

    def test_bare_recovered_place_phrase_gets_preposition_in_actual_pdf(self):
        self.intake.update(service_entity='Esquadra de Example City',
                           service_entity_type='police', entities_differ=True,
                           service_place='Esquadra de Example City',
                           service_place_phrase='ESQUADRA DE EXAMPLE CITY')
        rendered = build_rendered_request(self.intake, self.profile)
        target = self.root / 'photo-place-phrase.pdf'
        generate_pdf(rendered, target)
        text = ' '.join(PdfReader(target).pages[0].extract_text().split())
        self.assertIn('na ESQUADRA DE EXAMPLE CITY', text)
        self.intake['service_place_phrase'] = 'na Esquadra de Example City'
        rendered = build_rendered_request(self.intake, self.profile)
        self.assertIn('na Esquadra de Example City', rendered.service_paragraph)
        self.assertNotIn('na na ', rendered.service_paragraph)

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

    def test_explicit_mixed_notice_generates_only_interpreting_paragraph(self):
        self.intake['source_text'] = (
            'Fica nomeado interprete de lingua arabe para comparecer na audiencia em 15/01/2026 as 10:30.\n\n'
            'Devera ainda proceder a traducao escrita da acusacao no prazo de 10 dias; numero de palavras: 100.')
        self.assertEqual(classify_source_work(self.intake), 'mixed_interpreting')
        target = self.root / 'mixed-interpreting-only.pdf'
        generate_pdf(build_rendered_request(self.intake, self.profile), target)
        text = PdfReader(target).pages[0].extract_text().lower()
        self.assertIn('intérprete', text)
        for excluded in ('tradução', 'acusação', '100 palavras', '10 dias'):
            self.assertNotIn(excluded, text)
        self.intake['source_text'] = self.intake['source_text'].replace('15/01/2026', '15 de janeiro de 2026')
        self.assertEqual(classify_source_work(self.intake), 'mixed_interpreting')

    def test_words_titles_negation_and_optional_interpreter_do_not_establish_assignment(self):
        for text in (
            'Tradutor e interprete: traducao escrita da acusacao em 15/01/2026.',
            'Interprete: traducao escrita. Audiencia em 15/01/2026.',
            'Foi nomeado tradutor e interprete para traduzir a acusacao antes da audiencia em 15/01/2026.',
            'Nao deve comparecer como interprete na audiencia em 15/01/2026. Traducao escrita da acusacao.',
            'Caso necessario, comparecer como interprete na audiencia em 15/01/2026. Traducao escrita da acusacao.',
            'Foi nomeado interprete para comparecer na audiencia em 15/01/2026, entretanto cancelada. Traducao escrita da acusacao.',
        ):
            with self.subTest(text=text):
                self.intake['source_text'] = text
                self.assertEqual(classify_source_work(self.intake), 'ambiguous_mixed')
                with self.assertRaisesRegex(IntakeError, 'Confirm whether this mixed notice'):
                    build_rendered_request(self.intake, self.profile)

    def test_ai_field_or_filename_cannot_authorize_interpreting_on_translation_only_source(self):
        self.intake.update(source_text='Traducao escrita da acusacao, 100 palavras.',
                           source_filename='interprete-audiencia-20260115.pdf',
                           ai_recovery={'fields': {'work_type': 'interpreting', 'service_date': '2026-01-15'}})
        self.assertEqual(classify_source_work(self.intake), 'translation')
        with self.assertRaises(IntakeError):
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
