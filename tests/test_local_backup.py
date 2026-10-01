"""Synthetic backup moves, interruption and duplicate protection; never live Gmail."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from honorarios_app import backup, services
from honorarios_app.gmail_attempts import load_attempts, save_attempts, pending_attempt
from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from scripts.generate_pdf import IntakeError
from scripts.state_store import atomic_write_json
import test_source_email_groups as source_fixtures


class LocalBackupTests(unittest.TestCase):
    setUp = source_fixtures.GmailAttemptRecoveryTests.setUp
    rows = source_fixtures.GmailAttemptRecoveryTests.rows
    prepare = source_fixtures.GmailAttemptRecoveryTests.prepare
    request = source_fixtures.GmailAttemptRecoveryTests.request
    fake_transport = source_fixtures.GmailAttemptRecoveryTests.fake_transport
    prepared_request = source_fixtures.GmailAttemptRecoveryTests.prepared_request

    def destination(self, name="moved"):
        root = self.root / name
        create_synthetic_runtime(root)
        return services.AppPaths(**runtime_path_overrides(root))

    def snapshot(self):
        return services.export_local_backup(self.paths)["backup"]

    def restore(self, snapshot, paths=None):
        return services.restore_local_backup({"backup": snapshot, "confirm_restore": True,
            "confirmation_phrase": services.LOCAL_BACKUP_RESTORE_PHRASE, "restore_reason": "Fictional backup round trip"}, paths or self.paths)

    def pending(self, *, uncertain=False, started=False, partial=False, grouped=True):
        rows = self.rows(3)[1:] if grouped else self.rows(1)
        prepared = self.prepare(rows)
        request = self.request(prepared, prepared["email_groups"][0])
        if started:
            with patch("honorarios_app.services.create_gmail_draft_from_payload", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    services.create_and_record_gmail_api_draft(request, self.paths)
        else:
            with self.fake_transport(timeout_first=uncertain):
                target = "scripts.record_gmail_draft.write_duplicate_index" if partial else "scripts.record_gmail_draft.write_log"
                with patch(target, side_effect=PermissionError("Fictional write interruption")):
                    services.create_and_record_gmail_api_draft(request, self.paths)
        return load_attempts(self.paths.draft_log)[-1]

    def recover(self, attempt, paths, *, manual=False):
        request = {"recover_attempt_id": attempt["attempt_id"], "gmail_handoff_reviewed": True}
        if manual:
            request.update(confirmation_phrase="I CHECKED THE EXISTING GMAIL DRAFT", draft_id="fictional-manual-draft", message_id="fictional-manual-message")
        with patch("honorarios_app.services._PREPARED_REVIEW_SECRET", b"fictional-restarted-key"), patch("honorarios_app.services.create_gmail_draft_from_payload") as transport:
            response = services.reconcile_gmail_create_attempt(request, paths)
            transport.assert_not_called()
        return response

    def test_pending_group_backup_moves_original_files_and_recovers_exact_two_requests(self):
        original = self.pending(partial=True)
        snapshot = self.snapshot()
        destination = self.destination()
        self.restore(snapshot, destination)
        moved = load_attempts(destination.draft_log)[0]
        self.assertNotEqual(moved["payload"], original["payload"])
        self.assertNotIn("prepared_review_token", moved["prepared_review"])
        self.assertNotIn("review_fingerprint", moved["prepared_review"])
        self.assertEqual(moved["backup_original_target"], original["target"])
        for path, sha in moved["target"]["attachment_sha256"].items():
            self.assertTrue(Path(path).is_relative_to(destination.draft_output_dir))
            self.assertIn(sha, original["target"]["attachment_sha256"].values())
        response = self.recover(moved, destination)
        self.assertEqual(response["status"], "created")
        self.assertEqual(response["recorded_duplicate_count"], 2)
        self.assertEqual(len(json.loads(destination.draft_log.read_text())), 1)
        self.assertEqual(len(json.loads(destination.duplicate_index.read_text())), 2)
        self.assertEqual(response["draft_id"], original["gmail_result"]["draft_id"])

    def test_uncertain_and_started_round_trip_keep_blockers_and_allow_manual_existing_ids(self):
        for state in ("uncertain", "started"):
            with self.subTest(state=state):
                attempt = self.pending(uncertain=state == "uncertain", started=state == "started")
                snapshot = self.snapshot()
                destination = self.destination(state)
                self.restore(snapshot, destination)
                restored = load_attempts(destination.draft_log)[0]
                self.assertIsNotNone(pending_attempt([restored], restored["requests"]))
                self.assertEqual(self.recover(restored, destination, manual=True)["recorded_duplicate_count"], 2)
                # Use a fresh synthetic source for the second subtest.
                save_attempts(self.paths.draft_log, [])

    def test_recorded_attempt_round_trip_preserves_history_without_archiving_pdfs(self):
        with self.fake_transport():
            services.create_and_record_gmail_api_draft(self.prepared_request(), self.paths)
        snapshot = self.snapshot()
        self.assertEqual(snapshot["gmail_attempt_recovery"]["entries"], [])
        destination = self.destination()
        self.restore(snapshot, destination)
        self.assertEqual(load_attempts(destination.draft_log)[0]["state"], "recorded")
        self.assertNotEqual(services.draft_lifecycle_for_intake(self.rows(1)[0], destination)["status"], "clear")

    def test_recorded_attempt_cannot_restore_unrelated_case_or_message_history(self):
        with self.fake_transport():
            services.create_and_record_gmail_api_draft(self.prepared_request(), self.paths)
        original = self.snapshot()
        for field in ("case_number", "message_id", "status"):
            with self.subTest(field=field):
                snapshot = copy.deepcopy(original)
                for key in ("gmail_draft_log", "duplicate_index"):
                    for row in snapshot["datasets"][key]:
                        row[field] = "fictional-invalid"
                        for child in row.get("underlying_requests", []):
                            child[field] = "fictional-invalid"
                destination = self.destination(field)
                with self.assertRaises(IntakeError):
                    self.restore(snapshot, destination)
                self.assertEqual(load_attempts(destination.draft_log), [])
                self.assertEqual(json.loads(destination.draft_log.read_text()), [])

    def test_recorded_singleton_parent_child_and_actual_blocker_coverage_must_agree(self):
        with self.fake_transport():
            services.create_and_record_gmail_api_draft(self.prepared_request(), self.paths)
        original = self.snapshot()
        for mutation in ("parents_only", "missing_index", "index_alias", "log_alias", "sent_without_index"):
            with self.subTest(mutation=mutation):
                snapshot = copy.deepcopy(original)
                datasets = snapshot["datasets"]
                if mutation == "parents_only":
                    for key in ("gmail_draft_log", "duplicate_index"):
                        datasets[key][0]["case_number"] = "999/26.0TSTXX"
                elif mutation == "index_alias":
                    datasets["duplicate_index"][0]["status"] = "active"
                elif mutation == "log_alias":
                    datasets["gmail_draft_log"][0]["status"] = "drafted"
                else:
                    datasets["duplicate_index"] = []
                    if mutation == "sent_without_index":
                        datasets["gmail_draft_log"][0]["status"] = "sent"
                destination = self.destination(mutation)
                with self.assertRaises(IntakeError):
                    self.restore(snapshot, destination)
                self.assertEqual(load_attempts(destination.draft_log), [])
                self.assertEqual(json.loads(destination.draft_log.read_text()), [])

    def test_recorded_group_requires_each_child_duplicate_blocker(self):
        prepared = self.prepare(self.rows(3)[1:])
        with self.fake_transport():
            services.create_and_record_gmail_api_draft(self.request(prepared, prepared["email_groups"][0]), self.paths)
        snapshot = self.snapshot()
        destination = self.destination("complete-group")
        self.restore(snapshot, destination)
        for row in self.rows(3)[1:]:
            self.assertEqual(services.draft_lifecycle_for_intake(row, destination)["status"], "blocked")
        incomplete = copy.deepcopy(snapshot)
        incomplete["datasets"]["duplicate_index"].pop()
        incomplete_destination = self.destination("missing-group-child")
        with self.assertRaisesRegex(IntakeError, "missing matching duplicate protection"):
            self.restore(incomplete, incomplete_destination)
        self.assertEqual(load_attempts(incomplete_destination.draft_log), [])

    def test_older_or_legacy_backup_cannot_erase_new_pending_or_recorded_history(self):
        old = self.snapshot()
        old["datasets"].pop("gmail_attempts")
        old.pop("gmail_attempt_recovery")
        attempt = self.pending(partial=True)
        before = copy.deepcopy(load_attempts(self.paths.draft_log))
        self.restore(old)
        self.assertEqual(load_attempts(self.paths.draft_log), before)
        self.assertEqual(len(json.loads(self.paths.draft_log.read_text())), 1)
        self.recover(attempt, self.paths)
        self.restore(old)
        self.assertEqual(len(json.loads(self.paths.duplicate_index.read_text())), 2)
        self.assertEqual(load_attempts(self.paths.draft_log)[0]["state"], "recorded")

    def test_old_confirmed_absence_cannot_clear_new_local_uncertainty(self):
        attempt = self.pending(uncertain=True)
        snapshot = self.snapshot()
        snapshot["datasets"]["gmail_attempts"][0]["state"] = "confirmed_not_created"
        snapshot["gmail_attempt_recovery"]["entries"] = []
        self.restore(snapshot)
        self.assertEqual(load_attempts(self.paths.draft_log)[0]["state"], "uncertain")
        self.assertEqual(load_attempts(self.paths.draft_log)[0]["attempt_id"], attempt["attempt_id"])

    def test_older_pending_backup_does_not_reopen_a_locally_completed_attempt(self):
        attempt = self.pending()
        old = self.snapshot()
        self.recover(attempt, self.paths)
        self.restore(old)
        self.assertEqual(load_attempts(self.paths.draft_log)[0]["state"], "recorded")
        self.assertEqual(services.load_app_reference(self.paths)["pending_gmail_attempts"], [])

    def test_newer_local_sent_history_is_preserved_against_old_active_backup(self):
        with self.fake_transport():
            created = services.create_and_record_gmail_api_draft(self.prepared_request(), self.paths)
        snapshot = self.snapshot()
        services.record_draft({"draft_id": created["draft_id"], "message_id": created["message_id"],
                               "payload": created["draft_payload"], "status": "sent"}, self.paths)
        self.restore(snapshot)
        self.assertEqual(json.loads(self.paths.draft_log.read_text())[0]["status"], "sent")
        self.assertEqual(json.loads(self.paths.duplicate_index.read_text())[0]["status"], "sent")

    def test_missing_files_preserve_visible_blocker_with_actionable_recovery_error(self):
        self.pending()
        attempt = load_attempts(self.paths.draft_log)[0]
        Path(attempt["payload"]).unlink()  # disposable synthetic fixture only
        snapshot = self.snapshot()
        self.assertIn("lack some original", " ".join(snapshot["warnings"]))
        destination = self.destination()
        response = self.restore(snapshot, destination)
        self.assertIn("lack some original", response["message"])
        pending = services.load_app_reference(destination)["pending_gmail_attempts"]
        self.assertEqual(len(pending), 1)
        with self.assertRaisesRegex(IntakeError, "Restore a complete backup"):
            self.recover(load_attempts(destination.draft_log)[0], destination)

    def test_capsule_tampering_and_duplicate_paths_fail_before_history_or_artifact_writes(self):
        self.pending()
        original = self.snapshot()
        mutations = [lambda rows: rows.append(copy.deepcopy(rows[0])),
                     lambda rows: rows[0].update(role="executable"),
                     lambda rows: rows[0].update(data_base64="!!!!"),
                     lambda rows: rows[0].update(data_base64="eA=="),
                     lambda rows: rows[0].update(path="../../fictional.pdf")]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                snapshot = copy.deepcopy(original)
                mutate(snapshot["gmail_attempt_recovery"]["entries"][0]["artifacts"])
                destination = self.destination(f"tamper-{index}")
                before = destination.draft_log.read_bytes(), destination.duplicate_index.read_bytes()
                with self.assertRaises(IntakeError):
                    self.restore(snapshot, destination)
                self.assertEqual((destination.draft_log.read_bytes(), destination.duplicate_index.read_bytes()), before)
                self.assertFalse((destination.draft_output_dir / "restored-attempts").exists())

    def test_journal_cannot_export_files_outside_app_owned_roots(self):
        attempt = self.pending()
        outside = self.root / "fictional-unrelated-secret.json"
        outside.write_text('{"fictional_secret":"must never be read"}')
        attempt["payload"] = str(outside)
        attempt["target"]["draft_payload_sha256"] = backup.digest(outside.read_bytes())
        save_attempts(self.paths.draft_log, [attempt])
        original_open = Path.open
        def guarded_open(path, *args, **kwargs):
            if path == outside:
                raise AssertionError("Outside file was read")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", guarded_open):
            snapshot = self.snapshot()
        self.assertNotIn("must never be read", json.dumps(snapshot))
        self.assertIn("lack some original", " ".join(snapshot["warnings"]))

    def test_conflicting_local_ids_or_request_bindings_abort_without_writes(self):
        self.pending()
        snapshot = self.snapshot()
        snapshot["datasets"]["gmail_attempts"][0]["gmail_result"]["draft_id"] = "fictional-conflicting-id"
        before = self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes(), load_attempts(self.paths.draft_log)
        with self.assertRaisesRegex(IntakeError, "conflicts"):
            self.restore(snapshot)
        self.assertEqual((self.paths.draft_log.read_bytes(), self.paths.duplicate_index.read_bytes(), load_attempts(self.paths.draft_log)), before)

    def test_unreadable_personal_profile_store_is_rejected_before_restore(self):
        snapshot = self.snapshot()
        before = self.paths.personal_profiles.read_bytes()
        for store in ({}, {"profiles": []}, {"profiles": ["invalid"]}, {"profiles": {"broken": []}}):
            with self.subTest(store=store):
                snapshot["datasets"]["personal_profiles"] = store
                with self.assertRaisesRegex(IntakeError, "personal profiles have an invalid structure"):
                    services.preview_local_backup_import({"backup": snapshot}, self.paths)
                with self.assertRaises(IntakeError):
                    self.restore(snapshot)
                self.assertEqual(self.paths.personal_profiles.read_bytes(), before)

    def test_first_run_profile_backup_contains_an_editable_store(self):
        self.paths.personal_profiles.unlink()  # only a disposable synthetic store
        snapshot = self.snapshot()
        self.assertTrue(snapshot["datasets"]["personal_profiles"]["profiles"])
        self.assertEqual(services.preview_local_backup_import({"backup": snapshot}, self.paths)["status"], "ready")

    def test_interrupted_recorded_restore_reserves_blocker_then_retry_finishes(self):
        with self.fake_transport():
            services.create_and_record_gmail_api_draft(self.prepared_request(), self.paths)
        snapshot = self.snapshot()
        for key in ("gmail_draft_log", "duplicate_index", "personal_profiles"):
            with self.subTest(key=key):
                destination = self.destination(key)
                target = services.backup_dataset_paths(destination)[key][0]
                def write(path, value):
                    if path == target:
                        raise OSError("Fictional restore interruption")
                    atomic_write_json(path, value)
                with patch("honorarios_app.services.atomic_write_json", side_effect=write):
                    with self.assertRaises(OSError):
                        self.restore(snapshot, destination)
                attempts = load_attempts(destination.draft_log)
                self.assertIsNotNone(pending_attempt(attempts, attempts[0]["requests"]))
                self.assertTrue(attempts[0]["backup_restore_recorded_pending"])
                self.restore(snapshot, destination)
                self.assertEqual(load_attempts(destination.draft_log)[0]["state"], "recorded")
                self.assertEqual(len(json.loads(destination.duplicate_index.read_text())), 1)

    def test_interrupted_capsule_copy_keeps_reservation_and_retry_recovers(self):
        import os
        self.pending(partial=True)
        snapshot = self.snapshot()
        destination = self.destination()
        original_replace = os.replace
        def replace(source, target):
            if "restored-attempts" in str(target):
                raise OSError("Fictional capsule disk interruption")
            return original_replace(source, target)
        with patch("honorarios_app.backup.os.replace", side_effect=replace):
            with self.assertRaises(OSError):
                self.restore(snapshot, destination)
        attempt = load_attempts(destination.draft_log)[0]
        self.assertIsNotNone(pending_attempt([attempt], attempt["requests"]))
        self.assertTrue(attempt["backup_capsule_pending"])
        fresh = services.prepare_intakes(self.rows(3)[1:], destination, email_grouping="source")
        with patch("honorarios_app.services.create_gmail_draft_from_payload") as transport:
            guarded = services.create_and_record_gmail_api_draft(self.request(fresh, fresh["email_groups"][0]), destination)
        transport.assert_not_called()
        self.assertFalse(guarded["create_retry_allowed"])
        self.restore(snapshot, destination)
        restored = load_attempts(destination.draft_log)[0]
        self.assertNotIn("backup_capsule_pending", restored)
        self.assertTrue(Path(restored["payload"]).is_relative_to(destination.draft_output_dir))
        self.assertEqual(self.recover(restored, destination)["recorded_duplicate_count"], 2)

    def test_failure_finalizing_recorded_journal_keeps_reservation_until_same_backup_retry(self):
        with self.fake_transport():
            services.create_and_record_gmail_api_draft(self.prepared_request(), self.paths)
        snapshot = self.snapshot()
        destination = self.destination()
        count = 0
        def write(log, attempts):
            nonlocal count
            count += 1
            if count == 3:
                raise OSError("Fictional final journal interruption")
            save_attempts(log, attempts)
        with patch("honorarios_app.services.save_attempts", side_effect=write):
            with self.assertRaises(OSError):
                self.restore(snapshot, destination)
        self.assertEqual(load_attempts(destination.draft_log)[0]["state"], "created_unrecorded")
        self.assertEqual(len(json.loads(destination.duplicate_index.read_text())), 1)
        self.restore(snapshot, destination)
        self.assertEqual(load_attempts(destination.draft_log)[0]["state"], "recorded")

    def test_failed_initial_reservation_aborts_before_history_or_capsule_changes(self):
        self.pending()
        snapshot = self.snapshot()
        destination = self.destination()
        before = destination.draft_log.read_bytes(), destination.duplicate_index.read_bytes()
        with patch("honorarios_app.services.save_attempts", side_effect=OSError("Fictional read-only journal")):
            with self.assertRaises(OSError):
                self.restore(snapshot, destination)
        self.assertEqual((destination.draft_log.read_bytes(), destination.duplicate_index.read_bytes()), before)
        self.assertFalse((destination.draft_output_dir / "restored-attempts").exists())

    def test_export_waits_for_same_attempt_history_lock_used_by_create(self):
        started, completed = threading.Event(), threading.Event()
        errors = []
        def run():
            started.set()
            try:
                self.snapshot()
            except BaseException as exc:
                errors.append(exc)
            finally:
                completed.set()
        with backup.runtime_lock(self.paths.draft_log):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(started.wait(2))
            self.assertFalse(completed.wait(.1))
        thread.join(5)
        self.assertTrue(completed.is_set())
        self.assertEqual(errors, [])
