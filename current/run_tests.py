#!/usr/bin/env python3
"""Run starter regression cases in isolated, parallel Python processes.

Each test owns a separate temporary Git repository. Process isolation prevents Git
hooks, imported project modules, and platform-specific file handles from leaking
between cases. A bounded worker pool keeps the one-command suite fast while each
case retains an independent timeout.
"""
from __future__ import annotations

import os
import argparse
import hashlib
import subprocess
import sys
import time
import unittest
import json
import uuid
import tempfile
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent
TEST_DIR = ROOT / "tests"
CASE_TIMEOUT_SECONDS = 120
MAX_WORKERS = min(4, max(1, os.cpu_count() or 1))


@dataclass
class CaseResult:
    test_id: str
    returncode: int
    output: str
    timed_out: bool = False
    status: str = "fail"


def source_snapshot() -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(item for item in ROOT.rglob("*") if item.is_file()):
        rel = path.relative_to(ROOT)
        if any(part in {".git", "__pycache__", ".test-runtime"} for part in rel.parts):
            continue
        if path.suffix.lower() in {".pyc", ".pyo"}:
            continue
        snapshot[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def discover_test_ids() -> list[str]:
    suite = unittest.defaultTestLoader.discover(str(TEST_DIR), pattern="test_*.py")
    ids: list[str] = []

    def collect(node: unittest.TestSuite | unittest.TestCase) -> None:
        if isinstance(node, unittest.TestSuite):
            for child in node:
                collect(child)
        else:
            ids.append(node.id())

    collect(suite)
    return sorted(ids)


def run_worker(test_id: str, result_path: Path) -> int:
    """Write unittest's actual result separately from arbitrary test stdout."""
    sys.path.insert(0, str(TEST_DIR))
    suite = unittest.defaultTestLoader.loadTestsFromName(test_id)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        status = 'fail'
    elif result.skipped or result.expectedFailures:
        status = 'skip'
    elif result.testsRun == 1:
        status = 'pass'
    else:
        status = 'fail'
    result_path.write_text(json.dumps({'status': status, 'tests_run': result.testsRun,
        'skip_reasons': [reason for _, reason in result.skipped],
        'expected_failures': len(result.expectedFailures)}), encoding='utf-8')
    return 1 if status == 'fail' else 0


def run_case(test_id: str) -> CaseResult:
    with tempfile.TemporaryDirectory(prefix='starter-case-result-') as temp:
        result_path = Path(temp) / 'result.json'
        try:
            process = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve()),
                 '--worker-case', test_id, '--worker-result', str(result_path)],
                cwd=TEST_DIR, text=True, capture_output=True, timeout=CASE_TIMEOUT_SECONDS,
            )
            output = process.stdout + process.stderr
            status = 'fail'
            try:
                structured = json.loads(result_path.read_text(encoding='utf-8'))
                reported = structured['status']
                if process.returncode == 0 and reported in {'pass', 'skip'}:
                    status = reported
            except (OSError, ValueError, KeyError, TypeError):
                output += '\nMissing or invalid structured unittest result.\n'
            return CaseResult(test_id, process.returncode, output, status=status)
        except subprocess.TimeoutExpired as exc:
            captured = ""
            for part in (exc.stdout, exc.stderr):
                if part:
                    captured += part.decode(errors='replace') if isinstance(part, bytes) else part
            return CaseResult(test_id, 124, captured, timed_out=True, status='timeout')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, default=ROOT.parent / 'validation' / 'local-run')
    parser.add_argument('--verbose', action='store_true', help='Print every passing case as well as failures')
    parser.add_argument('--worker-case', help=argparse.SUPPRESS)
    parser.add_argument('--worker-result', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_case is not None:
        if args.worker_result is None:
            parser.error('--worker-result required for isolated worker')
        return run_worker(args.worker_case, args.worker_result)
    report_root = args.report_dir.resolve()
    if report_root == ROOT or ROOT in report_root.parents:
        raise SystemExit('Raw regression reports must be outside the immutable source package.')
    report_dir = report_root / ('run-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    report_dir.mkdir(parents=True)
    started_at = time.perf_counter()
    before = source_snapshot()
    test_ids = discover_test_ids()
    if not test_ids:
        print("No regression tests discovered.", file=sys.stderr)
        return 2

    results: dict[str, CaseResult] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(run_case, test_id): test_id for test_id in test_ids}
        for future in as_completed(futures):
            result = future.result()
            results[result.test_id] = result
            label = result.status.upper()
            raw_name = hashlib.sha256(result.test_id.encode('utf-8')).hexdigest()[:16] + '.log'
            (report_dir / raw_name).write_text(result.output, encoding='utf-8', newline='\n')
            if args.verbose or result.status in {'fail', 'timeout'}:
                print(f"[{label}] {result.test_id}", flush=True)

    after = source_snapshot()
    mutations = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    failures = [results[test_id] for test_id in test_ids if results[test_id].status in {'fail', 'timeout'}]
    counts = {status: sum(r.status == status for r in results.values()) for status in ('pass', 'skip', 'fail', 'timeout')}
    summary = {
        'status': 'fail' if failures or mutations else 'pass',
        'total': len(test_ids), 'passed': counts['pass'], 'skipped': counts['skip'],
        'failed': counts['fail'], 'timed_out': counts['timeout'], 'source_mutations': mutations,
        'elapsed_seconds': round(time.perf_counter() - started_at, 3),
        'workers': MAX_WORKERS, 'python': sys.version, 'token_metrics': None,
        'cases': [{'id': test_id, 'status': results[test_id].status,
                   'returncode': results[test_id].returncode,
                   'raw_log': hashlib.sha256(test_id.encode('utf-8')).hexdigest()[:16] + '.log'} for test_id in test_ids],
    }
    (report_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('REGRESSION_SUMMARY ' + str(report_dir / 'summary.json'), flush=True)
    print(f"Regression: {len(test_ids)} total; {counts['pass']} PASS, {counts['skip']} SKIP, {counts['fail']} FAIL, {counts['timeout']} TIMEOUT.", flush=True)
    if failures:
        print("\nRegression failures:", file=sys.stderr)
        for result in failures:
            print(f"\n--- {result.test_id} ---", file=sys.stderr)
            print(result.output[-6000:].rstrip(), file=sys.stderr)
            print('Full output retained in report directory.', file=sys.stderr)
    if mutations:
        print("\nSource package changed while tests were running:", file=sys.stderr)
        for path in mutations:
            state = "added" if path not in before else ("removed" if path not in after else "modified")
            print(f"- {path}: {state}", file=sys.stderr)
        print(f"Regression elapsed: {time.perf_counter() - started_at:.3f} seconds.")
        return 1

    print(f"Source package remained byte-for-byte unchanged ({len(after)} files).")
    if failures:
        print(f"Regression elapsed: {time.perf_counter() - started_at:.3f} seconds.")
        return 1
    print(f"\nRegression completed without failures with {MAX_WORKERS} workers.")
    print(f"Regression elapsed: {time.perf_counter() - started_at:.3f} seconds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
