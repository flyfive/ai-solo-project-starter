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


def refresh(root, p, task='', accept=False, actor='', reason=''):
    index = build_index(root, p)
    active = p.read_json(root / p.ACTIVE_FILE, default=None)
    if accept:
        if actor != 'project_manager_agent' or not reason.strip():
            raise SystemExit('Accepting changed context requires PM role and a reread/review reason.')
        if active:
            active['context_fingerprint'] = reference_fingerprint(index, active.get('context_refs', {}))
            active['context_review'] = {'at': p.now_iso(), 'reason': reason, 'actor_role': actor}
            p.write_json(root / p.ACTIVE_FILE, active)
    refs, selected, stale = selected_context(root, p, index, active, task)
    state = p.load_project_state(root)
    changes = p.open_changes(root)
    suspended = p.read_json(root / p.SUSPENDED_PROMOTION_BATCH_FILE, default=None)
    priority = p.resume_priority(state, changes, active, suspended)
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
    p.update_auto_block(state_path, snapshot)
    if p.governance_mode(root) == 'standard':
        p._write_bytes_atomically(root / INDEX, encoded(index))
    p.write_json(root / p.CONTEXT_FILE, manifest)
    handoff = '# 当前任务接管\n\n- 当前治理模式：`' + p.governance_mode(root) + '`\n\n先读 START_HERE、AGENTS 和 CURRENT_STATE，再读取 context.json 中的选定索引及 L2 正文。\n\n' + snapshot + '\n\n- 当前上下文状态：' + ('STALE，PM 重新读取确认后刷新' if stale else 'CURRENT') + '\n'
    if checkpoint:
        handoff += '\n- 最新假设：' + checkpoint['hypothesis'] + '\n- 其余排错事实见 context.json 的 active_batch.debug_checkpoint。\n'
    (root / p.HANDOFF_FILE).write_text(handoff, encoding='utf-8', newline='\n')
    return manifest


def ensure_fresh(root, p, active):
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
    task = task_fields(root, p, data)
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
        if data.get('implementation_fingerprint') != p.working_fingerprint(root) or data.get('implementation_tree') != p.git_implementation_tree_hash(root):
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
    path = root / (args.input or '.ai/runtime/unit_result.json')
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
    data = p.read_json(root / (args.input or '.ai/runtime/evidence_request.json'))
    active = p.read_json(root / p.ACTIVE_FILE, default={})
    if active:
        ensure_fresh(root, p, active)
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
    path = root / (args.input or '.ai/runtime/decision.json')
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
    if command == 'ai-context':
        return context_command(args, p)
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
        result_data = p.read_json(root / (args.result or p.RESULT_FILE))
        # Every submitted attempt is retained, including rejected or failed attempts.
        archive(root, p, 'batches', (before_active or {}).get('batch_id', 'unknown'), {'active_batch': before_active, 'result': result_data, 'submitted_at': p.now_iso()})
        finish_guard(root, p, result_data)
    if command == 'ai-acceptance' and before_active:
        ensure_fresh(root, p, before_active)
    if command == 'ai-acceptance':
        acceptance = p.read_json(root / (args.input or p.ACCEPTANCE_FILE))
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
    parser.add_argument('action', choices=['manifest', 'refresh', 'check', 'index', 'read', 'history', 'cold'])
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
