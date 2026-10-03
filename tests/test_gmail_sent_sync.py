"""Offline sent-message matching with synthetic files and read-only transports."""
from __future__ import annotations

import base64
import copy
import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from honorarios_app import gmail_sent_sync as sync
from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from scripts.record_gmail_draft import apply_verified_sent_unlocked, duplicate_records_for_log_record
from scripts.record_gmail_draft import main as record_draft
from scripts.build_email_draft import validate_draft_payload


def sha(content):
    return hashlib.sha256(content).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def draft_response(record, labels=("DRAFT",)):
    return {"id": record["draft_id"], "message": {"id": record["message_id"], "labelIds": list(labels)}}


class SentSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fictional-sent-sync-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        create_synthetic_runtime(self.root)
        self.paths = SimpleNamespace(**runtime_path_overrides(self.root))
        self.created = datetime.now(timezone.utc) - timedelta(days=2)
        self.sent_at = self.created + timedelta(hours=2)
        self.records, self.index = [], []
        self.fixture = self.paths.gmail_config.with_name("gmail-sent-sync-fixture.local.json")
        self.env = patch.dict(os.environ, {sync.FAKE_SENT_SYNC_ENV: "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        sync._last_checks.clear()
        sync._next_record.clear()
        sync._last_results.clear()
        for target in ("httpx.HTTPTransport.handle_request", "honorarios_app.gmail_draft_api.gmail_access_token", "honorarios_app.ai_recovery.OpenAI"):
            guard = patch(target, side_effect=AssertionError("Synthetic tests must not call providers"))
            guard.start()
            self.addCleanup(guard.stop)

    def save_history(self):
        write_json(self.paths.draft_log, self.records)
        write_json(self.paths.duplicate_index, self.index)

    def add_record(self, draft_id="draft-example", *, children=1, proof=False, anchor=True):
        child_payloads, child_rows, attachments = [], [], []
        for number in range(children):
            pdf = self.paths.output_dir / f"{draft_id}-{number}.pdf"
            pdf.parent.mkdir(parents=True, exist_ok=True)
            pdf.write_bytes(f"%PDF-synthetic-{draft_id}-{number}".encode())
            files = [str(pdf)]
            if proof and number == 0:
                extra = self.paths.source_upload_dir / f"{draft_id}-proof.png"
                extra.parent.mkdir(parents=True, exist_ok=True)
                extra.write_bytes(b"synthetic-proof-bytes")
                files.append(str(extra))
            hashes = {raw: sha(Path(raw).read_bytes()) for raw in files}
            child = {"case_number": f"{100 + len(self.records) * 10 + number}/26.0EXAMPLE", "service_date": "2026-05-02",
                     "service_period_label": "", "subject": "Requerimento de honorários", "to": "court@example.test",
                     "draft_only": True, "send_allowed": False, "gmail_create_draft_ready": True,
                     "gmail_tool": "_create_draft", "attachment_files": files, "attachment_sha256": hashes,
                     "pdf_sha256": hashes[str(pdf)], "claim_interpreting": True, "claim_transport": number == 0,
                     "source_sha256": "a" * 64, "personal_profile_id": "synthetic"}
            child["gmail_create_draft_args"] = {"to": child["to"], "subject": child["subject"], "body": "Synthetic request", "attachment_files": files}
            child_path = self.paths.draft_output_dir / f"{draft_id}-{number}.json"
            write_json(child_path, child)
            row = {key: child[key] for key in ("case_number", "service_date", "service_period_label", "claim_interpreting", "claim_transport", "source_sha256", "personal_profile_id")}
            row.update(pdf=str(pdf), pdf_sha256=hashes[str(pdf)], draft_payload=str(child_path),
                       draft_payload_sha256=sha(child_path.read_bytes()), recipient=child["to"])
            child_rows.append(row)
            child_payloads.append(child)
            attachments.extend(files)
        payload = copy.deepcopy(child_payloads[0])
        payload_path = Path(child_rows[0]["draft_payload"])
        if children > 1:
            payload.update(email_grouping="source", email_group_id="group-example", underlying_requests=child_rows,
                           attachment_files=attachments, attachment_sha256={raw: sha(Path(raw).read_bytes()) for raw in attachments})
            payload["gmail_create_draft_args"]["attachment_files"] = attachments
            payload_path = self.paths.draft_output_dir / f"{draft_id}-group.json"
            write_json(payload_path, payload)
        first = child_rows[0]
        record = {"draft_id": draft_id, "message_id": "original-" + draft_id, "thread_id": "thread-" + draft_id,
                  "status": "active", "updated_at": self.created.isoformat(), "recipient": payload["to"],
                  "case_number": first["case_number"], "service_date": first["service_date"], "service_period_label": "",
                  "pdf": first["pdf"], "pdf_sha256": first["pdf_sha256"], "draft_payload": str(payload_path),
                  "notes": "Preserve this note", "custom_metadata": {"keep": True}}
        if anchor:
            record.update(created_at=self.created.isoformat(), draft_payload_sha256=sha(payload_path.read_bytes()))
        if children > 1:
            record.update(email_grouping="source", email_group_id="group-example", underlying_requests=child_rows)
        self.records.append(record)
        for row in duplicate_records_for_log_record(record, payload):
            row["custom_child_metadata"] = {"keep": "child"}
            self.index.append(row)
        self.save_history()
        return record

    def message(self, record, message_id="sent-example", external=False):
        payload = read_json(Path(record["draft_payload"]))
        parts, attachments = [{"mimeType": "text/plain", "body": {"size": 4, "data": "Ym9keQ"}}], {}
        for number, raw in enumerate(payload["attachment_files"]):
            content = Path(raw).read_bytes()
            body = {"size": len(content), "data": base64.urlsafe_b64encode(content).decode().rstrip("=")}
            if external:
                key = "attachment-" + str(number)
                attachments[message_id + "/" + key] = body
                body = {"size": len(content), "attachmentId": key}
            parts.append({"mimeType": "application/pdf", "filename": Path(raw).name, "body": body})
        message = {"id": message_id, "threadId": "sent-thread", "labelIds": ["SENT"],
                   "internalDate": str(int(self.sent_at.timestamp() * 1000)),
                   "payload": {"mimeType": "multipart/mixed", "headers": [{"name": "To", "value": payload["to"]},
                               {"name": "Subject", "value": payload["subject"]}], "parts": parts}}
        return message, attachments

    def add_manual_record(self, draft_id='manual-example', *, children=3):
        record = self.add_record(draft_id, children=children)
        payload_path = Path(record['draft_payload'])
        payload = read_json(payload_path)
        visit = 'manual-visit-' + 'b' * 64
        declaration = {'manual_visit_id': visit, 'manual_visit_provenance': 'user_declared_manual_visit',
                       'source_kind': 'manual_review', 'source_sha256': '',
                       'service_place': 'GNR de Fictional City', 'payment_entity': 'Tribunal de Fictional City'}
        for child in payload['underlying_requests']:
            child_path = Path(child['draft_payload'])
            data = read_json(child_path)
            data.update(declaration, travel_group_id=visit,
                        travel_group_binding=[data['service_date'], 'gnr de fictional city', 'fictional city', 'synthetic', 'fictional origin'])
            write_json(child_path, data)
            child.update(declaration, travel_group_id=visit, travel_group_binding=data['travel_group_binding'],
                         draft_payload_sha256=sha(child_path.read_bytes()))
        payload.update(declaration, email_grouping='manual_visit', email_group_id='manual-email-' + 'b' * 64,
                       child_payload_paths=[child['draft_payload'] for child in payload['underlying_requests']])
        for key in ('claim_interpreting', 'claim_transport', 'travel_group_id', 'travel_group_binding'):
            payload.pop(key, None)
        write_json(payload_path, payload)
        record.update(declaration, email_grouping=payload['email_grouping'], email_group_id=payload['email_group_id'],
                      underlying_requests=payload['underlying_requests'], draft_payload_sha256=sha(payload_path.read_bytes()))
        self.index = [row for row in self.index if row.get('draft_id') != draft_id]
        self.index.extend(duplicate_records_for_log_record(record, payload))
        self.save_history()
        self.assertEqual(validate_draft_payload(payload), [])
        return record

    def record_manual(self, record, draft_id=None, *extra):
        args = ['--log', str(self.paths.draft_log), '--duplicate-index', str(self.paths.duplicate_index),
                '--payload', record['draft_payload'], '--draft-id', draft_id or record['draft_id'],
                '--message-id', record['message_id'], '--thread-id', record['thread_id'], *extra]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return record_draft(args)

    def write_fixture(self, messages, *, attachments=None, drafts=None):
        write_json(self.fixture, {"messages": messages, "attachments": attachments or {},
                                 "drafts": drafts if drafts is not None else {row["draft_id"]: None for row in self.records}})

    def run_sync(self, *, force=True, callback=None):
        callback = callback or (lambda record, evidence: apply_verified_sent_unlocked(self.paths.draft_log, self.paths.duplicate_index, record, evidence))
        return sync.sync_gmail_sent_status(self.paths, force=force, apply_confirmed=callback)

    def assert_unchanged(self, before, result):
        self.assertEqual((self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes()), before)
        self.assertEqual(result["sent_count"], 0)
        self.assertFalse(result["managed_data_changed"])
        self.assertFalse(result["send_allowed"])
        self.assertFalse(result["gmail_write_allowed"])

    def history_bytes(self):
        return self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes()

    def test_exact_sent_message_updates_group_and_preserves_all_original_fields(self):
        record = self.add_record(children=3, proof=True)
        message, attachments = self.message(record, external=True)
        self.write_fixture([message], attachments=attachments)
        before_record, before_index = copy.deepcopy(record), copy.deepcopy(self.index)
        result = self.run_sync()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["sent_count"], 1)
        self.assertTrue(result["managed_data_changed"])
        current = read_json(self.paths.draft_log)[0]
        self.assertEqual(current["status"], "sent")
        self.assertEqual(current["sent_message_id"], message["id"])
        self.assertNotEqual(current["message_id"], current["sent_message_id"])
        for key, value in before_record.items():
            if key not in {"status", "updated_at"}:
                self.assertEqual(current[key], value)
        for old, current_child in zip(before_index, read_json(self.paths.duplicate_index)):
            self.assertEqual(current_child["status"], "sent")
            for key, value in old.items():
                if key not in {"status", "updated_at"}:
                    self.assertEqual(current_child[key], value)

    def test_manual_visit_exact_sent_updates_every_own_pdf_and_preserves_declared_provenance(self):
        record = self.add_manual_record()
        message, attachments = self.message(record, external=True)
        self.write_fixture([message], attachments=attachments)
        result = self.run_sync()
        self.assertEqual(result['sent_count'], 1)
        protected = read_json(self.paths.duplicate_index)
        self.assertEqual(len(protected), 3)
        self.assertEqual(len({row['pdf'] for row in protected}), 3)
        self.assertEqual(sum(row['claim_transport'] for row in protected), 1)
        for row in [read_json(self.paths.draft_log)[0], *protected]:
            self.assertEqual(row['status'], 'sent')
            self.assertEqual(row['email_grouping'], 'manual_visit')
            self.assertEqual(row['manual_visit_provenance'], 'user_declared_manual_visit')
            self.assertEqual(row['manual_visit_id'], record['manual_visit_id'])
            self.assertEqual(row['source_kind'], 'manual_review')
            self.assertEqual(row['source_sha256'], '')
        before = self.history_bytes()
        self.assert_unchanged(before, self.run_sync())

    def test_manual_visit_payload_rejects_conflicting_visit_or_source_declarations(self):
        record = self.add_manual_record()
        original = read_json(Path(record['draft_payload']))
        changes = [lambda p: p.pop('manual_visit_id'),
                   lambda p: p.update(manual_visit_provenance='inferred'),
                   lambda p: p.update(source_filename='claimed-photo.jpg'),
                   lambda p: p.update(source_sha256='a' * 64),
                   lambda p: p['underlying_requests'][1].update(service_date='2026-05-03'),
                   lambda p: p['underlying_requests'][1].update(service_place='GNR de Other City'),
                   lambda p: p['underlying_requests'][1].update(payment_entity='Tribunal de Other City'),
                   lambda p: p['underlying_requests'][1].update(personal_profile_id='other'),
                   lambda p: p['underlying_requests'][1].update(recipient='other@example.test'),
                   lambda p: p['underlying_requests'][1].update(manual_visit_id='manual-visit-' + 'c' * 64),
                   lambda p: p['underlying_requests'][1].update(source_kind='photo'),
                   lambda p: p['underlying_requests'][1].update(claim_transport=True),
                   lambda p: p['underlying_requests'][0].update(claim_transport=False),
                   lambda p: [child['travel_group_binding'].__setitem__(1, 'gnr de other city') for child in p['underlying_requests']]]
        for number, change in enumerate(changes):
            with self.subTest(change=number):
                payload = copy.deepcopy(original)
                change(payload)
                self.assertTrue(validate_draft_payload(payload))
        single = copy.deepcopy(original)
        single['underlying_requests'] = single['underlying_requests'][:1]
        single['child_payload_paths'] = single['child_payload_paths'][:1]
        single['attachment_files'] = single['attachment_files'][:1]
        single['attachment_sha256'] = {raw: original['attachment_sha256'][raw] for raw in single['attachment_files']}
        single['gmail_create_draft_args']['attachment_files'] = single['attachment_files']
        self.assertIn('Manual visit email requires at least two reviewed requests.', validate_draft_payload(single))

    def test_manual_visit_changed_child_file_or_pdf_blocks_before_mailbox_reads(self):
        record = self.add_manual_record()
        child = record['underlying_requests'][1]
        for raw in (child['draft_payload'], child['pdf']):
            with self.subTest(artifact=Path(raw).suffix):
                path, original = Path(raw), Path(raw).read_bytes()
                path.write_bytes(b'changed original manual visit artifact')
                before = self.history_bytes()
                with patch.object(sync, 'FixtureSentReader', side_effect=AssertionError('Stale child must not reach mailbox')):
                    self.assert_unchanged(before, self.run_sync())
                path.write_bytes(original)

    def test_manual_visit_late_sent_or_uncovered_correction_never_partially_records(self):
        record = self.add_manual_record()
        self.index[1]['status'] = 'sent'
        self.index[1].pop('draft_id')
        self.save_history()
        before = self.history_bytes()
        self.assertEqual(self.record_manual(record, 'new-manual-draft'), 2)
        self.assertEqual(self.history_bytes(), before)
        self.index[1]['status'] = 'drafted'
        self.index[1]['draft_id'] = 'prior-draft'
        self.records.append({'draft_id': 'prior-draft', 'status': 'active', 'underlying_requests': [
            self.index[1], {'case_number': '999/26.0EXAMPLE', 'service_date': '2026-05-02'}]})
        self.save_history()
        before = self.history_bytes()
        self.assertEqual(self.record_manual(record, 'new-manual-draft', '--supersedes', 'prior-draft',
                                            '--notes', 'Intentional corrected manual request'), 2)
        self.assertEqual(self.history_bytes(), before)

    def test_manual_visit_record_retry_is_idempotent_and_sent_history_cannot_downgrade(self):
        record = self.add_manual_record()
        self.records, self.index = [], []
        self.save_history()
        with patch('scripts.record_gmail_draft.datetime') as clock:
            clock.now.return_value = self.created
            self.assertEqual(self.record_manual(record), 0)
            self.assertEqual(self.record_manual(record), 0)
        self.assertEqual(len(read_json(self.paths.draft_log)), 1)
        protected = read_json(self.paths.duplicate_index)
        self.assertEqual(len(protected), 3)
        self.assertEqual(len({row['pdf'] for row in protected}), 3)
        self.assertTrue(all(row['manual_visit_id'] == record['manual_visit_id'] for row in protected))
        self.assertTrue(all(row['source_sha256'] == '' for row in protected))
        message, attachments = self.message(record)
        self.write_fixture([message], attachments=attachments)
        self.assertEqual(self.run_sync()['sent_count'], 1)
        before = self.history_bytes()
        self.assertEqual(self.record_manual(record), 2)
        self.assertEqual(self.history_bytes(), before)

    def test_manual_visit_sync_rejects_changed_protected_declaration_and_attachment_multiset(self):
        record = self.add_manual_record()
        original, attachments = self.message(record)
        for alteration in ('protected_visit', 'omitted_pdf', 'repeated_pdf', 'replaced_pdf'):
            with self.subTest(alteration=alteration):
                self.save_history()
                message = copy.deepcopy(original)
                if alteration == 'protected_visit':
                    index = read_json(self.paths.duplicate_index)
                    index[1]['manual_visit_provenance'] = 'inferred'
                    write_json(self.paths.duplicate_index, index)
                elif alteration == 'omitted_pdf':
                    message['payload']['parts'].pop()
                elif alteration == 'repeated_pdf':
                    message['payload']['parts'].append(copy.deepcopy(message['payload']['parts'][-1]))
                else:
                    message['payload']['parts'][1]['body']['data'] = 'bm90LW9yaWdpbmFsLXBkZg'
                self.write_fixture([message], attachments=attachments)
                self.assert_unchanged(self.history_bytes(), self.run_sync())

    def test_true_draft_is_kept_only_after_complete_sent_search_has_no_match(self):
        record = self.add_record()
        self.write_fixture([], drafts={record["draft_id"]: draft_response(record)})
        before = self.history_bytes()
        with patch.object(sync, "_find_match", wraps=sync._find_match) as matcher:
            result = self.run_sync()
        matcher.assert_called_once()
        self.assert_unchanged(before, result)
        self.assertEqual(result["still_drafted_count"], 1)

    def test_exact_sent_proof_wins_over_sent_draft_alias_or_surviving_draft(self):
        record = self.add_record()
        message, _ = self.message(record)
        for labels in (("SENT", "CATEGORY_PERSONAL"), ("DRAFT",)):
            with self.subTest(labels=labels):
                self.save_history()
                response = draft_response(record, labels)
                if "SENT" in labels:
                    response["message"]["id"] = message["id"]
                self.write_fixture([message], drafts={record["draft_id"]: response})
                # The exact proof must succeed even if this unnecessary lookup
                # were unavailable; it never changes or deletes the resource.
                with patch.object(sync.FixtureSentReader, "draft_exists", side_effect=AssertionError("Exact sent proof needs no draft lookup")):
                    result = self.run_sync()
                self.assertEqual(result["sent_count"], 1)
                self.assertEqual(result["still_drafted_count"], 0)
                self.assertEqual(result["warnings"], [])
                stored = read_json(self.paths.draft_log)[0]
                self.assertEqual(stored["message_id"], record["message_id"])
                self.assertEqual(stored["sent_message_id"], message["id"])
                self.assertEqual(read_json(self.fixture)["drafts"][record["draft_id"]], response)

    def test_no_sent_match_and_missing_or_unexpected_draft_labels_needs_review(self):
        record = self.add_record()
        responses = [draft_response(record, labels) for labels in ((), ("SENT",), ("SENT", "DRAFT"), ("INBOX",))]
        responses.append({"id": record["draft_id"], "message": {"id": record["message_id"]}})
        for response in responses:
            with self.subTest(response=response):
                self.write_fixture([], drafts={record["draft_id"]: response})
                before = self.history_bytes()
                result = self.run_sync()
                self.assert_unchanged(before, result)
                self.assertEqual(result["still_drafted_count"], 0)
                self.assertEqual(result["needs_review_count"], 1)

    def test_missing_draft_with_no_sent_message_does_not_retire_protection(self):
        self.add_record()
        self.write_fixture([])
        before = self.history_bytes()
        result = self.run_sync()
        self.assert_unchanged(before, result)
        self.assertEqual(result["needs_review_count"], 1)

    def test_nonmatching_or_incomplete_messages_never_mark_sent(self):
        record = self.add_record(children=2, proof=True)
        original, _ = self.message(record)
        def replace_header(message, name, value):
            next(row for row in message["payload"]["headers"] if row["name"] == name)["value"] = value
        mutations = [lambda m: m.update(labelIds=["DRAFT"]), lambda m: m.update(labelIds=["SENT", "DRAFT"]),
                     lambda m: replace_header(m, "To", "other@example.test"),
                     lambda m: replace_header(m, "To", "court@example.test, extra@example.test"),
                     lambda m: replace_header(m, "Subject", "Different request"),
                     lambda m: m["payload"]["headers"].append({"name": "Cc", "value": "extra@example.test"}),
                     lambda m: m["payload"]["parts"].pop(),
                     lambda m: m["payload"]["parts"].append(copy.deepcopy(m["payload"]["parts"][-1])),
                     lambda m: m["payload"]["parts"][1]["body"].update(data="YnJva2Vu"),
                     lambda m: m.update(internalDate=str(int((self.created - timedelta(seconds=1)).timestamp() * 1000))),
                     lambda m: m.pop("internalDate"), lambda m: m.update(internalDate=str(int((datetime.now(timezone.utc) + timedelta(days=2)).timestamp() * 1000)))]
        for change in mutations:
            with self.subTest(change=mutations.index(change)):
                message = copy.deepcopy(original)
                change(message)
                self.write_fixture([message])
                before = self.history_bytes()
                self.assert_unchanged(before, self.run_sync())

    def test_two_exact_sent_messages_are_ambiguous(self):
        record = self.add_record()
        first, _ = self.message(record, "sent-first")
        second, _ = self.message(record, "sent-second")
        self.write_fixture([first, second], drafts={record["draft_id"]: draft_response(record)})
        before = self.history_bytes()
        with patch.object(sync.FixtureSentReader, "draft_exists", side_effect=AssertionError("Ambiguous Sent search must not classify as drafted")):
            result = self.run_sync()
        self.assert_unchanged(before, result)
        self.assertEqual(result["still_drafted_count"], 0)

    def test_nested_mime_attachments_and_encoded_subject_are_supported(self):
        record = self.add_record()
        message, _ = self.message(record)
        parts = message["payload"]["parts"]
        message["payload"]["parts"] = [{"mimeType": "multipart/mixed", "parts": parts}]
        message["payload"]["headers"][1]["value"] = "=?utf-8?b?" + base64.b64encode("Requerimento de honorários".encode()).decode() + "?="
        self.write_fixture([message])
        self.assertEqual(self.run_sync()["sent_count"], 1)

    def test_missing_original_review_binding_or_changed_local_files_keeps_record(self):
        record = self.add_record(anchor=False)
        message, _ = self.message(record)
        self.write_fixture([message])
        before = self.history_bytes()
        with patch.object(sync, "FixtureSentReader", side_effect=AssertionError("Unanchored history must not reach mailbox")):
            self.assert_unchanged(before, self.run_sync())
        record.update(created_at=self.created.isoformat(), draft_payload_sha256=sha(Path(record["draft_payload"]).read_bytes()))
        self.save_history()
        Path(record["pdf"]).write_bytes(b"changed-local-pdf")
        before = self.history_bytes()
        self.assert_unchanged(before, self.run_sync())

    def test_original_creation_attempt_can_anchor_legacy_record(self):
        record = self.add_record(anchor=False)
        payload = read_json(Path(record["draft_payload"]))
        target = {"draft_payload": record["draft_payload"], "draft_payload_sha256": sha(Path(record["draft_payload"]).read_bytes()),
                  "attachment_sha256": payload["attachment_sha256"], "child_payload_sha256": {}}
        write_json(self.paths.draft_log.with_name("gmail-create-attempts.local.json"), {"schema_version": 1, "attempts": [{
            "created_at": self.created.isoformat(), "state": "recorded", "target": target,
            "gmail_result": {"draft_id": record["draft_id"], "message_id": record["message_id"]}}]})
        message, _ = self.message(record)
        self.write_fixture([message])
        self.assertEqual(self.run_sync()["sent_count"], 1)

    def test_changed_payload_subject_cannot_rebind_recorded_review(self):
        record = self.add_record()
        payload_path = Path(record["draft_payload"])
        payload = read_json(payload_path)
        payload["subject"] = payload["gmail_create_draft_args"]["subject"] = "Changed subject"
        write_json(payload_path, payload)
        message, _ = self.message(record)
        self.write_fixture([message])
        before = self.history_bytes()
        self.assert_unchanged(before, self.run_sync())

    def test_old_active_record_remains_in_search_scope(self):
        self.created = datetime.now(timezone.utc) - timedelta(days=1300)
        self.sent_at = self.created + timedelta(hours=2)
        record = self.add_record()
        message, _ = self.message(record)
        self.write_fixture([message])
        self.assertEqual(self.run_sync()["sent_count"], 1)

    def test_incomplete_pagination_never_accepts_first_exact_match(self):
        record = self.add_record()
        message, _ = self.message(record)
        self.write_fixture([message])
        get = sync.FixtureSentReader.get
        def unfinished(reader, suffix="", **kwargs):
            result = get(reader, suffix, **kwargs)
            if not suffix:
                result["nextPageToken"] = "repeat"
            return result
        before = self.history_bytes()
        with patch.object(sync.FixtureSentReader, "get", unfinished):
            self.assert_unchanged(before, self.run_sync())

    def test_full_pagination_can_find_match_after_first_page(self):
        record = self.add_record()
        message, _ = self.message(record)
        irrelevant = [dict(copy.deepcopy(message), id=f"not-sent-{i}", labelIds=["INBOX"]) for i in range(sync.MAX_LIST_PAGE_SIZE)]
        self.write_fixture([*irrelevant, message])
        self.assertEqual(self.run_sync()["sent_count"], 1)

    def test_history_or_artifact_change_during_read_is_revalidated_before_commit(self):
        record = self.add_record()
        message, _ = self.message(record)
        self.write_fixture([message])
        get = sync.FixtureSentReader.get
        for change in ("history", "index", "payload", "pdf"):
            with self.subTest(change=change):
                self.save_history()
                originals = {raw: Path(raw).read_bytes() for raw in (record["draft_payload"], record["pdf"])}
                def changed(reader, suffix="", **kwargs):
                    result = get(reader, suffix, **kwargs)
                    if suffix:
                        if change == "history":
                            rows = read_json(self.paths.draft_log)
                            rows[0]["notes"] = "Changed concurrently"
                            write_json(self.paths.draft_log, rows)
                        elif change == "index":
                            rows = read_json(self.paths.duplicate_index)
                            rows[0]["status"] = "superseded"
                            write_json(self.paths.duplicate_index, rows)
                        else:
                            Path(record["draft_payload"] if change == "payload" else record["pdf"]).write_bytes(b"changed during read")
                    return result
                with patch.object(sync.FixtureSentReader, "get", changed):
                    result = self.run_sync(callback=lambda *_: self.fail("Changed snapshot must not commit"))
                self.assertEqual(result["sent_count"], 0)
                for raw, content in originals.items():
                    Path(raw).write_bytes(content)

    def test_message_already_bound_to_different_sent_record_is_not_reused(self):
        record = self.add_record()
        message, _ = self.message(record)
        self.records.append({"draft_id": "previous-draft", "status": "sent", "sent_message_id": message["id"]})
        self.save_history()
        self.write_fixture([message])
        before = self.history_bytes()
        self.assert_unchanged(before, self.run_sync())

    def test_second_write_failure_stays_blocking_reports_change_and_repairs_next_sync(self):
        record = self.add_record(children=2)
        message, _ = self.message(record)
        self.write_fixture([message])
        with patch("scripts.record_gmail_draft.write_log", side_effect=OSError("synthetic disk failure")):
            result = self.run_sync()
        self.assertEqual(result["sent_count"], 0)
        self.assertTrue(result["managed_data_changed"])
        self.assertEqual(read_json(self.paths.draft_log)[0]["status"], "active")
        self.assertTrue(all(row["status"] == "sent" for row in read_json(self.paths.duplicate_index)))
        repaired = self.run_sync()
        self.assertEqual(repaired["sent_count"], 1)
        self.assertEqual(read_json(self.paths.draft_log)[0]["status"], "sent")

    def test_automatic_cooldown_and_manual_force_never_override_busy_lock(self):
        record = self.add_record()
        self.write_fixture([], drafts={record["draft_id"]: draft_response(record)})
        completed = self.run_sync(force=False)
        self.assertEqual(completed["status"], "complete")
        cooldown = self.run_sync(force=False)
        self.assertEqual(cooldown["status"], "cooldown")
        self.assertEqual(cooldown["checked_at"], completed["checked_at"])
        self.assertEqual(cooldown["still_drafted_count"], 1)
        self.assertEqual(sync.sent_sync_last_result(self.paths), completed)
        self.assertEqual(self.run_sync(force=True)["status"], "complete")
        with sync._sync_lock:
            self.assertEqual(self.run_sync(force=True)["status"], "busy")

    def test_busy_without_previous_check_has_no_fabricated_time_or_counts(self):
        with sync._sync_lock:
            result = self.run_sync()
        self.assertNotIn("checked_at", result)
        self.assertNotIn("checked_count", result)
        self.assertIsNone(sync.sent_sync_last_result(self.paths))

    def test_later_lifecycle_edit_does_not_replace_immutable_creation_time(self):
        record = self.add_record()
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.save_history()
        message, _ = self.message(record)
        self.write_fixture([message])
        self.assertEqual(self.run_sync()["sent_count"], 1)

    def test_fake_requires_both_explicit_flag_and_synthetic_marker(self):
        self.assertTrue(sync.fake_gmail_sent_sync_enabled(self.paths))
        self.paths.synthetic_runtime_marker.unlink()
        self.assertFalse(sync.fake_gmail_sent_sync_enabled(self.paths))
        self.assertEqual(self.run_sync()["status"], "error")
        write_json(self.paths.synthetic_runtime_marker, {"synthetic_runtime": True})
        self.assertFalse(sync.fake_gmail_sent_sync_enabled(self.paths))
        self.assertEqual(self.run_sync()["status"], "error")

    def test_nonfake_synthetic_runtime_never_uses_inherited_oauth(self):
        with patch.dict(os.environ, {sync.FAKE_SENT_SYNC_ENV: "0"}):
            self.assertEqual(self.run_sync()["status"], "error")

    def test_auth_not_granted_stops_before_access_token_or_network(self):
        self.paths.synthetic_runtime_marker.unlink()
        with patch.dict(os.environ, {sync.FAKE_SENT_SYNC_ENV: "0"}), patch.object(sync.gmail_api, "gmail_sent_read_ready", return_value=False):
            self.assertEqual(self.run_sync()["status"], "authorization_required")

    def test_local_record_budget_rotates_past_old_still_existing_drafts(self):
        first = self.add_record("old-still-existing")
        second = self.add_record("later-sent")
        message, _ = self.message(second)
        self.write_fixture([message], drafts={first["draft_id"]: draft_response(first), second["draft_id"]: None})
        with patch.object(sync, "MAX_LOCAL_RECORDS", 1):
            initial = self.run_sync()
            self.assertEqual(initial["sent_count"], 0)
            self.assertEqual(initial["still_drafted_count"], 1)
            self.assertEqual(initial["needs_review_count"], 1)
            later = self.run_sync()
        self.assertEqual(later["sent_count"], 1)
        self.assertEqual(read_json(self.paths.draft_log)[0]["status"], "active")
        self.assertEqual(read_json(self.paths.draft_log)[1]["status"], "sent")

    def test_local_byte_budget_leaves_evidence_unread_and_records_unchanged(self):
        self.add_record()
        before = self.history_bytes()
        with patch.object(sync, "MAX_LOCAL_BYTES", 1), patch.object(sync, "FixtureSentReader", side_effect=AssertionError("No mailbox read before bounded evidence")):
            result = self.run_sync()
        self.assert_unchanged(before, result)
        self.assertEqual(result["checked_count"], 0)
        self.assertEqual(result["needs_review_count"], 1)

    def test_creation_journal_is_loaded_once_for_initial_batch(self):
        first = self.add_record("first-existing")
        second = self.add_record("second-existing")
        self.write_fixture([], drafts={first["draft_id"]: draft_response(first), second["draft_id"]: draft_response(second)})
        with patch.object(sync, "_creation_attempts", wraps=sync._creation_attempts) as attempts:
            self.assertEqual(self.run_sync()["still_drafted_count"], 2)
        self.assertEqual(attempts.call_count, 1)

    def test_transport_close_failure_never_leaves_sync_permanently_busy(self):
        record = self.add_record()
        self.write_fixture([], drafts={record["draft_id"]: draft_response(record)})
        with patch.object(sync.FixtureSentReader, "close", side_effect=OSError("synthetic close error")):
            self.assertEqual(self.run_sync()["status"], "complete")
        self.assertEqual(self.run_sync()["status"], "complete")


class SentTransportTests(unittest.TestCase):
    def reader(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch.object(sync.httpx, "Client", return_value=client):
            reader = sync.GmailSentReader("synthetic-secret-token")
        self.addCleanup(reader.close)
        return reader

    def test_transport_uses_only_get_official_endpoints_and_keeps_404_unknown(self):
        calls = []
        def handle(request):
            calls.append(request)
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.host, "gmail.googleapis.com")
            if "/drafts/" in request.url.path:
                return httpx.Response(404)
            return httpx.Response(200, json={"messages": []})
        reader = self.reader(handle)
        self.assertFalse(reader.draft_exists("synthetic-draft"))
        self.assertEqual(reader.get(params={"labelIds": "SENT"}), {"messages": []})
        self.assertEqual(len(calls), 2)
        self.assertIn("/drafts/synthetic-draft", calls[0].url.path)

    def test_read_errors_limits_and_redirects_do_not_become_absence(self):
        for code in (401, 403, 429, 500, 302):
            with self.subTest(code=code):
                reader = self.reader(lambda request: httpx.Response(code, headers={"Location": "https://foreign.invalid"}))
                with self.assertRaises(sync.Unconfirmed):
                    reader.draft_exists("synthetic-draft")
        reader = self.reader(lambda request: httpx.Response(200, json={"messages": []}))
        with patch.object(sync, "MAX_HTTP_REQUESTS", 0):
            with self.assertRaises(sync.Unconfirmed):
                reader.get()
        with patch.object(sync, "MAX_WIRE_BYTES", 1):
            with self.assertRaises(sync.Unconfirmed):
                reader.get()

    def test_unsafe_identifiers_are_rejected_before_transport(self):
        reader = self.reader(lambda request: self.fail("Unsafe ID must not reach HTTP"))
        for value in ("../other", "https://foreign.invalid", "draft?extra=yes", "", None):
            with self.subTest(value=value), self.assertRaises(sync.Unconfirmed):
                reader.draft_exists(value)

    def test_successful_draft_lookup_requires_draft_label_and_rejects_sent_alias(self):
        for labels, expected in ((["DRAFT"], True), (["DRAFT", "CATEGORY_PERSONAL"], True),
                                 (["SENT"], False), (["SENT", "CATEGORY_PERSONAL"], False),
                                 (["SENT", "DRAFT"], False), ([], False), (None, False)):
            with self.subTest(labels=labels):
                value = {"id": "original-draft", "message": {"id": "different-message", "labelIds": labels}}
                reader = self.reader(lambda request: httpx.Response(200, json=value))
                if expected:
                    self.assertTrue(reader.draft_exists("original-draft"))
                else:
                    with self.assertRaises(sync.Unconfirmed):
                        reader.draft_exists("original-draft")


if __name__ == "__main__":
    unittest.main()
