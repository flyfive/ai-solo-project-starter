"""Synthetic subprocess fixtures for regression accounting, never real projects."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest import mock
from test_regression import ROOT, PYTHON, make_temp_dir, remove_tree, run


class RunnerSummaryTests(unittest.TestCase):
    def fixture(self, body):
        base = make_temp_dir('runner-summary-')
        self.addCleanup(remove_tree, base)
        source = base / 'current'
        (source / 'tests').mkdir(parents=True)
        shutil.copyfile(ROOT / 'run_tests.py', source / 'run_tests.py')
        (source / 'tests/test_synthetic.py').write_text(body, encoding='utf-8')
        return base, source

    def execute(self, body, expect=0):
        base, source = self.fixture(body)
        process = run([PYTHON, '-B', str(source / 'run_tests.py'), '--report-dir', str(base / 'reports')], expect=expect)
        report = next((base / 'reports').glob('run-*/summary.json'))
        summary = json.loads(report.read_text(encoding='utf-8'))
        self.assertEqual(summary['total'], sum(summary[k] for k in ['passed', 'skipped', 'failed', 'timed_out']))
        for case in summary['cases']:
            self.assertTrue((report.parent / case['raw_log']).is_file())
        return summary, process, report

    def test_pass_skip_failure_and_raw_logs(self):
        summary, process, report = self.execute("""import unittest
class Synthetic(unittest.TestCase):
 def test_pass(self): print('synthetic raw marker'); self.assertTrue(True)
 @unittest.skip('deliberate synthetic skip')
 def test_skip(self): self.fail('must not run')
 def test_fail(self): self.fail('deliberate synthetic failure')
""", expect=1)
        self.assertEqual([summary[k] for k in ['total','passed','skipped','failed','timed_out']], [3,1,1,1,0])
        self.assertEqual({c['status'] for c in summary['cases']}, {'pass','skip','fail'})
        self.assertIn('1 SKIP', process.stdout)
        self.assertTrue(any('synthetic raw marker' in p.read_text(encoding='utf-8') for p in report.parent.glob('*.log')))

    def test_source_mutation_still_fails(self):
        summary, _, _ = self.execute("""import unittest
from pathlib import Path
class Synthetic(unittest.TestCase):
 def test_mutation(self): Path(__file__).parents[1].joinpath('changed.txt').write_text('synthetic mutation')
""", expect=1)
        self.assertEqual(summary['passed'], 1)
        self.assertEqual(summary['status'], 'fail')
        self.assertIn('changed.txt', summary['source_mutations'])

    def test_timeout_is_exclusive_and_retains_output(self):
        base, source = self.fixture("""import unittest,time
class Synthetic(unittest.TestCase):
 def test_timeout(self): print('before timeout',flush=True); time.sleep(10)
""")
        spec = importlib.util.spec_from_file_location('synthetic_runner_timeout', source / 'run_tests.py')
        runner = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {spec.name: runner}):
            spec.loader.exec_module(runner)
            runner.CASE_TIMEOUT_SECONDS = 1
            with mock.patch.object(sys, 'argv', ['run_tests.py','--report-dir',str(base / 'reports')]):
                self.assertEqual(runner.main(), 1)
        report = next((base / 'reports').glob('run-*/summary.json'))
        summary = json.loads(report.read_text(encoding='utf-8'))
        self.assertEqual([summary[k] for k in ['total','passed','skipped','failed','timed_out']], [1,0,0,0,1])
        self.assertEqual(summary['cases'][0]['status'], 'timeout')
        self.assertIn('before timeout', (report.parent / summary['cases'][0]['raw_log']).read_text(encoding='utf-8'))

    def test_zero_exit_without_result_is_not_pass(self):
        summary, _, _ = self.execute("""import unittest,os
class Synthetic(unittest.TestCase):
 def test_exit(self): os._exit(0)
""", expect=1)
        self.assertEqual(summary['failed'], 1)
        self.assertEqual(summary['passed'], 0)

    def test_class_skip_and_expected_failure_are_not_pass(self):
        summary, _, _ = self.execute("""import unittest
class Skipped(unittest.TestCase):
 @classmethod
 def setUpClass(cls): raise unittest.SkipTest('synthetic class skip')
 def test_skipped(self): pass
class Expected(unittest.TestCase):
 @unittest.expectedFailure
 def test_expected(self): self.fail('synthetic known failure')
""")
        self.assertEqual([summary[k] for k in ['total','passed','skipped','failed','timed_out']], [2,0,2,0,0])
