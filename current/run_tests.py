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


def run_case(test_id: str) -> CaseResult:
    try:
        result = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "-v", test_id],
            cwd=TEST_DIR,
            text=True,
            capture_output=True,
            timeout=CASE_TIMEOUT_SECONDS,
        )
        return CaseResult(test_id, result.returncode, result.stdout + result.stderr)
    except subprocess.TimeoutExpired as exc:
        captured = ""
        if exc.stdout:
            captured += exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout
        if exc.stderr:
            captured += exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr
        return CaseResult(test_id, 124, captured, timed_out=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, default=ROOT.parent / 'validation' / 'local-run')
    parser.add_argument('--verbose', action='store_true', help='Print every passing case as well as failures')
    args = parser.parse_args()
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
            label = "TIMEOUT" if result.timed_out else ("PASS" if result.returncode == 0 else "FAIL")
            raw_name = hashlib.sha256(result.test_id.encode('utf-8')).hexdigest()[:16] + '.log'
            (report_dir / raw_name).write_text(result.output, encoding='utf-8', newline='\n')
            if args.verbose or result.returncode:
                print(f"[{label}] {result.test_id}", flush=True)

    after = source_snapshot()
    mutations = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    failures = [results[test_id] for test_id in test_ids if results[test_id].returncode != 0]
    summary = {
        'status': 'fail' if failures or mutations else 'pass',
        'total': len(test_ids), 'passed': len(test_ids) - len(failures),
        'failed': len(failures), 'source_mutations': mutations,
        'elapsed_seconds': round(time.perf_counter() - started_at, 3),
        'workers': MAX_WORKERS, 'python': sys.version, 'token_metrics': None,
        'cases': [{'id': test_id, 'status': 'pass' if results[test_id].returncode == 0 else 'fail',
                   'returncode': results[test_id].returncode,
                   'raw_log': hashlib.sha256(test_id.encode('utf-8')).hexdigest()[:16] + '.log'} for test_id in test_ids],
    }
    (report_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('REGRESSION_SUMMARY ' + str(report_dir / 'summary.json'), flush=True)
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
    print(f"\nAll {len(test_ids)} isolated regression tests passed with {MAX_WORKERS} workers.")
    print(f"Regression elapsed: {time.perf_counter() - started_at:.3f} seconds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
