import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests
from main import run, main
from paperbot.ai import validate, summarize
from paperbot.arxiv import parse_id
from paperbot.config import Config
from paperbot.feishu import send, card
from paperbot.state import State
from paperbot.zotero import Zotero, note_html, item_identity, OWNER_TAG, OWNER_MARK
from paperbot.http import read, error_summary

PAPER = {'id': '2609.21848', 'version': 1, 'title': 'Edge computing <script>& test',
         'abstract': 'LLM cloud-edge <b>abstract</b>', 'url': 'https://arxiv.org/abs/2609.21848v1',
         'authors': ['First', 'Last']}
SUMMARY = validate({'relevant': True, 'method': '<script>unsafe & "text"</script>', 'keywords': ['边云协同']})
RECORD = {'paper': PAPER, 'ai': SUMMARY, 'model': '<model>', 'generated_at': '2026-10-05'}


class FakeZotero(Zotero):
    """In-memory server: exercises real deduplication/note code without HTTP."""
    def __init__(self):
        super().__init__(Config())
        self.items, self.notes, self.collections, self.writes = [], [], [], []
        self.lose_response = False

    def all(self, path):
        return copy.deepcopy(self.collections if path == '/collections' else
                             self.items if path == '/items/top' else self.notes)

    def create(self, path, data):
        key = 'KEY' + str(len(self.writes))
        item = {'key': key, 'version': 1, 'data': copy.deepcopy(data)}
        self.writes.append(item)
        target = self.collections if path == '/collections' else self.notes if data['itemType'] == 'note' else self.items
        target.append(item)
        if self.lose_response and path == '/items':
            self.lose_response = False
            raise requests.Timeout()
        return key


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'state.json'
        self.config = Config(enable_ai_notes=True)
        self.zot = FakeZotero()
        self.ai = Mock(return_value=copy.deepcopy(SUMMARY))
        self.sender = Mock()

    def tearDown(self):
        self.tmp.cleanup()

    def execute(self, papers=None, day='2026-10-05'):
        with State(self.path, dry_run=self.config.dry_run) as state:
            code = run(self.config, state, [copy.deepcopy(PAPER)] if papers is None else papers,
                       self.ai, self.zot, self.sender, day)
            return code, copy.deepcopy(state.data)

    def test_id_formats(self):
        for value, expected in [
            ('2609.21848v12', ('2609.21848', 12)),
            ('https://arxiv.org/pdf/2609.21848v2.pdf', ('2609.21848', 2)),
            ('http://arxiv.org/abs/hep-th/9901001v3', ('hep-th/9901001', 3)),
            ('https://doi.org/10.48550/arXiv.2609.21848', ('2609.21848', None)),
            ('arXiv: 2609.21848\narXiv version: 1', ('2609.21848', None)),
            ('https://example.org/2609.21848', (None, None))]:
            with self.subTest(value=value):
                self.assertEqual(parse_id(value), expected)

    def test_repeat_and_new_version_preserve_first_preview(self):
        self.assertEqual(self.execute()[0], 0)
        newer = {**PAPER, 'version': 2, 'abstract': 'Changed LLM abstract'}
        _, data = self.execute([newer])
        self.assertEqual(len(self.zot.items), 1)
        self.assertEqual(len(self.zot.notes), 1)
        self.ai.assert_called_once()
        self.sender.assert_called_once()
        self.assertEqual(data['papers'][PAPER['id']]['observed_versions'], [1, 2])
        self.assertEqual(self.zot.items[0]['data']['abstractNote'], PAPER['abstract'])
        self.assertIn('arXiv version: 1', self.zot.items[0]['data']['extra'])

    def test_legacy_recognition_only_changes_collection(self):
        old = {'key': 'OLD', 'version': 8, 'data': {'url': PAPER['url'], 'collections': [], 'abstractNote': 'personal old content'}}
        self.zot.items.append(old)
        with patch('paperbot.zotero.requests.patch') as write:
            self.assertEqual(self.zot.ensure_paper(PAPER), 'OLD')
            self.assertEqual(write.call_args.kwargs['json'], {'collections': [self.zot.collection_key]})
            self.assertEqual(write.call_args.kwargs['headers']['If-Unmodified-Since-Version'], '8')
        self.assertEqual(old['data']['abstractNote'], 'personal old content')
        self.assertEqual(item_identity({'DOI': '10.48550/arXiv.2609.21848'}), PAPER['id'])

    def test_historical_duplicates_report_no_write(self):
        self.zot.items = [{'key': key, 'data': {'url': PAPER['url']}} for key in ['A', 'B']]
        with self.assertLogs('paperbot.zotero', level='ERROR') as logs:
            with self.assertRaises(ValueError):
                self.zot.ensure_paper(PAPER)
        self.assertIn('A,B', ''.join(logs.output))
        self.assertEqual(self.zot.writes, [])

    def test_personal_same_title_note_untouched(self):
        personal = {'key': 'PERSONAL', 'data': {'itemType': 'note', 'note': '<h1>AI 预览｜基于摘要</h1>My judgment', 'tags': []}}
        self.zot.notes.append(copy.deepcopy(personal))
        key = self.zot.ensure_note('PARENT', RECORD)
        self.assertNotEqual(key, 'PERSONAL')
        self.assertEqual(self.zot.notes[0], personal)
        self.assertEqual(self.zot.ensure_note('PARENT', RECORD), key)
        self.assertEqual(len(self.zot.notes), 2)

    def test_only_one_management_marker_is_insufficient(self):
        self.zot.notes = [
            {'key': 'TAG_ONLY', 'data': {'itemType': 'note', 'note': 'My judgment', 'tags': [{'tag': OWNER_TAG}]}},
            {'key': 'BODY_ONLY', 'data': {'itemType': 'note', 'note': OWNER_MARK, 'tags': []}}]
        before = copy.deepcopy(self.zot.notes)
        key = self.zot.ensure_note('PARENT', RECORD)
        self.assertNotIn(key, ['TAG_ONLY', 'BODY_ONLY'])
        self.assertEqual(self.zot.notes[:2], before)

    def test_html_escape_all_untrusted_content(self):
        html = note_html(RECORD)
        self.assertNotIn('<script>', html)
        self.assertNotIn('<b>abstract</b>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('&lt;model&gt;', html)
        self.assertIn('&quot;text&quot;', html)
        self.assertIn(OWNER_MARK, html)

    def test_ai_failure_not_rejection_and_retries_outside_feed(self):
        self.ai.side_effect = ValueError('invalid structured output')
        code, data = self.execute()
        self.assertEqual(code, 1)
        self.assertNotIn('ai', data['papers'][PAPER['id']])
        self.sender.assert_not_called()
        self.ai.side_effect = None
        self.assertEqual(self.execute([])[0], 0)

    def test_rejection_is_cached(self):
        self.ai.return_value = {'relevant': False}
        self.execute()
        self.execute()
        self.ai.assert_called_once()
        self.sender.assert_not_called()
        self.assertEqual(self.zot.writes, [])

    def test_missing_and_invalid_structured_output(self):
        self.assertEqual(validate({'relevant': True})['claimed_results'], '摘要未说明')
        for invalid in [{'relevant': 'true'}, {'relevant': True, 'method': []}, {'relevant': True, 'keywords': [1]}, []]:
            with self.assertRaises(ValueError):
                validate(invalid)

    def test_zotero_uncertain_create_recovered_without_duplicate(self):
        self.zot.lose_response = True
        code, data = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(data['papers'][PAPER['id']]['feishu_status'], 'sent')
        self.assertEqual(self.execute([])[0], 0)
        self.assertEqual(len(self.zot.items), 1)
        self.sender.assert_called_once()
        self.ai.assert_called_once()

    def test_feishu_failure_retains_zotero_and_reserves_budget(self):
        self.sender.side_effect = requests.Timeout()
        _, data = self.execute()
        self.assertIn('zotero_key', data['papers'][PAPER['id']])
        self.assertEqual(data['papers'][PAPER['id']]['feishu_status'], 'pending')
        self.assertEqual(data['attempts']['2026-10-05'], 1)
        self.sender.side_effect = None
        self.execute([])
        self.execute()
        self.assertEqual(self.sender.call_count, 2)
        self.assertEqual(len(self.zot.items), 1)

    def test_notes_disabled_then_enabled_reuses_ai(self):
        self.config.enable_ai_notes = False
        self.execute()
        self.assertEqual(len(self.zot.notes), 0)
        self.config.enable_ai_notes = True
        self.execute([])
        self.ai.assert_called_once()
        self.assertEqual(len(self.zot.notes), 1)

    def test_note_failure_does_not_lose_library_success(self):
        original = self.zot.ensure_note
        self.zot.ensure_note = Mock(side_effect=requests.Timeout())
        code, data = self.execute()
        self.assertEqual(code, 1)
        self.assertIn('zotero_key', data['papers'][PAPER['id']])
        self.assertEqual(data['papers'][PAPER['id']]['feishu_status'], 'sent')
        self.zot.ensure_note = original
        self.execute([])
        self.assertEqual(len(self.zot.items), 1)

    def test_daily_budget_shared_across_runs(self):
        papers = [{**PAPER, 'id': f'2609.2184{i}'} for i in range(5)]
        self.execute(papers)
        self.execute(papers)
        self.assertEqual(self.sender.call_count, 3)
        self.execute(papers, day='2026-10-06')
        self.assertEqual(self.sender.call_count, 5)

    def test_dry_run_no_ai_no_writes_no_state_directory(self):
        self.config.dry_run = True
        self.path = self.path.parent / 'absent' / 'state.json'
        self.execute()
        self.assertFalse(self.path.parent.exists())
        self.ai.assert_not_called()
        self.sender.assert_not_called()
        self.assertEqual(self.zot.writes, [])

    def test_dry_run_keeps_existing_state_byte_identical(self):
        self.execute()
        before = self.path.read_bytes()
        self.config.dry_run = True
        self.execute([{**PAPER, 'version': 9}])
        self.assertEqual(self.path.read_bytes(), before)

    def test_uncertain_note_write_reconciles_owned_note(self):
        self.zot.ensure_paper(PAPER)
        self.zot.lose_response = True
        self.assertEqual(self.execute()[0], 1)
        self.assertEqual(len(self.zot.notes), 1)
        self.assertEqual(self.execute([])[0], 0)
        self.assertEqual(len(self.zot.notes), 1)

    def test_destinations_independent(self):
        self.config.enable_zotero = False
        self.execute()
        self.assertEqual(self.zot.writes, [])
        self.sender.assert_called_once()
        self.config.enable_zotero = True
        self.config.enable_feishu = False
        self.execute([])
        self.sender.assert_called_once()
        self.assertEqual(len(self.zot.items), 1)

    def test_state_failure_stops_before_service_writes(self):
        with State(self.path) as state:
            state.save = Mock(side_effect=RuntimeError('checkpoint failed'))
            with self.assertRaises(RuntimeError):
                run(self.config, state, [PAPER], self.ai, self.zot, self.sender, '2026-10-05')
        self.sender.assert_not_called()
        self.assertEqual(self.zot.writes, [])


class PersistenceTests(unittest.TestCase):
    def test_ephemeral_runs_recheck_zotero_without_files_or_git(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'unused' / 'state.json'
            config = Config(enable_ai_notes=True)
            zot = FakeZotero()
            ai, sender = Mock(return_value=copy.deepcopy(SUMMARY)), Mock()
            with patch('paperbot.state.subprocess.run') as git:
                for _ in range(2):
                    with State(path, persistent=False) as state:
                        self.assertEqual(run(config, state, [copy.deepcopy(PAPER)],
                                             ai, zot, sender, day='2026-10-05'), 0)
                        self.assertEqual(state.data['attempts']['2026-10-05'], 1)
                git.assert_not_called()
            self.assertFalse(path.parent.exists())
            self.assertEqual(len(zot.items), 1)
            self.assertEqual(len(zot.notes), 1)
            self.assertEqual(ai.call_count, 2)
            self.assertEqual(sender.call_count, 2)

    def test_ephemeral_state_does_not_read_or_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            path.write_bytes(b'private old state, even if invalid JSON')
            with State(path, persistent=False) as state:
                self.assertEqual(state.data['papers'], {})
                state.data['papers']['example'] = {'done': True}
                state.save()
            self.assertEqual(path.read_bytes(), b'private old state, even if invalid JSON')
            self.assertFalse(path.with_suffix('.lock').exists())
            self.assertFalse(path.with_suffix('.tmp').exists())

    def test_cli_persistence_is_opt_in(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch('main.Config.from_env') as config, \
                patch('main.fetch_papers', return_value=[]), \
                patch('main.State', wraps=State) as state_class:
            config.return_value = Config(enable_feishu=False, enable_zotero=False)
            with patch('sys.argv', ['main.py']):
                self.assertEqual(main(), 0)
            self.assertFalse(state_class.call_args.kwargs['persistent'])
            path = Path(directory) / 'local.json'
            with patch('sys.argv', ['main.py', '--state', str(path)]):
                self.assertEqual(main(), 0)
            self.assertTrue(state_class.call_args.kwargs['persistent'])
            self.assertFalse(path.with_suffix('.lock').exists())
            config.return_value.enable_persistence = True
            with patch('sys.argv', ['main.py']), \
                    patch('main.State') as enabled_state:
                self.assertEqual(main(), 0)
                self.assertTrue(enabled_state.call_args.kwargs['persistent'])

    def test_persistence_env_default_and_boolean_values(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertFalse(Config.from_env(dry_run=True).enable_persistence)
            for value, expected in [('true', True), ('1', True), ('FALSE', False), ('0', False)]:
                with patch.dict('os.environ', {'ENABLE_PERSISTENCE': value}):
                    self.assertEqual(Config.from_env(dry_run=True).enable_persistence, expected)
            with patch.dict('os.environ', {'ENABLE_PERSISTENCE': 'invalid'}):
                with self.assertRaises(ValueError):
                    Config.from_env(dry_run=True)


class ResponseTests(unittest.TestCase):
    def test_http_logs_safe_status_and_bounded_retry(self):
        response = Mock(status_code=503)
        failure = requests.HTTPError('secret-key https://private-webhook.invalid/token', response=response)
        with patch('paperbot.http.requests.get', side_effect=failure) as get, patch('paperbot.http.time.sleep') as sleep:
            with self.assertLogs('paperbot.http', level='WARNING') as logs:
                with self.assertRaises(requests.HTTPError):
                    read('https://private-webhook.invalid/token', service='arXiv')
        output = '\n'.join(logs.output)
        self.assertIn('arXiv', output)
        self.assertIn('HTTP 503', output)
        self.assertIn('3 attempt(s)', output)
        self.assertNotIn('secret-key', output)
        self.assertNotIn('private-webhook', output)
        self.assertEqual(get.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [3, 6])
        self.assertEqual(error_summary(SimpleNamespace(status_code=429)), 'SimpleNamespace; HTTP 429')

    def test_main_identifies_arxiv_failure_without_writing_or_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            response = Mock(status_code=429)
            with patch('sys.argv', ['main.py', '--dry-run', '--state', str(Path(directory) / 'state.json')]), \
                 patch('main.Config.from_env', return_value=Config(dry_run=True)), \
                 patch('main.fetch_papers', side_effect=requests.HTTPError('private-value', response=response)), \
                 patch('main.run') as pipeline:
                with self.assertLogs('main', level='ERROR') as logs:
                    self.assertEqual(main(), 1)
                self.assertIn('arXiv fetch', '\n'.join(logs.output))
                self.assertIn('HTTP 429', '\n'.join(logs.output))
                self.assertNotIn('private-value', '\n'.join(logs.output))
                pipeline.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_feishu_short_preview_keeps_details_in_zotero_only(self):
        record = copy.deepcopy(RECORD)
        record['ai'].update(
            translated_title='译名', one_sentence='核心贡献', research_question='研究场景',
            method='协同架构', claimed_results='延迟降低3.17倍',
            missing_information='设备未说明', relation='AI 推测：研究关联', keywords=['稳定检索词'])
        rendered = card(record)
        content = rendered['card']['elements'][0]['content']
        for text in ['标题翻译：译名', '🌟 一句话总结：核心贡献', '🔍 痛点与场景：研究场景',
                     '🛠️ 核心架构/方法：协同架构', '📈 评估效果：延迟降低3.17倍']:
            self.assertIn(text, content)
        for text in ['摘要事实', '未独立验证', '设备未说明', 'AI 推测', '稳定检索词', '检索词：']:
            self.assertNotIn(text, content)
        self.assertEqual(rendered['card']['elements'][1]['actions'][0]['url'], PAPER['url'])
        html = note_html(record)
        for text in ['设备未说明', 'AI 推测', '稳定检索词', '未独立验证', '仅标题与摘要']:
            self.assertIn(text, html)

    def test_ai_invalid_json_truncated_and_service_failure(self):
        completion = Mock()
        fake_module = SimpleNamespace(OpenAI=Mock(return_value=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))))
        choice = SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content='not JSON'))
        completion.return_value = SimpleNamespace(choices=[choice])
        with patch.dict('sys.modules', {'openai': fake_module}):
            with self.assertRaises(json.JSONDecodeError):
                summarize(PAPER, Config())
            choice.message.content = '{"relevant": true}'
            result = summarize(PAPER, Config())
            self.assertEqual(result['method'], '摘要未说明')
            choice.finish_reason = 'length'
            with self.assertRaises(ValueError):
                summarize(PAPER, Config())
            completion.side_effect = requests.Timeout()
            with self.assertRaises(requests.Timeout):
                summarize(PAPER, Config())
        self.assertEqual(fake_module.OpenAI.call_args.kwargs['max_retries'], 2)

    def test_zotero_pagination(self):
        first, last = Mock(), Mock()
        first.json.return_value = [{'key': str(i)} for i in range(100)]
        last.json.return_value = [{'key': 'last'}]
        with patch('paperbot.zotero.read', side_effect=[first, last]) as get:
            self.assertEqual(len(Zotero(Config()).all('/items/top')), 101)
            self.assertEqual(get.call_args.kwargs['params']['start'], 100)

    def test_get_retry_is_bounded_and_client_error_not_retried(self):
        with patch('paperbot.http.requests.get', side_effect=requests.Timeout()) as get, patch('paperbot.http.time.sleep'):
            with self.assertRaises(requests.Timeout):
                read('https://example.invalid')
            self.assertEqual(get.call_count, 3)
        response = Mock(status_code=403)
        with patch('paperbot.http.requests.get', side_effect=requests.HTTPError(response=response)) as get:
            with self.assertRaises(requests.HTTPError):
                read('https://example.invalid')
            get.assert_called_once()

    def test_git_checkpoint_push_failure_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            path.write_text('{"schema":1,"papers":{},"attempts":{}}', encoding='utf-8')
            def git_result(command, **kwargs):
                args = command[3:]
                stdout = ''
                if args == ['rev-parse', '--show-toplevel']:
                    stdout = directory
                elif args == ['branch', '--show-current']:
                    stdout = 'bot-state'
                elif args == ['diff', '--cached', '--name-only']:
                    stdout = 'state.json'
                return SimpleNamespace(returncode=int(args[0] == 'push'), stdout=stdout)
            with patch('paperbot.state.subprocess.run', side_effect=git_result) as git:
                with State(path, git=True) as state:
                    with self.assertRaises(RuntimeError):
                        state.save()
            calls = [call.args[0][3:] for call in git.call_args_list]
            self.assertIn(['push', 'origin', 'HEAD:bot-state'], calls)
            self.assertNotIn('--force', str(calls))
            self.assertFalse(path.with_suffix('.lock').exists())

    def test_git_state_missing_refuses_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            with self.assertRaises(ValueError):
                with State(path, git=True):
                    pass
            self.assertFalse(path.exists())

    def test_feishu_checks_application_code_and_http(self):
        with patch('paperbot.feishu.requests.post') as post:
            post.return_value.json.return_value = {'code': 1}
            with self.assertRaises(ValueError):
                send(RECORD, Config())
            post.return_value.json.return_value = {'code': 0}
            send(RECORD, Config())
            self.assertEqual(post.call_args.kwargs['timeout'], (10, 30))
            post.return_value.raise_for_status.side_effect = requests.HTTPError()
            with self.assertRaises(requests.HTTPError):
                send(RECORD, Config())
        self.assertNotIn('通讯作者', str(card(RECORD)))

    def test_zotero_checks_per_item_errors(self):
        with patch('paperbot.zotero.requests.post') as post:
            post.return_value.json.return_value = {'successful': {}, 'failed': {'0': {'code': 400}}}
            with self.assertRaises(ValueError):
                Zotero(Config()).create('/items', {})

    def test_state_lock_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            with State(path):
                with self.assertRaises(FileExistsError):
                    with State(path):
                        pass
            path.write_text('{invalid', encoding='utf-8')
            with self.assertRaises(json.JSONDecodeError):
                with State(path):
                    pass
            self.assertFalse(path.with_suffix('.lock').exists())


if __name__ == '__main__':
    unittest.main()
