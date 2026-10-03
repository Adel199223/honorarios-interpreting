"""Google Photos contract checks with exact offline HTTP routes and fictional data."""
from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from honorarios_app import services as app
from honorarios_app.runtime import create_synthetic_runtime, runtime_path_overrides
from honorarios_app.web import create_app
from scripts.generate_pdf import IntakeError


class GooglePhotosTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='honorarios-photos-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        create_synthetic_runtime(self.root)
        self.paths = app.AppPaths(**runtime_path_overrides(self.root))
        self.config = self.paths.google_photos_config
        self.token_path = self.config.with_name('google-photos-token.local.json')
        self.config.write_text(json.dumps({'client_id': 'fictional.apps.googleusercontent.com',
                                          'client_secret': 'fictional-client-secret',
                                          'token_path': 'config/google-photos-token.local.json'}), encoding='utf-8')
        self.write_token()
        self.env = patch.dict('os.environ', {key: '' for key in (
            'GOOGLE_PHOTOS_CLIENT_ID', 'GOOGLE_PHOTOS_CLIENT_SECRET', 'GOOGLE_PHOTOS_TOKEN_PATH', 'GOOGLE_PHOTOS_REDIRECT_URI')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.requests = []
        self.ready = True
        self.pages = [{'mediaItems': [self.item()]}]
        self.status = 200
        self.token_payload = {'access_token': 'fictional-new-access', 'refresh_token': 'fictional-new-refresh',
                              'expires_in': 3600, 'scope': app.GOOGLE_PHOTOS_PICKER_SCOPE}
        image = BytesIO()
        Image.new('RGB', (640, 480), 'white').save(image, format='JPEG')
        self.content = image.getvalue()
        self.download_status = 200
        self.original_client = httpx.Client
        self.transport = httpx.MockTransport(self.handle)
        self.client_patch = patch.object(app.httpx, 'Client', side_effect=lambda **kwargs: self.original_client(transport=self.transport, **kwargs))
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)

    @staticmethod
    def item(**changes):
        return {'id': 'fictional-photo', 'type': 'PHOTO', 'createTime': '2026-09-28T23:30:00Z',
                'mediaFile': {'filename': 'case.jpg', 'mimeType': 'image/jpeg',
                              'baseUrl': 'https://lh3.googleusercontent.com/fictional-photo'}, **changes}

    def write_token(self, **changes):
        token = {'access_token': 'fictional-access', 'refresh_token': 'fictional-refresh',
                 'scope': app.GOOGLE_PHOTOS_PICKER_SCOPE,
                 'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), **changes}
        self.token_path.write_text(json.dumps(token), encoding='utf-8')

    def read_token(self):
        return json.loads(self.token_path.read_text(encoding='utf-8'))

    def handle(self, request):
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={'error': 'fictional-private-provider-body'})
        if str(request.url) == app.GOOGLE_OAUTH_TOKEN_URL:
            return httpx.Response(200, json=self.token_payload)
        if request.url.host == 'photospicker.googleapis.com':
            if request.method == 'POST' and request.url.path == '/v1/sessions':
                return httpx.Response(200, json={'id': 'fictional-session', 'pickerUri': 'https://photos.google.com/picker/fictional',
                                                 'pollingConfig': {'pollInterval': '3s'}})
            if request.method == 'GET' and request.url.path == '/v1/sessions/fictional-session':
                return httpx.Response(200, json={'id': 'fictional-session', 'mediaItemsSet': self.ready,
                                                 'pollingConfig': {'pollInterval': '3s'}})
            if request.method == 'GET' and request.url.path == '/v1/mediaItems':
                self.assertEqual(request.url.params['sessionId'], 'fictional-session')
                index = int(request.url.params.get('pageToken', '0'))
                return httpx.Response(200, json=self.pages[index])
        if str(request.url) == 'https://lh3.googleusercontent.com/fictional-photo=d':
            return httpx.Response(self.download_status, content=self.content, headers={'content-type': 'image/jpeg'})
        raise AssertionError('Unexpected offline route: ' + str(request.url))

    def assert_secret_free(self, value):
        serialized = json.dumps(value)
        for secret in ('fictional-access', 'fictional-refresh', 'fictional-new-access', 'fictional-new-refresh',
                       'fictional-client-secret', 'fictional-private-provider-body', 'lh3.googleusercontent.com'):
            self.assertNotIn(secret, serialized)

    def test_relative_token_path_and_secret_free_truthful_status(self):
        self.assertEqual(app._google_photos_config(self.config)['token_path'], self.token_path)
        status = app.google_photos_status_payload(self.config)
        self.assertTrue(status['connected'])
        self.assertFalse(status['connection_verified'])
        self.assertFalse(status['metadata_capabilities']['location_from_picker'])
        self.assert_secret_free(status)
        self.assertFalse(self.requests)
        for token in ({'scope': ''}, {'scope': 'other'}, {'refresh_token': '', 'expires_at': '2000-01-01T00:00:00Z'},
                      {'refresh_token': '', 'expires_at': ''}):
            with self.subTest(token=token):
                self.write_token(**token)
                self.assertFalse(app.google_photos_status_payload(self.config)['connected'])

    def test_create_picker_uses_official_string_max_item_count(self):
        result = app.google_photos_create_picker_session({'max_items': 1}, self.paths)
        self.assertEqual(json.loads(self.requests[0].content)['pickingConfig']['maxItemCount'], '1')
        self.assertEqual(result['session_id'], 'fictional-session')
        self.assert_secret_free(result)

    def test_waiting_selection_does_not_call_list(self):
        self.ready = False
        result = app.google_photos_list_session_media('fictional-session', self.paths)
        self.assertEqual(result['status'], 'waiting_for_selection')
        self.assertEqual(result['polling_config'], {'pollInterval': '3s'})
        self.assertEqual(len(self.requests), 1)
        self.assert_secret_free(result)

    def test_list_uses_session_get_then_paginated_official_media_endpoint(self):
        self.pages = [{'mediaItems': [self.item()], 'nextPageToken': '1'}, {'mediaItems': [self.item(id='second')]}]
        result = app.google_photos_list_session_media('fictional-session', self.paths)
        self.assertEqual(result['selected_count'], 2)
        self.assertEqual([request.url.path for request in self.requests], ['/v1/sessions/fictional-session', '/v1/mediaItems', '/v1/mediaItems'])
        self.assertEqual(result['items'][0]['create_time'], '2026-09-28T23:30:00Z')
        self.assert_secret_free(result)

    def test_import_preserves_server_timestamp_personal_profile_and_exact_download(self):
        with patch.object(app, 'recover_source_upload', return_value={'status': 'uploaded'}) as recover:
            result = app.google_photos_import_selected({'session_id': 'fictional-session', 'personal_profile_id': 'secondary',
                                                       'provider_metadata': {'google_photos_create_time': 'fake-client-date'}}, self.paths)
        values = recover.call_args.kwargs
        self.assertEqual(values['provider_metadata'], {'google_photos_create_time': '2026-09-28T23:30:00Z', 'google_photos_filename': 'case.jpg'})
        self.assertEqual(values['personal_profile_id'], 'secondary')
        self.assertEqual(values['content'], self.content)
        self.assertEqual(str(self.requests[-1].url), 'https://lh3.googleusercontent.com/fictional-photo=d')
        self.assertEqual(self.requests[-1].headers['Authorization'], 'Bearer fictional-access')
        self.assert_secret_free(result)
        self.assertFalse(result['send_allowed'])

    def test_import_rejects_waiting_multiple_and_video_without_source_reading(self):
        scenarios = [(False, [self.item()]), (True, [self.item(), self.item(id='second')]),
                     (True, [self.item(type='VIDEO')])]
        for ready, items in scenarios:
            with self.subTest(ready=ready, items=items), patch.object(app, 'recover_source_upload') as recover:
                self.ready, self.pages, self.requests = ready, [{'mediaItems': items}], []
                with self.assertRaises(IntakeError):
                    app.google_photos_import_selected({'session_id': 'fictional-session'}, self.paths)
                recover.assert_not_called()
                self.assertTrue(all(request.url.host == 'photospicker.googleapis.com' for request in self.requests))

    def test_multiple_items_on_second_page_are_not_silently_discarded(self):
        self.pages = [{'mediaItems': [self.item()], 'nextPageToken': '1'}, {'mediaItems': [self.item(id='second')]}]
        with self.assertRaisesRegex(IntakeError, 'exactly one'), patch.object(app, 'recover_source_upload') as recover:
            app.google_photos_import_selected({'session_id': 'fictional-session'}, self.paths)
        recover.assert_not_called()

    def test_repeated_page_token_stops_incomplete_selection(self):
        self.pages = [{'mediaItems': [self.item()], 'nextPageToken': '1'}, {'mediaItems': [], 'nextPageToken': '1'}]
        with self.assertRaisesRegex(IntakeError, 'incomplete selection'):
            app.google_photos_list_session_media('fictional-session', self.paths)
        self.assertEqual(len(self.requests), 3)

    def test_expired_download_link_and_redirect_do_not_read_source(self):
        for status in (403, 302):
            with self.subTest(status=status), patch.object(app, 'recover_source_upload') as recover:
                self.download_status = status
                with self.assertRaises(IntakeError) as error:
                    app.google_photos_import_selected({'session_id': 'fictional-session'}, self.paths)
                self.assert_secret_free(str(error.exception))
                recover.assert_not_called()

    def test_expired_token_refresh_is_scoped_and_stored(self):
        self.write_token(expires_at='2000-01-01T00:00:00Z')
        status = app.google_photos_status_payload(self.config)
        self.assertTrue(status['refresh_needed'])
        app.google_photos_list_session_media('fictional-session', self.paths)
        self.assertEqual(str(self.requests[0].url), app.GOOGLE_OAUTH_TOKEN_URL)
        self.assertEqual(self.requests[1].headers['Authorization'], 'Bearer fictional-new-access')
        self.assertEqual(self.read_token()['access_token'], 'fictional-new-access')

    def test_missing_scope_stops_before_any_provider_call(self):
        self.write_token(scope='other')
        with self.assertRaisesRegex(IntakeError, 'permission is missing'):
            app.google_photos_list_session_media('fictional-session', self.paths)
        self.assertFalse(self.requests)

    def test_oauth_has_pkce_ttl_and_one_use_state(self):
        started = app.google_photos_oauth_start(self.paths)
        token = self.read_token()
        params = parse_qs(urlparse(started['authorization_url']).query)
        expected = base64.urlsafe_b64encode(hashlib.sha256(token['oauth_code_verifier'].encode()).digest()).rstrip(b'=').decode()
        self.assertEqual(params['code_challenge'], [expected])
        self.assertEqual(params['code_challenge_method'], ['S256'])
        self.assertNotIn(token['oauth_code_verifier'], json.dumps(started))
        response = app.google_photos_oauth_callback(code='fictional-code', state=started['state'], paths=self.paths)
        exchanged = parse_qs(self.requests[0].content.decode())
        self.assertEqual(exchanged['code_verifier'], [token['oauth_code_verifier']])
        self.assertFalse(any(key.startswith('oauth_') for key in self.read_token()))
        self.assert_secret_free(response)
        with self.assertRaisesRegex(IntakeError, 'state mismatch'):
            app.google_photos_oauth_callback(code='fictional-code', state=started['state'], paths=self.paths)
        self.assertEqual(len(self.requests), 1)

    def test_oauth_expired_and_wrong_state_cannot_exchange(self):
        started = app.google_photos_oauth_start(self.paths)
        with self.assertRaisesRegex(IntakeError, 'state mismatch'):
            app.google_photos_oauth_callback(code='fictional-code', state='wrong', paths=self.paths)
        token = self.read_token()
        token['oauth_started_at'] = '2000-01-01T00:00:00+00:00'
        self.token_path.write_text(json.dumps(token), encoding='utf-8')
        with self.assertRaisesRegex(IntakeError, 'authorization expired'):
            app.google_photos_oauth_callback(code='fictional-code', state=started['state'], paths=self.paths)
        self.assertFalse(self.requests)

    def test_oauth_refused_scope_keeps_prior_token_and_consumes_callback(self):
        started = app.google_photos_oauth_start(self.paths)
        self.token_payload['scope'] = 'other'
        with self.assertRaisesRegex(IntakeError, 'permission was not granted'):
            app.google_photos_oauth_callback(code='fictional-code', state=started['state'], paths=self.paths)
        self.assertEqual(self.read_token()['access_token'], 'fictional-access')
        self.assertFalse(any(key.startswith('oauth_') for key in self.read_token()))

    def test_oauth_omitted_scope_means_requested_scope_but_explicit_empty_is_refused(self):
        started = app.google_photos_oauth_start(self.paths)
        self.token_payload.pop('scope')
        result = app.google_photos_oauth_callback(code='fictional-code', state=started['state'], paths=self.paths)
        self.assertEqual(result['scope'], app.GOOGLE_PHOTOS_PICKER_SCOPE)
        started = app.google_photos_oauth_start(self.paths)
        self.token_payload['scope'] = ''
        with self.assertRaisesRegex(IntakeError, 'permission was not granted'):
            app.google_photos_oauth_callback(code='fictional-code', state=started['state'], paths=self.paths)

    def test_provider_errors_are_actionable_without_raw_response_or_url(self):
        for status in (400, 401, 403, 404, 429, 503):
            with self.subTest(status=status):
                self.status = status
                with self.assertRaises(IntakeError) as error:
                    app.google_photos_list_session_media('fictional-session', self.paths)
                self.assertIn(f'HTTP {status}', str(error.exception))
                self.assert_secret_free(str(error.exception))
        with patch.object(self.transport, 'handle_request', side_effect=httpx.ConnectError('fictional-access')):
            with self.assertRaisesRegex(IntakeError, 'could not be reached') as error:
                app.google_photos_list_session_media('fictional-session', self.paths)
            self.assert_secret_free(str(error.exception))

    def test_download_is_bounded_and_never_follows_unexpected_host(self):
        with patch.object(app, 'MAX_SOURCE_UPLOAD_BYTES', 100), patch.object(app, 'recover_source_upload') as recover:
            with self.assertRaisesRegex(IntakeError, '25 MiB'):
                app.google_photos_import_selected({'session_id': 'fictional-session'}, self.paths)
            recover.assert_not_called()
        for url in ('http://lh3.googleusercontent.com/fictional-photo', 'https://attacker.invalid/fictional-photo',
                    'https://googleusercontent.com.attacker.invalid/fictional-photo', 'https://user:pass@lh3.googleusercontent.com/file'):
            with self.subTest(url=url):
                self.requests = []
                item = self.item()
                item['mediaFile']['baseUrl'] = url
                self.pages = [{'mediaItems': [item]}]
                with self.assertRaisesRegex(IntakeError, 'unexpected download address'):
                    app.google_photos_import_selected({'session_id': 'fictional-session'}, self.paths)
                self.assertEqual(len(self.requests), 2)

    def test_import_runs_real_source_review_without_writing_fee_or_draft_records(self):
        before = {path: path.read_bytes() for path in (self.paths.duplicate_index, self.paths.draft_log)}
        result = app.google_photos_import_selected({'session_id': 'fictional-session', 'ai_recovery': 'off'}, self.paths)
        self.assertEqual(result['status'], 'uploaded')
        self.assertEqual(result['source']['metadata']['picker_create_time'], '2026-09-28T23:30:00Z')
        self.assertIn('review', result)
        self.assertFalse(result['send_allowed'])
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertFalse(list(self.paths.output_dir.glob('*')))
        self.assertFalse(list(self.paths.draft_output_dir.glob('*')))


class GooglePhotosCallbackTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='honorarios-photos-callback-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        create_synthetic_runtime(root)
        self.client = TestClient(create_app(**runtime_path_overrides(root)), base_url='http://127.0.0.1')

    def test_browser_success_redirects_off_secret_query_to_readable_local_page(self):
        with patch('honorarios_app.web.google_photos_oauth_callback', return_value={'status': 'connected', 'sentinel': 'private-result'}) as callback:
            response = self.client.get('/api/google-photos/oauth/callback?code=private-code&state=private-state',
                                       headers={'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.url.path, '/google-photos/connected')
        self.assertFalse(response.url.query)
        self.assertEqual(response.history[0].status_code, 303)
        self.assertEqual(response.history[0].headers['location'], '/google-photos/connected')
        self.assertIn('Google Photos connected', response.text)
        self.assertIn('href="/"', response.text)
        self.assertIn('Return to Honorários', response.text)
        for secret in ('private-result', 'private-code', 'private-state'):
            self.assertNotIn(secret, response.text)
        self.assertNotIn('<script', response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.headers['referrer-policy'], 'no-referrer')
        self.assertIn("default-src 'none'", response.headers['content-security-policy'])
        self.assertEqual(callback.call_args.kwargs['code'], 'private-code')

    def test_browser_error_page_never_echoes_provider_or_query_details(self):
        with patch('honorarios_app.web.google_photos_oauth_callback', side_effect=IntakeError('private failure https://private.invalid/token')):
            response = self.client.get('/api/google-photos/oauth/callback?error=private-denial&state=private-state',
                                       headers={'Accept': 'text/html'})
        self.assertEqual(response.url.path, '/google-photos/connection-error')
        self.assertFalse(response.url.query)
        self.assertIn('connection needs another try', response.text)
        self.assertNotIn('private', response.text)
        self.assertNotIn('https://', response.text)
        self.assertEqual(response.history[0].status_code, 303)

    def test_json_success_and_failure_contracts_remain_available(self):
        result = {'status': 'connected', 'provider': 'google_photos', 'send_allowed': False}
        for accept in ('application/json', '*/*', 'text/html;q=0,application/json', 'application/json;q=1,text/html;q=0.5'):
            with self.subTest(accept=accept), patch('honorarios_app.web.google_photos_oauth_callback', return_value=result):
                response = self.client.get('/api/google-photos/oauth/callback?code=fictional&state=fictional', headers={'Accept': accept})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), result)
                self.assertFalse(response.history)
                self.assertEqual(response.headers['cache-control'], 'no-store')
        with patch('honorarios_app.web.google_photos_oauth_callback', side_effect=IntakeError('Start the OAuth flow again.')):
            response = self.client.get('/api/google-photos/oauth/callback', headers={'Accept': 'application/json'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {'detail': 'Start the OAuth flow again.'})
        self.assertEqual(response.headers['cache-control'], 'no-store')


class GooglePhotosUiTests(unittest.TestCase):
    def test_duplicate_import_is_coalesced_and_personal_profile_is_retained(self):
        root = Path(__file__).resolve().parents[1]
        # Exercise the actual import action while its first server response is pending.
        script = r"""
import fs from 'node:fs';import vm from 'node:vm';
const source=fs.readFileSync('honorarios_app/static/app.js','utf8');
const start=source.indexOf('async function importGooglePhotosPickerSelection()');
const end=source.indexOf('\nfunction renderPublicReadiness',start);
let release;const gate=new Promise(resolve=>release=resolve);let calls=0,payload;const busyStates=[];
const context={state:{workflowRevision:0,sourceRecoveryKeys:new Set()},
 $:selector=>({value:({'#google-photos-session-id':'fictional-session','#personal_profile_id':'secondary'})[selector]||''}),
 syncSourceRecoveryGates(){busyStates.push(context.state.sourceRecoveryKeys.size)},
 clearPreparedArtifacts(){context.state.workflowRevision++},clearSourceCaseReview(){},
 async requestWorkflowJson(url,options){calls++;payload=JSON.parse(options.body);await gate;return null;}};
vm.runInNewContext(source.slice(start,end)+'\nthis.run=importGooglePhotosPickerSelection;',context);
const first=context.run();const second=await context.run();const activeBeforeRelease=context.state.sourceRecoveryKeys.size;release();await first;
console.log(JSON.stringify({calls,second,payload,pending:context.state.sourceUploadPending,
 activeBeforeRelease,activeAfterRelease:context.state.sourceRecoveryKeys.size,busyStates}));
"""
        result = subprocess.run(['node', '--input-type=module', '-'], input=script, cwd=root,
                                encoding='utf-8', capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['calls'], 1)
        self.assertEqual(data['payload']['personal_profile_id'], 'secondary')
        self.assertIsNone(data['second'])
        self.assertIsNone(data['pending'])
        self.assertEqual(data['activeBeforeRelease'], 1)
        self.assertEqual(data['activeAfterRelease'], 0)
        self.assertEqual(data['busyStates'], [1, 0])


if __name__ == '__main__':
    unittest.main()
