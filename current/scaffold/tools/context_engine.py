# Copyright (c) 2026 FeiXiaorong
# SPDX-License-Identifier: MIT
# Template-origin code; retain the license in NOTICE.template.txt.
"""File-only context selection, freshness, retained evidence and internal work units.

This module is called by project.py, which remains the governance authority.
Disk validation is deliberately separate from the content returned to an AI.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import contextlib
import io
import json
import os
import platform
import re
import subprocess
import sys
import uuid
from pathlib import Path

INDEX = Path('.ai/context_index.json')
ARCH = 'docs/ARCHITECTURE.md'
DEC = 'docs/DECISIONS.md'
KINDS = ('requirements', 'architecture', 'decisions')
COLD_REASONS = {'regression', 'history_conflict', 'compatibility', 'owner_request', 'referenced_evidence'}
FULL_REASONS = {'first_baseline', 'architecture_refactor', 'stage_audit', 'release_audit', 'fact_conflict', 'owner_request'}
POLICIES = ['AGENTS.md', 'PROJECT.toml', 'docs/PROJECT_RULES.md', 'docs/ROLE_BOUNDARIES.md',
            'docs/AI_EXECUTION_RULES.md', 'docs/CONTEXT_LOADING_PROTOCOL.md', '.ai/AUTOMATION_CONTRACT.md']


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def short(value, limit=180):
    return ' '.join(str(value or '').split())[:limit]


def safe_path(root, raw, exists=True):
    raw = str(raw).replace('\\', '/')
    path = Path(raw)
    if not raw or path.is_absolute() or ':' in raw or '..' in path.parts:
        raise SystemExit('Context/evidence path must be relative and inside project: ' + raw)
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise SystemExit('Context/evidence path escapes project: ' + raw) from None
    if exists and not resolved.is_file():
        raise SystemExit('Context/evidence file missing: ' + raw)
    return resolved


def sections(path):
    """Return real Markdown sections; ignore example headings in fenced blocks."""
    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    headings, fenced = [], False
    for i, line in enumerate(lines):
        if re.match(r'^\s*(```|~~~)', line):
            fenced = not fenced
        if not fenced:
            match = re.match(r'^(#{1,6})\s+(.+?)\s*$', line)
            if match:
                headings.append((i, len(match[1]), match[2]))
    result = []
    for i, (start, level, title) in enumerate(headings):
        end = next((s for s, l, _ in headings[i + 1:] if l <= level), len(lines))
        result.append({'title': title, 'start_line': start + 1, 'end_line': end,
                       'body': ''.join(lines[start:end])})
    return result


def metadata(body):
    match = re.search(r'<!--\s*CONTEXT:\s*(\{.*?\})\s*-->', body, re.S)
    if not match:
        return {}
    try:
        data = json.loads(match[1])
    except ValueError as exc:
        raise SystemExit('Invalid architecture CONTEXT metadata: ' + str(exc)) from exc
    if not isinstance(data, dict):
        raise SystemExit('CONTEXT metadata must be an object')
    return data


def strings(value, label):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise SystemExit(label + ' must be an array of nonempty strings')
    return list(dict.fromkeys(x.strip() for x in value))


def build_index(root, p, registry=None):
    registry = registry if registry is not None else p.load_requirement_registry(root)
    data = {'schema_version': '1.9.0', 'requirements': {}, 'architecture': {}, 'decisions': {}, 'sources': {},
            'policy_hashes': {rel: p.file_hash(root / rel) for rel in POLICIES if (root / rel).exists()}}
    data['sources']['.ai/requirement_registry.json'] = p.file_hash(root / p.REQUIREMENT_REGISTRY_FILE)
    for req in registry['requirements']:
        rid = req['requirement_id']
        current = {k: v for k, v in req.items() if k != 'revisions'}
        data['requirements'][rid] = {
            'id': rid, 'version': req['current_version'], 'title': req['title'],
            'status': req['status'], 'priority': req['priority'],
            'module': req.get('module', req['category']),
            'summary': short(req.get('summary') or req['description']),
            'locator': {'path': '.ai/requirement_registry.json', 'selector': rid},
            'formal_document': {'path': 'docs/PRODUCT_REQUIREMENTS.md', 'heading': req['current_version'] + '：' + req['title']},
            'ac_refs': [x['id'] for x in req['acceptance_criteria']],
            'last_change': req.get('change_id', ''),
            'architecture': strings(req.get('architecture_refs', []), 'architecture_refs'),
            'decisions': strings(req.get('decision_refs', []), 'decision_refs'),
            'sha256': digest(current),
        }
    if (root / ARCH).exists():
        data['sources'][ARCH] = p.file_hash(root / ARCH)
        for item in sections(root / ARCH):
            match = re.match(r'(C[0-9]+)\b[\s:：|.-]*(.*)', item['title'])
            if not match:
                continue
            key, title = match.groups()
            if key in data['architecture']:
                raise SystemExit('Duplicate architecture ID: ' + key)
            meta = metadata(item['body'])
            for code in strings(meta.get('code_paths', []), 'code_paths'):
                safe_path(root, code, exists=False)
            data['architecture'][key] = {
                'id': key, 'title': title, 'summary': short(meta.get('summary', title)),
                'requirements': strings(meta.get('requirements', []), 'requirements'),
                'code_paths': strings(meta.get('code_paths', []), 'code_paths'),
                'decisions': strings(meta.get('decisions', []), 'decisions'),
                'red_lines': strings(meta.get('red_lines', []), 'red_lines'),
                'global_constraint': bool(meta.get('global_constraint', False)),
                'locator': {'path': ARCH, 'start_line': item['start_line'], 'end_line': item['end_line']},
                'sha256': hashlib.sha256(item['body'].encode('utf-8')).hexdigest(),
            }
    decision_paths = [root / DEC] + sorted((root / 'docs/decisions').glob('*.md'))
    for path in decision_paths:
        if not path.exists():
            continue
        rel = path.relative_to(root).as_posix()
        data['sources'][rel] = p.file_hash(path)
        for item in sections(path):
            match = re.match(r'(DEC-[0-9]+(?:-[0-9]+)?)\b[\s:：|.-]*(.*)', item['title'])
            if not match:
                continue
            key, title = match.groups()
            if key in data['decisions']:
                raise SystemExit('Duplicate formal Decision ID: ' + key)
            def field(name):
                found = re.search(r'^- ' + name + r'[:：]\s*(.*)$', item['body'], re.M)
                return short(found[1]) if found else ''
            data['decisions'][key] = {
                'id': key, 'title': title, 'date': field('日期'), 'status': field('状态'),
                'impact': field('影响范围'), 'summary': field('当前方案'),
                'locator': {'path': rel, 'start_line': item['start_line'], 'end_line': item['end_line']},
                'sha256': hashlib.sha256(item['body'].encode('utf-8')).hexdigest(),
            }
    for req in data['requirements'].values():
        validate_refs(data, {'architecture': req['architecture'], 'decisions': req['decisions']})
    for arch in data['architecture'].values():
        validate_refs(data, {'requirements': arch['requirements'], 'decisions': arch['decisions']})
    return data


def validate_refs(index, raw):
    if not isinstance(raw, dict) or set(raw) - set(KINDS):
        raise SystemExit('context_refs must contain requirements/architecture/decisions only')
    refs = {kind: strings(raw.get(kind, []), 'context_refs.' + kind) for kind in KINDS}
    for kind, ids in refs.items():
        for key in ids:
            if key not in index[kind]:
                raise SystemExit('Unresolved context reference: ' + key)
    return refs


def expanded_refs(index, raw):
    refs = validate_refs(index, raw)
    refs['architecture'] += [key for key, row in index['architecture'].items() if row.get('global_constraint')]
    # One bounded dependency closure through declared references, never history.
    for key in list(refs['requirements']):
        req = index['requirements'][key]
        refs['architecture'] += req['architecture']
        refs['decisions'] += req['decisions']
    for key in set(refs['architecture']):
        refs['decisions'] += index['architecture'][key]['decisions']
    return {k: list(dict.fromkeys(v)) for k, v in refs.items()}


def reference_fingerprint(index, refs):
    facts = {k: {i: index[k][i]['sha256'] for i in ids} for k, ids in expanded_refs(index, refs).items()}
    facts['policies'] = index['policy_hashes']
    return digest(facts)


def index_errors(root, p):
    try:
        expected = build_index(root, p)
        if p.governance_mode(root) == 'standard':
            actual = p.read_json(root / INDEX, default=None)
            if actual != expected:
                return ['Context index missing/stale; run ai-context refresh before continuing.']
        return []
    except (SystemExit, ValueError, OSError, KeyError) as exc:
        return ['Context reference validation: ' + str(exc)]


def active_context_errors(root, p):
    active = p.read_json(root / p.ACTIVE_FILE, default=None)
    if active:
        try:
            ensure_fresh(root, p, active)
        except SystemExit as exc:
            return [str(exc)]
    return []


def selected_context(root, p, index, active, task=''):
    raw = (active or {}).get('context_refs', {})
    refs = expanded_refs(index, raw)
    # Explicit IDs in a user-supplied task are selectors, not guessed keywords.
    for kind, pattern in [('requirements', r'R-\d+'), ('architecture', r'\bC\d+\b'), ('decisions', r'DEC-\d+(?:-\d+)?')]:
        for key in re.findall(pattern, task):
            if key not in index[kind]:
                raise SystemExit('Unresolved explicit task ID: ' + key)
            refs[kind].append(key)
    refs = expanded_refs(index, {k: list(dict.fromkeys(v)) for k, v in refs.items()})
    selected = {kind: [index[kind][key] for key in ids] for kind, ids in refs.items()}
    stale = bool(active and active.get('context_fingerprint') and active['context_fingerprint'] != reference_fingerprint(index, raw))
    return refs, selected, stale


def refresh(root, p, task='', accept=False, actor='', reason='', *, preview=None, payloads=None):
    index = build_index(root, p)
    active = preview['active'] if preview is not None else p.read_json(root / p.ACTIVE_FILE, default=None)
    if accept:
        if actor != 'project_manager_agent' or not reason.strip():
            raise SystemExit('Accepting changed context requires PM role and a reread/review reason.')
        if active:
            if active.get('acceptance_contract'):
                c = p.read_json(safe_path(root,active['acceptance_contract']))
                checked = contract_preflight(root,p,{'acceptance_contract':c,'run_id':'review-' + uuid.uuid4().hex})
                if checked['compatibility'] != 'compatible_without_candidate_change':
                    raise SystemExit('CONTRACT_INCOMPATIBLE')
                declared = set(active.get('acceptance_criteria', [])) | set(active.get('required_checks', []))
                if not declared.issubset({row['criterion_id'] for row in c['coverage']}):
                    raise SystemExit('Contract review cannot remove batch coverage')
                archive(root,p,'contracts',active['batch_id'],{'previous_hash':active['acceptance_contract_hash'],'new_hash':checked['acceptance_contract_hash'],'reason':reason})
                active['acceptance_contract_hash'] = checked['acceptance_contract_hash']
            active['context_fingerprint'] = reference_fingerprint(index, active.get('context_refs', {}))
            active['context_review'] = {'at': p.now_iso(), 'reason': reason, 'actor_role': actor}
            p.write_json(root / p.ACTIVE_FILE, active)
    refs, selected, stale = selected_context(root, p, index, active, task)
    state = preview['state'] if preview is not None else p.load_project_state(root)
    changes = p.open_changes(root)
    suspended = p.read_json(root / p.SUSPENDED_PROMOTION_BATCH_FILE, default=None)
    priority = p.resume_priority(state, changes, active, suspended)
    pending = state.get('pending_batch_handoff')
    if preview is None and (pending or (root / p.PENDING_BATCH_HANDOFF_FILE).exists()):
        p.checked_pending_handoff(root)
    latest = p.read_json(root / p.LATEST_FILE, default={})
    summary = None if not active else {k: active.get(k) for k in ['batch_id', 'stage_id', 'title', 'goal', 'status', 'scope', 'blockers', 'context_refs']}
    if summary is not None:
        summary['work_units'] = [{'unit_id': x['unit_id'], 'status': x.get('status', 'pending'), 'title': x.get('title', '')} for x in active.get('work_units', [])]
        summary['context_stale'] = stale
        if active.get('task_contract'):
            summary['task_contract'] = active['task_contract']
        if active.get('debug_checkpoint'):
            summary['debug_checkpoint'] = checkpoint_summary(active['debug_checkpoint'])
    state_subset = {k: state.get(k) for k in ['governance_mode', 'project_status', 'current_release_version', 'current_stage', 'standard_baseline']}
    baseline = state.get('last_release_baseline') or {}
    state_subset['last_release_baseline'] = {k: baseline.get(k) for k in ['baseline_id', 'release_version']} if baseline else None
    priority_tasks = {'complete_standard_baseline_audit': '完成 Standard 升级基线审计',
                      'complete_document_writeback': '先完成变更对应的正式文档写回',
                      'complete_pending_change': '优先完成未关闭变更及必要重新验收',
                      'complete_governance_promotion': '完成已授权的治理升级并恢复挂起批次'}
    next_step = 'Refresh relevant facts with PM before implementation' if stale else priority_tasks.get(priority, short((active or {}).get('goal')) or short(latest.get('next_task')) or '建立当前需求与任务引用')
    if pending and priority == 'start_handoff_successor':
        next_step = 'Start named successor ' + pending['successor_batch_id'] + '; responsibilities only, not PASS: ' + pending['record_path']
    checkpoint = checkpoint_summary((active or {}).get('debug_checkpoint'))
    if checkpoint and not stale and priority == 'resume_active_batch' and active.get('status') in {'active', 'partial', 'blocked'}:
        next_step = checkpoint['next_check']
    cold = {'default': 'none', 'entrypoints': ['docs/logs/', '.ai/history/', 'docs/evidence/', 'docs/decisions/', 'docs/REQUIREMENT_CHANGELOG.md'], 'requires_reason': sorted(COLD_REASONS)}
    project = p.load_config(root)['project']
    hot_paths = ['START_HERE.md', 'AGENTS.md', 'docs/CURRENT_STATE.md']
    plan = {'mode': 'hot', 'must_read': hot_paths, 'task_references': refs,
            'task_selectors': [{'kind': kind, 'id': key} for kind, ids in refs.items() for key in ids],
            'read_if_relevant': ['PROJECT.toml', 'docs/ROLE_BOUNDARIES.md', 'docs/DEVELOPMENT_PLAN.md'],
            'do_not_read_by_default': cold['entrypoints'], 'changed_since_previous_context': [], 'document_hashes': {}}
    manifest = {'schema_version': '1.9.0', 'manifest_type': 'CONTEXT_LOAD_MANIFEST',
                'project': {k: project[k] for k in ['name', 'description', 'profile']},
                'project_state': state_subset, 'active_batch': summary,
                'pending_changes': [{'change_id': x['change_id'], 'status': x['status']} for x in changes],
                'priority': priority, 'next_step': next_step, 'reading_plan': plan,
                'selected_index': selected, 'cold': cold, 'freshness': {'stale': stale, 'selected_fingerprint': reference_fingerprint(index, (active or {}).get('context_refs', {}))},
                'policy_hashes': index['policy_hashes'],
                'metrics': {'unit': 'utf8_bytes_and_characters_not_tokens', 'cold_history_loaded': False,
                            'selected_requirements': len(refs['requirements']), 'selected_architecture': len(refs['architecture']), 'selected_decisions': len(refs['decisions'])}}
    if pending:
        manifest['pending_batch_handoff'] = pending
    if active and active.get('inherited_handoff'):
        manifest['active_batch']['inherited_handoff'] = {k:active['inherited_handoff'][k] for k in ['handoff_id','source_batch_id','record_path']}
    inv_summary = investigation_summary(investigation_state(root, p))
    if inv_summary:
        manifest['investigation'] = inv_summary
        if inv_summary['owner_decision_required']:
            manifest['next_step'] = inv_summary['next_step']
            next_step = inv_summary['next_step']
    red_lines = [line for row in selected['architecture'] for line in row['red_lines']]
    cfg = p.load_config(root)
    forbidden = [key for key, allowed in cfg.get('authorization', {}).items() if allowed is False]
    snapshot = '\n'.join([
        '## 自动状态快照', '', '- 项目：' + project['name'], '- 项目目标：' + short(project['description']),
        '- 当前产品版本：' + (state.get('current_release_version') or '尚未指定'),
        '- 当前阶段：' + (state.get('current_stage') or '项目探索与需求定义'),
        '- 最近固定基线：' + str(baseline.get('baseline_id') or '无'),
        '- 唯一活动批次：' + (str(active['batch_id']) if active else '无'),
        '- 升级挂起批次：' + (str(suspended.get('batch_id')) if suspended else '无'),
        '- 当前目标：' + next_step,
        '- 未完成项：' + ('；'.join(short(x) for x in (active or {}).get('scope', [])) or '按当前计划定位下一任务'),
        '- 未关闭变更：' + str(len(changes)),
        '- 当前阻塞：' + ('；'.join(short(x) for x in (active or {}).get('blockers', [])) or ('相关上下文已失效' if stale else '无')),
        '- Requirement IDs：' + (', '.join(refs['requirements']) or '未指定；实施前由 PM 确认范围'),
        '- Architecture IDs：' + (', '.join(refs['architecture']) or '无'),
        '- 相关 Decision：' + (', '.join(refs['decisions']) or '无'),
        '- 最近阶段验收：' + str(state.get('stage_acceptance', {}).get('status', 'not_started')),
        '- 架构红线：' + ('；'.join(red_lines) or '读取本批引用章节；不得推测未加载事实'),
        '- 未授权操作：' + ', '.join(forbidden), '- 下一步：' + next_step,
        '- Cold History：通过 ai-context history/cold 精确定位；默认不读 docs/logs、.ai/history、docs/evidence。',
    ])
    if checkpoint:
        snapshot += '\n- 最新排错检查点：见 context.json 的 active_batch.debug_checkpoint（只读该处，不加载旧尝试）'
    state_path = root / 'docs/CURRENT_STATE.md'
    rendered = [(state_path, p.auto_region_bytes(state_path, p.AUTO_START, p.AUTO_END, snapshot))]
    if p.governance_mode(root) == 'standard':
        rendered.append((root / INDEX, encoded(index)))
    rendered.append((root / p.CONTEXT_FILE, p.json_bytes(manifest)))
    handoff = '# 当前任务接管\n\n- 当前治理模式：`' + p.governance_mode(root) + '`\n\n先读 START_HERE、AGENTS 和 CURRENT_STATE，再读取 context.json 中的选定索引及 L2 正文。\n\n' + snapshot + '\n\n- 当前上下文状态：' + ('STALE，PM 重新读取确认后刷新' if stale else 'CURRENT') + '\n'
    if checkpoint:
        handoff += '\n- 最新假设：' + checkpoint['hypothesis'] + '\n- 其余排错事实见 context.json 的 active_batch.debug_checkpoint。\n'
    rendered.append((root / p.HANDOFF_FILE, handoff.encode('utf-8')))
    if payloads is not None:
        payloads.extend(rendered)
    else:
        for path, content in rendered:
            p._write_bytes_atomically(path, content)
    return manifest


def ensure_fresh(root, p, active):
    if active.get('acceptance_contract'):
        c = p.read_json(safe_path(root,active['acceptance_contract']))
        if digest(c) != active.get('acceptance_contract_hash'):
            raise SystemExit('Acceptance contract changed; PM must review via context refresh')
    for path in active.get('task_contract', {}).get('reference_paths', []):
        safe_path(root, path)
    for path, expected in active.get('debug_checkpoint', {}).get('evidence_hashes', {}).items():
        if p.file_hash(safe_path(root, path)) != expected:
            raise SystemExit('Checkpoint evidence changed: ' + path)
    index = build_index(root, p)
    if active.get('context_fingerprint') and reference_fingerprint(index, active.get('context_refs', {})) != active['context_fingerprint']:
        raise SystemExit('Active context is stale; PM must reread changed facts and explicitly refresh.')


# Helper text inserted into the existing context engine, not a generated new module.
def task_fields(root, p, data):
    raw = data.get('task_contract')
    if raw is None:
        return {}  # Legacy requests retain their original contract, without new assurances.
    if not isinstance(raw, dict):
        raise SystemExit('task_contract must be an object')
    kind = raw.get('kind')
    if kind == 'investigation':
        raise SystemExit('investigation must not start implementation; retain findings in existing notes or an active debug checkpoint')
    if kind not in {'small_change', 'planned'}:
        raise SystemExit('task_contract.kind must be investigation, small_change or planned')
    work_type = raw.get('work_type')
    if work_type not in {'fix', 'feature', 'other'}:
        raise SystemExit('task_contract.work_type must be fix, feature or other')
    reason = p.require_text(raw, 'risk_reason')
    unchanged = strings(raw.get('unchanged_behaviors', []), 'unchanged_behaviors')
    if kind == 'small_change':
        if (data.get('risk_level', 'normal') != 'normal' or data.get('risk_tags')
                or str(data.get('required_test_level', 'L1')) >= 'L4' or data.get('stage_transition')
                or data.get('requires_user_authorization') or data.get('execution_mode', 'single') != 'single'
                or data.get('work_units')):
            raise SystemExit('small_change cannot bypass risk, authorization or planning requirements; use planned')
        if not unchanged:
            raise SystemExit('small_change requires unchanged_behaviors')
    paths = strings(raw.get('reference_paths', []), 'reference_paths')
    if len(paths) > 12:
        raise SystemExit('Use at most 12 task-relevant reference_paths')
    for path in paths:
        safe_path(root, path)
    no_reference = str(raw.get('no_reference_reason', '')).strip()
    if not paths and not no_reference:
        raise SystemExit('Provide reference_paths or a no_reference_reason')
    return {'task_contract': {'kind': kind, 'work_type': work_type, 'risk_reason': reason,
            'unchanged_behaviors': unchanged, 'reference_paths': paths, 'no_reference_reason': no_reference}}


def checkpoint_fields(root, p, raw):
    if not isinstance(raw, dict):
        raise SystemExit('debug_checkpoint must be an object')
    checkpoint = {key: p.require_text(raw, key) for key in ['symptom', 'expected', 'hypothesis', 'next_check']}
    if any(len(value) > 4000 for value in checkpoint.values()):
        raise SystemExit('Keep checkpoint fields within 4000 characters; reference long raw logs')
    reproduction = raw.get('reproduction', 'not_reproduced')
    if reproduction not in {'reproduced', 'not_reproduced', 'environment_blocked'}:
        raise SystemExit('Invalid checkpoint reproduction status')
    cause = raw.get('root_cause_status', 'unknown')
    if cause not in {'unknown', 'confirmed'}:
        raise SystemExit('Invalid root_cause_status')
    hashes = {}
    def retained_refs(value):
        refs = strings(value, 'checkpoint evidence_refs')
        if not refs or len(refs) > 8:
            raise SystemExit('Checkpoint evidence_refs must have 1..8 retained files')
        for ref in refs:
            hashes[ref] = p.file_hash(safe_path(root, ref))
        return refs
    evidence = retained_refs(raw.get('evidence_refs', []))
    eliminated = raw.get('eliminated', [])
    if not isinstance(eliminated, list) or len(eliminated) > 8:
        raise SystemExit('Checkpoint eliminated must be a bounded array')
    exclusions = []
    for row in eliminated:
        if not isinstance(row, dict):
            raise SystemExit('Eliminated cause must be an object')
        exclusions.append({'cause': p.require_text(row, 'cause'), 'evidence_refs': retained_refs(row.get('evidence_refs', []))})
    cause_refs = []
    if cause == 'confirmed':
        if reproduction != 'reproduced':
            raise SystemExit('Cannot claim confirmed cause without reproduced symptom')
        cause_refs = retained_refs(raw.get('root_cause_evidence', []))
    checkpoint.update(reproduction=reproduction, root_cause_status=cause, evidence_refs=evidence,
                      eliminated=exclusions, root_cause_evidence=cause_refs, evidence_hashes=hashes)
    return checkpoint


def checkpoint_summary(checkpoint):
    if not checkpoint:
        return None
    return {**{key: short(checkpoint.get(key)) for key in ['symptom', 'expected', 'hypothesis', 'next_check', 'reproduction', 'root_cause_status']},
            'evidence_refs': checkpoint.get('evidence_refs', []),
            'eliminated': [{'cause': short(row['cause']), 'evidence_refs': row['evidence_refs']} for row in checkpoint.get('eliminated', [])]}


def scoped_finish_guard(root, p, active, result):
    if 'debug_checkpoint' in result:
        checkpoint_fields(root, p, result['debug_checkpoint'])
    contract = active.get('task_contract')
    if not contract:
        return
    names = list(active.get('acceptance_criteria', []))
    if contract['work_type'] == 'fix':
        names.append('original_symptom')
    elif contract['work_type'] == 'feature':
        names.append('entry_wiring')
    names = list(dict.fromkeys(names))
    checks = result.get('checks', {})
    if not isinstance(checks, dict):
        raise SystemExit('checks must be an object')
    passing = str(result.get('status', '')).lower() == 'pass'
    for name in names:
        row = checks.get(name)
        if not row:
            if passing:
                raise SystemExit('Missing scoped goal check: ' + name)
            continue
        if not isinstance(row, dict) or row.get('status') not in {'pass', 'fail', 'not_run'}:
            raise SystemExit('Invalid scoped check status: ' + name)
        if row['status'] == 'pass':
            p.require_text(row, 'details')
            ref = p.require_text(row, 'evidence')
            verify_evidence(root, p, [ref], active.get('required_test_level', 'L1'), active['batch_id'])
            if active.get('acceptance_contract_hash'):
                summary = p.read_json(safe_path(root,ref))
                if name not in {item['criterion_id'] for item in summary.get('coverage',[])}:
                    raise SystemExit('Typed evidence does not cover scoped check: ' + name)
        else:
            p.require_text(row, 'reason')
            if passing:
                raise SystemExit('Unverified scoped goal: ' + name)
    # A reproduction/diagnosis checkpoint never becomes a successful retest by implication.
    if passing and contract['work_type'] == 'fix':
        checkpoint = result.get('debug_checkpoint', active.get('debug_checkpoint'))
        if checkpoint and checkpoint.get('reproduction', 'not_reproduced') != 'reproduced':
            raise SystemExit('Original symptom was not reproduced; retain partial/blocked with evidence')


def batch_fields(root, p, data):
    if data.get('scope_expansion'):
        scope = strings(data['scope_expansion'], 'scope_expansion')
        inv = investigation_state(root,p)
        if not inv or inv.get('approved_scope_expansion') != scope:
            inv = inv or {'investigation_id':'scope','iterations':0,'failed_gates':0,'candidate_hashes':[]}
            inv.update(status='blocked',owner_decision_required=True,scope_expansion=scope,reason_code='OWNER_SCOPE_DECISION_REQUIRED')
            save_investigation(root,p,inv,{'scope_expansion':scope})
            raise SystemExit('OWNER_SCOPE_DECISION_REQUIRED')
    task = task_fields(root, p, data)
    if data.get('acceptance_contract'):
        c = p.read_json(safe_path(root, data['acceptance_contract']))
        identity = contract_preflight(root,p,{'acceptance_contract':c,'run_id':'preflight-' + uuid.uuid4().hex})
        if identity['compatibility'] != 'compatible_without_candidate_change':
            raise SystemExit('CONTRACT_INCOMPATIBLE: ' + identity['compatibility'])
        declared = set(data.get('acceptance_criteria', [])) | set(data.get('required_checks', []))
        extra_check = {'fix':'original_symptom','feature':'entry_wiring'}.get(data.get('task_contract',{}).get('work_type'))
        if extra_check: declared.add(extra_check)
        if not declared.issubset({row['criterion_id'] for row in c['coverage']}):
            raise SystemExit('Coverage map must include every batch criterion and required check')
        task.update(acceptance_contract=data['acceptance_contract'],acceptance_contract_hash=identity['acceptance_contract_hash'])
    index = build_index(root, p)
    refs = validate_refs(index, data.get('context_refs', {}))
    level = str(data.get('required_test_level', 'L1'))
    if level not in {'L1', 'L2', 'L3', 'L4', 'L5'}:
        raise SystemExit('required_test_level must be L1..L5')
    risk_tags = strings(data.get('risk_tags', []), 'risk_tags')
    if data.get('risk_level') == 'high' or set(risk_tags) & {'security', 'data_integrity', 'migration'}:
        level = max(level, 'L4')
    units = data.get('work_units', [])
    if not isinstance(units, list):
        raise SystemExit('work_units must be an array')
    normalized, ids = [], set()
    if units:
        p.require_standard_governance(root, 'Parent batch/internal work units')
        level = max(level, 'L3')
    for raw in units:
        if not isinstance(raw, dict):
            raise SystemExit('work unit must be an object')
        uid = p.require_text(raw, 'unit_id')
        if not re.fullmatch(r'U[0-9]+', uid) or uid in ids:
            raise SystemExit('Invalid/duplicate unit_id: ' + uid)
        ids.add(uid)
        urefs = validate_refs(index, raw.get('context_refs', refs))
        if any(set(urefs[k]) - set(expanded_refs(index, refs)[k]) for k in KINDS):
            raise SystemExit('Unit context must stay inside parent declared references')
        ulevel = str(raw.get('required_test_level', 'L1'))
        if ulevel not in {'L1', 'L2', 'L3', 'L4', 'L5'}:
            raise SystemExit('Unit required_test_level must be L1..L5')
        if level >= 'L4':
            ulevel = max(ulevel, 'L4')
        normalized.append({'unit_id': uid, 'title': p.require_text(raw, 'title'),
                           'scope': p.str_list(raw, 'scope', required=True), 'context_refs': urefs,
                           'required_test_level': ulevel, 'status': 'pending', 'attempts': []})
    checks = strings(data.get('required_checks', []), 'required_checks')
    if units and not checks:
        raise SystemExit('Parent batch must declare required_checks, including applicable consumer/browser/package/report/checks')
    return {**task, 'context_refs': refs, 'context_fingerprint': reference_fingerprint(index, refs),
            'layered_test_contract': bool(units or any(refs.values()) or level > 'L1'),
            'required_test_level': level, 'risk_tags': risk_tags, 'work_units': normalized, 'required_checks': checks}


def archive(root, p, category, key, payload):
    safe = re.sub(r'[^A-Za-z0-9_.-]', '_', str(key))[:100]
    rel = Path('.ai/history') / category / safe / (uuid.uuid4().hex + '.json')
    safe_path(root, rel.as_posix(), exists=False)
    p.write_json(root / rel, payload)
    return rel.as_posix()


def verify_evidence(root, p, refs, minimum, batch_id=None):
    refs = strings(refs, 'evidence_refs')
    if not refs:
        raise SystemExit('Layered test result requires retained evidence_refs')
    for ref in refs:
        path = safe_path(root, ref)
        data = p.read_json(path)
        if data.get('status') != 'pass' or data.get('level', '') < minimum:
            raise SystemExit('Evidence has not passed required level ' + minimum + ': ' + ref)
        if batch_id and data.get('batch_id') != batch_id:
            raise SystemExit('Evidence belongs to a different parent batch: ' + ref)
        for raw in data.get('raw', []):
            target = safe_path(root, raw['path'])
            if p.file_hash(target) != raw['sha256']:
                raise SystemExit('Raw evidence changed: ' + raw['path'])
        if not data.get('raw'):
            raise SystemExit('Evidence summary has no raw evidence')
        active = p.read_json(root / p.ACTIVE_FILE, default=None)
        if data.get('schema') == 'acceptance/1':
            verify_hardening_evidence(root, p, data, active, ref)
        elif data.get('implementation_fingerprint') != p.working_fingerprint(root) or data.get('implementation_tree') != p.git_implementation_tree_hash(root):
            raise SystemExit('Evidence is stale for current implementation: ' + ref)
        active = p.read_json(root / p.ACTIVE_FILE, default=None)
        if active and data.get('context_fingerprint') != active.get('context_fingerprint'):
            raise SystemExit('Evidence is stale for active formal facts: ' + ref)


def lifecycle_gate(root, p, purpose, level):
    state = p.load_project_state(root)
    if not state.get('layered_test_contract'):
        return  # V1.8.1-compatible requests retain the original mandatory test gates.
    ref = state.get('test_summaries', {}).get(purpose)
    if not ref:
        raise SystemExit(purpose + ' requires retained ' + level + ' evidence before acceptance/baseline')
    verify_evidence(root, p, [ref], level)
    evidence = p.read_json(safe_path(root, ref))
    if evidence.get('purpose') != purpose or evidence.get('stage_id') != state.get('current_stage'):
        raise SystemExit('Lifecycle evidence belongs to another purpose/stage')
    if evidence.get('formal_fact_hashes') != p.current_audit_hashes(root):
        raise SystemExit('Lifecycle evidence is stale for current formal facts')


def finish_guard(root, p, result):
    active = p.read_json(root / p.ACTIVE_FILE)
    ensure_fresh(root, p, active)
    scoped_finish_guard(root, p, active, result)
    if str(result.get('status', '')).lower() == 'pass':
        investigation_guard(root, p)
        if active.get('acceptance_contract_hash'):
            if not result.get('evidence_refs'):
                raise SystemExit('Batch requires typed acceptance evidence')
            for ref in result['evidence_refs']:
                record = p.read_json(safe_path(root, ref))
                if record.get('acceptance_contract_hash') != active['acceptance_contract_hash']:
                    raise SystemExit('Batch requires evidence for its declared acceptance contract')
    if str(result.get('status', '')).lower() != 'pass':
        return
    units = active.get('work_units', [])
    if units and any(x.get('status') != 'pass' for x in units):
        raise SystemExit('Parent cannot close until all internal units pass')
    required = active.get('required_test_level', 'L1')
    # Legacy L1 batches retain their existing test contract; opt-in levels require raw evidence.
    if active.get('layered_test_contract') or units or required > 'L1' or result.get('evidence_refs'):
        verify_evidence(root, p, result.get('evidence_refs', []), required, active['batch_id'])
    checks = result.get('checks', {})
    for name in active.get('required_checks', []):
        item = checks.get(name, {}) if isinstance(checks, dict) else {}
        if item.get('status') == 'not_applicable' and str(item.get('reason', '')).strip():
            continue
        if item.get('status') != 'pass' or not str(item.get('evidence', '')).strip():
            raise SystemExit('Missing/failed parent completion check: ' + name)
        safe_path(root, item['evidence'])


def unit_command(args, p):
    root = p.find_root()
    p.require_standard_governance(root, 'Internal unit')
    p.ensure_project_open(root, '记录内部工作单元')
    active = p.read_json(root / p.ACTIVE_FILE)
    ensure_fresh(root, p, active)
    path = p.resolve_project_input(root, args.input, '.ai/runtime/unit_result.json')
    data = p.read_json(path)
    if data.get('actor_role') not in {'project_manager_agent', 'code_executor'}:
        raise SystemExit('Unit results require PM or code_executor role')
    uid = p.require_text(data, 'unit_id')
    unit = next((x for x in active.get('work_units', []) if x['unit_id'] == uid), None)
    if unit is None:
        raise SystemExit('Unknown unit: ' + uid)
    status = p.require_text(data, 'status').lower()
    tests = p.validate_tests(data)
    if status not in {'pass', 'fail', 'blocked'} or not tests:
        raise SystemExit('Unit needs pass/fail/blocked status and actual test records')
    if status == 'pass':
        investigation_guard(root, p)
        if any(x['status'] != 'pass' for x in tests):
            raise SystemExit('Unit pass requires all local tests pass')
        verify_evidence(root, p, data.get('evidence_refs', []), unit['required_test_level'], active['batch_id'])
    elif not str(data.get('reason', '')).strip():
        raise SystemExit('Failed/blocked unit requires a reason')
    if status != 'pass':
        refs = strings(data.get('evidence_refs', []), 'evidence_refs')
        if not refs:
            raise SystemExit('Failed/blocked units must retain original evidence')
        for ref in refs:
            evidence = p.read_json(safe_path(root, ref))
            if not evidence.get('raw'):
                raise SystemExit('Failed evidence has no raw output')
            for raw in evidence['raw']:
                if p.file_hash(safe_path(root, raw['path'])) != raw['sha256']:
                    raise SystemExit('Failed raw evidence was changed')
    record = {**data, 'batch_id': active['batch_id'], 'recorded_at': p.now_iso()}
    rel = Path('.ai/history/units') / re.sub(r'[^A-Za-z0-9_.-]', '_', active['batch_id']) / (uid + '-' + uuid.uuid4().hex + '.json')
    unit['status'] = status
    unit['attempts'].append(rel.as_posix())
    p.atomic_file_transaction([(root / rel, encoded(record)), (root / p.ACTIVE_FILE, encoded(active))])
    path.unlink()
    refresh(root, p)
    print('AI_UNIT_RECORDED', uid, status.upper(), rel.as_posix())
    return 0 if status == 'pass' else 1


def evidence_command(args, p):
    root = p.find_root()
    p.ensure_project_open(root, '保存执行证据')
    data = p.read_json(p.resolve_project_input(root, args.input, '.ai/runtime/evidence_request.json'))
    active = p.read_json(root / p.ACTIVE_FILE, default={})
    if active:
        ensure_fresh(root, p, active)
    if 'acceptance_contract' in data:
        return hardening_evidence(root, p, data, active)
    if data.get('action', 'import') == 'run':
        investigation_guard(root, p)
        investigation_attempt(root,p,digest(p.working_fingerprint(root)),begin=True)
    level = p.require_text(data, 'level')
    if level not in {'L1', 'L2', 'L3', 'L4', 'L5'}:
        raise SystemExit('Evidence level must be L1..L5')
    if data.get('actor_role') not in {'project_manager_agent', 'code_executor', 'integration_reviewer'}:
        raise SystemExit('Evidence requires an execution/review role')
    run_id = uuid.uuid4().hex
    state = p.load_project_state(root)
    purpose = str(data.get('purpose', 'batch' if active else 'stage'))
    if purpose not in {'batch', 'stage', 'release'}:
        raise SystemExit('Evidence purpose must be batch/stage/release')
    rel = Path('docs/evidence') / run_id
    raw_payloads, output, exit_code = [], '', None
    action = data.get('action', 'import')
    if action == 'run':
        if data.get('execution_authorized') is not True:
            raise SystemExit('Command capture requires existing execution authorization recorded as true')
        argv = strings(data.get('argv', []), 'argv')
        # Preserve repeated arguments; strings() above is only validation.
        argv = data.get('argv', [])
        if not argv:
            raise SystemExit('argv cannot be empty')
        try:
            proc = subprocess.run(argv, cwd=root, capture_output=True, timeout=min(max(int(data.get('timeout_seconds', 120)), 1), 3600), shell=False)
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, exit_code = exc.stdout or b'', (exc.stderr or b'') + b'\nTIMEOUT', 124
        except OSError as exc:
            stdout, stderr, exit_code = b'', str(exc).encode('utf-8'), 127
        status = 'pass' if exit_code == 0 else 'fail'
        raw_payloads = [(rel / 'stdout.log', stdout), (rel / 'stderr.log', stderr)]
        output = (stderr or stdout).decode('utf-8', errors='replace')
    elif action == 'import':
        p.require_text(data, 'source')
        tests = p.validate_tests(data)
        if not tests:
            raise SystemExit('Imported evidence requires actual checks')
        status = 'pass' if all(x['status'] == 'pass' for x in tests) else 'fail'
        for i, raw in enumerate(strings(data.get('raw_paths', []), 'raw_paths')):
            src = safe_path(root, raw)
            raw_payloads.append((rel / (str(i) + '-' + src.name), src.read_bytes()))
        if not raw_payloads:
            raise SystemExit('Import requires raw_paths; summary alone is not evidence')
        output = '\n'.join(x['name'] + ': ' + x['details'] for x in tests if x['status'] != 'pass')
    else:
        raise SystemExit('Evidence action must be run or import')
    tests = p.validate_tests(data) if data.get('tests') else []
    failed = [x['name'] for x in tests if x['status'] != 'pass']
    if failed:
        status = 'fail'
    raw_meta = [{'path': path.as_posix(), 'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)} for path, content in raw_payloads]
    summary = {'schema_version': '1.9.0', 'run_id': run_id, 'status': status, 'level': level,
               'batch_id': active.get('batch_id'), 'unit_id': data.get('unit_id'),
               'exit_code': exit_code, 'failed_cases': failed, 'new_failures': [],
               'test_count': len(tests) if tests else None, 'raw': raw_meta,
               'environment': {'python': platform.python_version(), 'platform': platform.platform()},
               'source': data.get('source', 'local argv execution'), 'argv': data.get('argv'),
               'git_head': p.git_info(root)['head'], 'implementation_fingerprint': p.working_fingerprint(root),
               'implementation_tree': p.git_implementation_tree_hash(root),
               'purpose': purpose, 'stage_id': state.get('current_stage'), 'formal_fact_hashes': p.current_audit_hashes(root),
               'context_fingerprint': active.get('context_fingerprint'), 'created_at': p.now_iso()}
    previous = data.get('previous_summary')
    if previous:
        old = p.read_json(safe_path(root, previous))
        summary['new_failures'] = sorted(set(failed) - set(old.get('failed_cases', [])))
    payloads = [(root / path, content) for path, content in raw_payloads]
    payloads.append((root / rel / 'summary.json', encoded(summary)))
    state.setdefault('test_summaries', {})[purpose] = (rel / 'summary.json').as_posix()
    payloads.append((root / p.PROJECT_STATE_FILE, encoded(state)))
    p.atomic_file_transaction(payloads)
    result = {'status': status, 'level': level, 'failed_cases': failed, 'new_failures': summary['new_failures'],
              'exit_code': exit_code, 'test_count': summary['test_count'], 'summary': (rel / 'summary.json').as_posix(), 'raw': raw_meta}
    if status != 'pass':
        result['failure_excerpt'] = output[-3000:]
    if action == 'run':
        investigation_attempt(root,p,digest(p.working_fingerprint(root)),failed=status != 'pass')
    emit(result)
    return 0 if status == 'pass' else 1


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def receipt(root, p, layer, selector, content, files):
    text = content if isinstance(content, str) else encoded(content).decode('utf-8')
    value = {'layer': layer, 'selector': selector, 'files': files, 'returned_bytes': len(text.encode('utf-8')),
             'returned_characters': len(text), 'cold_history_loaded': layer == 'L3', 'at': p.now_iso()}
    # Receipts are evidence, never part of the normal context.
    archive(root, p, 'context_reads', uuid.uuid4().hex, value)
    return value


def read_selected(root, p, index, kind, key):
    aliases = {'requirement': 'requirements', 'decision': 'decisions', 'architecture': 'architecture'}
    kind = aliases.get(kind, kind)
    if kind not in KINDS or key not in index[kind]:
        raise SystemExit('Unknown context selector: ' + str(key))
    row = index[kind][key]
    if kind == 'requirements':
        req = next(x for x in p.load_requirement_registry(root)['requirements'] if x['requirement_id'] == key)
        content = {k: v for k, v in req.items() if k != 'revisions'}
    else:
        loc = row['locator']
        lines = safe_path(root, loc['path']).read_text(encoding='utf-8').splitlines(keepends=True)
        content = ''.join(lines[loc['start_line'] - 1:loc['end_line']])
    return content, row


def context_command(args, p):
    root = p.find_root()
    action = args.action
    if action == 'refresh':
        manifest = refresh(root, p, args.task, args.accept_changes, args.actor_role, args.reason)
        emit({'status': 'stale' if manifest['freshness']['stale'] else 'current', 'manifest': '.ai/runtime/context.json', 'task_references': manifest['reading_plan']['task_references']})
        return 1 if manifest['freshness']['stale'] else 0
    if action == 'manifest':
        emit(refresh(root, p, args.task))
        return 0
    if action == 'check':
        errors = index_errors(root, p)
        emit({'status': 'fail' if errors else 'pass', 'errors': errors})
        return 2 if errors else 0
    errors = index_errors(root, p)
    if errors:
        raise SystemExit('\n'.join(errors))
    index = build_index(root, p)
    kind = {'requirement': 'requirements', 'decision': 'decisions'}.get(args.kind, args.kind)
    if action == 'index':
        if kind not in KINDS:
            raise SystemExit('Specify --kind requirement/architecture/decision')
        rows = list(index[kind].values())
        if args.id:
            rows = [x for x in rows if x['id'] == args.id]
            if not rows:
                raise SystemExit('Unknown index ID: ' + args.id)
        limit = min(max(args.limit, 1), 50)
        emit({'kind': kind, 'total': len(rows), 'offset': args.offset, 'items': rows[args.offset:args.offset + limit]})
        return 0
    if action == 'read':
        content, row = read_selected(root, p, index, kind, args.id)
        meta = receipt(root, p, 'L2', args.id, content, [row['locator']['path']])
        emit({'content': content, 'source': row['locator'], 'metrics': meta})
        return 0
    if action in {'history', 'cold'}:
        if args.reason not in COLD_REASONS:
            raise SystemExit('Cold history requires explicit reason: ' + ', '.join(sorted(COLD_REASONS)))
        if action == 'history':
            if kind == 'requirements':
                req = next((x for x in p.load_requirement_registry(root)['requirements'] if x['requirement_id'] == args.id), None)
                if req is None:
                    raise SystemExit('Unknown historical requirement')
                rows = req['revisions']
                result = {'id': args.id, 'total': len(rows), 'revisions': rows[args.offset:args.offset + min(max(args.limit, 1), 50)]}
            elif kind == 'decisions':
                content, row = read_selected(root, p, index, kind, args.id)
                result = {'content': content, 'source': row['locator']}
            elif kind in {'batch', 'change'}:
                category = 'batches' if kind == 'batch' else 'changes'
                if not re.fullmatch(r'[A-Za-z0-9_.-]+', args.id or ''):
                    raise SystemExit('Invalid history ID')
                paths = sorted((root / '.ai/history' / category / args.id).glob('*.json'))
                result = {'id': args.id, 'total': len(paths), 'paths': [x.relative_to(root).as_posix() for x in paths[args.offset:args.offset + min(max(args.limit, 1), 50)]]}
            else:
                raise SystemExit('History kind must be requirement/decision/batch/change')
        else:
            path = safe_path(root, args.path)
            normalized = path.relative_to(root).as_posix()
            allowed = normalized.startswith(('docs/logs/', 'docs/evidence/', 'docs/decisions/', '.ai/history/', 'docs/delivery/', '.ai/release_baselines/')) or normalized in {'docs/REQUIREMENT_CHANGELOG.md', DEC}
            if not allowed:
                raise SystemExit('Path is not a registered Cold History/evidence location')
            lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
            start = max(args.offset, 0)
            count = min(max(args.limit, 1), 200)
            result = {'path': normalized, 'start_line': start + 1, 'total_lines': len(lines), 'content': '\n'.join(lines[start:start + count])}
        result['metrics'] = receipt(root, p, 'L3', args.id or args.path, result, [args.path] if args.path else [])
        emit(result)
        return 0
    raise SystemExit('Unknown context action')


def decision_command(args, p):
    root = p.find_root()
    if p.governance_mode(root) == 'lite':
        return p.new_decision(args)
    p.ensure_project_open(root, '新增项目决策')
    path = p.resolve_project_input(root, args.input, '.ai/runtime/decision.json')
    data = p.read_json(path)
    if data.get('actor_role', 'project_manager_agent') != 'project_manager_agent':
        raise SystemExit('Only PM may write a formal decision')
    title, current, reason, impact = [p.require_text(data, k) for k in ['title', 'current', 'reason', 'impact']]
    index = build_index(root, p)
    key = p.next_decision_id('\n'.join(index['decisions']))
    target = root / 'docs/decisions' / (key + '.md')
    if target.exists():
        raise SystemExit('Decision already exists')
    body = f"# {key}：{title}\n\n- 日期：{p.date.today().isoformat()}\n- 状态：生效\n- 原方案：{data.get('old', '无')}\n- 当前方案：{current}\n- 原因：{reason}\n- 影响范围：{impact}\n- 替代关系：{data.get('supersedes', '无')}\n"
    navigation = (root / DEC).read_text(encoding='utf-8') + f'\n- [{key}：{title}](decisions/{key}.md)\n'
    p.atomic_file_transaction([(target, body.encode('utf-8')), (root / DEC, navigation.encode('utf-8'))])
    path.unlink()
    print('AI_DECISION_CREATED', key)
    return 0


def run(args, p):
    root = p.find_root()
    command = args.command
    # Validate explicit CLI inputs before wrappers archive results or mutate state.
    for field in ('input', 'request', 'result'):
        value = getattr(args, field, None)
        if value is not None:
            p.resolve_project_input(root, value, '')
    if command == 'ai-context':
        if args.action == 'investigation':
            return investigation_command(args, p)
        return context_command(args, p)
    if command == 'ai-start':
        investigation_guard(root, p, implementation=True)
    if command == 'ai-unit':
        return unit_command(args, p)
    if command == 'ai-evidence':
        return evidence_command(args, p)
    if command == 'ai-resume':
        mode = getattr(args, 'mode', 'auto')
        full_reason = getattr(args, 'full_reason', '')
        if mode == 'full' and full_reason not in FULL_REASONS:
            raise SystemExit('Full review requires --full-reason: ' + ', '.join(sorted(FULL_REASONS)))
        manifest = refresh(root, p, args.task)
        if mode == 'full':
            manifest['reading_plan']['mode'] = 'full'
            manifest['reading_plan']['full_review_reason'] = full_reason
            manifest['reading_plan']['must_read'] = list(dict.fromkeys(manifest['reading_plan']['must_read'] + [rel for rel in p.CORE_CURRENT_DOCS if (root / rel).exists()]))
            archive(root, p, 'full_reviews', full_reason, {'reason': full_reason, 'at': p.now_iso(), 'documents': manifest['reading_plan']['must_read']})
        if args.json:
            emit(manifest)
        else:
            emit({'status': 'stale' if manifest['freshness']['stale'] else 'ready', 'priority': manifest['priority'], 'next_step': manifest['next_step'], 'manifest': '.ai/runtime/context.json', 'reading_plan': manifest['reading_plan']})
        code = p.health(argparse.Namespace(json=False, quiet=True))
        return max(code, 1 if manifest['freshness']['stale'] else 0)
    if command in {'health', 'pre-commit-check'}:
        if command == 'health' and getattr(args, 'json', False):
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                code = args.func(args)
            report = json.loads(captured.getvalue())
            errors = index_errors(root, p) + active_context_errors(root, p)
            report['fail'].extend(errors)
            emit(report)
            return 2 if errors else code
        code = args.func(args)
        errors = index_errors(root, p) + active_context_errors(root, p)
        if errors:
            if not getattr(args, 'quiet', False):
                print('\n'.join('FAIL ' + x for x in errors))
            return 2
        return code
    before_active = p.read_json(root / p.ACTIVE_FILE, default=None)
    result_data = None
    if command == 'ai-finish':
        result_data = p.read_json(p.resolve_project_input(root, args.result, p.RESULT_FILE))
        # Every submitted attempt is retained, including rejected or failed attempts.
        archive(root, p, 'batches', (before_active or {}).get('batch_id', 'unknown'), {'active_batch': before_active, 'result': result_data, 'submitted_at': p.now_iso()})
        finish_guard(root, p, result_data)
    if command == 'ai-acceptance' and before_active:
        ensure_fresh(root, p, before_active)
    if command == 'ai-acceptance':
        acceptance = p.read_json(p.resolve_project_input(root, args.input, p.ACCEPTANCE_FILE))
        if acceptance.get('status') == 'passed' and before_active:
            submitted = p.read_json(root / p.SUBMITTED_FILE, default=None)
            if submitted:
                finish_guard(root, p, submitted)
        if acceptance.get('status') == 'passed' and (acceptance.get('scope') == 'stage' or acceptance.get('stage_complete')):
            lifecycle_gate(root, p, 'stage', 'L4')
    code = decision_command(args, p) if command == 'new-decision' else args.func(args)
    if code in {0, 1} and command == 'ai-audit':
        state = p.load_project_state(root)
        if state.get('standard_baseline', {}).get('status') == 'passed' and before_active is None:
            restored = p.read_json(root / p.ACTIVE_FILE, default=None)
            if restored:
                restored['context_fingerprint'] = reference_fingerprint(build_index(root, p), restored.get('context_refs', {}))
                restored['context_review'] = {'reason': 'Owner-authorized promotion baseline audit completed', 'actor_role': 'project_manager_agent'}
                p.write_json(root / p.ACTIVE_FILE, restored)
    if getattr(args, '_handoff_transaction_complete', False):
        return code
    if code in {0, 1} and command == 'ai-start':
        active = p.read_json(root / p.ACTIVE_FILE)
        if active.get('layered_test_contract'):
            state = p.load_project_state(root)
            state['layered_test_contract'] = True
            p.save_project_state(root, state)
    if code in {0, 1} and command not in {'status', 'rotate-log', 'install-hooks', 'ai-delivery-verify'}:
        refresh(root, p)
    return code


def add_parsers(sub):
    parser = sub.add_parser('ai-context', help='Select context and validate freshness without loading history')
    parser.add_argument('action', choices=['manifest', 'refresh', 'check', 'index', 'read', 'history', 'cold', 'investigation'])
    parser.add_argument('--kind', default='')
    parser.add_argument('--id', default='')
    parser.add_argument('--task', default='')
    parser.add_argument('--path', default='')
    parser.add_argument('--reason', default='')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--accept-changes', action='store_true')
    parser.add_argument('--actor-role', default='')
    for name in ['ai-unit', 'ai-evidence']:
        parser = sub.add_parser(name)
        parser.add_argument('--input')


# acceptance/1 is opt-in: legacy evidence retains its original contract.
EVIDENCE_KINDS = {'static', 'model', 'runtime', 'integration', 'manual', 'simulation', 'browser', 'external-system'}
INVESTIGATION = Path('.ai/runtime/investigation.json')
STOP_LIMITS = {'max_iterations': 'iterations', 'owner_review_after': 'iterations',
               'max_candidate_revisions': 'candidate_revisions', 'max_failed_gates': 'failed_gates'}
FAILURE_CLASSES = {'CANDIDATE_FAILURE', 'HARNESS_FAILURE', 'AUDITOR_FAILURE',
                   'ENVIRONMENT_BLOCKED', 'CONTRACT_INCOMPATIBLE', 'EVIDENCE_INSUFFICIENT'}


def hard_file(root, raw):
    """Regular project file identity, rejecting links/reparse points on ancestors."""
    path = safe_path(root, raw)
    relative = Path(raw.replace('\\', '/'))
    if '..' in relative.parts:
        raise SystemExit('Identity path traversal forbidden')
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        info = cursor.lstat()
        if cursor.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise SystemExit('Identity symlink/junction/reparse point forbidden: ' + raw)
    if not path.is_file():
        raise SystemExit('Identity requires a regular file: ' + raw)
    return {'path': relative.as_posix(), 'canonical_path': str(path.resolve()),
            'file_type': 'regular', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'reparse': False}


def identity_manifest(root, obj):
    if not isinstance(obj, dict) or not str(obj.get('revision', '')).strip():
        raise SystemExit('Identity requires revision and files')
    rows = obj.get('files')
    if not isinstance(rows, list) or not rows:
        raise SystemExit('Identity files must be a nonempty approved manifest')
    result, seen = [], set()
    for item in rows:
        if not isinstance(item, dict):
            raise SystemExit('Identity manifest entry must be an object')
        record = hard_file(root, str(item.get('path', '')))
        if record['canonical_path'] in seen or record['sha256'] != item.get('sha256'):
            raise SystemExit('Identity hash mismatch or duplicate: ' + record['path'])
        seen.add(record['canonical_path']); result.append(record)
    if obj.get('entrypoint') not in {x['path'] for x in result}:
        raise SystemExit('Identity entrypoint must belong to approved manifest')
    return sorted(result, key=lambda x: x['path'])


def executable_identity(harness):
    raw = harness.get('executable', '')
    if not isinstance(raw, str) or not Path(raw).is_absolute():
        raise SystemExit('Harness executable must be a canonical absolute file')
    path = Path(raw)
    for cursor in [path, *path.parents]:
        info = cursor.lstat()
        if cursor.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise SystemExit('Executable identity contains a link/reparse point')
    if not path.is_file() or str(path.resolve()) != raw:
        raise SystemExit('Executable canonical identity mismatch')
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != harness.get('executable_sha256'):
        raise SystemExit('Executable identity hash mismatch')
    return {'canonical_path': raw, 'sha256': actual, 'file_type': 'regular', 'reparse': False}


def contract_preflight(root, p, data, *, reuse=False):
    c = data.get('acceptance_contract')
    if not isinstance(c, dict) or c.get('schema') != 'acceptance/1':
        raise SystemExit('Contract schema must be acceptance/1')
    for key in ['revision', 'approval_id', 'acceptance_rule_version']:
        p.require_text(c, key)
    auth = c.get('authorization', {})
    if not isinstance(auth, dict) or auth.get('granted') is not True or not str(auth.get('note', '')).strip():
        raise SystemExit('Contract execution requires existing authorization and its basis')
    run_id = p.require_text(data, 'run_id')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', run_id):
        raise SystemExit('Invalid evidence run_id')
    rel = 'docs/evidence/' + run_id
    safe_path(root, rel, exists=False)
    if not reuse and (root / rel).exists():
        raise SystemExit('Evidence directory already exists; never reuse a run_id')
    for ancestor in [root / 'docs', root / 'docs/evidence']:
        if ancestor.exists() and (ancestor.is_symlink() or getattr(ancestor.lstat(), 'st_file_attributes', 0) & 0x400):
            raise SystemExit('Evidence destination must not contain links/reparse points')
    parent = root / 'docs/evidence' if (root / 'docs/evidence').exists() else root / 'docs'
    if not os.access(parent, os.W_OK):
        raise SystemExit('Evidence directory permissions unavailable')
    candidate = identity_manifest(root, c.get('candidate'))
    harness = identity_manifest(root, c.get('harness'))
    if {x['path'] for x in candidate} & {x['path'] for x in harness}:
        raise SystemExit('Candidate and Harness manifests must be separate')
    executable = executable_identity(c['harness'])
    argv = c['harness'].get('argv')
    if not isinstance(argv, list) or any(not isinstance(x, str) for x in argv) or len(argv) < 2:
        raise SystemExit('Harness argv must contain executable and approved entrypoint')
    if argv[0] != executable['canonical_path'] or argv[1] != c['harness']['entrypoint']:
        raise SystemExit('Spawn target must match verified executable and Harness entrypoint')
    timeout = c.get('timeout_seconds')
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        raise SystemExit('Contract timeout_seconds must be 1..3600')
    participants = strings(c.get('participants', []), 'participants')
    if not participants:
        raise SystemExit('Contract requires participants')
    capabilities = strings(c['candidate'].get('capabilities', []), 'candidate capabilities')
    required = strings(c.get('required_capabilities', []), 'required_capabilities')
    compatibility = 'compatible_without_candidate_change'
    if set(required) - set(capabilities):
        compatibility = 'requires_candidate_change'
    elif c['schema'] not in strings(c['harness'].get('supported_schema', []), 'supported_schema'):
        compatibility = 'requires_harness_change'
    if c.get('product_or_safety_semantics_changed') is True:
        compatibility = 'requires_candidate_change'
    if c.get('compatibility_decision') == 'incompatible':
        compatibility = 'incompatible'
    coverage = c.get('coverage')
    if not isinstance(coverage, list) or not coverage:
        raise SystemExit('Contract requires a structured coverage map')
    ids = set()
    for row in coverage:
        if not isinstance(row, dict):
            raise SystemExit('Coverage row must be an object, not a bool/model assertion')
        cid = p.require_text(row, 'criterion_id'); p.require_text(row, 'requirement')
        if cid in ids or row.get('required_evidence_kind') not in EVIDENCE_KINDS:
            raise SystemExit('Duplicate criterion or invalid required_evidence_kind')
        ids.add(cid)
        entry = p.require_text(row, 'actual_entrypoint')
        if entry not in {x['path'] for x in candidate + harness}:
            raise SystemExit('Coverage entrypoint must exist in approved manifests')
        actors = strings(row.get('actual_participants', []), 'coverage participants')
        if not actors or set(actors) - set(participants):
            raise SystemExit('Coverage participants must be declared in contract')
        if row.get('planned_evidence_kind', row['required_evidence_kind']) != row['required_evidence_kind']:
            raise SystemExit('Coverage kind mismatch; model/static cannot satisfy runtime')
    volatile = c.get('volatile_identity', [])
    if not isinstance(volatile, list):
        raise SystemExit('volatile_identity must be an array')
    for item in volatile:
        if not isinstance(item, dict) or not str(item.get('reason', '')).strip() or item.get('field') != 'directory_mtime_ns':
            raise SystemExit('Volatile hard gate needs explicit reason and supported field')
        relative, target = p.resolve_project_artifact_path(root, item.get('path', ''))
        cursor = root
        for part in Path(relative).parts:
            cursor = cursor / part
            if cursor.is_symlink() or getattr(cursor.lstat(), 'st_file_attributes', 0) & 0x400:
                raise SystemExit('Volatile identity path contains reparse/link')
        if not target.is_dir() or target.stat().st_mtime_ns != item.get('expected'):
            raise SystemExit('Explicit volatile identity gate mismatch')
    return {'candidate_revision': c['candidate']['revision'], 'candidate_source_hash': digest(candidate),
            'candidate_manifest': candidate, 'acceptance_contract_revision': c['revision'],
            'acceptance_contract_hash': digest(c), 'harness_revision': c['harness']['revision'],
            'harness_source_hash': digest(harness), 'harness_manifest': harness,
            'executable_identity': executable, 'evidence_run_id': run_id,
            'compatibility': compatibility, 'evidence_directory': rel}



def investigation_state(root, p):
    return p.read_json(root / INVESTIGATION, default=None)


def investigation_guard(root, p, *, implementation=False):
    inv = investigation_state(root, p)
    if not inv or inv.get('status') == 'closed':
        return
    if inv.get('owner_decision_required'):
        raise SystemExit(inv.get('reason_code', 'OWNER_DECISION_REQUIRED') + ': owner decision required before another revision/helper/tool/run')
    if implementation and inv.get('kind') == 'investigation':
        raise SystemExit('investigation must not start implementation; owner must close investigation first')


def save_investigation(root, p, inv, event):
    inv['updated_at'] = p.now_iso()
    for boundary, counter in STOP_LIMITS.items():
        value = len(inv.get('candidate_hashes', [])) if counter == 'candidate_revisions' else inv.get(counter, 0)
        if boundary in inv and value >= inv[boundary]:
            inv.update(status='blocked', owner_decision_required=True)
            if inv.get('reason_code') != 'OWNER_SCOPE_DECISION_REQUIRED':
                inv['reason_code'] = 'OWNER_DECISION_REQUIRED'
    rel = Path('.ai/history/investigations') / (uuid.uuid4().hex + '.json')
    p.atomic_file_transaction([(root / rel, encoded({'event': event, 'state': inv})), (root / INVESTIGATION, encoded(inv))])


def investigation_attempt(root, p, identity, *, failed=False, begin=False):
    inv = investigation_state(root, p)
    if not inv or inv.get('status') == 'closed':
        return
    if begin:
        inv['iterations'] = inv.get('iterations', 0) + 1
        hashes = inv.setdefault('candidate_hashes', [])
        if identity not in hashes:
            hashes.append(identity)
    if failed:
        inv['failed_gates'] = inv.get('failed_gates', 0) + 1
    save_investigation(root, p, inv, 'attempt_started' if begin else 'attempt_completed')


def investigation_command(args, p):
    root = p.find_root(); p.ensure_project_open(root, '调查止损')
    data = p.read_json(root / (args.path or '.ai/runtime/investigation_request.json'))
    action = data.get('action'); inv = investigation_state(root, p)
    if action == 'owner-decision':
        if not inv or data.get('actor_role') != 'project_owner' or data.get('owner_authorization') is not True:
            raise SystemExit('Investigation continuation requires project_owner authorization')
        p.require_text(data, 'reason')
        hard_file(root, p.require_text(data, 'decision_evidence'))
        if data.get('decision') not in {'close', 'continue'}:
            raise SystemExit('Owner decision must close or continue')
        for key in STOP_LIMITS:
            if key in data:
                if type(data[key]) is not int or data[key] <= 0:
                    raise SystemExit('stop-loss boundary must be positive integer')
                inv[key] = data[key]
        inv.update(status='closed' if data['decision'] == 'close' else 'active', owner_decision_required=False)
        inv['owner_decision'] = {k: data[k] for k in ['reason', 'decision', 'decision_evidence']}
        if inv.get('scope_expansion') and data['decision'] == 'continue':
            if data.get('approved_scope_expansion') != inv['scope_expansion']:
                raise SystemExit('Owner must explicitly approve the exact scope expansion')
            inv['approved_scope_expansion'] = inv['scope_expansion']
        if inv['status'] == 'closed':
            archive(root, p, 'investigations', inv.get('investigation_id', 'scope'), {'event': data, 'state': inv})
            p.write_json(root / INVESTIGATION, inv)
        else:
            save_investigation(root, p, inv, data)
    elif action == 'start':
        if inv and inv.get('status') != 'closed':
            raise SystemExit('Existing investigation must not be replaced or reset')
        if data.get('actor_role') != 'project_manager_agent':
            raise SystemExit('Investigation start requires PM')
        inv = {'investigation_id': p.require_text(data, 'investigation_id'), 'kind': 'investigation',
               'status': 'active', 'owner_decision_required': False, 'iterations': 0, 'failed_gates': 0,
               'candidate_hashes': [], 'risk_level': data.get('risk_level', 'normal'),
               'scope_expansion_forbidden': data.get('scope_expansion_forbidden', True)}
        for key in STOP_LIMITS:
            if key in data:
                if type(data[key]) is not int or data[key] <= 0:
                    raise SystemExit('stop-loss boundary must be positive integer')
                inv[key] = data[key]
        if inv['risk_level'] not in {'normal', 'high'}:
            raise SystemExit('Invalid investigation risk level')
        if inv['risk_level'] == 'high' and not any(key in inv for key in STOP_LIMITS):
            raise SystemExit('High-risk investigation needs at least one stop-loss boundary')
        save_investigation(root, p, inv, data)
    elif action == 'scope':
        if data.get('actor_role') not in {'project_manager_agent', 'code_executor', 'analysis_review_agent'}:
            raise SystemExit('Scope reporting requires project role')
        scope = strings(data.get('scope_expansion', []), 'scope_expansion')
        if not scope:
            raise SystemExit('Scope expansion must identify the added infrastructure/capability')
        p.require_text(data, 'reason')
        inv = inv or {'investigation_id': 'scope', 'iterations': 0, 'candidate_hashes': [], 'failed_gates': 0}
        inv.update(status='blocked', owner_decision_required=True, scope_expansion=scope, reason_code='OWNER_SCOPE_DECISION_REQUIRED')
        save_investigation(root, p, inv, data)
    elif action == 'record':
        investigation_guard(root, p)
        if not inv or inv.get('status') == 'closed':
            raise SystemExit('No active investigation')
        if data.get('actor_role') not in {'project_manager_agent', 'analysis_review_agent', 'code_executor'}:
            raise SystemExit('Investigation checkpoint requires project role')
        inv['debug_checkpoint'] = checkpoint_fields(root, p, data.get('debug_checkpoint'))
        inv['iterations'] += 1
        if data.get('candidate'):
            value = digest(identity_manifest(root, data['candidate']))
            if value not in inv['candidate_hashes']:
                inv['candidate_hashes'].append(value)
        if data.get('failed_gate_evidence'):
            record = p.read_json(safe_path(root, data['failed_gate_evidence']))
            if record.get('status') not in {'fail', 'blocked'} or not record.get('raw'):
                raise SystemExit('Failed gate requires retained failure evidence')
            for raw in record['raw']:
                if p.file_hash(safe_path(root, raw['path'])) != raw['sha256']:
                    raise SystemExit('Failed gate raw evidence changed')
            inv['failed_gates'] += 1
        save_investigation(root, p, inv, data)
    else:
        raise SystemExit('Investigation action must be start/record/scope/owner-decision')
    refresh(root, p)
    emit(investigation_summary(inv) or {'status':'closed','owner_decision_required':False})
    return 1 if inv.get('owner_decision_required') else 0


def investigation_summary(inv):
    if not inv or inv.get('status') == 'closed':
        return None
    result = {k: inv.get(k) for k in ['investigation_id', 'status', 'owner_decision_required', 'reason_code', 'iterations', 'failed_gates']}
    if inv.get('debug_checkpoint'):
        result['debug_checkpoint'] = checkpoint_summary(inv['debug_checkpoint'])
    result['next_step'] = 'Wait for project owner decision' if inv.get('owner_decision_required') else (result.get('debug_checkpoint') or {}).get('next_check', 'Continue bounded investigation only')
    return result


def read_runtime_audit(root, p, runtime):
    """Read-only auditor: no execution or mutation of runtime/previous audits."""
    c = runtime['contract']; identity = runtime['identity']
    try:
        if digest(identity_manifest(root, c['candidate'])) != identity['candidate_source_hash']:
            raise SystemExit('Candidate identity changed')
        if digest(c) != identity['acceptance_contract_hash']:
            raise SystemExit('Contract identity changed')
        for raw in runtime['raw']:
            if hard_file(root, raw['path'])['sha256'] != raw['sha256']:
                raise SystemExit('Raw evidence identity changed: ' + raw['path'])
        report = runtime.get('report')
        if not isinstance(report, dict):
            raise SystemExit('Harness did not produce a structured runtime result')
        rows = report.get('coverage')
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise SystemExit('Coverage must be structured rows, not bool/model assertions')
        if len({row.get('criterion_id') for row in rows}) != len(rows):
            raise SystemExit('Duplicate actual coverage criteria')
        out = []
        raw_paths = {x['path'] for x in runtime['raw'] if x['bytes'] > 0}
        for requirement in c['coverage']:
            cid = requirement['criterion_id']
            row = next((x for x in rows if x.get('criterion_id') == cid), {})
            if row.get('status') != 'pass' or row.get('evidence_kind') != requirement['required_evidence_kind']:
                raise SystemExit('Evidence kind/status cannot satisfy criterion: ' + cid)
            if row.get('actual_entrypoint') != requirement['actual_entrypoint'] or set(strings(row.get('actual_participants', []), 'actual participants')) != set(requirement['actual_participants']):
                raise SystemExit('Coverage entrypoint/participants mismatch: ' + cid)
            refs = strings(row.get('actual_evidence', []), 'actual_evidence')
            if any(Path(x).name in {'contract.json','runtime-result.json','runtime.json','summary.json'} or Path(x).name.startswith('audit-') for x in refs):
                raise SystemExit('Contract/result/summary cannot replace raw runtime evidence')
            actual = [identity['evidence_directory'] + '/' + x for x in refs]
            if not refs or set(actual) - raw_paths:
                raise SystemExit('Coverage requires retained nonempty raw evidence: ' + cid)
            if row['evidence_kind'] in {'runtime', 'integration', 'browser', 'external-system'}:
                if not runtime.get('process_started') or report.get('candidate_runtime_status') != 'PASS':
                    raise SystemExit('No captured runtime execution for criterion: ' + cid)
            if row['evidence_kind'] == 'manual':
                if c.get('manual_acceptance', {}).get('actor_role') != 'project_owner' or c['manual_acceptance'].get('approved') is not True:
                    raise SystemExit('Manual evidence cannot be approved by automatic verification')
            out.append({**requirement, **row, 'actual_evidence': actual})
        if runtime.get('failure_class'):
            return {'status': 'fail', 'failure_class': runtime['failure_class'], 'reason': 'Runtime/harness execution did not complete successfully', 'coverage': out}
        return {'status': 'pass', 'failure_class': None, 'coverage': out}
    except (SystemExit, ValueError, KeyError, TypeError, OSError) as exc:
        return {'status': 'fail', 'failure_class': 'EVIDENCE_INSUFFICIENT', 'reason': str(exc), 'coverage': []}



def hardening_evidence(root, p, data, active):
    action = data.get('action', 'preflight')
    if data.get('actor_role') not in {'project_manager_agent', 'code_executor', 'integration_reviewer'}:
        raise SystemExit('Acceptance evidence requires execution/review role')
    if data.get('level') not in {'L1','L2','L3','L4','L5'}:
        raise SystemExit('Acceptance evidence requires L1..L5')
    if action == 'audit':
        source = p.read_json(safe_path(root, p.require_text(data, 'summary')))
        runtime = bound_runtime_evidence(root, p, source, data['summary'])
        if digest(data['acceptance_contract']) != runtime['identity']['acceptance_contract_hash'] or (data.get('run_id') and data['run_id'] != runtime['identity']['evidence_run_id']):
            emit({'status':'blocked','failure_class':'CONTRACT_INCOMPATIBLE','reason':'Audit only verifies the original contract/run; a new contract requires a new evidence run','candidate_runtime_status':runtime['candidate_runtime_status']})
            return 1
        if data.get('auditor_error'):
            audit = {'status':'fail', 'failure_class':'AUDITOR_FAILURE', 'reason':p.require_text(data,'auditor_error'), 'coverage':[]}
        else:
            audit = guarded_runtime_audit(root, p, runtime)
        origin_ref = source.get('origin_summary', data['summary'])
        origin_path = safe_path(root, origin_ref)
        origin = p.read_json(origin_path)
        identity = runtime['identity']
        uid = uuid.uuid4().hex
        ref = identity['evidence_directory'] + '/audit-' + uid + '.json'
        summary_ref = identity['evidence_directory'] + '/summary-audit-' + uid + '.json'
        binding = {'runtime_record':source['runtime_record'], 'runtime_sha256':source['runtime_sha256'],
                   'identity':identity, 'origin_summary':origin_ref, 'origin_summary_sha256':p.file_hash(origin_path)}
        record = {**audit, **binding}
        with (root/ref).open('xb') as f:
            f.write(encoded(record))
        base = {key:value for key,value in origin.items() if key != 'reason'}
        summary = {**base, **audit, **binding, 'audit_record':ref, 'audit_sha256':p.file_hash(root/ref)}
        with (root/summary_ref).open('xb') as f:
            f.write(encoded(summary))
        # Never replace newer-run evidence or rewrite the original failed summary.
        state = p.load_project_state(root)
        previous = state.get('test_summaries', {}).get(summary['purpose'])
        if audit['status'] == 'pass' and previous and Path(previous).parent == Path(origin_ref).parent:
            state['test_summaries'][summary['purpose']] = summary_ref
            p.save_project_state(root, state)
        emit({**audit, 'candidate_runtime_status':runtime['candidate_runtime_status'],
              'acceptance_contract_hash':identity['acceptance_contract_hash'],
              'evidence_run_id':identity['evidence_run_id'], 'audit':ref, 'summary':summary_ref})
        return 0 if audit['status'] == 'pass' else 1
    if action not in {'preflight', 'run'}:
        raise SystemExit('Acceptance protocol supports preflight/run/audit; legacy import is not runtime proof')
    investigation_guard(root, p)
    try:
        identity = contract_preflight(root, p, data)
        if identity['compatibility'] != 'compatible_without_candidate_change':
            emit({**identity, 'status':'blocked','failure_class':'CONTRACT_INCOMPATIBLE','candidate_runtime_status':'NOT_RUN'})
            return 1
    except (SystemExit, ValueError, OSError, KeyError, TypeError) as exc:
        emit({'status':'blocked','failure_class':'CONTRACT_INCOMPATIBLE','compatibility':'incompatible','candidate_runtime_status':'NOT_RUN','reason':str(exc)})
        return 1
    if action == 'preflight':
        emit({**identity,'status':'ready','candidate_runtime_status':'NOT_RUN'})
        return 0
    c = data['acceptance_contract']
    purpose = data.get('purpose','batch' if active else 'stage')
    if purpose not in {'batch','stage','release'} or (purpose == 'batch' and not active):
        raise SystemExit('Invalid evidence purpose/batch')
    if active and not active.get('acceptance_contract_hash'):
        raise SystemExit('Bind the acceptance contract to this batch before typed execution')
    expected = active.get('acceptance_contract_hash')
    if expected and expected != identity['acceptance_contract_hash']:
        raise SystemExit('Acceptance contract differs from active batch; revise through PM context review')
    rel = Path(identity['evidence_directory']); dest = root / rel
    dest.mkdir(parents=True, exist_ok=False)  # Reserve once; failed/crashed runs remain.
    p.write_json(dest / 'contract.json', c)
    investigation_attempt(root, p, identity['candidate_source_hash'], begin=True)
    env = os.environ.copy(); env.update(AI_ACCEPTANCE_CONTRACT=str(dest/'contract.json'), AI_EVIDENCE_DIR=str(dest), AI_EVIDENCE_RUN_ID=identity['evidence_run_id'])
    stdout, stderr, code, started, failure = b'', b'', None, False, None
    try:
        contract_preflight(root, p, data, reuse=True)
        proc = subprocess.Popen(c['harness']['argv'], cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
        started = True
        try:
            stdout, stderr = proc.communicate(timeout=c['timeout_seconds'])
            code = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired as exc:
                stdout, stderr = exc.stdout or b'', (exc.stderr or b'') + b'\nHarness descendants did not release capture pipes; owner/environment cleanup required.'
                proc.stdout.close(); proc.stderr.close()
            code = 124
            failure = 'ENVIRONMENT_BLOCKED'
    except (OSError, SystemExit) as exc:
        stderr = str(exc).encode('utf-8'); failure = 'HARNESS_FAILURE'
    for name, content in [('stdout.log',stdout),('stderr.log',stderr)]:
        with (dest/name).open('xb') as f:
            f.write(content)
    report = None
    try:
        if (dest/'runtime-result.json').exists():
            hard_file(root, (rel/'runtime-result.json').as_posix())
            report = p.read_json(dest/'runtime-result.json')
            if not isinstance(report, dict) or report.get('candidate_runtime_status') not in {'NOT_RUN','PASS','FAIL','UNKNOWN'}:
                raise ValueError('Invalid candidate runtime status')
    except (OSError, ValueError, SystemExit, TypeError) as exc:
        report = None; failure = 'HARNESS_FAILURE'
        with (dest/'collection-error.log').open('xb') as f: f.write(str(exc).encode('utf-8'))
    try:
        if digest(identity_manifest(root,c['harness'])) != identity['harness_source_hash'] or executable_identity(c['harness']) != identity['executable_identity'] or p.read_json(dest/'contract.json') != c:
            raise SystemExit('Harness/executable/contract identity changed during capture')
    except (SystemExit,OSError,ValueError) as exc:
        failure = 'HARNESS_FAILURE'
        with (dest/('identity-error-' + uuid.uuid4().hex + '.log')).open('xb') as f: f.write(str(exc).encode('utf-8'))
    # Freeze this run's regular files, including output left before report failure.
    # Never follow links or inspect another project's/output tree.
    raw, collection_errors = [], []
    for directory, dirs, files in os.walk(dest, followlinks=False, onerror=lambda exc: collection_errors.append(str(exc))):
        for name in list(dirs):
            path = Path(directory)/name
            if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
                dirs.remove(name)
                collection_errors.append('Linked evidence directory: ' + str(path.relative_to(dest)))
        for name in sorted(files):
            path = Path(directory)/name
            target_rel = path.relative_to(root).as_posix()
            try:
                item = hard_file(root, target_rel)
                if not path.resolve().is_relative_to(dest.resolve()):
                    raise SystemExit('Raw evidence escaped its run directory')
                raw.append({'path':target_rel,'sha256':item['sha256'],'bytes':path.stat().st_size})
            except (SystemExit, OSError, ValueError) as exc:
                collection_errors.append(str(exc))
    if collection_errors:
        failure = failure or 'HARNESS_FAILURE'
    runtime_status, failure = captured_outcome(report, code, started, failure, raw, identity['evidence_directory'])
    runtime = {'schema':'acceptance/1', 'identity':identity, 'contract':c, 'raw':raw,
               'candidate_runtime_status':runtime_status,'failure_class':failure, 'report':report,
               'process_started':started,'exit_code':code,'argv':c['harness']['argv'], 'created_at':p.now_iso(),
               'collection_errors':collection_errors,
               'audit_metadata':{'root_directory_mtime_ns':root.stat().st_mtime_ns}}
    with (dest/'runtime.json').open('xb') as f:
        f.write(encoded(runtime))
    audit = guarded_runtime_audit(root, p, runtime)
    if failure and failure != 'EVIDENCE_INSUFFICIENT':
        audit.update(status='fail',failure_class=failure)
    summary = {**identity, **audit, 'identity':identity, 'schema':'acceptance/1','evidence_kind':'mixed',
               'candidate_runtime_status':runtime_status, 'raw':raw,'level':data['level'],
               'batch_id':active.get('batch_id'),'context_fingerprint':active.get('context_fingerprint'),
               'formal_fact_hashes':p.current_audit_hashes(root), 'stage_id':p.load_project_state(root).get('current_stage'),
               'purpose':data.get('purpose','batch' if active else 'stage'),
               'runtime_record':(rel/'runtime.json').as_posix(),'runtime_sha256':p.file_hash(dest/'runtime.json')}
    with (dest/'summary.json').open('xb') as f:
        f.write(encoded(summary))
    state = p.load_project_state(root)
    state['layered_test_contract'] = True
    state.setdefault('test_summaries',{})[summary['purpose']] = (rel/'summary.json').as_posix()
    p.save_project_state(root,state)
    investigation_attempt(root,p,identity['candidate_source_hash'],failed=audit['status'] != 'pass')
    result = {key: summary[key] for key in ['candidate_revision','candidate_source_hash','acceptance_contract_revision','acceptance_contract_hash','harness_revision','evidence_run_id','status','failure_class','candidate_runtime_status']}
    result.update(summary=(rel/'summary.json').as_posix(),coverage_count=len(audit['coverage']))
    if audit.get('reason'): result['reason'] = audit['reason']
    emit(result)
    return 0 if audit['status'] == 'pass' else 1


def verify_hardening_evidence(root, p, data, active, ref):
    runtime = bound_runtime_evidence(root, p, data, ref)
    audit = guarded_runtime_audit(root,p,runtime)
    if audit['status'] != 'pass' or runtime.get('failure_class'):
        raise SystemExit('Acceptance evidence is stale/insufficient: ' + audit.get('reason','runtime failure'))
    if data.get('acceptance_contract_hash') != runtime['identity']['acceptance_contract_hash']:
        raise SystemExit('Evidence contract identity mismatch')
    if active and not active.get('acceptance_contract_hash'):
        raise SystemExit('Legacy batch cannot substitute typed evidence for its implementation fingerprint')
    if active and active.get('acceptance_contract_hash') and active['acceptance_contract_hash'] != data['acceptance_contract_hash']:
        raise SystemExit('Evidence belongs to a different acceptance contract')


def guarded_runtime_audit(root, p, runtime):
    try:
        return read_runtime_audit(root, p, runtime)
    except Exception as exc:
        return {'status':'fail','failure_class':'AUDITOR_FAILURE','reason':type(exc).__name__ + ': ' + str(exc),'coverage':[]}



def bound_runtime_evidence(root, p, data, ref):
    """Validate existing summary fields plus append-only re-audit bindings."""
    try:
        path = safe_path(root, data['runtime_record'])
        if p.file_hash(path) != data['runtime_sha256']:
            raise SystemExit('Frozen runtime record changed')
        runtime = p.read_json(path)
        identity = runtime['identity']
        directory = identity['evidence_directory']
        if data['runtime_record'] != directory + '/runtime.json' or Path(ref).parent.as_posix() != directory:
            raise SystemExit('Evidence binding points outside its original run')
        if data['identity'] != identity or data['raw'] != runtime['raw']:
            raise SystemExit('Evidence identity/raw binding mismatch')
        for key in ['candidate_revision','candidate_source_hash','acceptance_contract_revision',
                    'acceptance_contract_hash','harness_revision','harness_source_hash','evidence_run_id']:
            if data[key] != identity[key]:
                raise SystemExit('Evidence identity binding mismatch: ' + key)
        if data['candidate_runtime_status'] != runtime['candidate_runtime_status']:
            raise SystemExit('Evidence runtime status binding mismatch')
        if Path(ref).name != 'summary.json':
            origin_ref = data['origin_summary']
            if origin_ref != directory + '/summary.json':
                raise SystemExit('Reaudit must bind original summary, not an audit chain')
            origin_path = safe_path(root, origin_ref)
            if p.file_hash(origin_path) != data['origin_summary_sha256']:
                raise SystemExit('Original summary changed')
            origin = p.read_json(origin_path)
            bound_runtime_evidence(root, p, origin, origin_ref)
            for key in ['level','batch_id','context_fingerprint','formal_fact_hashes','stage_id','purpose',
                        'runtime_record','runtime_sha256','raw','identity']:
                if data[key] != origin[key]:
                    raise SystemExit('Reaudit cannot change original evidence context: ' + key)
            audit_ref = data['audit_record']
            if Path(audit_ref).parent.as_posix() != directory or not Path(audit_ref).name.startswith('audit-'):
                raise SystemExit('Invalid audit binding')
            audit_path = safe_path(root, audit_ref)
            if p.file_hash(audit_path) != data['audit_sha256']:
                raise SystemExit('Audit record changed')
            audit = p.read_json(audit_path)
            for key in ['identity','origin_summary','origin_summary_sha256','runtime_record','runtime_sha256',
                        'status','failure_class','coverage']:
                if audit[key] != data[key]:
                    raise SystemExit('Audit result/binding mismatch: ' + key)
        elif any(key in data for key in ['origin_summary','audit_record','audit_sha256']):
            raise SystemExit('Original summary cannot be replaced by a derived audit')
        return runtime
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise SystemExit('Missing/invalid evidence binding: ' + str(exc)) from None


def captured_outcome(report, code, started, observed_failure, raw, directory):
    """0 completes reporting, including legacy candidate FAIL. 1 is candidate
    failure only with explicit completed harness + FAIL; >=2/signals are facility
    failures. Observed collector/identity/timeout failures override declarations.
    """
    status = 'UNKNOWN' if started else 'NOT_RUN'
    if not isinstance(report, dict):
        return status, observed_failure or 'HARNESS_FAILURE'
    status = report['candidate_runtime_status']
    rows = report.get('coverage')
    valid_rows = isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
    claimed = report.get('failure_class')
    valid_claim = claimed is None or (isinstance(claimed, str) and claimed in FAILURE_CLASSES)
    conflict = (not valid_rows or not valid_claim
                or (claimed == 'CANDIDATE_FAILURE' and status != 'FAIL'))
    if status == 'FAIL' and (not valid_rows or not any(row.get('status') == 'fail' for row in rows)):
        conflict = True
    if code == 1 and not (status == 'FAIL' and report.get('harness_status') == 'completed'
                          and claimed in (None, 'CANDIDATE_FAILURE')):
        conflict = True
    if status == 'NOT_RUN' and started:
        refs = report.get('not_run_evidence', [])
        raw_paths = {item['path'] for item in raw if item['bytes'] > 0}
        reliable = (report.get('harness_status') == 'failed' and isinstance(refs, list) and refs
                    and all(isinstance(ref, str) and directory + '/' + ref in raw_paths
                            and Path(ref).name not in {'contract.json','runtime-result.json'} for ref in refs))
        if not reliable:
            status = 'UNKNOWN'
    if conflict:
        return 'UNKNOWN' if started else 'NOT_RUN', observed_failure or 'HARNESS_FAILURE'
    if observed_failure:
        return status, observed_failure
    if code not in {0, 1} or report.get('harness_status') == 'failed':
        return status, 'HARNESS_FAILURE'
    if claimed:
        return status, claimed
    if status == 'FAIL':
        return status, 'CANDIDATE_FAILURE'
    if status in {'UNKNOWN', 'NOT_RUN'}:
        return status, 'EVIDENCE_INSUFFICIENT'
    return status, None
