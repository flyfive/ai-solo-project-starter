from __future__ import annotations

import json
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
import uuid
import warnings
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / "starter.py"
PYTHON = sys.executable
TEST_TEMP_ROOT = Path(os.environ.get("AI_STARTER_TEST_TEMP_ROOT", tempfile.gettempdir()))
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)


def make_temp_dir(prefix: str) -> Path:
    for _ in range(20):
        candidate = TEST_TEMP_ROOT / f"{prefix}{uuid.uuid4().hex[:12]}"
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError(f"could not allocate an isolated test directory under {TEST_TEMP_ROOT}")


def run(
    cmd: list[str],
    cwd: Path | None = None,
    expect: int | set[int] = 0,
    *,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd, cwd=cwd, text=True, capture_output=True, env=env, input=input_text, timeout=timeout
    )
    allowed = {expect} if isinstance(expect, int) else expect
    if result.returncode not in allowed:
        raise AssertionError(
            f"command failed ({result.returncode}, expected {allowed}): {cmd}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def remove_tree(path: Path) -> None:
    def remove_readonly(function, item_path, _exc_info):
        os.chmod(item_path, stat.S_IWRITE)
        function(item_path)

    shutil.rmtree(path, onerror=remove_readonly)


class ProjectHarness:
    def __init__(
        self,
        case: unittest.TestCase,
        *,
        name: str = "Regression Project",
        description: str = "Regression test project",
        governance_mode: str | None = None,
    ):
        self.case = case
        self.temp_root = make_temp_dir("ai-starter-v181-")
        self.root = self.temp_root / "project"
        self.case.addCleanup(self.close)
        command = [
            PYTHON, str(STARTER), "init", "--target", str(self.root),
            "--name", name, "--description", description, "--profile", "generic",
        ]
        if governance_mode:
            command.extend(["--governance-mode", governance_mode])
        run(command)
        run(["git", "config", "user.email", "tests@example.invalid"], self.root)
        run(["git", "config", "user.name", "Template Regression"], self.root)

    def close(self) -> None:
        if os.environ.get("AI_STARTER_KEEP_TEST_PROJECTS", "").strip().lower() in {"1", "true", "yes"}:
            return
        if not self.temp_root.exists():
            return
        for attempt in range(8):
            try:
                remove_tree(self.temp_root)
                return
            except OSError as exc:
                if attempt == 7:
                    warnings.warn(f"could not clean test project {self.temp_root}: {exc}", RuntimeWarning)
                    return
                time.sleep(0.1 * (attempt + 1))

    def tool(
        self,
        *args: str,
        expect: int | set[int] = 0,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return run([PYTHON, "tools/project.py", *args], self.root, expect, env=env)

    def commit(self, message: str) -> str:
        run(["git", "add", "-A"], self.root)
        run(["git", "commit", "-m", message], self.root)
        return run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()

    def start_batch(self, batch_id: str = "P1-001", stage: str = "P1") -> None:
        write_json(self.root / ".ai/runtime/batch_request.json", {
            "batch_id": batch_id,
            "stage_id": stage,
            "title": "Regression batch",
            "goal": "Exercise batch state machine",
            "scope": ["test scope"],
            "acceptance_criteria": ["test passes"],
            "change_ids": [],
            "risk_level": "normal",
            "requires_user_authorization": False,
            "execution_mode": "single",
        })
        self.tool("ai-start")

    def register_ready_bug_change(self) -> str:
        write_json(self.root / ".ai/runtime/change_request.json", {
            "source": "development",
            "origin_batch_id": "",
            "raw_feedback": "Fix an implementation defect",
            "change_types": ["bug_fix"],
            "affected_implementation": ["src/a", "src/b"],
            "requires_reacceptance": False,
        })
        captured = self.tool("ai-register-change")
        change_id = captured.stdout.strip().split()[1]
        self.tool("ai-change-ready", change_id)
        return change_id

    def start_parallel_batch(self, change_id: str = "") -> None:
        write_json(self.root / ".ai/runtime/batch_request.json", {
            "batch_id": "P1-001",
            "stage_id": "P1",
            "title": "Parallel regression batch",
            "goal": "Exercise the parallel integration gate",
            "scope": ["parallel work"],
            "acceptance_criteria": ["main and integration checks pass"],
            "change_ids": [change_id] if change_id else [],
            "risk_level": "normal",
            "requires_user_authorization": False,
            "execution_mode": "parallel",
            "execution_threads": [
                {
                    "thread_id": "worker-a",
                    "role": "code_executor",
                    "scope": ["component A"],
                    "allowed_paths": ["src/a"],
                    "prohibited_paths": [],
                },
                {
                    "thread_id": "worker-b",
                    "role": "code_executor",
                    "scope": ["component B"],
                    "allowed_paths": ["src/b"],
                    "prohibited_paths": [],
                },
            ],
        })
        self.tool("ai-start")

    def result_payload(self, status: str, tests: list[dict], blockers: list[str] | None = None) -> dict:
        return {
            "batch_id": "P1-001",
            "stage_id": "P1",
            "title": "Regression batch",
            "status": status,
            "summary": f"Result {status}",
            "tests": tests,
            "next_task": "continue",
            "blockers": blockers or [],
            "memory_changes": [],
            "manual_acceptance": "not_required",
            "changed_files": [],
            "change_ids": [],
            "manager_review": {
                "status": "approved", "reviewer": "project_manager_agent", "note": "reviewed"
            },
            "integration_review": {"status": "not_required", "reviewer_role": "", "note": "", "tests": []},
        }

    def create_complete_requirement(self, release: str = "1.0.0") -> None:
        write_json(self.root / ".ai/runtime/requirement_update.json", {
            "actor_role": "project_manager_agent",
            "action": "create",
            "title": "Core feature",
            "description": "The released application provides the core feature.",
            "status": "active",
            "priority": "must",
            "category": "functional",
            "release_target": release,
            "customer_visible": True,
            "release_blocking": True,
            "acceptance_criteria": [{
                "description": "Core feature works", "method": "both", "status": "pass",
                "evidence": "tests/core-feature", "note": "verified",
            }],
            "implementation_refs": ["src/core.txt"],
            "test_refs": ["tests/core-feature"],
            "manual_acceptance": {"status": "passed", "date": "2026-07-30", "note": "owner passed"},
            "user_instructions": "Open the application and use the Core feature entry.",
            "user_instructions_verified": True,
            "help_notes": ["If the feature is unavailable, restart the application."],
            "known_limitations": [],
        })
        self.tool("ai-requirement")

    def record_full_audit(self, stage: str = "P1") -> None:
        # Set stage through a valid closed batch if it is not set yet.
        state = json.loads((self.root / ".ai/project_state.json").read_text(encoding="utf-8"))
        if not state.get("current_stage"):
            self.start_batch()
            write_json(self.root / ".ai/runtime/batch_result.json", self.result_payload(
                "pass", [{"name": "batch check", "status": "pass", "details": "ok"}]
            ))
            self.tool("ai-finish", expect={0, 1})
        project_module = self.root / "tools/project.py"
        namespace: dict = {}
        exec(compile(project_module.read_text(encoding="utf-8"), str(project_module), "exec"), namespace)
        docs = [rel for rel in namespace["CORE_CURRENT_DOCS"] if (self.root / rel).exists()]
        write_json(self.root / ".ai/runtime/audit_result.json", {
            "stage_id": stage,
            "status": "passed",
            "documents_read": docs,
            "conflicts": [],
            "resolutions": [],
            "summary": "All current facts are consistent.",
            "manager_review": {"status": "approved", "reviewer": "project_manager_agent", "note": "approved"},
        })
        self.tool("ai-audit")

    def create_baseline(self, release: str = "1.0.0", supersedes: str | None = None) -> str:
        data = {
            "actor_role": "project_manager_agent",
            "release_version": release,
            "release_name": release,
            "scope_note": "Regression release",
        }
        if supersedes:
            data["supersedes_baseline_id"] = supersedes
        write_json(self.root / ".ai/runtime/release_baseline.json", data)
        result = self.tool("ai-release-baseline")
        parts = result.stdout.strip().split()
        return parts[2]

    def close_release(self, release: str, stage: str) -> tuple[str, Path]:
        src = self.root / "src/core.txt"
        src.parent.mkdir(parents=True, exist_ok=True)
        if not src.exists():
            src.write_text("v1\n", encoding="utf-8")
        self.create_complete_requirement(release)
        self.record_full_audit(stage)
        self.commit(f"{release} release ready")
        baseline_id = self.create_baseline(release)
        artifact = self.deliver_and_close_release(release)
        return baseline_id, artifact

    def deliver_and_close_release(self, release: str) -> Path:
        artifact = self.root / "dist" / f"app-{release}.bin"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(f"release-{release}".encode("utf-8"))
        write_json(self.root / ".ai/runtime/delivery_request.json", {
            "actor_role": "project_manager_agent",
            "release_version": release,
            "customer_name": "Customer",
            "maintenance_note": "Standard maintenance.",
            "artifacts": [{
                "name": "Application",
                "path": artifact.relative_to(self.root).as_posix(),
                "version": release,
                "status": "ready",
            }],
        })
        self.tool("ai-generate-delivery")
        self.tool("ai-delivery-verify", "--release", release)
        write_json(self.root / ".ai/runtime/final_acceptance.json", {
            "recorder_role": "project_manager_agent",
            "release_version": release,
            "owner_decision": "passed",
            "owner_note": f"Accepted {release}.",
        })
        self.tool("ai-final-acceptance")
        self.tool("ai-delivery-verify", "--release", release)
        write_json(self.root / ".ai/runtime/project_close.json", {
            "actor_role": "project_manager_agent",
            "release_version": release,
            "closure_note": f"Release {release} deliverables accepted and archived.",
        })
        self.tool("ai-close-project")
        return artifact


class V181RegressionTests(unittest.TestCase):
    def _assert_parallel_integration_rejected(
        self, integration_tests: list[dict], expected_fragment: str
    ) -> None:
        h = ProjectHarness(self)
        try:
            change_id = h.register_ready_bug_change()
            h.start_parallel_batch(change_id)
            state_path = h.root / ".ai/project_state.json"
            log_path = next((h.root / "docs/logs").glob("*.md"))
            state_before = state_path.read_bytes()
            log_before = log_path.read_bytes()
            payload = h.result_payload(
                "pass", [{"name": "unit", "status": "pass", "details": "ok"}]
            )
            payload["title"] = "Parallel regression batch"
            payload["change_ids"] = [change_id]
            payload["integration_review"] = {
                "status": "approved",
                "reviewer_role": "integration_reviewer",
                "note": "reviewed",
                "tests": integration_tests,
            }
            write_json(h.root / ".ai/runtime/batch_result.json", payload)
            rejected = h.tool("ai-finish", expect=1)
            output = (rejected.stdout + rejected.stderr).lower()
            self.assertIn(expected_fragment.lower(), output)
            self.assertTrue((h.root / ".ai/runtime/active_batch.json").exists())
            pending = json.loads((h.root / ".ai/runtime/pending_changes.json").read_text(encoding="utf-8"))
            self.assertEqual(pending["changes"][0]["status"], "docs_ready")
            self.assertEqual(state_before, state_path.read_bytes())
            self.assertEqual(log_before, log_path.read_bytes())
        finally:
            h.close()

    def test_atomic_init_and_toml_escaping(self) -> None:
        h = ProjectHarness(self, name='Project "Quoted" \\ Demo', description='Line 1 "quoted"\\path\nLine 2')
        try:
            with (h.root / "PROJECT.toml").open("rb") as fh:
                cfg = tomllib.load(fh)
            self.assertEqual(cfg["project"]["name"], 'Project "Quoted" \\ Demo')
            self.assertIn("Line 2", cfg["project"]["description"])
            self.assertTrue((h.root / ".githooks/python-path").exists())
            self.assertEqual(run(["git", "rev-list", "--count", "HEAD"], h.root).stdout.strip(), "1")
            self.assertFalse(any("__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"} for path in h.root.rglob("*")))
            existing_root = make_temp_dir("ai-starter-existing-")
            try:
                existing = existing_root / "existing"
                existing.mkdir(); (existing / "marker.txt").write_text("keep", encoding="utf-8")
                rejected = run([PYTHON, str(STARTER), "init", "--target", str(existing), "--name", "X", "--description", "Y", "--profile", "generic"], expect=2)
                self.assertTrue((existing / "marker.txt").exists())
                forced = run([PYTHON, str(STARTER), "init", "--target", str(existing), "--name", "X", "--description", "Y", "--profile", "generic", "--force"])
                self.assertIn("原目录已安全备份", forced.stdout)
                no_git_target = existing_root / "no-git"
                no_git = run([
                    PYTHON, str(STARTER), "init", "--target", str(no_git_target),
                    "--name", "X", "--description", "Y", "--profile", "generic", "--no-git-init",
                ], expect=2)
                self.assertFalse(no_git_target.exists())
                self.assertIn("no-git-init", no_git.stderr)
            finally:
                remove_tree(existing_root)
        finally:
            h.close()

    def test_lite_mode_initializes_a_smaller_compatible_project(self) -> None:
        h = ProjectHarness(
            self,
            description="A personal helper expected to take one or two days.",
            governance_mode="lite",
        )
        try:
            with (h.root / "PROJECT.toml").open("rb") as fh:
                cfg = tomllib.load(fh)
            self.assertEqual(cfg["governance"]["mode"], "lite")
            common_required = cfg["documents"]["required"]
            standard_required = cfg["documents"]["standard_required"]
            self.assertTrue(all((h.root / rel).exists() for rel in common_required))
            self.assertTrue(all(not (h.root / rel).exists() for rel in standard_required))
            self.assertTrue((h.root / ".ai/standard_mode_templates.json").exists())
            self.assertTrue((h.root / "docs/PRODUCT_REQUIREMENTS.md").exists())
            self.assertTrue((h.root / "docs/REQUIREMENT_CHANGELOG.md").exists())
            self.assertTrue((h.root / "docs/CURRENT_STATE.md").exists())
            self.assertTrue((h.root / "docs/DECISIONS.md").exists())
            non_git_files = [
                path for path in h.root.rglob("*")
                if path.is_file() and ".git" not in path.relative_to(h.root).parts
            ]
            self.assertTrue((h.root / "NOTICE.template.txt").is_file())
            self.assertLessEqual(len(non_git_files), 23)
            health = h.tool("health", "--json", expect={0, 1})
            result = json.loads(health.stdout)
            self.assertEqual(result["fail"], [])
            self.assertIn("Lite 治理模式已启用", result["pass"])
            self.assertEqual(run(["git", "status", "--porcelain"], h.root).stdout.strip(), "")
        finally:
            h.close()

    def test_auto_governance_selects_by_description_and_manual_choice_wins(self) -> None:
        temp = make_temp_dir("ai-starter-v181-auto-")
        try:
            cases = [
                (
                    "auto-lite",
                    "A tiny personal script expected to take one or two days.",
                    "auto",
                    "lite",
                ),
                (
                    "auto-standard",
                    "A multi-stage customer delivery with authentication, deployment and data migration.",
                    "auto",
                    "standard",
                ),
                (
                    "manual-standard",
                    "A tiny personal script expected to take one day.",
                    "standard",
                    "standard",
                ),
                (
                    "auto-lite-zh",
                    "预计一两天完成的个人小工具，只给自己使用。",
                    "auto",
                    "lite",
                ),
                (
                    "auto-standard-zh",
                    "需要正式交付给客户，包含权限、部署和多阶段迭代。",
                    "auto",
                    "standard",
                ),
            ]
            for slug, description, requested, expected in cases:
                with self.subTest(slug=slug):
                    target = temp / slug
                    result = run([
                        PYTHON,
                        str(STARTER),
                        "init",
                        "--target",
                        str(target),
                        "--name",
                        slug,
                        "--description",
                        description,
                        "--profile",
                        "generic",
                        "--governance-mode",
                        requested,
                    ])
                    with (target / "PROJECT.toml").open("rb") as fh:
                        cfg = tomllib.load(fh)
                    self.assertEqual(cfg["governance"]["mode"], expected)
                    self.assertIn(f"GOVERNANCE_MODE {expected}", result.stdout)
        finally:
            if temp.exists():
                remove_tree(temp)

    def test_auto_standard_hard_triggers_cannot_be_offset_by_short_duration(self) -> None:
        temp = make_temp_dir("ai-starter-v181-auto-hard-")
        try:
            cases = [
                (
                    "customer-two-days",
                    "A two-day Windows tool for formal customer delivery.",
                    "desktop-windows",
                ),
                (
                    "sensitive-one-day",
                    "A one-day personal helper that processes sensitive account data.",
                    "python-local-tool",
                ),
                (
                    "hardware-one-day",
                    "A one-day personal board check.",
                    "hardware-pcb",
                ),
                (
                    "client-two-days-zh",
                    "预计两天完成并正式交付给客户的 Windows 小工具。",
                    "desktop-windows",
                ),
            ]
            for slug, description, profile in cases:
                with self.subTest(slug=slug):
                    target = temp / slug
                    result = run([
                        PYTHON,
                        str(STARTER),
                        "init",
                        "--target",
                        str(target),
                        "--name",
                        slug,
                        "--description",
                        description,
                        "--profile",
                        profile,
                        "--governance-mode",
                        "auto",
                    ])
                    with (target / "PROJECT.toml").open("rb") as fh:
                        cfg = tomllib.load(fh)
                    self.assertEqual(cfg["governance"]["mode"], "standard")
                    self.assertIn("硬触发", result.stdout)

            manual = temp / "manual-lite"
            run([
                PYTHON,
                str(STARTER),
                "init",
                "--target",
                str(manual),
                "--name",
                "manual-lite",
                "--description",
                "A two-day customer delivery.",
                "--profile",
                "desktop-windows",
                "--governance-mode",
                "lite",
            ])
            with (manual / "PROJECT.toml").open("rb") as fh:
                self.assertEqual(tomllib.load(fh)["governance"]["mode"], "lite")
        finally:
            if temp.exists():
                remove_tree(temp)

    def test_mode_specific_configuration_matches_effective_capabilities(self) -> None:
        lite = ProjectHarness(self, governance_mode="lite")
        standard = ProjectHarness(self, governance_mode="standard")
        try:
            with (lite.root / "PROJECT.toml").open("rb") as fh:
                lite_cfg = tomllib.load(fh)
            with (standard.root / "PROJECT.toml").open("rb") as fh:
                standard_cfg = tomllib.load(fh)
            self.assertFalse(lite_cfg["role_policy"]["parallel_code_execution_allowed"])
            self.assertFalse(lite_cfg["requirement_policy"]["release_baseline_required"])
            self.assertFalse(lite_cfg["automation"]["require_final_acceptance_before_closure"])
            self.assertEqual(lite_cfg["context"]["default_entry_mode"], "light")
            self.assertTrue(standard_cfg["role_policy"]["parallel_code_execution_allowed"])
            self.assertTrue(standard_cfg["requirement_policy"]["release_baseline_required"])
            self.assertTrue(standard_cfg["automation"]["require_final_acceptance_before_closure"])
            self.assertEqual(standard_cfg["context"]["default_entry_mode"], "standard")
        finally:
            lite.close()
            standard.close()

    def test_standard_template_bundle_hash_blocks_tampering(self) -> None:
        h = ProjectHarness(self, governance_mode="lite")
        try:
            bundle_path = h.root / ".ai/standard_mode_templates.json"
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            self.assertEqual(bundle["schema_version"], "1.9.0")
            self.assertEqual(set(bundle["files"]), set(bundle["file_sha256"]))
            self.assertRegex(bundle["content_sha256"], r"^[0-9a-f]{64}$")
            with (h.root / "PROJECT.toml").open("rb") as fh:
                cfg = tomllib.load(fh)
            self.assertEqual(
                cfg["governance"]["standard_mode_templates_sha256"],
                bundle["content_sha256"],
            )

            bundle["files"]["docs/ARCHITECTURE.md"] = (
                "# CORRUPTED BUT VALID\n\nThis is not an architecture document.\n"
            )
            write_json(bundle_path, bundle)
            health = json.loads(h.tool("health", "--json", expect=2).stdout)
            self.assertTrue(
                any("模板" in item and "哈希" in item for item in health["fail"]),
                health,
            )
            write_json(h.root / ".ai/runtime/governance_promotion.json", {
                "actor_role": "project_manager_agent",
                "owner_authorization": True,
                "owner_note": "Owner approved.",
                "reason": "The project grew.",
            })
            promoted = h.tool("ai-promote-standard", expect=1)
            self.assertIn("哈希", promoted.stdout + promoted.stderr)
            self.assertFalse((h.root / "docs/ARCHITECTURE.md").exists())
            with (h.root / "PROJECT.toml").open("rb") as fh:
                self.assertEqual(tomllib.load(fh)["governance"]["mode"], "lite")
        finally:
            h.close()

    def test_blocked_lite_batch_can_suspend_promote_audit_and_resume(self) -> None:
        h = ProjectHarness(self, governance_mode="lite")
        try:
            h.start_batch()
            write_json(
                h.root / ".ai/runtime/batch_result.json",
                h.result_payload(
                    "blocked",
                    [{
                        "name": "architecture discovery",
                        "status": "blocked",
                        "details": "Standard governance is required.",
                    }],
                    ["The project now requires a formal architecture baseline."],
                ),
            )
            h.tool("ai-finish", expect=1)
            write_json(h.root / ".ai/runtime/governance_suspension.json", {
                "actor_role": "project_manager_agent",
                "owner_authorization": True,
                "owner_note": "Owner approved suspending the blocked Lite batch.",
                "reason": "The batch discovered Standard-level architecture work.",
                "unfinished_work": ["Complete architecture design and resume P1-001."],
                "test_status": "Architecture discovery is blocked; no passing claim was made.",
                "resume_after_promotion": True,
            })
            suspended = h.tool("ai-suspend-for-promotion")
            self.assertIn("AI_BATCH_SUSPENDED_FOR_PROMOTION", suspended.stdout)
            self.assertFalse((h.root / ".ai/runtime/active_batch.json").exists())
            self.assertTrue((h.root / ".ai/runtime/suspended_batch_for_promotion.json").exists())

            write_json(h.root / ".ai/runtime/governance_promotion.json", {
                "actor_role": "project_manager_agent",
                "owner_authorization": True,
                "owner_note": "Owner approved Standard governance.",
                "reason": "The blocked batch requires Standard governance.",
            })
            promoted = h.tool("ai-promote-standard")
            self.assertIn("AI_GOVERNANCE_PROMOTED standard", promoted.stdout)
            state = json.loads(
                (h.root / ".ai/project_state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["standard_baseline"]["status"], "pending")
            self.assertEqual(state["standard_baseline"]["suspended_batch_id"], "P1-001")

            expected_labels = {
                "START_HERE.md": "治理模式：Standard 标准治理（`standard`）",
                "AGENTS.md": "治理模式：Standard 标准治理（`standard`）",
                "README.md": "治理模式：Standard 标准治理（`standard`）",
            }
            for rel, label in expected_labels.items():
                self.assertIn(label, (h.root / rel).read_text(encoding="utf-8"))
            context = json.loads(
                (h.root / ".ai/runtime/context.json").read_text(encoding="utf-8")
            )
            self.assertEqual(context["project_state"]["governance_mode"], "standard")
            self.assertEqual(context["priority"], "complete_standard_baseline_audit")
            self.assertIn(
                "当前治理模式：`standard`",
                (h.root / ".ai/runtime/HANDOFF_CURRENT.md").read_text(encoding="utf-8"),
            )
            memory = (h.root / "docs/PROJECT_MEMORY.md").read_text(encoding="utf-8")
            self.assertIn("完成 Standard 升级基线审计", memory)

            write_json(h.root / ".ai/runtime/batch_request.json", {
                "batch_id": "P1-002",
                "stage_id": "P1",
                "title": "Must wait for promotion audit",
                "goal": "This must not start yet.",
                "scope": ["new work"],
                "acceptance_criteria": ["not started"],
                "change_ids": [],
                "risk_level": "normal",
                "requires_user_authorization": False,
                "execution_mode": "single",
            })
            gated = h.tool("ai-start", expect=1)
            self.assertIn("Standard 基线审计", gated.stdout + gated.stderr)
            (h.root / ".ai/runtime/batch_request.json").unlink()

            namespace: dict = {}
            project_module = h.root / "tools/project.py"
            exec(
                compile(
                    project_module.read_text(encoding="utf-8"),
                    str(project_module),
                    "exec",
                ),
                namespace,
            )
            docs = [
                rel
                for rel in namespace["CORE_CURRENT_DOCS"]
                if (h.root / rel).exists()
            ]
            write_json(h.root / ".ai/runtime/audit_result.json", {
                "stage_id": "P1",
                "status": "passed",
                "documents_read": docs,
                "conflicts": [],
                "resolutions": [],
                "summary": "Standard architecture, plan, memory and current implementation agree.",
                "standard_baseline_completed": True,
                "standard_baseline_evidence": [
                    "Reviewed existing code and Git status.",
                    "Updated architecture, plan and project memory for current facts.",
                    "Reconciled current requirements and the suspended batch.",
                ],
                "manager_review": {
                    "status": "approved",
                    "reviewer": "project_manager_agent",
                    "note": "Standard promotion baseline approved.",
                },
            })
            audited = h.tool("ai-audit")
            self.assertIn("AI_STANDARD_BASELINE_READY", audited.stdout)
            self.assertFalse(
                (h.root / ".ai/runtime/suspended_batch_for_promotion.json").exists()
            )
            active = json.loads(
                (h.root / ".ai/runtime/active_batch.json").read_text(encoding="utf-8")
            )
            self.assertEqual(active["batch_id"], "P1-001")
            state = json.loads(
                (h.root / ".ai/project_state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["standard_baseline"]["status"], "passed")

            write_json(
                h.root / ".ai/runtime/batch_result.json",
                h.result_payload(
                    "pass",
                    [{"name": "post-promotion check", "status": "pass", "details": "ok"}],
                ),
            )
            h.tool("ai-finish", expect={0, 1})
            self.assertFalse((h.root / ".ai/runtime/active_batch.json").exists())
        finally:
            h.close()

    def test_governance_suspension_transaction_rolls_back_on_fault(self) -> None:
        h = ProjectHarness(self, governance_mode="lite")
        try:
            h.start_batch()
            write_json(
                h.root / ".ai/runtime/batch_result.json",
                h.result_payload(
                    "blocked",
                    [{"name": "scope", "status": "blocked", "details": "needs Standard"}],
                    ["Standard governance is required."],
                ),
            )
            h.tool("ai-finish", expect=1)
            active_path = h.root / ".ai/runtime/active_batch.json"
            state_path = h.root / ".ai/project_state.json"
            log_path = next((h.root / "docs/logs").glob("*.md"))
            protected = [active_path, state_path, log_path]
            before = {path: path.read_bytes() for path in protected}
            write_json(h.root / ".ai/runtime/governance_suspension.json", {
                "actor_role": "project_manager_agent",
                "owner_authorization": True,
                "owner_note": "Owner approved.",
                "reason": "The blocked work requires Standard.",
                "unfinished_work": ["Resume the blocked batch after audit."],
                "test_status": "Blocked; no pass was claimed.",
                "resume_after_promotion": True,
            })
            env = os.environ.copy()
            env["AI_STARTER_TEST_FAIL_GOVERNANCE_SUSPENSION_AFTER"] = "2"
            rejected = h.tool(
                "ai-suspend-for-promotion",
                expect=1,
                env=env,
            )
            self.assertIn("restored", (rejected.stdout + rejected.stderr).lower())
            self.assertEqual(before, {path: path.read_bytes() for path in protected})
            self.assertFalse(
                (h.root / ".ai/runtime/suspended_batch_for_promotion.json").exists()
            )
        finally:
            h.close()

    def test_lite_mode_blocks_parallel_and_formal_release_until_promotion(self) -> None:
        h = ProjectHarness(self, governance_mode="lite")
        try:
            write_json(h.root / ".ai/runtime/batch_request.json", {
                "batch_id": "P1-001",
                "stage_id": "P1",
                "title": "Parallel work",
                "goal": "Parallel work should require Standard mode.",
                "scope": ["component A", "component B"],
                "acceptance_criteria": ["integration passes"],
                "change_ids": [],
                "risk_level": "normal",
                "requires_user_authorization": False,
                "execution_mode": "parallel",
                "execution_threads": [
                    {
                        "thread_id": "worker-a",
                        "role": "code_executor",
                        "scope": ["component A"],
                        "allowed_paths": ["src/a"],
                        "prohibited_paths": [],
                    },
                    {
                        "thread_id": "worker-b",
                        "role": "code_executor",
                        "scope": ["component B"],
                        "allowed_paths": ["src/b"],
                        "prohibited_paths": [],
                    },
                ],
            })
            parallel = h.tool("ai-start", expect=1)
            self.assertIn("ai-promote-standard", parallel.stdout + parallel.stderr)
            self.assertFalse((h.root / ".ai/runtime/active_batch.json").exists())

            write_json(h.root / ".ai/runtime/batch_request.json", {
                "batch_id": "P2-001",
                "stage_id": "P2",
                "title": "Formal next stage",
                "goal": "A formal stage transition should require Standard.",
                "scope": ["next stage"],
                "acceptance_criteria": ["stage accepted"],
                "change_ids": [],
                "risk_level": "normal",
                "requires_user_authorization": False,
                "execution_mode": "single",
                "stage_transition": True,
            })
            transition = h.tool("ai-start", expect=1)
            self.assertIn("ai-promote-standard", transition.stdout + transition.stderr)
            self.assertFalse((h.root / ".ai/runtime/active_batch.json").exists())

            release = h.tool("ai-release-baseline", expect=1)
            self.assertIn("ai-promote-standard", release.stdout + release.stderr)
        finally:
            h.close()

    def test_lite_promotes_to_standard_without_losing_requirement_history(self) -> None:
        h = ProjectHarness(self, governance_mode="lite")
        try:
            h.create_complete_requirement("")
            head_before = h.commit("record lite requirement")
            registry_path = h.root / ".ai/requirement_registry.json"
            registry_before = registry_path.read_bytes()
            write_json(h.root / ".ai/runtime/governance_promotion.json", {
                "actor_role": "project_manager_agent",
                "owner_authorization": True,
                "owner_note": "The owner approved Standard governance.",
                "reason": "The project now has multiple stages and a formal delivery.",
            })
            promoted = h.tool("ai-promote-standard")
            self.assertIn("AI_GOVERNANCE_PROMOTED standard", promoted.stdout)
            with (h.root / "PROJECT.toml").open("rb") as fh:
                cfg = tomllib.load(fh)
            self.assertEqual(cfg["governance"]["mode"], "standard")
            self.assertTrue(all((h.root / rel).exists() for rel in cfg["documents"]["standard_required"]))
            self.assertEqual(registry_path.read_bytes(), registry_before)
            self.assertEqual(
                run(["git", "rev-parse", "HEAD"], h.root).stdout.strip(),
                head_before,
            )
            state = json.loads((h.root / ".ai/project_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["governance_mode"], "standard")
            self.assertEqual(state["governance_history"][-1]["from"], "lite")
            self.assertEqual(state["governance_history"][-1]["to"], "standard")
            health = json.loads(h.tool("health", "--json", expect={0, 1}).stdout)
            self.assertEqual(health["fail"], [])
            again = h.tool("ai-promote-standard", expect=1)
            self.assertIn("already uses standard governance", (again.stdout + again.stderr).lower())
        finally:
            h.close()

    def test_governance_promotion_transaction_rolls_back_on_fault(self) -> None:
        h = ProjectHarness(self, governance_mode="lite")
        try:
            with (h.root / "PROJECT.toml").open("rb") as fh:
                cfg = tomllib.load(fh)
            protected = [
                h.root / "PROJECT.toml",
                h.root / ".ai/project_state.json",
                next((h.root / "docs/logs").glob("*.md")),
                *[h.root / rel for rel in cfg["documents"]["standard_required"]],
            ]
            before = {path: path.read_bytes() if path.exists() else None for path in protected}
            write_json(h.root / ".ai/runtime/governance_promotion.json", {
                "actor_role": "project_manager_agent",
                "owner_authorization": True,
                "owner_note": "The owner approved Standard governance.",
                "reason": "The project grew.",
            })
            env = os.environ.copy()
            env["AI_STARTER_TEST_FAIL_GOVERNANCE_PROMOTION_AFTER"] = "3"
            failed = h.tool("ai-promote-standard", expect=1, env=env)
            self.assertIn("restored", (failed.stdout + failed.stderr).lower())
            after = {path: path.read_bytes() if path.exists() else None for path in protected}
            self.assertEqual(after, before)
            with (h.root / "PROJECT.toml").open("rb") as fh:
                self.assertEqual(tomllib.load(fh)["governance"]["mode"], "lite")
        finally:
            h.close()

    def test_lite_growth_boundaries_require_standard_owner_authorization(self) -> None:
        h = ProjectHarness(self, governance_mode="lite")
        try:
            write_json(h.root / ".ai/runtime/change_request.json", {
                "source": "development",
                "raw_feedback": "Split the application into multiple services.",
                "change_types": ["architecture_change"],
                "affected_implementation": ["src"],
                "requires_reacceptance": True,
            })
            architecture = h.tool("ai-register-change", expect=1)
            self.assertIn("ai-promote-standard", architecture.stdout + architecture.stderr)
            self.assertFalse((h.root / ".ai/runtime/pending_changes.json").exists())

            write_json(h.root / ".ai/runtime/governance_promotion.json", {
                "actor_role": "project_manager_agent",
                "owner_authorization": False,
                "owner_note": "No authorization was granted.",
                "reason": "The project grew.",
            })
            unauthorized = h.tool("ai-promote-standard", expect=1)
            self.assertIn("owner_authorization=true", unauthorized.stdout + unauthorized.stderr)

            h.start_batch()
            write_json(h.root / ".ai/runtime/governance_promotion.json", {
                "actor_role": "project_manager_agent",
                "owner_authorization": True,
                "owner_note": "Owner approved.",
                "reason": "The project grew.",
            })
            active = h.tool("ai-promote-standard", expect=1)
            self.assertIn("活动批次", active.stdout + active.stderr)
            with (h.root / "PROJECT.toml").open("rb") as fh:
                self.assertEqual(tomllib.load(fh)["governance"]["mode"], "lite")
        finally:
            h.close()

    def test_lite_requirement_revision_works_without_standard_memory_document(self) -> None:
        h = ProjectHarness(self, governance_mode="lite")
        try:
            h.create_complete_requirement("")
            h.commit("create lite requirement")
            write_json(h.root / ".ai/runtime/change_request.json", {
                "source": "development",
                "raw_feedback": "Change the personal helper behavior.",
                "change_types": ["requirement_change"],
                "affected_implementation": ["src/helper.py"],
                "requires_reacceptance": True,
            })
            captured = h.tool("ai-register-change")
            change_id = captured.stdout.strip().split()[1]
            write_json(h.root / ".ai/runtime/requirement_update.json", {
                "actor_role": "project_manager_agent",
                "action": "revise",
                "requirement_id": "R-001",
                "expected_current_version": "R-001.1",
                "change_id": change_id,
                "reason": "Owner changed the behavior.",
                "description": "The personal helper follows the revised behavior.",
            })
            revised = h.tool("ai-requirement")
            self.assertIn("R-001.2", revised.stdout)
            write_json(h.root / ".ai/runtime/decision.json", {
                "title": "Revise personal helper behavior",
                "current": "Use the revised behavior in R-001.2.",
                "reason": "The owner changed the requirement.",
                "impact": "Requirement, implementation and tests.",
            })
            h.tool("new-decision")
            ready = h.tool("ai-change-ready", change_id)
            self.assertIn("AI_CHANGE_DOCS_READY", ready.stdout)
            registry = json.loads(
                (h.root / ".ai/requirement_registry.json").read_text(encoding="utf-8")
            )
            requirement = registry["requirements"][0]
            self.assertEqual(requirement["current_version"], "R-001.2")
            self.assertEqual(
                [revision["version"] for revision in requirement["revisions"]],
                ["R-001.1", "R-001.2"],
            )
            self.assertFalse((h.root / "docs/PROJECT_MEMORY.md").exists())
        finally:
            h.close()

    def test_pass_requires_all_tests_passed_and_blocked_stays_open(self) -> None:
        h = ProjectHarness(self)
        try:
            h.start_batch()
            write_json(h.root / ".ai/runtime/batch_result.json", h.result_payload(
                "pass", [{"name": "not executed", "status": "not_run", "details": ""}]
            ))
            failed = h.tool("ai-finish", expect=1)
            self.assertIn("全部测试或检查必须为 pass", failed.stderr + failed.stdout)
            self.assertTrue((h.root / ".ai/runtime/active_batch.json").exists())

            write_json(h.root / ".ai/runtime/batch_result.json", h.result_payload(
                "blocked", [{"name": "dependency", "status": "blocked", "details": "offline"}], ["dependency offline"]
            ))
            blocked = h.tool("ai-finish", expect=1)
            self.assertIn("AI_BATCH_REMAINS_OPEN", blocked.stdout)
            active = json.loads((h.root / ".ai/runtime/active_batch.json").read_text(encoding="utf-8"))
            self.assertEqual(active["status"], "blocked")

            write_json(h.root / ".ai/runtime/batch_result.json", h.result_payload(
                "pass", [{"name": "dependency", "status": "pass", "details": "restored"}]
            ))
            h.tool("ai-finish", expect={0, 1})
            self.assertFalse((h.root / ".ai/runtime/active_batch.json").exists())
        finally:
            h.close()

    def test_requirement_optimistic_lock_and_real_change_link(self) -> None:
        h = ProjectHarness(self)
        try:
            h.create_complete_requirement()
            write_json(h.root / ".ai/runtime/requirement_update.json", {
                "actor_role": "project_manager_agent", "action": "link",
                "requirement_id": "R-001", "expected_current_version": "R-001.0",
                "test_refs": ["new-test"],
            })
            stale = h.tool("ai-requirement", expect=1)
            self.assertIn("需求版本冲突", stale.stderr + stale.stdout)

            write_json(h.root / ".ai/runtime/requirement_update.json", {
                "actor_role": "project_manager_agent", "action": "revise",
                "requirement_id": "R-001", "expected_current_version": "R-001.1",
                "change_id": "CHG-FAKE", "reason": "change", "description": "new semantics",
            })
            fake = h.tool("ai-requirement", expect=1)
            self.assertIn("变更不存在", fake.stderr + fake.stdout)

            write_json(h.root / ".ai/runtime/change_request.json", {
                "source": "manual_acceptance", "origin_batch_id": "P1-001",
                "raw_feedback": "Change core behavior", "change_types": ["requirement_change"],
                "affected_implementation": ["src/core.txt"], "requires_reacceptance": True,
            })
            captured = h.tool("ai-register-change")
            change_id = captured.stdout.strip().split()[1]
            write_json(h.root / ".ai/runtime/requirement_update.json", {
                "actor_role": "project_manager_agent", "action": "revise",
                "requirement_id": "R-001", "expected_current_version": "R-001.1",
                "change_id": change_id, "reason": "owner changed behavior",
                "description": "The core feature now follows the revised behavior.",
            })
            revised = h.tool("ai-requirement")
            self.assertIn("R-001.2", revised.stdout)
        finally:
            h.close()

    def test_waived_acceptance_requires_reason(self) -> None:
        h = ProjectHarness(self)
        try:
            write_json(h.root / ".ai/runtime/requirement_update.json", {
                "actor_role": "project_manager_agent", "action": "create",
                "title": "Waiver", "description": "Waiver test", "status": "active",
                "acceptance_criteria": [{"description": "criterion", "status": "waived", "method": "manual"}],
            })
            result = h.tool("ai-requirement", expect=1)
            self.assertIn("批准理由", result.stderr + result.stdout)
        finally:
            h.close()

    def test_immutable_baseline_and_git_head_lock(self) -> None:
        h = ProjectHarness(self)
        try:
            (h.root / "src").mkdir(); (h.root / "src/core.txt").write_text("v1\n", encoding="utf-8")
            h.create_complete_requirement()
            h.record_full_audit()
            h.commit("release ready")
            baseline1 = h.create_baseline()
            h.commit("record baseline metadata")
            write_json(h.root / ".ai/runtime/release_baseline.json", {
                "actor_role": "project_manager_agent", "release_version": "1.0.0",
                "release_name": "same", "scope_note": "duplicate",
            })
            rejected = h.tool("ai-release-baseline", expect=1)
            self.assertIn("不得覆盖", rejected.stderr + rejected.stdout)
            baseline2 = h.create_baseline(supersedes=baseline1)
            self.assertNotEqual(baseline1, baseline2)
            first = json.loads((h.root / ".ai/release_baselines" / f"{baseline1}.json").read_text(encoding="utf-8"))
            self.assertEqual(first["status"], "superseded")

            (h.root / "src/core.txt").write_text("v2\n", encoding="utf-8")
            h.commit("change after baseline")
            write_json(h.root / ".ai/runtime/delivery_request.json", {
                "actor_role": "project_manager_agent", "release_version": "1.0.0",
                "artifacts": [{"name": "source", "path": "src/core.txt"}],
            })
            invalid = h.tool("ai-generate-delivery", expect=1)
            self.assertIn("Git HEAD", invalid.stderr + invalid.stdout)
        finally:
            h.close()

    def test_customer_visible_nonblocking_requirement_still_needs_evidence(self) -> None:
        h = ProjectHarness(self)
        try:
            write_json(h.root / ".ai/runtime/requirement_update.json", {
                "actor_role": "project_manager_agent", "action": "create",
                "title": "Visible optional feature", "description": "Shown to customers",
                "status": "active", "priority": "could", "category": "functional",
                "release_target": "1.0.0", "customer_visible": True, "release_blocking": False,
                "acceptance_criteria": [{"description": "works", "method": "both", "status": "pending"}],
                "user_instructions": "Use the optional feature.", "user_instructions_verified": True,
            })
            h.tool("ai-requirement")
            h.record_full_audit(); h.commit("audit incomplete visible requirement")
            write_json(h.root / ".ai/runtime/release_baseline.json", {
                "actor_role": "project_manager_agent", "release_version": "1.0.0",
                "release_name": "1.0.0", "scope_note": "test",
            })
            result = h.tool("ai-release-baseline", expect=1)
            self.assertIn("追踪状态", result.stderr + result.stdout)
        finally:
            h.close()

    def test_artifact_hash_and_transactional_closure_and_terminal_reopen(self) -> None:
        h = ProjectHarness(self)
        try:
            (h.root / "src").mkdir(); (h.root / "src/core.txt").write_text("v1\n", encoding="utf-8")
            h.create_complete_requirement()
            h.record_full_audit()
            h.commit("release ready")
            baseline_id = h.create_baseline()
            # Real build artifacts are often produced after the source baseline and
            # are not committed. They must be frozen by artifact SHA-256 instead.
            (h.root / "dist").mkdir(); artifact = h.root / "dist/app.bin"; artifact.write_bytes(b"release-v1")
            write_json(h.root / ".ai/runtime/delivery_request.json", {
                "actor_role": "project_manager_agent", "release_version": "1.0.0",
                "customer_name": "Customer", "maintenance_note": "Standard maintenance.",
                "artifacts": [{"name": "Application", "path": "dist/app.bin", "version": "1.0.0", "status": "ready"}],
            })
            h.tool("ai-generate-delivery")
            h.tool("ai-delivery-verify", "--release", "1.0.0")
            artifact.write_bytes(b"tampered")
            tampered = h.tool("ai-delivery-verify", "--release", "1.0.0", expect=2)
            self.assertIn("交付物内容已变化", tampered.stdout + tampered.stderr)
            artifact.write_bytes(b"release-v1")
            h.tool("ai-delivery-verify", "--release", "1.0.0")

            write_json(h.root / ".ai/runtime/final_acceptance.json", {
                "recorder_role": "project_manager_agent", "release_version": "1.0.0",
                "owner_decision": "passed", "owner_note": "Accepted.",
            })
            h.tool("ai-final-acceptance")
            h.tool("ai-delivery-verify", "--release", "1.0.0")

            baseline_path = h.root / ".ai/release_baselines" / f"{baseline_id}.json"
            before = baseline_path.read_bytes()
            write_json(h.root / ".ai/runtime/project_close.json", {
                "actor_role": "project_manager_agent", "release_version": "1.0.0",
                "closure_note": "TODO invalid closure note",
            })
            failed = h.tool("ai-close-project", expect=1)
            self.assertIn("事务失败", failed.stderr + failed.stdout)
            self.assertEqual(before, baseline_path.read_bytes())
            state = json.loads((h.root / ".ai/project_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["project_status"], "active")

            write_json(h.root / ".ai/runtime/project_close.json", {
                "actor_role": "project_manager_agent", "release_version": "1.0.0",
                "closure_note": "All deliverables accepted and archived.",
            })
            h.tool("ai-close-project")
            state = json.loads((h.root / ".ai/project_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["project_status"], "closed")

            write_json(h.root / ".ai/runtime/batch_request.json", {
                "batch_id": "P2-001", "stage_id": "P2", "title": "forbidden",
                "goal": "forbidden", "scope": ["x"], "acceptance_criteria": ["x"],
            })
            closed = h.tool("ai-start", expect=1)
            self.assertIn("项目已结案", closed.stderr + closed.stdout)

            write_json(h.root / ".ai/runtime/project_reopen.json", {
                "actor_role": "project_manager_agent", "owner_authorization": True,
                "owner_note": "Owner approved a new maintenance cycle.",
                "reopen_reason": "Start the next maintenance cycle.",
                "new_stage": "P2", "closed_version": "1.0.0", "reopen_version": "1.1.0",
            })
            h.tool("ai-reopen-project")
            state = json.loads((h.root / ".ai/project_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["project_status"], "active")
        finally:
            h.close()


    def test_precommit_rejects_requirement_document_tampering(self) -> None:
        h = ProjectHarness(self)
        try:
            h.create_complete_requirement()
            h.commit("record requirement")
            requirement_doc = h.root / "docs/PRODUCT_REQUIREMENTS.md"
            text = requirement_doc.read_text(encoding="utf-8")
            self.assertIn("Core feature", text)
            requirement_doc.write_text(text.replace("Core feature", "Tampered feature", 1), encoding="utf-8", newline="\n")
            run(["git", "add", "docs/PRODUCT_REQUIREMENTS.md"], h.root)
            rejected = run(["git", "commit", "-m", "tamper generated requirement"], h.root, expect={1, 2})
            self.assertIn("需求登记表与生成文档不一致", rejected.stdout + rejected.stderr)
        finally:
            h.close()

    def test_release_key_collision_resistance(self) -> None:
        h = ProjectHarness(self)
        try:
            namespace: dict = {}
            project_module = h.root / "tools/project.py"
            exec(compile(project_module.read_text(encoding="utf-8"), str(project_module), "exec"), namespace)
            self.assertEqual(namespace["safe_release_name"]("1/0"), namespace["safe_release_name"]("1-0"))
            self.assertNotEqual(namespace["release_key"]("1/0"), namespace["release_key"]("1-0"))
            long_a = "1.0.0+" + ("a" * 300)
            long_b = "1.0.0+" + ("a" * 299) + "b"
            namespace["parse_release_version"](long_a)
            self.assertLessEqual(len(namespace["release_key"](long_a)), 160)
            self.assertNotEqual(namespace["release_key"](long_a), namespace["release_key"](long_b))
        finally:
            h.close()

    def test_hook_uses_recorded_interpreter(self) -> None:
        h = ProjectHarness(self)
        try:
            self.assertEqual(run(["git", "rev-list", "--count", "HEAD"], h.root).stdout.strip(), "1")
            hook = (h.root / ".githooks/pre-commit").read_text(encoding="utf-8")
            self.assertIn(".githooks/python-path", hook)
            self.assertLess(hook.index("python-path"), hook.index("command -v python"))
        finally:
            h.close()

    def test_parallel_integration_fail_stays_open(self) -> None:
        self._assert_parallel_integration_rejected(
            [{"name": "integration-api", "status": "fail", "details": "failed"}],
            "integration-api",
        )

    def test_parallel_integration_blocked_stays_open(self) -> None:
        self._assert_parallel_integration_rejected(
            [{"name": "integration-api", "status": "blocked", "details": "offline"}],
            "integration-api",
        )

    def test_parallel_integration_not_run_stays_open(self) -> None:
        self._assert_parallel_integration_rejected(
            [{"name": "integration-api", "status": "not_run", "details": "not executed"}],
            "integration-api",
        )

    def test_parallel_integration_unknown_stays_open(self) -> None:
        self._assert_parallel_integration_rejected(
            [{"name": "integration-api", "status": "unknown", "details": "invalid"}],
            "integration-api",
        )

    def test_parallel_integration_missing_stays_open(self) -> None:
        self._assert_parallel_integration_rejected([], "integration")

    def test_parallel_integration_wrong_role_stays_open(self) -> None:
        h = ProjectHarness(self)
        try:
            change_id = h.register_ready_bug_change()
            h.start_parallel_batch(change_id)
            payload = h.result_payload("pass", [{"name": "unit", "status": "pass", "details": "ok"}])
            payload["change_ids"] = [change_id]
            payload["integration_review"] = {
                "status": "approved",
                "reviewer_role": "project_manager_agent",
                "note": "wrong role for an independent integration review",
                "tests": [{"name": "integration-api", "status": "pass", "details": "ok"}],
            }
            write_json(h.root / ".ai/runtime/batch_result.json", payload)
            wrong_role = h.tool("ai-finish", expect=1)
            self.assertIn("integration_reviewer", wrong_role.stdout + wrong_role.stderr)
            self.assertTrue((h.root / ".ai/runtime/active_batch.json").exists())
        finally:
            h.close()

    def test_parallel_integration_all_pass_closes(self) -> None:
        h = ProjectHarness(self)
        try:
            change_id = h.register_ready_bug_change()
            h.start_parallel_batch(change_id)
            payload = h.result_payload("pass", [{"name": "unit", "status": "pass", "details": "ok"}])
            payload["title"] = "Parallel regression batch"
            payload["change_ids"] = [change_id]
            payload["integration_review"] = {
                "status": "approved",
                "reviewer_role": "integration_reviewer",
                "note": "all integration checks passed",
                "tests": [
                    {"name": "integration-api", "status": "pass", "details": "ok"},
                    {"name": "integration-ui", "status": "pass", "details": "ok"},
                ],
            }
            write_json(h.root / ".ai/runtime/batch_result.json", payload)
            h.tool("ai-finish", expect={0, 1})
            self.assertFalse((h.root / ".ai/runtime/active_batch.json").exists())
            self.assertFalse((h.root / ".ai/runtime/pending_changes.json").exists())
            state = json.loads((h.root / ".ai/project_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["last_closed_batch"]["status"], "pass")
        finally:
            h.close()

    def test_revision_history_preserves_complete_semantics(self) -> None:
        h = ProjectHarness(self)
        try:
            write_json(h.root / ".ai/runtime/requirement_update.json", {
                "actor_role": "project_manager_agent",
                "action": "create",
                "title": "Historical behavior",
                "description": "Old description",
                "rationale": "Old rationale",
                "status": "active",
                "priority": "must",
                "category": "functional",
                "release_target": "1.0.0",
                "customer_visible": True,
                "release_blocking": True,
                "acceptance_criteria": [{
                    "description": "Old criterion",
                    "method": "manual",
                    "status": "pending",
                    "evidence": "",
                    "note": "Old criterion note",
                }],
                "user_instructions": "Old guide",
                "user_instructions_verified": False,
                "help_notes": ["Old help"],
                "known_limitations": ["Old limit"],
                "notes": ["Old requirement note"],
            })
            h.tool("ai-requirement")
            registry_path = h.root / ".ai/requirement_registry.json"
            created = json.loads(registry_path.read_text(encoding="utf-8"))["requirements"][0]
            criterion_id = created["acceptance_criteria"][0]["id"]

            write_json(h.root / ".ai/runtime/change_request.json", {
                "source": "manual_acceptance",
                "origin_batch_id": "P1-001",
                "raw_feedback": "Change all customer-visible requirement semantics",
                "change_types": ["requirement_change"],
                "affected_implementation": ["src/core.txt"],
                "requires_reacceptance": True,
            })
            change_id = h.tool("ai-register-change").stdout.strip().split()[1]
            write_json(h.root / ".ai/runtime/requirement_update.json", {
                "actor_role": "project_manager_agent",
                "action": "revise",
                "requirement_id": "R-001",
                "expected_current_version": "R-001.1",
                "change_id": change_id,
                "reason": "Owner approved revised behavior",
                "description": "New description",
                "rationale": "New rationale",
                "acceptance_criteria": [{
                    "id": criterion_id,
                    "description": "New criterion",
                    "method": "both",
                    "status": "pending",
                    "evidence": "",
                    "note": "New criterion note",
                }],
                "user_instructions": "New guide",
                "user_instructions_verified": True,
                "help_notes": ["New help"],
                "known_limitations": ["New limit"],
                "notes": ["New requirement note"],
            })
            h.tool("ai-requirement")

            requirement = json.loads(registry_path.read_text(encoding="utf-8"))["requirements"][0]
            old, new = requirement["revisions"]
            self.assertEqual(old["description"], "Old description")
            self.assertEqual(old["acceptance_criteria"][0]["description"], "Old criterion")
            self.assertEqual(old["acceptance_criteria"][0]["method"], "manual")
            self.assertEqual(old["user_instructions"], "Old guide")
            self.assertFalse(old["user_instructions_verified"])
            self.assertEqual(old["help_notes"], ["Old help"])
            self.assertEqual(old["known_limitations"], ["Old limit"])
            self.assertEqual(old["notes"], ["Old requirement note"])
            self.assertEqual(new["acceptance_criteria"][0]["description"], "New criterion")
            self.assertEqual(new["user_instructions"], "New guide")
            changelog = (h.root / "docs/REQUIREMENT_CHANGELOG.md").read_text(encoding="utf-8")
            for historical_value in [
                "Old criterion", "Old guide", "Old help", "Old limit", "Old requirement note",
                "New criterion", "New guide", "New help", "New limit", "New requirement note",
            ]:
                self.assertIn(historical_value, changelog)

            requirement["revisions"][0]["acceptance_criteria"][0].pop("method")
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["requirements"][0] = requirement
            write_json(registry_path, registry)
            health = h.tool("health", "--json", expect=2)
            self.assertTrue(
                any("历史验收条件缺少字段" in item for item in json.loads(health.stdout)["fail"])
            )
        finally:
            h.close()

    def test_release_target_create_and_revise_require_semver_atomically(self) -> None:
        h = ProjectHarness(self)
        try:
            protected = [
                h.root / ".ai/requirement_registry.json",
                h.root / "docs/PRODUCT_REQUIREMENTS.md",
                h.root / "docs/ACCEPTANCE_CRITERIA.md",
                h.root / "docs/REQUIREMENT_CHANGELOG.md",
                h.root / "docs/REQUIREMENT_TRACEABILITY_MATRIX.md",
            ]
            for invalid_target in ["1.0", "v1.0.0", "1.0.O", "1.1٢.3"]:
                with self.subTest(target=invalid_target):
                    before = {path: path.read_bytes() for path in protected}
                    write_json(h.root / ".ai/runtime/requirement_update.json", {
                        "actor_role": "project_manager_agent",
                        "action": "create",
                        "title": "Invalid target",
                        "description": "Must be rejected before registry mutation.",
                        "status": "active",
                        "release_target": invalid_target,
                    })
                    rejected = h.tool("ai-requirement", expect=1)
                    self.assertIn("SemVer", rejected.stdout + rejected.stderr)
                    self.assertEqual(before, {path: path.read_bytes() for path in protected})

            h.create_complete_requirement("1.0.0-rc.1")
            registry_path = h.root / ".ai/requirement_registry.json"
            requirement = json.loads(registry_path.read_text(encoding="utf-8"))["requirements"][0]
            write_json(h.root / ".ai/runtime/change_request.json", {
                "source": "manual_acceptance",
                "origin_batch_id": "P1-001",
                "raw_feedback": "Move the requirement to another release",
                "change_types": ["requirement_change"],
                "affected_implementation": ["src/core.txt"],
                "requires_reacceptance": True,
            })
            change_id = h.tool("ai-register-change").stdout.strip().split()[1]
            before = {path: path.read_bytes() for path in protected}
            write_json(h.root / ".ai/runtime/requirement_update.json", {
                "actor_role": "project_manager_agent",
                "action": "revise",
                "requirement_id": requirement["requirement_id"],
                "expected_current_version": requirement["current_version"],
                "change_id": change_id,
                "reason": "Move target",
                "release_target": "1.0",
            })
            rejected = h.tool("ai-requirement", expect=1)
            self.assertIn("SemVer", rejected.stdout + rejected.stderr)
            self.assertEqual(before, {path: path.read_bytes() for path in protected})
        finally:
            h.close()

    def test_health_rejects_tampered_invalid_release_target(self) -> None:
        h = ProjectHarness(self)
        try:
            h.create_complete_requirement("1.0.0")
            registry_path = h.root / ".ai/requirement_registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["requirements"][0]["release_target"] = "1.0"
            write_json(registry_path, registry)
            health = h.tool("health", "--json", expect=2)
            result = json.loads(health.stdout)
            self.assertTrue(any("SemVer" in item and "R-001.1" in item for item in result["fail"]))
        finally:
            h.close()

    def test_registry_rejects_semantic_drift_from_latest_revision(self) -> None:
        h = ProjectHarness(self)
        try:
            h.create_complete_requirement("1.0.0")
            registry_path = h.root / ".ai/requirement_registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["requirements"][0]["release_target"] = "2.0.0"
            registry["requirements"][0]["acceptance_criteria"][0]["description"] = "Tampered semantics"
            write_json(registry_path, registry)
            write_json(h.root / ".ai/runtime/requirement_update.json", {
                "actor_role": "project_manager_agent",
                "action": "sync",
            })
            rejected = h.tool("ai-requirement", expect=1)
            self.assertIn("latest revision snapshot", (rejected.stdout + rejected.stderr).lower())
        finally:
            h.close()

    def test_overdue_release_target_blocks_baseline(self) -> None:
        h = ProjectHarness(self)
        try:
            (h.root / "src").mkdir()
            (h.root / "src/core.txt").write_text("v1\n", encoding="utf-8")
            h.create_complete_requirement("1.0.0")
            h.create_complete_requirement("0.9.0")
            h.record_full_audit()
            h.commit("release scope ready")
            write_json(h.root / ".ai/runtime/release_baseline.json", {
                "actor_role": "project_manager_agent",
                "release_version": "1.0.0",
                "release_name": "1.0.0",
                "scope_note": "Overdue target must not disappear.",
            })
            rejected = h.tool("ai-release-baseline", expect=1)
            self.assertIn("overdue", (rejected.stdout + rejected.stderr).lower())
        finally:
            h.close()

    def test_future_release_target_is_excluded_but_recorded_in_scope(self) -> None:
        h = ProjectHarness(self)
        try:
            (h.root / "src").mkdir()
            (h.root / "src/core.txt").write_text("v1\n", encoding="utf-8")
            h.create_complete_requirement("1.0.0")
            h.create_complete_requirement("2.0.0")
            h.record_full_audit()
            h.commit("release scope ready")
            baseline_id = h.create_baseline("1.0.0")
            baseline = json.loads(
                (h.root / ".ai/release_baselines" / f"{baseline_id}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(baseline["requirement_versions"], ["R-001.1"])
            self.assertEqual(baseline["requirement_scope"]["future"], ["R-002.1"])
            self.assertEqual(baseline["requirement_scope"]["included"], ["R-001.1"])
            self.assertEqual(baseline["requirement_scope"]["overdue"], [])
        finally:
            h.close()

    def test_closed_target_is_historical_only_if_baseline_froze_that_requirement_version(self) -> None:
        h = ProjectHarness(self)
        try:
            h.close_release("1.0.0", "P1")
            write_json(h.root / ".ai/runtime/project_reopen.json", {
                "actor_role": "project_manager_agent",
                "owner_authorization": True,
                "owner_note": "Owner approved release 1.1.0 work.",
                "reopen_reason": "Start the next maintenance release.",
                "new_stage": "P2",
                "closed_version": "1.0.0",
                "reopen_version": "1.1.0",
            })
            h.tool("ai-reopen-project")
            h.create_complete_requirement("1.1.0")
            h.create_complete_requirement("1.1.0")
            registry_path = h.root / ".ai/requirement_registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["requirements"][1]["release_target"] = "1.0.0"
            registry["requirements"][1]["revisions"][-1]["release_target"] = "1.0.0"
            write_json(registry_path, registry)
            write_json(h.root / ".ai/runtime/requirement_update.json", {
                "actor_role": "project_manager_agent",
                "action": "sync",
            })
            h.tool("ai-requirement")
            h.record_full_audit("P2")
            h.commit("new release scope with an invalid old-target requirement")
            write_json(h.root / ".ai/runtime/release_baseline.json", {
                "actor_role": "project_manager_agent",
                "release_version": "1.1.0",
                "release_name": "1.1.0",
                "scope_note": "A new requirement may not hide behind an old closed release.",
            })
            rejected = h.tool("ai-release-baseline", expect=1)
            output = (rejected.stdout + rejected.stderr).lower()
            self.assertIn("r-002.1", output)
            self.assertIn("overdue", output)
            self.assertEqual(len(list((h.root / ".ai/release_baselines").glob("RB-*.json"))), 1)
        finally:
            h.close()

    def test_requirement_create_and_revise_cannot_target_a_closed_release(self) -> None:
        h = ProjectHarness(self)
        try:
            h.close_release("1.0.0", "P1")
            write_json(h.root / ".ai/runtime/project_reopen.json", {
                "actor_role": "project_manager_agent",
                "owner_authorization": True,
                "owner_note": "Owner approved release 1.1.0 work.",
                "reopen_reason": "Start the next maintenance release.",
                "new_stage": "P2",
                "closed_version": "1.0.0",
                "reopen_version": "1.1.0",
            })
            h.tool("ai-reopen-project")
            protected = [
                h.root / ".ai/requirement_registry.json",
                h.root / "docs/PRODUCT_REQUIREMENTS.md",
                h.root / "docs/ACCEPTANCE_CRITERIA.md",
                h.root / "docs/REQUIREMENT_CHANGELOG.md",
                h.root / "docs/REQUIREMENT_TRACEABILITY_MATRIX.md",
            ]
            before = {path: path.read_bytes() for path in protected}
            write_json(h.root / ".ai/runtime/requirement_update.json", {
                "actor_role": "project_manager_agent",
                "action": "create",
                "title": "Forbidden historical requirement",
                "description": "Must not target a closed release.",
                "status": "active",
                "release_target": "1.0.0",
            })
            rejected_create = h.tool("ai-requirement", expect=1)
            self.assertIn("closed", (rejected_create.stdout + rejected_create.stderr).lower())
            self.assertEqual(before, {path: path.read_bytes() for path in protected})

            write_json(h.root / ".ai/runtime/change_request.json", {
                "source": "manual_acceptance",
                "origin_batch_id": "P2-001",
                "raw_feedback": "Revise the old requirement for the new release",
                "change_types": ["requirement_change"],
                "affected_implementation": ["src/core.txt"],
                "requires_reacceptance": True,
            })
            change_id = h.tool("ai-register-change").stdout.strip().split()[1]
            write_json(h.root / ".ai/runtime/requirement_update.json", {
                "actor_role": "project_manager_agent",
                "action": "revise",
                "requirement_id": "R-001",
                "expected_current_version": "R-001.1",
                "change_id": change_id,
                "reason": "New maintenance behavior",
                "description": "Changed behavior but still points to the closed release.",
            })
            rejected_revise = h.tool("ai-requirement", expect=1)
            self.assertIn("closed", (rejected_revise.stdout + rejected_revise.stderr).lower())
            self.assertEqual(before, {path: path.read_bytes() for path in protected})

            write_json(h.root / ".ai/runtime/requirement_update.json", {
                "actor_role": "project_manager_agent",
                "action": "revise",
                "requirement_id": "R-001",
                "expected_current_version": "R-001.1",
                "change_id": change_id,
                "reason": "New maintenance behavior",
                "description": "Changed behavior for the new maintenance release.",
                "release_target": "1.1.0",
            })
            revised = h.tool("ai-requirement")
            self.assertIn("R-001.2", revised.stdout)
        finally:
            h.close()

    def test_cross_platform_package_uses_posix_paths_and_extracts_cleanly(self) -> None:
        temp = make_temp_dir("ai-starter-v181-package-")
        try:
            run([
                PYTHON,
                str(ROOT / "build_package.py"),
                "--source",
                str(ROOT),
                "--output-dir",
                str(temp),
            ])
            package_name = "AI_Solo_Developer_Project_Starter_V" + (ROOT / "VERSION").read_text(encoding="utf-8").strip()
            archive = temp / f"{package_name}.zip"
            checksum_path = temp / f"{package_name}_SHA256.txt"
            self.assertTrue(archive.exists())
            with zipfile.ZipFile(archive) as package:
                names = package.namelist()
                self.assertTrue(names)
                self.assertTrue(all("\\" not in name for name in names))
                self.assertTrue(all(name.startswith(package_name + "/") for name in names))
                self.assertFalse(any("__pycache__" in name or name.endswith((".pyc", ".pyo")) for name in names))
                self.assertIsNone(package.testzip())
                extract_root = temp / "extracted"
                package.extractall(extract_root)
            extracted = extract_root / package_name
            expected = {
                path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in ROOT.rglob("*")
                if path.is_file()
                and not any(part in {".git", ".test-runtime", "__pycache__"} for part in path.parts)
                and path.suffix not in {".pyc", ".pyo"}
            }
            actual = {
                path.relative_to(extracted).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in extracted.rglob("*")
                if path.is_file()
            }
            self.assertEqual(expected, actual)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertEqual(checksum_path.read_text(encoding="utf-8").strip(), f"{digest}  {archive.name}")
        finally:
            if temp.exists():
                remove_tree(temp)

    def test_package_rejects_outside_links_and_excludes_tool_caches(self) -> None:
        temp = make_temp_dir("ai-starter-v181-package-boundary-")
        link: Path | None = None
        try:
            source = temp / "source"
            source.mkdir()
            (source / "VERSION").write_text("1.9.0\n", encoding="utf-8", newline="\n")
            (source / "payload.txt").write_text("inside\n", encoding="utf-8", newline="\n")
            cache = source / ".pytest_cache"
            cache.mkdir()
            (cache / "cache.txt").write_text("exclude me\n", encoding="utf-8", newline="\n")
            safe_output = temp / "safe-output"
            run([
                PYTHON, str(ROOT / "build_package.py"),
                "--source", str(source), "--output-dir", str(safe_output),
            ])
            with zipfile.ZipFile(safe_output / "AI_Solo_Developer_Project_Starter_V1.9.0.zip") as package:
                self.assertFalse(any(".pytest_cache" in name for name in package.namelist()))

            outside = temp / "outside"
            outside.mkdir()
            (outside / "secret.txt").write_text("outside\n", encoding="utf-8", newline="\n")
            link = source / "escape"
            if os.name == "nt":
                run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)])
            else:
                link.symlink_to(outside, target_is_directory=True)
            rejected = run([
                PYTHON, str(ROOT / "build_package.py"),
                "--source", str(source), "--output-dir", str(temp / "unsafe-output"),
            ], expect=1)
            self.assertIn("outside", (rejected.stdout + rejected.stderr).lower())
            self.assertFalse((temp / "unsafe-output/AI_Solo_Developer_Project_Starter_V1.9.0.zip").exists())
        finally:
            if link and link.exists():
                if os.name == "nt":
                    link.rmdir()
                else:
                    link.unlink()
            if temp.exists():
                remove_tree(temp)

    def test_package_zip_and_checksum_publish_as_one_transaction(self) -> None:
        temp = make_temp_dir("ai-starter-v181-package-transaction-")
        try:
            source = temp / "source"
            source.mkdir()
            (source / "VERSION").write_text("1.9.0\n", encoding="utf-8", newline="\n")
            (source / "payload.txt").write_text("inside\n", encoding="utf-8", newline="\n")
            output = temp / "output"
            env = os.environ.copy()
            env["AI_STARTER_TEST_FAIL_PACKAGE_TRANSACTION_AFTER"] = "1"
            rejected = run([
                PYTHON, str(ROOT / "build_package.py"),
                "--source", str(source), "--output-dir", str(output),
            ], expect=1, env=env)
            self.assertIn("transaction", (rejected.stdout + rejected.stderr).lower())
            self.assertFalse((output / "AI_Solo_Developer_Project_Starter_V1.9.0.zip").exists())
            self.assertFalse((output / "AI_Solo_Developer_Project_Starter_V1.9.0_SHA256.txt").exists())
        finally:
            if temp.exists():
                remove_tree(temp)

    def test_create_project_cmd_preserves_initializer_exit_code(self) -> None:
        if os.name != "nt":
            return
        temp = make_temp_dir("ai-starter-v181-create-cmd-")
        try:
            shutil.copy2(ROOT / "CREATE_PROJECT.cmd", temp / "CREATE_PROJECT.cmd")
            marker = temp / "runs.txt"
            (temp / "starter.py").write_text(
                "import os\n"
                "from pathlib import Path\n"
                "path = Path(os.environ['AI_STARTER_CREATE_MARKER'])\n"
                "path.write_text((path.read_text() if path.exists() else '') + 'run\\n')\n"
                "raise SystemExit(7)\n",
                encoding="utf-8",
                newline="\n",
            )
            env = os.environ.copy()
            env["AI_STARTER_CREATE_MARKER"] = str(marker)
            result = run(
                ["cmd.exe", "/d", "/c", str(temp / "CREATE_PROJECT.cmd")],
                cwd=ROOT.parent,
                expect=7,
                env=env,
                input_text="\n",
            )
            self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["run"])
            self.assertEqual(result.returncode, 7)
        finally:
            if temp.exists():
                remove_tree(temp)

    def test_version_labels_and_hook_are_v181(self) -> None:
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "1.9.2")
        hook = (ROOT / "scaffold/.githooks/pre-commit").read_text(encoding="utf-8")
        self.assertIn("V1.9.0 强制文档写回提交前检查", hook)
        self.assertIn("无法执行 V1.9.0 文档写回检查", hook)

    def test_link_whitelist_allows_only_trace_evidence_without_revision(self) -> None:
        h = ProjectHarness(self)
        try:
            h.create_complete_requirement()
            registry_path = h.root / ".ai/requirement_registry.json"
            before = json.loads(registry_path.read_text(encoding="utf-8"))["requirements"][0]
            version = before["current_version"]
            criterion = before["acceptance_criteria"][0]
            write_json(h.root / ".ai/runtime/requirement_update.json", {
                "actor_role": "project_manager_agent",
                "action": "link",
                "requirement_id": before["requirement_id"],
                "expected_current_version": version,
                "implementation_refs": ["src/core.txt", "src/adapter.txt"],
                "test_refs": ["tests/core-feature", "reports/core-feature.xml"],
                "acceptance_criteria": [{
                    "id": criterion["id"],
                    "status": "pass",
                    "evidence": "reports/core-feature.xml",
                    "note": "latest test evidence",
                }],
            })
            h.tool("ai-requirement")
            after = json.loads(registry_path.read_text(encoding="utf-8"))["requirements"][0]
            self.assertEqual(after["current_version"], version)
            self.assertIn("src/adapter.txt", after["implementation_refs"])
            self.assertIn("reports/core-feature.xml", after["test_refs"])
            self.assertEqual(after["acceptance_criteria"][0]["description"], criterion["description"])
            self.assertEqual(after["acceptance_criteria"][0]["method"], criterion["method"])
            self.assertEqual(after["acceptance_criteria"][0]["evidence"], "reports/core-feature.xml")
        finally:
            h.close()

    def test_link_whitelist_rejects_semantic_fields_without_partial_writes(self) -> None:
        h = ProjectHarness(self)
        try:
            h.create_complete_requirement()
            registry_path = h.root / ".ai/requirement_registry.json"
            requirement = json.loads(registry_path.read_text(encoding="utf-8"))["requirements"][0]
            criterion_id = requirement["acceptance_criteria"][0]["id"]
            protected = [
                registry_path,
                h.root / "docs/PRODUCT_REQUIREMENTS.md",
                h.root / "docs/ACCEPTANCE_CRITERIA.md",
                h.root / "docs/REQUIREMENT_CHANGELOG.md",
                h.root / "docs/REQUIREMENT_TRACEABILITY_MATRIX.md",
            ]
            forbidden_payloads = [
                {"title": "Silently ignored semantic title"},
                {"acceptance_criteria": [{"id": criterion_id, "description": "Weaker rule"}]},
                {"acceptance_criteria": [{"id": criterion_id, "method": "automatic"}]},
                {"release_target": "9.9.9"},
                {"user_instructions": "Different customer behavior"},
                {"known_limitations": ["A newly declared product limitation"]},
                {
                    "manual_acceptance": {
                        "status": "passed",
                        "date": "2026-07-30",
                        "note": "Owner evidence",
                        "user_instructions": "Nested semantic bypass",
                    }
                },
            ]
            for fields in forbidden_payloads:
                with self.subTest(fields=sorted(fields)):
                    before = {path: path.read_bytes() for path in protected}
                    write_json(h.root / ".ai/runtime/requirement_update.json", {
                        "actor_role": "project_manager_agent",
                        "action": "link",
                        "requirement_id": requirement["requirement_id"],
                        "expected_current_version": requirement["current_version"],
                        **fields,
                    })
                    rejected = h.tool("ai-requirement", expect=1)
                    self.assertIn("revise", (rejected.stdout + rejected.stderr).lower())
                    self.assertEqual(before, {path: path.read_bytes() for path in protected})
        finally:
            h.close()

    def test_closed_release_version_is_frozen_after_explicit_reopen(self) -> None:
        h = ProjectHarness(self)
        try:
            baseline_id, _ = h.close_release("1.0.0", "P1")
            baseline_path = h.root / ".ai/release_baselines" / f"{baseline_id}.json"
            frozen_hash = baseline_path.read_bytes()
            for invalid_version in ["1.0.0", "0.9.9"]:
                write_json(h.root / ".ai/runtime/project_reopen.json", {
                    "actor_role": "project_manager_agent",
                    "owner_authorization": True,
                    "owner_note": "Owner approved maintenance.",
                    "reopen_reason": "Start a new delivery cycle.",
                    "new_stage": "P2",
                    "closed_version": "1.0.0",
                    "reopen_version": invalid_version,
                })
                rejected = h.tool("ai-reopen-project", expect=1)
                self.assertIn("higher", (rejected.stdout + rejected.stderr).lower())
                state = json.loads((h.root / ".ai/project_state.json").read_text(encoding="utf-8"))
                self.assertEqual(state["project_status"], "closed")

            write_json(h.root / ".ai/runtime/project_reopen.json", {
                "actor_role": "project_manager_agent",
                "owner_authorization": True,
                "owner_note": "Owner approved release 1.1.0 work.",
                "reopen_reason": "Start the next maintenance release.",
                "new_stage": "P2",
                "closed_version": "1.0.0",
                "reopen_version": "1.1.0",
            })
            h.tool("ai-reopen-project")

            for supersedes in [None, baseline_id]:
                request = {
                    "actor_role": "project_manager_agent",
                    "release_version": "1.0.0",
                    "release_name": "forbidden",
                    "scope_note": "must remain frozen",
                }
                if supersedes:
                    request["supersedes_baseline_id"] = supersedes
                write_json(h.root / ".ai/runtime/release_baseline.json", request)
                rejected = h.tool("ai-release-baseline", expect=1)
                self.assertIn("closed", (rejected.stdout + rejected.stderr).lower())
                self.assertEqual(frozen_hash, baseline_path.read_bytes())
            self.assertEqual(len(list((h.root / ".ai/release_baselines").glob("RB-*.json"))), 1)
        finally:
            h.close()

    def test_reopened_release_can_publish_replace_active_then_freeze_on_close(self) -> None:
        h = ProjectHarness(self)
        try:
            closed_id, _ = h.close_release("1.0.0", "P1")
            write_json(h.root / ".ai/runtime/project_reopen.json", {
                "actor_role": "project_manager_agent",
                "owner_authorization": True,
                "owner_note": "Owner approved release 1.1.0 work.",
                "reopen_reason": "Start the next maintenance release.",
                "new_stage": "P2",
                "closed_version": "1.0.0",
                "reopen_version": "1.1.0",
            })
            h.tool("ai-reopen-project")
            h.create_complete_requirement("1.1.0")
            h.record_full_audit("P2")
            h.commit("1.1.0 release ready")
            write_json(h.root / ".ai/runtime/release_baseline.json", {
                "actor_role": "project_manager_agent",
                "release_version": "1.1.0",
                "release_name": "invalid cross-version replacement",
                "scope_note": "must not reference a closed release",
                "supersedes_baseline_id": closed_id,
            })
            cross_version = h.tool("ai-release-baseline", expect=1)
            self.assertIn("closed", (cross_version.stdout + cross_version.stderr).lower())
            baseline1 = h.create_baseline("1.1.0")
            baseline1_record = json.loads(
                (h.root / ".ai/release_baselines" / f"{baseline1}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(baseline1_record["requirement_scope"]["historical_closed"], ["R-001.1"])
            self.assertEqual(baseline1_record["requirement_scope"]["overdue"], [])
            h.commit("record active 1.1.0 baseline")
            baseline2 = h.create_baseline("1.1.0", supersedes=baseline1)
            first = json.loads((h.root / ".ai/release_baselines" / f"{baseline1}.json").read_text(encoding="utf-8"))
            self.assertEqual(first["status"], "superseded")
            h.deliver_and_close_release("1.1.0")

            write_json(h.root / ".ai/runtime/project_reopen.json", {
                "actor_role": "project_manager_agent",
                "owner_authorization": True,
                "owner_note": "Owner approved release 1.2.0 work.",
                "reopen_reason": "Start another maintenance release.",
                "new_stage": "P3",
                "closed_version": "1.1.0",
                "reopen_version": "1.2.0",
            })
            h.tool("ai-reopen-project")
            write_json(h.root / ".ai/runtime/release_baseline.json", {
                "actor_role": "project_manager_agent",
                "release_version": "1.1.0",
                "release_name": "forbidden",
                "scope_note": "closed release",
                "supersedes_baseline_id": baseline2,
            })
            rejected = h.tool("ai-release-baseline", expect=1)
            self.assertIn("closed", (rejected.stdout + rejected.stderr).lower())
        finally:
            h.close()

    def test_release_baseline_replacement_transaction_rolls_back_on_fault(self) -> None:
        h = ProjectHarness(self)
        try:
            (h.root / "src").mkdir()
            (h.root / "src/core.txt").write_text("v1\n", encoding="utf-8")
            h.create_complete_requirement()
            h.record_full_audit()
            h.commit("release ready")
            baseline1 = h.create_baseline()
            h.commit("record first baseline")
            tracked = [
                h.root / ".ai/release_baselines/index.json",
                h.root / ".ai/project_state.json",
                next((h.root / "docs/logs").glob("*.md")),
                h.root / ".ai/release_baselines" / f"{baseline1}.json",
            ]
            before = {path: path.read_bytes() for path in tracked}
            before_files = sorted(path.name for path in (h.root / ".ai/release_baselines").glob("*.json"))
            write_json(h.root / ".ai/runtime/release_baseline.json", {
                "actor_role": "project_manager_agent",
                "release_version": "1.0.0",
                "release_name": "fault injection",
                "scope_note": "transaction rollback",
                "supersedes_baseline_id": baseline1,
            })
            env = os.environ.copy()
            env["AI_STARTER_TEST_FAIL_BASELINE_TRANSACTION_AFTER"] = "2"
            failed = h.tool("ai-release-baseline", expect=1, env=env)
            self.assertIn("transaction", (failed.stdout + failed.stderr).lower())
            self.assertEqual(before, {path: path.read_bytes() for path in tracked})
            self.assertEqual(before_files, sorted(path.name for path in (h.root / ".ai/release_baselines").glob("*.json")))
        finally:
            h.close()

    def test_requirement_registry_and_generated_documents_roll_back_together(self) -> None:
        h = ProjectHarness(self)
        try:
            h.create_complete_requirement()
            registry_path = h.root / ".ai/requirement_registry.json"
            requirement = json.loads(registry_path.read_text(encoding="utf-8"))["requirements"][0]
            protected = [
                registry_path,
                h.root / "docs/PRODUCT_REQUIREMENTS.md",
                h.root / "docs/ACCEPTANCE_CRITERIA.md",
                h.root / "docs/REQUIREMENT_CHANGELOG.md",
                h.root / "docs/REQUIREMENT_TRACEABILITY_MATRIX.md",
            ]
            before = {path: path.read_bytes() for path in protected}
            write_json(h.root / ".ai/runtime/requirement_update.json", {
                "actor_role": "project_manager_agent",
                "action": "link",
                "requirement_id": requirement["requirement_id"],
                "expected_current_version": requirement["current_version"],
                "test_refs": ["tests/new-evidence"],
            })
            env = os.environ.copy()
            env["AI_STARTER_TEST_FAIL_REQUIREMENT_TRANSACTION_AFTER"] = "2"
            rejected = h.tool("ai-requirement", expect=1, env=env)
            self.assertIn("transaction", (rejected.stdout + rejected.stderr).lower())
            self.assertEqual(before, {path: path.read_bytes() for path in protected})
        finally:
            h.close()

    def test_delivery_artifact_paths_cannot_escape_project_root(self) -> None:
        h = ProjectHarness(self)
        link_path: Path | None = None
        try:
            (h.root / "src").mkdir()
            (h.root / "src/core.txt").write_text("v1\n", encoding="utf-8")
            h.create_complete_requirement()
            h.record_full_audit()
            h.commit("release ready")
            h.create_baseline()

            outside_file = h.temp_root / "outside.bin"
            outside_file.write_bytes(b"outside")
            outside_dir = h.temp_root / "outside-dir"
            outside_dir.mkdir()
            (outside_dir / "payload.bin").write_bytes(b"outside-link")
            link_path = h.root / "escape"
            if os.name == "nt":
                run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link_path), str(outside_dir)])
            else:
                link_path.symlink_to(outside_dir, target_is_directory=True)

            for artifact_path in [str(outside_file), "../outside.bin", "escape/payload.bin"]:
                with self.subTest(path=artifact_path):
                    write_json(h.root / ".ai/runtime/delivery_request.json", {
                        "actor_role": "project_manager_agent",
                        "release_version": "1.0.0",
                        "customer_name": "Customer",
                        "maintenance_note": "Test.",
                        "artifacts": [{"name": "Unsafe", "path": artifact_path, "version": "1.0.0", "status": "ready"}],
                    })
                    rejected = h.tool("ai-generate-delivery", expect=1)
                    self.assertIn("project root", (rejected.stdout + rejected.stderr).lower())

            if os.name == "nt":
                link_path.rmdir()
            else:
                link_path.unlink()
            link_path = None

            nested_artifact = h.root / "artifacts/nested"
            nested_artifact.mkdir(parents=True)
            (nested_artifact / "inside.bin").write_bytes(b"inside")
            link_path = nested_artifact / "outside-link"
            if os.name == "nt":
                run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link_path), str(outside_dir)])
            else:
                link_path.symlink_to(outside_dir, target_is_directory=True)
            write_json(h.root / ".ai/runtime/delivery_request.json", {
                "actor_role": "project_manager_agent",
                "release_version": "1.0.0",
                "customer_name": "Customer",
                "maintenance_note": "Test.",
                "artifacts": [{
                    "name": "Nested escape",
                    "path": "artifacts/nested",
                    "version": "1.0.0",
                    "status": "ready",
                }],
            })
            nested_rejected = h.tool("ai-generate-delivery", expect=1)
            self.assertIn("project root", (nested_rejected.stdout + nested_rejected.stderr).lower())
            if os.name == "nt":
                link_path.rmdir()
            else:
                link_path.unlink()
            link_path = None
            remove_tree(nested_artifact)

            artifact = h.root / "artifacts/release/app.bin"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"inside")
            write_json(h.root / ".ai/runtime/delivery_request.json", {
                "actor_role": "project_manager_agent",
                "release_version": "1.0.0",
                "customer_name": "Customer",
                "maintenance_note": "Test.",
                "artifacts": [{"name": "Safe", "path": "artifacts/release/app.bin", "version": "1.0.0", "status": "ready"}],
            })
            h.tool("ai-generate-delivery")
            h.tool("ai-delivery-verify", "--release", "1.0.0")
            manifest = next((h.root / "docs/delivery").rglob("delivery_manifest.json"))
            artifact_record = json.loads(manifest.read_text(encoding="utf-8"))["artifacts"][0]
            self.assertEqual(artifact_record["path"], "artifacts/release/app.bin")
            self.assertEqual(artifact_record["size_bytes"], len(b"inside"))
            self.assertEqual(artifact_record["file_count"], 1)
        finally:
            if link_path and link_path.exists():
                if os.name == "nt":
                    link_path.rmdir()
                else:
                    link_path.unlink()
            h.close()

    def test_delivery_regeneration_requires_force_and_refreshes_checklist(self) -> None:
        h = ProjectHarness(self)
        try:
            (h.root / "src").mkdir()
            (h.root / "src/core.txt").write_text("v1\n", encoding="utf-8")
            h.create_complete_requirement()
            h.record_full_audit()
            h.commit("release ready")
            baseline_id = h.create_baseline()
            artifact = h.root / "dist/app.bin"
            artifact.parent.mkdir()
            artifact.write_bytes(b"first")
            request = {
                "actor_role": "project_manager_agent",
                "release_version": "1.0.0",
                "customer_name": "Customer",
                "maintenance_note": "Test.",
                "artifacts": [{
                    "name": "Application",
                    "path": "dist/app.bin",
                    "version": "1.0.0",
                    "status": "ready",
                }],
            }
            write_json(h.root / ".ai/runtime/delivery_request.json", request)
            h.tool("ai-generate-delivery")
            delivery = h.root / "docs/delivery"
            checklist = next(delivery.rglob("DELIVERY_CHECKLIST.md"))
            manifest_path = next(delivery.rglob("delivery_manifest.json"))
            baseline_path = h.root / ".ai/release_baselines" / f"{baseline_id}.json"
            protected = [checklist, manifest_path, baseline_path]
            before = {path: path.read_bytes() for path in protected}

            artifact.write_bytes(b"second")
            write_json(h.root / ".ai/runtime/delivery_request.json", request)
            rejected = h.tool("ai-generate-delivery", expect=1)
            self.assertIn("force", (rejected.stdout + rejected.stderr).lower())
            self.assertEqual(before, {path: path.read_bytes() for path in protected})

            request["force"] = True
            write_json(h.root / ".ai/runtime/delivery_request.json", request)
            h.tool("ai-generate-delivery")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            new_sha = hashlib.sha256(b"second").hexdigest()
            self.assertEqual(manifest["artifacts"][0]["sha256"], new_sha)
            self.assertIn(new_sha, checklist.read_text(encoding="utf-8"))
            h.tool("ai-delivery-verify", "--release", "1.0.0")
        finally:
            h.close()

    def test_delivery_generation_transaction_rolls_back_on_fault(self) -> None:
        h = ProjectHarness(self)
        try:
            (h.root / "src").mkdir()
            (h.root / "src/core.txt").write_text("v1\n", encoding="utf-8")
            h.create_complete_requirement()
            h.record_full_audit()
            h.commit("release ready")
            baseline_id = h.create_baseline()
            artifact = h.root / "dist/app.bin"
            artifact.parent.mkdir()
            artifact.write_bytes(b"release")
            baseline_path = h.root / ".ai/release_baselines" / f"{baseline_id}.json"
            log_path = next((h.root / "docs/logs").glob("*.md"))
            before = {path: path.read_bytes() for path in [baseline_path, log_path]}
            write_json(h.root / ".ai/runtime/delivery_request.json", {
                "actor_role": "project_manager_agent",
                "release_version": "1.0.0",
                "customer_name": "Customer",
                "maintenance_note": "Test.",
                "artifacts": [{"name": "Application", "path": "dist/app.bin"}],
            })
            env = os.environ.copy()
            env["AI_STARTER_TEST_FAIL_DELIVERY_TRANSACTION_AFTER"] = "2"
            rejected = h.tool("ai-generate-delivery", expect=1, env=env)
            self.assertIn("transaction", (rejected.stdout + rejected.stderr).lower())
            self.assertEqual(before, {path: path.read_bytes() for path in [baseline_path, log_path]})
            delivery_root = h.root / "docs/delivery"
            self.assertFalse(
                delivery_root.exists()
                and any(path.is_file() for path in delivery_root.rglob("*"))
            )
        finally:
            h.close()

    def test_final_acceptance_transaction_rolls_back_on_fault(self) -> None:
        h = ProjectHarness(self)
        try:
            (h.root / "src").mkdir()
            (h.root / "src/core.txt").write_text("v1\n", encoding="utf-8")
            h.create_complete_requirement()
            h.record_full_audit()
            h.commit("release ready")
            baseline_id = h.create_baseline()
            artifact = h.root / "dist/app.bin"
            artifact.parent.mkdir()
            artifact.write_bytes(b"release")
            write_json(h.root / ".ai/runtime/delivery_request.json", {
                "actor_role": "project_manager_agent",
                "release_version": "1.0.0",
                "customer_name": "Customer",
                "maintenance_note": "Test.",
                "artifacts": [{"name": "Application", "path": "dist/app.bin"}],
            })
            h.tool("ai-generate-delivery")
            baseline_path = h.root / ".ai/release_baselines" / f"{baseline_id}.json"
            acceptance_report = next((h.root / "docs/delivery").rglob("FINAL_ACCEPTANCE_REPORT.md"))
            state_path = h.root / ".ai/project_state.json"
            log_path = next((h.root / "docs/logs").glob("*.md"))
            protected = [baseline_path, acceptance_report, state_path, log_path]
            before = {path: path.read_bytes() for path in protected}
            write_json(h.root / ".ai/runtime/final_acceptance.json", {
                "recorder_role": "project_manager_agent",
                "release_version": "1.0.0",
                "owner_decision": "passed",
                "owner_note": "Owner accepted the release.",
            })
            env = os.environ.copy()
            env["AI_STARTER_TEST_FAIL_FINAL_ACCEPTANCE_TRANSACTION_AFTER"] = "2"
            rejected = h.tool("ai-final-acceptance", expect=1, env=env)
            self.assertIn("transaction", (rejected.stdout + rejected.stderr).lower())
            self.assertEqual(before, {path: path.read_bytes() for path in protected})
        finally:
            h.close()

    def test_run_tests_cmd_propagates_failure_and_runs_once(self) -> None:
        if os.name != "nt":
            return
        temp = make_temp_dir("ai-starter-v181-cmd-")
        try:
            shutil.copy2(ROOT / "RUN_TESTS.cmd", temp / "RUN_TESTS.cmd")
            marker = temp / "runs.txt"
            (temp / "run_tests.py").write_text(
                "import os\n"
                "from pathlib import Path\n"
                "path = Path(os.environ['AI_STARTER_RUN_MARKER'])\n"
                "path.write_text((path.read_text() if path.exists() else '') + 'run\\n')\n"
                "raise SystemExit(7)\n",
                encoding="utf-8",
                newline="\n",
            )
            env = os.environ.copy()
            env["AI_STARTER_RUN_MARKER"] = str(marker)
            result = run(
                ["cmd.exe", "/d", "/c", str(temp / "RUN_TESTS.cmd")],
                cwd=ROOT.parent,
                expect=7,
                env=env,
            )
            self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["run"])
            self.assertEqual(result.returncode, 7)
        finally:
            if temp.exists():
                remove_tree(temp)

    def test_test_harness_cleans_temporary_project(self) -> None:
        h = ProjectHarness(self)
        temp_root = h.temp_root
        self.assertTrue(temp_root.exists())
        h.close()
        self.assertFalse(temp_root.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
