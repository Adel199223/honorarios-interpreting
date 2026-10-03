"""Offline OAuth, API boundary and atomic sent-transition acceptance."""
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs

from fastapi.testclient import TestClient
from honorarios_app import gmail_draft_api as gmail
from honorarios_app import services
from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from honorarios_app.web import create_app
from scripts.generate_pdf import IntakeError
from scripts.record_gmail_draft import apply_verified_sent_unlocked


class GmailSentSyncApiTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='sent-sync-api-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        create_synthetic_runtime(self.root)
        self.paths = services.AppPaths(**runtime_path_overrides(self.root))
        self.config = self.paths.gmail_config
        self.config.write_text(json.dumps({'client_id': 'fictional.apps.googleusercontent.com', 'client_secret': 'fictional-secret'}))
        self.token_path = self.config.with_name('gmail-token.local.json')
        self.original = {'access_token': 'fictional-access', 'refresh_token': 'fictional-refresh', 'scope': gmail.GMAIL_COMPOSE_SCOPE}
        self.save_token(self.original)
        env = patch.dict(os.environ, {key: '' for key in ('GMAIL_CLIENT_ID','GMAIL_CLIENT_SECRET','GMAIL_TOKEN_PATH','GMAIL_REDIRECT_URI',
            'HONORARIOS_FAKE_GMAIL_DRAFT_API_FOR_SMOKE','HONORARIOS_FAKE_GMAIL_SENT_SYNC_FOR_SMOKE')})
        env.start(); self.addCleanup(env.stop)
        self.client = TestClient(create_app(**runtime_path_overrides(self.root)), base_url='http://127.0.0.1')

    def save_token(self, value): self.token_path.write_text(json.dumps(value))
    def token(self): return json.loads(self.token_path.read_text())
    def start(self): return gmail.gmail_oauth_start(self.config, purpose='sent_sync')['state']
    def grant(self, **changes):
        return {'access_token':'new-access','refresh_token':'new-refresh',
                'scope': gmail.GMAIL_COMPOSE_SCOPE+' '+gmail.GMAIL_READONLY_SCOPE, **changes}
    def callback(self, state): return gmail.gmail_oauth_callback(code='fictional-code', state=state, config_path=self.config)

    def test_incremental_start_preserves_actual_scope_and_working_credentials(self):
        result = gmail.gmail_oauth_start(self.config, purpose='sent_sync')
        query = parse_qs(urlparse(result['authorization_url']).query)
        self.assertEqual(query['include_granted_scopes'], ['true'])
        self.assertIn(gmail.GMAIL_READONLY_SCOPE, query['scope'][0])
        for key,value in self.original.items(): self.assertEqual(self.token()[key], value)
        self.assertFalse(gmail.gmail_sent_read_ready(self.config))

    def test_denial_preserves_connection_and_consumes_state(self):
        state=self.start()
        with self.assertRaises(IntakeError): gmail.gmail_oauth_callback(code='',state=state,error='access_denied',config_path=self.config)
        self.assertEqual(self.token(),self.original)
        with self.assertRaises(IntakeError): self.callback(state)

    def test_partial_and_unspecified_scopes_never_replace_working_token(self):
        for scope in ('', gmail.GMAIL_READONLY_SCOPE, gmail.GMAIL_COMPOSE_SCOPE):
            state=self.start()
            with patch.object(gmail,'exchange_google_token',return_value=self.grant(scope=scope)), self.assertRaises(IntakeError): self.callback(state)
            self.assertEqual(self.token(),self.original)

    def test_success_checks_account_and_is_not_replayable(self):
        state=self.start()
        with patch.object(gmail,'exchange_google_token',return_value=self.grant()), patch.object(gmail,'_gmail_account_hash',return_value='same-account'):
            response=self.callback(state)
        self.assertTrue(response['connected']); self.assertTrue(gmail.gmail_sent_read_ready(self.config))
        self.assertEqual(self.token()['gmail_account_hash'],'same-account')
        self.assertNotIn('access_token',response)
        with self.assertRaises(IntakeError): self.callback(state)

    def test_missing_refresh_retained_only_for_verified_same_account(self):
        self.original['gmail_account_hash']='same-account';self.save_token(self.original)
        state=self.start();grant=self.grant();grant.pop('refresh_token')
        with patch.object(gmail,'exchange_google_token',return_value=grant), patch.object(gmail,'_gmail_account_hash',return_value='same-account'):
            self.callback(state)
        self.assertEqual(self.token()['refresh_token'],'fictional-refresh')
        self.save_token(self.original);state=self.start()
        with patch.object(gmail,'exchange_google_token',return_value=grant), patch.object(gmail,'_gmail_account_hash',return_value='different-account'), self.assertRaises(IntakeError): self.callback(state)
        self.assertEqual(self.token(),self.original)

    def test_expired_callback_does_not_exchange(self):
        state=self.start();token=self.token();token['oauth_started_at']=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat();self.save_token(token)
        with patch.object(gmail,'exchange_google_token') as exchange, self.assertRaises(IntakeError): self.callback(state)
        exchange.assert_not_called();self.assertEqual(self.token(),self.original)

    def test_wrong_state_does_not_consume_pending_authorization(self):
        self.start();before=self.token()
        with self.assertRaises(IntakeError): self.callback('wrong-state')
        self.assertEqual(self.token(),before)

    def test_readonly_token_does_not_enable_draft_creation(self):
        self.save_token({**self.original,'scope':gmail.GMAIL_READONLY_SCOPE})
        self.assertTrue(gmail.gmail_sent_read_ready(self.config))
        self.assertFalse(gmail.gmail_status_payload(self.config)['draft_create_ready'])

    def test_provider_error_details_are_redacted_and_credentials_preserved(self):
        state=self.start()
        with patch.object(gmail,'exchange_google_token',side_effect=IntakeError('fictional-secret-provider-detail')):
            with self.assertRaises(IntakeError) as error: self.callback(state)
        self.assertNotIn('fictional-secret',str(error.exception));self.assertEqual(self.token(),self.original)

    def test_refresh_cannot_overwrite_concurrent_authorization(self):
        self.save_token({**self.original,'expires_at':'2020-01-01T00:00:00+00:00'})
        state=self.start();entered=threading.Event();release=threading.Event();errors=[]
        def exchange(form):
            if form['grant_type']=='refresh_token':
                entered.set()
                if not release.wait(3): raise RuntimeError('test timeout')
                return {'access_token':'refreshed-old','scope':gmail.GMAIL_COMPOSE_SCOPE}
            return self.grant()
        def run(action):
            try: action()
            except Exception as error: errors.append(error)
        with patch.object(gmail,'exchange_google_token',side_effect=exchange), patch.object(gmail,'_gmail_account_hash',return_value='same-account'):
            refresh=threading.Thread(target=run,args=(lambda:gmail.gmail_access_token(self.config),));refresh.start()
            self.assertTrue(entered.wait(3))
            callback=threading.Thread(target=run,args=(lambda:self.callback(state),));callback.start()
            release.set();refresh.join(3);callback.join(3)
        self.assertFalse(refresh.is_alive());self.assertFalse(callback.is_alive());self.assertFalse(errors)
        self.assertEqual(self.token()['access_token'],'new-access');self.assertNotIn('oauth_state',self.token())

    def test_status_and_wrong_workspace_are_nonwriting_and_secret_free(self):
        before=self.token_path.read_bytes()
        response=self.client.get('/api/gmail/sent-sync/status')
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json()['read_ready'])
        self.assertNotIn('fictional-secret',response.text)
        response=self.client.post('/api/gmail/sent-sync',json={'workspace_id':'wrong'})
        self.assertEqual(response.status_code,400)
        self.assertFalse(response.json()['send_allowed'])
        self.assertEqual(self.token_path.read_bytes(),before)

    def test_cross_origin_cannot_start_sync_or_oauth(self):
        for route in ('/api/gmail/sent-sync','/api/gmail/oauth/start'):
            response=self.client.post(route,json={},headers={'Origin':'https://evil.example'})
            self.assertEqual(response.status_code,403)

    def seed_group(self):
        children=[{'case_number':f'{i}/26.0TEST','service_date':'2026-10-01','pdf':f'file-{i}.pdf','claim_transport':i==1} for i in (1,2)]
        record={'draft_id':'draft-test','message_id':'old-message','thread_id':'old-thread','status':'active',
                'created_at':'2026-10-01T10:00:00+00:00','underlying_requests':children,'custom_history':'retain',
                'attachment_sha256': {'original.pdf':'original-hash'}}
        index=[dict(child,draft_id='draft-test',status='drafted',message_id='old-message',custom_child='retain') for child in children]
        evidence={'sent_message_id':'sent-message','sent_thread_id':'sent-thread','sent_at':'2026-10-02T10:00:00+00:00',
                  'sent_date':'2026-10-02','sent_verified_at':'2026-10-02T11:00:00+00:00',
                  'verification_method':'gmail_sent_exact_attachments','attachment_sha256':['a'*64,'b'*64]}
        self.paths.draft_log.write_text(json.dumps([record]));self.paths.duplicate_index.write_text(json.dumps(index))
        return record,index,evidence

    def test_all_group_children_and_original_metadata_survive_sent_transition(self):
        record,index,evidence=self.seed_group()
        result=apply_verified_sent_unlocked(self.paths.draft_log,self.paths.duplicate_index,record,evidence)
        self.assertEqual(result['sent_request_count'],2)
        updated=json.loads(self.paths.draft_log.read_text())[0]
        self.assertEqual(updated['message_id'],'old-message');self.assertEqual(updated['underlying_requests'],record['underlying_requests'])
        self.assertEqual(updated['custom_history'],'retain')
        self.assertEqual(updated['attachment_sha256'],record['attachment_sha256'])
        self.assertEqual(updated['sent_attachment_sha256'],evidence['attachment_sha256'])
        for child in json.loads(self.paths.duplicate_index.read_text()):
            self.assertEqual(child['status'],'sent');self.assertEqual(child['custom_child'],'retain')
            self.assertEqual(child['message_id'],'old-message');self.assertEqual(child['sent_message_id'],'sent-message')

    def test_second_write_failure_keeps_blockers_and_retry_repairs_log(self):
        record,index,evidence=self.seed_group()
        with patch('scripts.record_gmail_draft.write_log',side_effect=OSError('fictional failure')), self.assertRaises(OSError):
            apply_verified_sent_unlocked(self.paths.draft_log,self.paths.duplicate_index,record,evidence)
        self.assertEqual(json.loads(self.paths.draft_log.read_text())[0]['status'],'active')
        self.assertTrue(all(row['status']=='sent' for row in json.loads(self.paths.duplicate_index.read_text())))
        apply_verified_sent_unlocked(self.paths.draft_log,self.paths.duplicate_index,record,evidence)
        self.assertEqual(json.loads(self.paths.draft_log.read_text())[0]['status'],'sent')

    def test_partial_retry_refuses_conflicting_sent_evidence(self):
        record,index,evidence=self.seed_group()
        with patch('scripts.record_gmail_draft.write_log',side_effect=OSError()), self.assertRaises(OSError):
            apply_verified_sent_unlocked(self.paths.draft_log,self.paths.duplicate_index,record,evidence)
        evidence['sent_message_id']='different-message'
        with self.assertRaises(ValueError): apply_verified_sent_unlocked(self.paths.draft_log,self.paths.duplicate_index,record,evidence)

    def test_changed_record_missing_child_or_retired_child_never_partially_update(self):
        for variant in ('record','missing','retired'):
            record,index,evidence=self.seed_group()
            if variant=='record': record['custom_history']='changed'
            elif variant=='missing': self.paths.duplicate_index.write_text(json.dumps(index[:1]))
            else: index[0]['status']='trashed';self.paths.duplicate_index.write_text(json.dumps(index))
            before=(self.paths.draft_log.read_bytes(),self.paths.duplicate_index.read_bytes())
            with self.assertRaises(ValueError): apply_verified_sent_unlocked(self.paths.draft_log,self.paths.duplicate_index,record,evidence)
            self.assertEqual(before,(self.paths.draft_log.read_bytes(),self.paths.duplicate_index.read_bytes()))


if __name__ == '__main__': unittest.main()
