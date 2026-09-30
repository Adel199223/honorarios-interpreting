"""Behavior checks for browser guidance, using fictional inputs and no browser state."""
from pathlib import Path
import json
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReviewGuidanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        module_url = (ROOT / "honorarios_app/static/review_guidance.js").as_uri()
        script = "import * as g from " + json.dumps(module_url) + ";\n" + """
console.log(JSON.stringify({
  stages: ['idle','answer_questions','set_aside_translation','prepare_pdf',
    'review_gmail_draft_args','unknown'].map(g.guidedStepForState),
  labels: [g.questionFieldLabel({field:'transport.km_one_way'}),
    g.questionFieldLabel({number:7,question:'Unknown fictional detail'})],
  examples: [g.questionAnswerExample({number:3,field:'service_date_source'}),
    g.questionAnswerExample({number:4,field:'closing_date'}),
    g.questionAnswerExample({number:5,field:'recipient_email'})],
  titles: [g.friendlyQuestionTitle({detail:'1 numbered question remains.'}),
    g.friendlyQuestionTitle({detail:'3 numbered questions remain.'})],
  needed: g.beginnerNeededLabels([{field:'service_date'},{field:'service_date'},
    {field:'recipient_email'}]),
  found: g.beginnerFoundLabels({}, {case_number:'FICT-001',
    photo_metadata_date:'2026-09-28', service_place:'Fictional Place'}),
  list: [g.humanList([]),g.humanList(['date']),g.humanList(['date','place']),
    g.humanList(['date','','place','recipient'])],
  needsDate: [g.questionNeedsServiceDate([{field:'service_date_source'}]),
    g.questionNeedsServiceDate([{field:'recipient_email'}])],
  literal: g.shortDateLabel('<fictional date>'),
  today: g.todayIsoDate()
}));
"""
        result = subprocess.run(["node", "--input-type=module", "-"], input=script,
                                text=True, capture_output=True, check=True, cwd=ROOT)
        cls.result = json.loads(result.stdout)

    def test_guided_progress_uses_review_states(self):
        self.assertEqual(self.result["stages"], [1, 3, 2, 4, 5, 2])

    def test_numbered_questions_keep_date_confirmation_and_safe_examples(self):
        self.assertEqual(self.result["labels"], ["one-way kilometers", "question 7"])
        self.assertEqual(self.result["examples"][0], "3. yes, use the photo date")
        self.assertEqual(self.result["examples"][1], "4. " + self.result["today"])
        self.assertEqual(self.result["examples"][2], "5. court@example.test")
        self.assertEqual(self.result["titles"], ["Answer 1 question before PDF creation",
                                                "Answer 3 questions before PDF creation"])

    def test_metadata_date_is_presented_as_evidence_without_claiming_service_date(self):
        labels = self.result["found"]
        self.assertIn("case number", labels)
        self.assertIn("service place", labels)
        self.assertNotIn("service date", labels)
        self.assertTrue(any(value.startswith("photo metadata date (") for value in labels))
        self.assertEqual(self.result["needsDate"], [True, False])

    def test_labels_are_deduplicated_and_literals_remain_text(self):
        self.assertEqual(self.result["needed"], ["service date", "recipient email"])
        self.assertEqual(self.result["list"], ["", "date", "date and place",
                                             "date, place, and recipient"])
        self.assertEqual(self.result["literal"], "<fictional date>")
