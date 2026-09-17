from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import unittest
from pathlib import Path

from test_regression import ProjectHarness, PYTHON, ROOT, STARTER, make_temp_dir, remove_tree, run, write_json


class ContextEfficiencyTests(unittest.TestCase):
    def project(self, mode='standard'):
        return ProjectHarness(self, governance_mode=mode)

    def requirement(self, h, title='Current feature', **extra):
        payload = {'actor_role': 'project_manager_agent', 'action': 'create', 'title': title,
                   'description': 'Formal behavior of ' + title, 'status': 'active',
                   'module': 'Core', 'summary': 'One current behavior', 'architecture_refs': [],
                   'acceptance_criteria': [{'description': 'Check ' + title, 'method': 'automatic', 'status': 'pending'}], **extra}
        write_json(h.root / '.ai/runtime/requirement_update.json', payload)
        return h.tool('ai-requirement')

    def start(self, h, refs=None, units=False, **extra):
        payload = {'batch_id': 'P1-001', 'stage_id': 'P1', 'title': 'Regression batch', 'goal': 'Implement current feature',
                   'scope': ['src/current'], 'acceptance_criteria': ['current feature passes'],
                   'change_ids': [], 'execution_mode': 'single',
                   'context_refs': refs or {'requirements': [], 'architecture': [], 'decisions': []}, **extra}
        if units:
            payload['work_units'] = [{'unit_id': 'U1', 'title': 'First component', 'scope': ['src/a']},
                                     {'unit_id': 'U2', 'title': 'Second component', 'scope': ['src/b']}]
            payload['required_checks'] = ['consumer', 'browser', 'package', 'report', 'checks']
        write_json(h.root / '.ai/runtime/batch_request.json', payload)
        return h.tool('ai-start')

    def evidence(self, h, level='L1', fail=False, lines=1, purpose=None):
        script = "import json,pathlib; r=json.loads(pathlib.Path('.ai/requirement_registry.json').read_text(encoding='utf-8')); assert 'requirements' in r; "
        script += f"print('PASS fixture check\\n'*{lines}); "
        if fail:
            script += "raise SystemExit('fixture failure')"
        request = {
            'actor_role': 'code_executor', 'action': 'run', 'level': level,
            'execution_authorized': True, 'argv': [PYTHON, '-B', '-c', script]}
        if purpose:
            request['purpose'] = purpose
        write_json(h.root / '.ai/runtime/evidence_request.json', request)
        output = h.tool('ai-evidence', expect=1 if fail else 0)
        return json.loads(output.stdout)

    def unit(self, h, uid, evidence=None, status='pass'):
        payload = {'actor_role': 'code_executor', 'unit_id': uid, 'status': status,
                   'tests': [{'name': 'fixture check', 'status': 'pass' if status == 'pass' else 'fail', 'details': 'actual retained command output'}],
                   'reason': '' if status == 'pass' else 'fixture failed and must be repaired',
                   'evidence_refs': [evidence] if evidence else []}
        write_json(h.root / '.ai/runtime/unit_result.json', payload)
        return h.tool('ai-unit', expect=0 if status == 'pass' else 1)

    def test_hot_manifest_uses_selected_ids_and_no_full_formal_documents(self):
        h = self.project()
        self.requirement(h, architecture_refs=['C01'])
        self.requirement(h, title='Unrelated feature')
        self.start(h, {'requirements': ['R-001']})
        manifest = json.loads(h.tool('ai-resume', '--json', expect={0, 1}).stdout)
        self.assertEqual(manifest['reading_plan']['task_references']['requirements'], ['R-001'])
        self.assertIn('C01', manifest['reading_plan']['task_references']['architecture'])
        self.assertEqual(manifest['cold']['default'], 'none')
        self.assertFalse(manifest['metrics']['cold_history_loaded'])
        for forbidden in ['docs/PRODUCT_REQUIREMENTS.md', 'docs/ARCHITECTURE.md', 'docs/DECISIONS.md', 'docs/REQUIREMENT_CHANGELOG.md']:
            self.assertNotIn(forbidden, manifest['reading_plan']['must_read'])
        self.assertNotIn('Unrelated feature', json.dumps(manifest))

    def test_requirement_selection_returns_full_ac_without_history(self):
        h = self.project()
        self.requirement(h, title='Unique selected behavior')
        self.requirement(h, title='Never load unrelated behavior')
        item = json.loads(h.tool('ai-context', 'read', '--kind', 'requirement', '--id', 'R-001').stdout)
        self.assertEqual(item['content']['title'], 'Unique selected behavior')
        self.assertTrue(item['content']['acceptance_criteria'])
        self.assertNotIn('revisions', item['content'])
        self.assertNotIn('Never load unrelated behavior', json.dumps(item))
        self.assertGreater(item['metrics']['returned_bytes'], 0)

    def test_architecture_selection_and_duplicate_id_guard(self):
        h = self.project()
        item = json.loads(h.tool('ai-context', 'read', '--kind', 'architecture', '--id', 'C03').stdout)
        self.assertIn('C03', item['content'])
        self.assertNotIn('C04', item['content'])
        arch = h.root / 'docs/ARCHITECTURE.md'
        arch.write_text(arch.read_text(encoding='utf-8') + '\n## C03 | Duplicate\nBad\n', encoding='utf-8')
        rejected = h.tool('ai-context', 'refresh', expect=1)
        self.assertIn('Duplicate architecture ID', rejected.stderr)

    def test_decision_body_is_independent_and_exactly_resolvable(self):
        h = self.project()
        write_json(h.root / '.ai/runtime/decision.json', {'actor_role': 'project_manager_agent',
            'title': 'Grant scope rule', 'current': 'Scope binds to grant', 'reason': 'Prevent overly broad access', 'impact': 'Authorization'})
        key = h.tool('new-decision').stdout.strip().split()[1]
        self.assertTrue((h.root / 'docs/decisions' / (key + '.md')).exists())
        index = json.loads(h.tool('ai-context', 'index', '--kind', 'decision', '--id', key).stdout)
        self.assertEqual(index['items'][0]['summary'], 'Scope binds to grant')
        read = json.loads(h.tool('ai-context', 'read', '--kind', 'decision', '--id', key).stdout)
        self.assertIn('Prevent overly broad access', read['content'])
        self.assertNotIn('Prevent overly broad access', (h.root / 'docs/DECISIONS.md').read_text(encoding='utf-8'))

    def test_stale_architecture_blocks_finish_until_pm_acknowledges(self):
        h = self.project()
        self.start(h, {'architecture': ['C03']})
        path = h.root / 'docs/ARCHITECTURE.md'
        path.write_text(path.read_text(encoding='utf-8').replace('## C03 | 技术栈', '## C03 | 技术栈\n\n- Confirmed stack changed.'), encoding='utf-8')
        h.tool('pre-commit-check', expect=2)
        h.tool('ai-context', 'refresh', expect=1)
        result = h.result_payload('pass', [{'name': 'check', 'status': 'pass'}])
        write_json(h.root / '.ai/runtime/batch_result.json', result)
        self.assertIn('stale', h.tool('ai-finish', expect=1).stderr)
        h.tool('ai-context', 'refresh', '--accept-changes', '--actor-role', 'code_executor', '--reason', 'read', expect=1)
        h.tool('ai-context', 'refresh', '--accept-changes', '--actor-role', 'project_manager_agent', '--reason', 'Re-read changed C03')
        evidence = self.evidence(h)
        result['evidence_refs'] = [evidence['summary']]
        write_json(h.root / '.ai/runtime/batch_result.json', result)
        h.tool('ai-finish', expect={0, 1})

    def test_invalid_requirement_reference_is_rejected_before_transaction(self):
        h = self.project()
        before = (h.root / '.ai/requirement_registry.json').read_bytes()
        write_json(h.root / '.ai/runtime/requirement_update.json', {'actor_role': 'project_manager_agent', 'action': 'create',
            'title': 'Invalid ref', 'description': 'Must be rejected', 'architecture_refs': ['C999']})
        h.tool('ai-requirement', expect=1)
        self.assertEqual(before, (h.root / '.ai/requirement_registry.json').read_bytes())

    def test_unknown_active_requirement_cannot_start(self):
        h = self.project()
        write_json(h.root / '.ai/runtime/batch_request.json', {'batch_id': 'P1-001', 'stage_id': 'P1', 'title': 'Unknown ref',
            'goal': 'Cannot guess', 'scope': ['src'], 'acceptance_criteria': ['valid references'], 'context_refs': {'requirements': ['R-999']}})
        h.tool('ai-start', expect=1)
        self.assertFalse((h.root / '.ai/runtime/active_batch.json').exists())

    def test_full_review_requires_reason_and_does_not_stick(self):
        h = self.project()
        h.tool('ai-resume', '--mode', 'full', expect=1)
        manifest = json.loads(h.tool('ai-resume', '--mode', 'full', '--full-reason', 'stage_audit', '--json', expect={0, 1}).stdout)
        self.assertEqual(manifest['reading_plan']['mode'], 'full')
        normal = json.loads(h.tool('ai-resume', '--json', expect={0, 1}).stdout)
        self.assertEqual(normal['reading_plan']['mode'], 'hot')
        self.assertTrue(list((h.root / '.ai/history/full_reviews').rglob('*.json')))

    def test_cold_history_requires_reason_and_prevents_escape(self):
        h = self.project()
        log = next((h.root / 'docs/logs').glob('*.md')).relative_to(h.root).as_posix()
        h.tool('ai-context', 'cold', '--path', log, expect=1)
        result = json.loads(h.tool('ai-context', 'cold', '--path', log, '--reason', 'compatibility', '--limit', '4').stdout)
        self.assertTrue(result['metrics']['cold_history_loaded'])
        self.assertLessEqual(len(result['content'].splitlines()), 4)
        for path in ['../outside.txt', 'C:/Windows/win.ini', 'PROJECT.toml']:
            h.tool('ai-context', 'cold', '--path', path, '--reason', 'owner_request', expect=1)

    def test_parent_units_require_local_pass_and_parent_regression(self):
        h = self.project()
        self.start(h, units=True)
        fail = self.evidence(h, fail=True)
        self.unit(h, 'U1', fail['summary'], status='fail')
        local = self.evidence(h)
        self.unit(h, 'U1', local['summary'])
        result = h.result_payload('pass', [{'name': 'parent regression', 'status': 'pass'}])
        write_json(h.root / '.ai/runtime/batch_result.json', result)
        h.tool('ai-finish', expect=1)
        self.unit(h, 'U2', local['summary'])
        result['evidence_refs'] = [local['summary']]
        write_json(h.root / '.ai/runtime/batch_result.json', result)
        self.assertIn('L3', h.tool('ai-finish', expect=1).stderr)
        regression = self.evidence(h, level='L3')
        result['evidence_refs'] = [regression['summary']]
        result['checks'] = {key: {'status': 'not_applicable', 'reason': 'Governance fixture has no app/package'} for key in ['browser', 'package']}
        result['checks'].update({key: {'status': 'pass', 'evidence': regression['summary']} for key in ['consumer', 'report', 'checks']})
        write_json(h.root / '.ai/runtime/batch_result.json', result)
        h.tool('ai-finish', expect={0, 1})
        self.assertFalse((h.root / '.ai/runtime/active_batch.json').exists())
        attempts = list((h.root / '.ai/history/units/P1-001').glob('U1-*.json'))
        self.assertEqual(len(attempts), 2)
        self.assertTrue(any(json.loads(x.read_text(encoding='utf-8'))['status'] == 'fail' for x in attempts))
        histories = json.loads(h.tool('ai-context', 'history', '--kind', 'batch', '--id', 'P1-001', '--reason', 'regression').stdout)
        self.assertTrue(histories['paths'])
        manifest = json.loads(h.tool('ai-resume', '--json', expect={0, 1}).stdout)
        self.assertIsNone(manifest['active_batch'])
        self.assertNotIn('work_units', json.dumps(manifest))

    def test_lite_rejects_parent_and_stays_at_23_files_with_notice(self):
        h = self.project('lite')
        files = [x for x in h.root.rglob('*') if x.is_file() and '.git' not in x.relative_to(h.root).parts]
        self.assertEqual(len(files), 23)
        self.assertFalse((h.root / '.ai/context_index.json').exists())
        self.assertFalse((h.root / 'docs/AI_EXECUTION_RULES.md').exists())
        write_json(h.root / '.ai/runtime/batch_request.json', {'batch_id': 'P1-001', 'stage_id': 'P1', 'title': 'Lite parent',
            'goal': 'Reject', 'scope': ['src'], 'acceptance_criteria': ['reject'],
            'work_units': [{'unit_id': 'U1', 'title': 'x', 'scope': ['src']}], 'required_checks': ['checks']})
        h.tool('ai-start', expect=1)

    def test_high_risk_raises_regression_level(self):
        h = self.project()
        self.start(h, risk_tags=['migration'])
        active = json.loads((h.root / '.ai/runtime/active_batch.json').read_text(encoding='utf-8'))
        self.assertEqual(active['required_test_level'], 'L4')
        evidence = self.evidence(h, 'L2')
        result = h.result_payload('pass', [{'name': 'module', 'status': 'pass'}])
        result['evidence_refs'] = [evidence['summary']]
        write_json(h.root / '.ai/runtime/batch_result.json', result)
        self.assertIn('L4', h.tool('ai-finish', expect=1).stderr)

    def test_raw_evidence_retained_and_success_output_is_small(self):
        h = self.project()
        self.start(h)
        result = self.evidence(h, lines=1500)
        self.assertNotIn('failure_excerpt', result)
        size = sum(x['bytes'] for x in result['raw'])
        self.assertGreater(size, 20000)
        self.assertLess(len(json.dumps(result).encode('utf-8')), size / 5)
        for raw in result['raw']:
            self.assertEqual(hashlib.sha256((h.root / raw['path']).read_bytes()).hexdigest(), raw['sha256'])

    def test_changed_raw_evidence_cannot_close_batch(self):
        h = self.project()
        self.start(h, required_test_level='L2')
        evidence = self.evidence(h, 'L2')
        (h.root / evidence['raw'][0]['path']).write_text('tampered', encoding='utf-8')
        result = h.result_payload('pass', [{'name': 'module', 'status': 'pass'}])
        result['evidence_refs'] = [evidence['summary']]
        write_json(h.root / '.ai/runtime/batch_result.json', result)
        self.assertIn('Raw evidence changed', h.tool('ai-finish', expect=1).stderr)

    def test_implementation_change_invalidates_previous_evidence(self):
        h = self.project()
        self.start(h, required_test_level='L2')
        evidence = self.evidence(h, 'L2')
        (h.root / 'implementation.txt').write_text('changed after tests', encoding='utf-8')
        result = h.result_payload('pass', [{'name': 'module', 'status': 'pass'}])
        result['evidence_refs'] = [evidence['summary']]
        write_json(h.root / '.ai/runtime/batch_result.json', result)
        self.assertIn('stale', h.tool('ai-finish', expect=1).stderr)

    def test_closed_change_has_structured_history(self):
        h = self.project()
        key = h.register_ready_bug_change()
        self.start(h, change_ids=[key])
        result = h.result_payload('pass', [{'name': 'bug regression', 'status': 'pass'}])
        result['change_ids'] = [key]
        write_json(h.root / '.ai/runtime/batch_result.json', result)
        h.tool('ai-finish', expect={0, 1})
        history = json.loads(h.tool('ai-context', 'history', '--kind', 'change', '--id', key, '--reason', 'regression').stdout)
        self.assertEqual(history['total'], 1)
        record = json.loads((h.root / history['paths'][0]).read_text(encoding='utf-8'))
        self.assertEqual(record['raw_feedback'], 'Fix an implementation defect')
        self.assertEqual(record['status'], 'closed')

    def test_long_history_does_not_increase_default_context(self):
        h = self.project()
        self.requirement(h, architecture_refs=['C03'])
        self.start(h, {'requirements': ['R-001']})
        before = json.loads(h.tool('ai-resume', '--json', expect={0, 1}).stdout)
        before_state = (h.root / 'docs/CURRENT_STATE.md').read_bytes()
        before_read = json.loads(h.tool('ai-context', 'read', '--kind', 'requirement', '--id', 'R-001').stdout)['content']
        history_bytes = 0
        for i in range(400):
            records = {
                f'.ai/history/batches/HIST-{i:04d}/closed.json': json.dumps({'batch_id': f'HIST-{i:04d}', 'status': 'closed', 'raw': 'old batch evidence ' * 100}),
                f'.ai/history/changes/OLD-{i:04d}/closed.json': json.dumps({'status': 'closed', 'raw': 'old change evidence ' * 80}),
                f'docs/evidence/old-{i:04d}/raw.log': 'old acceptance PASS\n' * 100,
                f'docs/decisions/DEC-{i+1000}.md': f'# DEC-{i+1000}: Historical decision {i}\n\n- 日期：2025-01-01\n- 状态：已替代\n- 当前方案：Historical {i}\n- 影响范围：Old capability\n\n' + ('Historical rationale only.\n' * 30),
            }
            for rel, content in records.items():
                path = h.root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
                history_bytes += len(content.encode('utf-8'))
        log = h.root / 'docs/logs/2025-01.md'
        log_text = '# Historical development log\n\n' + ('Old batch completed; see archived evidence.\n' * 30000)
        log.write_text(log_text, encoding='utf-8')
        history_bytes += len(log_text.encode('utf-8'))
        after = json.loads(h.tool('ai-resume', '--json', expect={0, 1}).stdout)
        self.assertEqual(before, after)
        self.assertEqual(before_state, (h.root / 'docs/CURRENT_STATE.md').read_bytes())
        after_read = json.loads(h.tool('ai-context', 'read', '--kind', 'requirement', '--id', 'R-001').stdout)['content']
        self.assertEqual(before_read, after_read)
        found = json.loads(h.tool('ai-context', 'history', '--kind', 'decision', '--id', 'DEC-1234', '--reason', 'history_conflict').stdout)
        self.assertIn('Historical decision 234', found['content'])
        self.assertNotIn('Historical decision 235', found['content'])
        report = {'historical_batches': 400, 'historical_changes': 400, 'historical_decisions': 400,
                  'raw_acceptance_reports': 400, 'development_log_lines': 30002,
                  'added_history_bytes': history_bytes,
                  'manifest_bytes_before': len(json.dumps(before, ensure_ascii=False, indent=2).encode('utf-8')),
                  'manifest_bytes_after': len(json.dumps(after, ensure_ascii=False, indent=2).encode('utf-8')),
                  'current_state_bytes': len(before_state), 'requirement_payload_equal': before_read == after_read,
                  'exact_cold_decision_found': 'DEC-1234', 'token_metrics': None}
        output = os.environ.get('AI_STARTER_REPORT_DIR')
        if output:
            write_json(Path(output) / 'long_project_metrics.json', report)

    def test_all_profiles_both_modes_generate_and_hook(self):
        import tomllib
        profiles = tomllib.loads((ROOT / 'profiles.toml').read_text(encoding='utf-8'))
        temp = make_temp_dir('v190-profile-matrix-')
        self.addCleanup(remove_tree, temp)
        results = []
        for profile in profiles:
            for mode in ['lite', 'standard']:
                target = temp / (profile + '-' + mode)
                run([PYTHON, '-B', str(STARTER), 'init', '--target', str(target), '--name', profile,
                     '--description', 'Matrix fixture', '--profile', profile, '--governance-mode', mode])
                run([PYTHON, '-B', 'tools/project.py', 'pre-commit-check'], target)
                run([PYTHON, '-B', 'tools/project.py', 'ai-context', 'check'], target)
                files = [x for x in target.rglob('*') if x.is_file() and '.git' not in x.relative_to(target).parts]
                if mode == 'lite':
                    self.assertEqual(len(files), 23)
                dirty = run(['git', 'status', '--porcelain'], target).stdout
                self.assertEqual(dirty, '')
                results.append({'profile': profile, 'mode': mode, 'files': len(files), 'hook': 'pass', 'context': 'pass'})
        if os.environ.get('AI_STARTER_REPORT_DIR'):
            write_json(Path(os.environ['AI_STARTER_REPORT_DIR']) / 'profile_matrix.json', {'results': results})

    def test_requirement_revision_refreshes_index_and_preserves_old_semantics(self):
        h = self.project()
        self.requirement(h, architecture_refs=['C03'])
        self.start(h, {'requirements': ['R-001']})
        write_json(h.root / '.ai/runtime/change_request.json', {'raw_feedback': 'Change domain and behavior',
            'change_types': ['requirement_change'], 'affected_implementation': ['src/current'], 'requires_reacceptance': True})
        key = h.tool('ai-register-change').stdout.strip().split()[1]
        write_json(h.root / '.ai/runtime/requirement_update.json', {'actor_role': 'project_manager_agent', 'action': 'revise',
            'requirement_id': 'R-001', 'expected_current_version': 'R-001.1', 'change_id': key,
            'reason': 'Owner changed scope', 'module': 'NewDomain', 'summary': 'New summary',
            'description': 'New formal behavior', 'architecture_refs': ['C04']})
        h.tool('ai-requirement')
        manifest = json.loads(h.tool('ai-resume', '--json', expect=2).stdout)
        self.assertTrue(manifest['freshness']['stale'])
        row = json.loads(h.tool('ai-context', 'index', '--kind', 'requirement', '--id', 'R-001').stdout)['items'][0]
        self.assertEqual(row['version'], 'R-001.2')
        self.assertEqual(row['module'], 'NewDomain')
        self.assertEqual(row['architecture'], ['C04'])
        history = json.loads(h.tool('ai-context', 'history', '--kind', 'requirement', '--id', 'R-001', '--reason', 'compatibility').stdout)
        self.assertEqual(history['revisions'][0]['module'], 'Core')
        self.assertEqual(history['revisions'][0]['architecture_refs'], ['C03'])
        write_json(h.root / '.ai/runtime/requirement_update.json', {'actor_role': 'project_manager_agent', 'action': 'link',
            'requirement_id': 'R-001', 'expected_current_version': 'R-001.2', 'module': 'Forbidden'})
        h.tool('ai-requirement', expect=1)

    def test_execution_rule_change_invalidates_active_context(self):
        h = self.project()
        self.start(h)
        path = h.root / 'docs/AI_EXECUTION_RULES.md'
        path.write_text(path.read_text(encoding='utf-8') + '\nNew authorized restriction.\n', encoding='utf-8')
        h.tool('pre-commit-check', expect=2)
        manifest = json.loads(h.tool('ai-resume', '--json', expect={0, 1}).stdout)
        self.assertTrue(manifest['freshness']['stale'])
        result = h.result_payload('pass', [{'name': 'test', 'status': 'pass'}])
        write_json(h.root / '.ai/runtime/batch_result.json', result)
        self.assertIn('stale', h.tool('ai-finish', expect=1).stderr)

    def test_layered_stage_acceptance_requires_l4_retained_evidence(self):
        h = self.project()
        self.requirement(h)
        self.start(h, {'requirements': ['R-001']})
        evidence = self.evidence(h)
        result = h.result_payload('pass', [{'name': 'local', 'status': 'pass'}])
        result['evidence_refs'] = [evidence['summary']]
        write_json(h.root / '.ai/runtime/batch_result.json', result)
        h.tool('ai-finish', expect={0, 1})
        acceptance = {'scope': 'stage', 'stage_id': 'P1', 'status': 'passed', 'note': 'Fixture owner acceptance'}
        write_json(h.root / '.ai/runtime/acceptance.json', acceptance)
        self.assertIn('L4', h.tool('ai-acceptance', expect=1).stderr)
        self.evidence(h, 'L4', purpose='stage')
        h.tool('ai-acceptance', expect={0, 1})

    def test_layered_release_requires_l5_after_real_final_checks(self):
        h = self.project()
        h.create_complete_requirement()
        self.start(h, {'requirements': ['R-001']})
        evidence = self.evidence(h)
        result = h.result_payload('pass', [{'name': 'local', 'status': 'pass'}])
        result['evidence_refs'] = [evidence['summary']]
        write_json(h.root / '.ai/runtime/batch_result.json', result)
        h.tool('ai-finish', expect={0, 1})
        h.record_full_audit()
        h.commit('facts ready for release')
        baseline = {'actor_role': 'project_manager_agent', 'release_version': '1.0.0', 'release_name': '1.0.0', 'scope_note': 'fixture'}
        write_json(h.root / '.ai/runtime/release_baseline.json', baseline)
        self.assertIn('L5', h.tool('ai-release-baseline', expect=1).stderr)
        self.evidence(h, 'L5', purpose='release')
        h.commit('retain final raw evidence')
        h.tool('ai-release-baseline')

    def test_imported_browser_evidence_is_copied_and_retained(self):
        h = self.project()
        self.start(h)
        raw = h.root / 'browser-result.json'
        raw.write_text(json.dumps({'fixture': 'browser evidence transport', 'checks': [{'name': 'fixture assertion', 'actual': True}]}), encoding='utf-8')
        write_json(h.root / '.ai/runtime/evidence_request.json', {'action': 'import', 'actor_role': 'code_executor', 'level': 'L2',
            'source': 'Explicit fixture for importing browser output, not a real browser test', 'raw_paths': ['browser-result.json'],
            'tests': [{'name': 'fixture assertion', 'status': 'pass', 'details': 'Transport fixture'}]})
        result = json.loads(h.tool('ai-evidence').stdout)
        self.assertEqual(raw.read_bytes(), (h.root / result['raw'][0]['path']).read_bytes())
        manifest = json.loads(h.tool('ai-resume', '--json', expect={0, 1}).stdout)
        self.assertNotIn(result['raw'][0]['path'], json.dumps(manifest))

    def test_architecture_change_follows_existing_change_gate_and_closes(self):
        h = self.project()
        write_json(h.root / '.ai/runtime/change_request.json', {'raw_feedback': 'Specify implementation boundary',
            'change_types': ['architecture_change'], 'affected_implementation': ['src/current'], 'requires_reacceptance': False})
        change = h.tool('ai-register-change').stdout.strip().split()[1]
        h.tool('ai-change-ready', change, expect=1)
        arch = h.root / 'docs/ARCHITECTURE.md'
        arch.write_text(arch.read_text(encoding='utf-8').replace('## C03 | 技术栈', '## C03 | 技术栈\n\nLocal file adapter must remain isolated.'), encoding='utf-8')
        plan = h.root / 'docs/DEVELOPMENT_PLAN.md'
        plan.write_text(plan.read_text(encoding='utf-8') + '\nCurrent phase implements isolated local adapter (C03).\n', encoding='utf-8')
        write_json(h.root / '.ai/runtime/decision.json', {'actor_role': 'project_manager_agent', 'title': 'Adapter boundary',
            'current': 'Keep local adapter isolated', 'reason': 'Preserve architecture boundary', 'impact': 'C03'})
        decision = h.tool('new-decision').stdout.strip().split()[1]
        h.tool('ai-change-ready', change)
        self.start(h, {'architecture': ['C03'], 'decisions': [decision]}, change_ids=[change])
        evidence = self.evidence(h)
        result = h.result_payload('pass', [{'name': 'adapter fixture', 'status': 'pass'}])
        result['change_ids'] = [change]
        result['evidence_refs'] = [evidence['summary']]
        write_json(h.root / '.ai/runtime/batch_result.json', result)
        h.tool('ai-finish', expect={0, 1})
        self.assertFalse((h.root / '.ai/runtime/active_batch.json').exists())
        history = json.loads(h.tool('ai-context', 'history', '--kind', 'change', '--id', change, '--reason', 'compatibility').stdout)
        self.assertEqual(history['total'], 1)
        # New independent Decision bodies and stable execution rules participate in full audits.
        h.start_batch('P1-002')
        h.tool('ai-context', 'check')

    def test_windows_paths_survive_formal_requirement_views(self):
        h = self.project()
        description = r'Read C:\input\items and write D:\结果\报告 without changing paths.'
        self.requirement(h, description=description)
        document = (h.root / 'docs/PRODUCT_REQUIREMENTS.md').read_text(encoding='utf-8')
        self.assertIn(description, document)
        history = (h.root / 'docs/REQUIREMENT_CHANGELOG.md').read_text(encoding='utf-8')
        self.assertIn(description, history)
        h.tool('pre-commit-check')


if __name__ == '__main__':
    unittest.main()
