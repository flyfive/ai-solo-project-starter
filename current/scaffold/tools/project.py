#!/usr/bin/env python3
# Copyright (c) 2026 FeiXiaorong
# SPDX-License-Identifier: MIT
# Template-origin code; retain the license in NOTICE.template.txt.
"""V1.9.0 工具无关双模式项目维护引擎。

用户无需输入维护命令。该工具提供流程级强约束：
- 验收/开发反馈先登记为待处理变更；
- 语义文档先于实现修改；
- 文档哈希与 Git 工作区指纹验证；
- 未关闭变更阻止批次关闭和阶段推进；
- Git Hook 在提交前再次检查；
- 项目记忆摘要和分层读取计划减少重复上下文消耗；
- 阶段切换前执行一次低频完整审计；
- 正式需求永久编号、语义修订、验收、实现、测试与发布全链路追踪；
- 发布基线、客户文档、最终验收与项目结案闭环。

这不是操作系统沙箱。具备完整终端权限的执行器仍可能绕过本地工具，
因此必须同时保留 AGENTS.md 规则、Git/CI 审计和项目经理复核。
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
sys.dont_write_bytecode = True
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit("需要 Python 3.11 或更高版本。") from exc

AUTO_START = "<!-- AUTO:PROJECT_STATUS:START -->"
AUTO_END = "<!-- AUTO:PROJECT_STATUS:END -->"
MEMORY_AUTO_START = "<!-- AUTO:PROJECT_MEMORY_STATUS:START -->"
MEMORY_AUTO_END = "<!-- AUTO:PROJECT_MEMORY_STATUS:END -->"
RUNTIME_DIR = Path(".ai/runtime")
REQUEST_FILE = RUNTIME_DIR / "batch_request.json"
RESULT_FILE = RUNTIME_DIR / "batch_result.json"
ACTIVE_FILE = RUNTIME_DIR / "active_batch.json"
BATCH_HANDOFF_INPUT_FILE = RUNTIME_DIR / "batch_handoff.json"
PENDING_BATCH_HANDOFF_FILE = RUNTIME_DIR / "pending_batch_handoff.json"
BATCH_HANDOFF_HISTORY = Path(".ai/history/batch_handoffs")
SUBMITTED_FILE = RUNTIME_DIR / "submitted_result.json"
ACCEPTANCE_FILE = RUNTIME_DIR / "acceptance.json"
CHANGE_REQUEST_FILE = RUNTIME_DIR / "change_request.json"
PENDING_CHANGES_FILE = RUNTIME_DIR / "pending_changes.json"
CONTEXT_FILE = RUNTIME_DIR / "context.json"
HANDOFF_FILE = RUNTIME_DIR / "HANDOFF_CURRENT.md"
LATEST_FILE = RUNTIME_DIR / "latest_summary.json"
AUDIT_FILE = RUNTIME_DIR / "audit_result.json"
PROJECT_STATE_FILE = Path(".ai/project_state.json")
REQUIREMENT_REGISTRY_FILE = Path(".ai/requirement_registry.json")
RELEASE_BASELINES_DIR = Path(".ai/release_baselines")
RELEASE_BASELINE_INDEX_FILE = RELEASE_BASELINES_DIR / "index.json"
PROJECT_REOPEN_INPUT_FILE = RUNTIME_DIR / "project_reopen.json"
REQUIREMENT_UPDATE_FILE = RUNTIME_DIR / "requirement_update.json"
RELEASE_BASELINE_FILE = RUNTIME_DIR / "release_baseline.json"
DELIVERY_REQUEST_FILE = RUNTIME_DIR / "delivery_request.json"
FINAL_ACCEPTANCE_INPUT_FILE = RUNTIME_DIR / "final_acceptance.json"
PROJECT_CLOSE_INPUT_FILE = RUNTIME_DIR / "project_close.json"
GOVERNANCE_PROMOTION_INPUT_FILE = RUNTIME_DIR / "governance_promotion.json"
GOVERNANCE_SUSPENSION_INPUT_FILE = RUNTIME_DIR / "governance_suspension.json"
SUSPENDED_PROMOTION_BATCH_FILE = RUNTIME_DIR / "suspended_batch_for_promotion.json"
STANDARD_TEMPLATE_BUNDLE_FILE = Path(".ai/standard_mode_templates.json")
REQ_CATALOG_START = "<!-- AUTO:REQUIREMENT_CATALOG:START -->"
REQ_CATALOG_END = "<!-- AUTO:REQUIREMENT_CATALOG:END -->"
ACCEPTANCE_CATALOG_START = "<!-- AUTO:ACCEPTANCE_CATALOG:START -->"
ACCEPTANCE_CATALOG_END = "<!-- AUTO:ACCEPTANCE_CATALOG:END -->"
REQ_CHANGELOG_START = "<!-- AUTO:REQUIREMENT_CHANGELOG:START -->"
REQ_CHANGELOG_END = "<!-- AUTO:REQUIREMENT_CHANGELOG:END -->"
TRACE_MATRIX_START = "<!-- AUTO:TRACEABILITY_MATRIX:START -->"
TRACE_MATRIX_END = "<!-- AUTO:TRACEABILITY_MATRIX:END -->"
FINAL_ACCEPTANCE_START = "<!-- AUTO:FINAL_ACCEPTANCE_STATUS:START -->"
FINAL_ACCEPTANCE_END = "<!-- AUTO:FINAL_ACCEPTANCE_STATUS:END -->"
PROJECT_CLOSURE_START = "<!-- AUTO:PROJECT_CLOSURE_STATUS:START -->"
PROJECT_CLOSURE_END = "<!-- AUTO:PROJECT_CLOSURE_STATUS:END -->"
_MISSING = object()

MEMORY_DOCS = {
    "project_memory": "docs/PROJECT_MEMORY.md",
    "requirements": "docs/PRODUCT_REQUIREMENTS.md",
    "acceptance": "docs/ACCEPTANCE_CRITERIA.md",
    "requirement_changelog": "docs/REQUIREMENT_CHANGELOG.md",
    "traceability": "docs/REQUIREMENT_TRACEABILITY_MATRIX.md",
    "architecture": "docs/ARCHITECTURE.md",
    "plan": "docs/DEVELOPMENT_PLAN.md",
    "decision": "docs/DECISIONS.md",
    "pitfall": "docs/PITFALLS.md",
    "rules": "docs/PROJECT_RULES.md",
    "roles": "docs/ROLE_BOUNDARIES.md",
    "delivery_rules": "docs/DELIVERY_AND_CLOSURE.md",
}
CHANGE_TYPE_MATRIX = {
    "bug_fix": [],
    "requirement_change": ["requirements", "acceptance", "requirement_changelog", "traceability", "decision", "project_memory"],
    "acceptance_change": ["acceptance", "traceability", "decision", "project_memory"],
    "architecture_change": ["architecture", "plan", "decision", "project_memory"],
    "plan_change": ["plan", "decision", "project_memory"],
    "ui_behavior_change": ["requirements", "acceptance", "requirement_changelog", "traceability", "decision", "project_memory"],
    "pitfall_rule": ["pitfall", "project_memory"],
    "execution_rule_change": ["rules", "decision", "project_memory"],
    "role_boundary_change": ["roles", "rules", "decision", "project_memory"],
    "delivery_rule_change": ["delivery_rules", "rules", "decision", "project_memory"],
}
STANDARD_ONLY_CHANGE_TYPES = {
    "architecture_change",
    "plan_change",
    "pitfall_rule",
    "execution_rule_change",
    "role_boundary_change",
    "delivery_rule_change",
}
CORE_CURRENT_DOCS = [
    "AGENTS.md",
    "PROJECT.toml",
    ".ai/AUTOMATION_CONTRACT.md",
    "docs/PROJECT_RULES.md",
    "docs/AI_EXECUTION_RULES.md",
    "docs/CONTEXT_LOADING_PROTOCOL.md",
    "docs/ROLE_BOUNDARIES.md",
    "docs/PROJECT_MEMORY.md",
    "docs/CURRENT_STATE.md",
    ".ai/requirement_registry.json",
    "docs/PRODUCT_REQUIREMENTS.md",
    "docs/ACCEPTANCE_CRITERIA.md",
    "docs/REQUIREMENT_CHANGELOG.md",
    "docs/REQUIREMENT_TRACEABILITY_MATRIX.md",
    "docs/ARCHITECTURE.md",
    "docs/DEVELOPMENT_PLAN.md",
    "docs/DECISIONS.md",
    "docs/PITFALLS.md",
    "docs/DELIVERY_AND_CLOSURE.md",
]

CONTEXT_KEYWORDS = {
    "docs/ROLE_BOUNDARIES.md": ["角色", "权限", "职责", "越权", "并行", "执行器", "审核", "项目经理"],
    "docs/PRODUCT_REQUIREMENTS.md": ["需求", "功能", "业务", "范围", "用户", "流程", "产品"],
    "docs/ACCEPTANCE_CRITERIA.md": ["验收", "测试", "通过", "完成条件", "标准"],
    "docs/REQUIREMENT_CHANGELOG.md": ["需求版本", "修订", "历史需求", "旧需求", "需求变更台账"],
    "docs/REQUIREMENT_TRACEABILITY_MATRIX.md": ["追踪", "可追溯", "实现证据", "测试证据", "最终验收", "发布基线"],
    "docs/DELIVERY_AND_CLOSURE.md": ["客户文档", "用户手册", "帮助文档", "结案", "交付", "发布说明"],
    "docs/ARCHITECTURE.md": ["架构", "技术栈", "模块", "服务", "部署", "重构"],
    "docs/DEVELOPMENT_PLAN.md": ["规划", "阶段", "批次", "里程碑", "优先级"],
    "docs/DECISIONS.md": ["为什么", "决定", "取舍", "替代", "变更原因"],
    "docs/PITFALLS.md": ["避坑", "错误", "风险", "不要", "禁止"],
    "docs/API_DESIGN.md": ["api", "接口", "请求", "响应", "契约"],
    "docs/DATA_MODEL.md": ["数据库", "数据模型", "表", "字段", "实体", "迁移"],
    "docs/UI_SPEC.md": ["ui", "页面", "界面", "交互", "原型", "按钮"],
    "docs/RUNBOOK.md": ["启动", "环境", "运行", "故障", "端口"],
    "docs/SECURITY.md": ["安全", "权限", "凭据", "授权", "鉴权"],
    "docs/TEST_PLAN.md": ["测试计划", "回归", "覆盖率"],
    "docs/HARDWARE_RULES.md": ["pcb", "硬件", "布线", "原理图", "drc", "erc"],
    "docs/BOM_MANAGEMENT.md": ["bom", "器件", "物料", "替代料"],
    "docs/AUTOMATION_WORKFLOWS.md": ["自动化", "工作流", "机械臂", "脚本"],
    "docs/DATA_PIPELINE.md": ["数据管道", "采集", "增量", "回填", "质量"],
    "docs/DEPLOYMENT.md": ["发布", "部署", "安装包", "上线", "回滚"],
}

PROFILE_DOCS = {
    "generic": [],
    "web-fullstack": ["API_DESIGN", "DATA_MODEL", "UI_SPEC", "RUNBOOK"],
    "desktop-windows": ["UI_SPEC", "RUNBOOK", "SECURITY", "DEPLOYMENT"],
    "android": ["UI_SPEC", "API_DESIGN", "SECURITY", "DEPLOYMENT"],
    "python-local-tool": ["RUNBOOK", "DATA_MODEL", "TEST_PLAN"],
    "hardware-pcb": ["HARDWARE_RULES", "BOM", "TEST_PLAN"],
    "ai-automation": ["AUTOMATION_WORKFLOWS", "SECURITY", "RUNBOOK", "TEST_PLAN"],
    "data-platform": ["DATA_MODEL", "DATA_PIPELINE", "RUNBOOK", "TEST_PLAN"],
}
OPTIONAL_DOCS = {
    "API_DESIGN": ("docs/API_DESIGN.md", "# API 设计\n\n## 1. 设计原则\n\n- 待补充。\n\n## 2. 接口清单\n\n| 接口 | 方法 | 输入 | 输出 | 错误 |\n|---|---|---|---|---|\n| 待补充 | | | | |\n\n## 3. 契约与版本规则\n\n- 待补充。\n"),
    "DATA_MODEL": ("docs/DATA_MODEL.md", "# 数据模型\n\n## 1. 数据口径\n\n- 待补充。\n\n## 2. 实体与关系\n\n| 实体 | 关键字段 | 关系 | 约束 |\n|---|---|---|---|\n| 待补充 | | | |\n\n## 3. 迁移与兼容\n\n- 待补充。\n"),
    "UI_SPEC": ("docs/UI_SPEC.md", "# UI 与交互规范\n\n## 1. 信息架构\n\n- 待补充。\n\n## 2. 页面与状态\n\n| 页面 | 入口 | 核心功能 | 空/错/加载状态 |\n|---|---|---|---|\n| 待补充 | | | |\n\n## 3. 视觉和交互约束\n\n- 待补充。\n"),
    "RUNBOOK": ("docs/RUNBOOK.md", "# 环境与运行手册\n\n## 1. 环境要求\n\n- 待补充。\n\n## 2. 安装与启动\n\n```text\n待补充。\n```\n\n## 3. 常见故障与恢复\n\n- 待补充。\n"),
    "SECURITY": ("docs/SECURITY.md", "# 安全与风险边界\n\n## 1. 数据与凭据\n\n- 待补充。\n\n## 2. 权限与授权\n\n- 以 `PROJECT.toml` 为基础，补充项目专属边界。\n\n## 3. 威胁与缓解\n\n| 风险 | 影响 | 缓解措施 | 验证 |\n|---|---|---|---|\n| 待补充 | | | |\n"),
    "TEST_PLAN": ("docs/TEST_PLAN.md", "# 测试计划\n\n## 1. 测试范围\n\n- 待补充。\n\n## 2. 测试矩阵\n\n| 层级 | 场景 | 工具 | 通过条件 |\n|---|---|---|---|\n| 待补充 | | | |\n\n## 3. 人工验收\n\n- 待补充。\n"),
    "HARDWARE_RULES": ("docs/HARDWARE_RULES.md", "# 硬件与 PCB 规则\n\n## 1. 电气约束\n\n- 待补充。\n\n## 2. 布局与布线\n\n- 待补充。\n\n## 3. ERC / DRC / 制造门禁\n\n- 待补充。\n"),
    "BOM": ("docs/BOM_MANAGEMENT.md", "# BOM 管理\n\n## 1. 器件清单规则\n\n- 待补充。\n\n## 2. 替代料与生命周期\n\n| 位号/器件 | 主料 | 替代料 | 约束 | 状态 |\n|---|---|---|---|---|\n| 待补充 | | | | |\n"),
    "AUTOMATION_WORKFLOWS": ("docs/AUTOMATION_WORKFLOWS.md", "# 自动化工作流\n\n## 1. 工作流清单\n\n| 工作流 | 触发 | 输入 | 操作 | 失败恢复 | 人工门禁 |\n|---|---|---|---|---|---|\n| 待补充 | | | | | |\n\n## 2. 幂等与审计\n\n- 待补充。\n"),
    "DATA_PIPELINE": ("docs/DATA_PIPELINE.md", "# 数据管道设计\n\n## 1. 数据源与口径\n\n- 待补充。\n\n## 2. 采集、校验与增量\n\n| 阶段 | 输入 | 输出 | 质量门禁 | 重试/回填 |\n|---|---|---|---|---|\n| 待补充 | | | | |\n"),
    "DEPLOYMENT": ("docs/DEPLOYMENT.md", "# 部署与发布\n\n## 1. 环境\n\n- 待补充。\n\n## 2. 构建与部署步骤\n\n- 待补充。\n\n## 3. 回滚与验证\n\n- 待补充。\n"),
}


def find_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "PROJECT.toml").exists():
            return candidate
    raise SystemExit("未找到 PROJECT.toml。")


def context_extension():
    """Load the small context companion without changing the existing governance API."""
    import importlib.util
    import types
    global _context_module
    if "_context_module" not in globals():
        spec = importlib.util.spec_from_file_location("project_context_engine", find_root() / "tools/context_engine.py")
        _context_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_context_module)
    return _context_module, types.SimpleNamespace(**globals())


def load_config(root: Path) -> dict:
    with (root / "PROJECT.toml").open("rb") as fh:
        return tomllib.load(fh)


def governance_mode(root: Path, cfg: dict | None = None) -> str:
    cfg = cfg or load_config(root)
    mode = str(cfg.get("governance", {}).get("mode", "standard")).strip().lower()
    if mode not in {"lite", "standard"}:
        raise SystemExit("PROJECT.toml governance.mode 必须为 lite 或 standard。")
    return mode


def required_project_documents(cfg: dict) -> list[str]:
    documents = cfg.get("documents", {})
    required = list(documents.get("required", []))
    if str(cfg.get("governance", {}).get("mode", "standard")).lower() == "standard":
        required.extend(documents.get("standard_required", []))
    return list(dict.fromkeys(str(item) for item in required))


def require_standard_governance(root: Path, operation: str) -> None:
    if governance_mode(root) != "standard":
        raise SystemExit(
            f"{operation} requires Standard governance. "
            "Complete the current Lite work, obtain project-owner authorization, "
            "then use ai-promote-standard. Lite to Standard is one-way."
        )


def standard_template_hashes(files: dict[str, str]) -> tuple[dict[str, str], str]:
    per_file = {
        key: hashlib.sha256(value.encode("utf-8")).hexdigest()
        for key, value in sorted(files.items())
    }
    canonical = json.dumps(
        files,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return per_file, hashlib.sha256(canonical).hexdigest()


def validate_standard_template_bundle(root: Path, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config(root)
    bundle_path = root / STANDARD_TEMPLATE_BUNDLE_FILE
    bundle = require_dict(read_json(bundle_path), str(bundle_path))
    if bundle.get("schema_version") != "1.9.0":
        raise SystemExit("Standard 治理扩展模板包 schema_version 必须为 1.9.0。")
    files = bundle.get("files")
    if not isinstance(files, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in files.items()
    ):
        raise SystemExit("Standard 治理扩展模板 files 必须是文本映射。")
    expected = set(
        str(item) for item in cfg.get("documents", {}).get("standard_required", [])
    )
    if set(files) != expected:
        raise SystemExit("Standard 治理扩展模板包文件集合与 PROJECT.toml 不一致。")
    file_hashes, content_hash = standard_template_hashes(files)
    if bundle.get("file_sha256") != file_hashes:
        raise SystemExit("Standard 治理扩展模板包单文件哈希校验失败。")
    if bundle.get("content_sha256") != content_hash:
        raise SystemExit("Standard 治理扩展模板包整体内容哈希校验失败。")
    configured_hash = str(
        cfg.get("governance", {}).get("standard_mode_templates_sha256", "")
    ).strip()
    if configured_hash != content_hash:
        raise SystemExit("PROJECT.toml 中的 Standard 模板包哈希与实际内容不一致。")
    for rel, content in files.items():
        if not content.strip().startswith("#"):
            raise SystemExit("Standard 治理扩展模板缺少 Markdown 标题：" + rel)
        if re.search(r"\{\{[A-Z0-9_]+\}\}", content):
            raise SystemExit("Standard 治理扩展模板仍含未替换变量：" + rel)
    memory = files.get("docs/PROJECT_MEMORY.md", "")
    if MEMORY_AUTO_START not in memory or MEMORY_AUTO_END not in memory:
        raise SystemExit("Standard 治理扩展模板中的 PROJECT_MEMORY 自动区标记缺失。")
    return bundle


def standard_baseline_status(state: dict) -> str:
    baseline = state.get("standard_baseline")
    if not isinstance(baseline, dict):
        return "not_required"
    return str(baseline.get("status", "not_required")).strip().lower()


def require_standard_baseline_ready(root: Path, operation: str) -> None:
    state = load_project_state(root)
    if governance_mode(root) == "standard" and standard_baseline_status(state) == "pending":
        raise SystemExit(
            f"{operation} 被阻止：Lite→Standard 升级后的 Standard 基线审计尚未完成。"
            "请先补全架构、开发计划和项目记忆，再通过 ai-audit 完成升级基线审计。"
        )


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def json_bytes(data: Any) -> bytes:
    encoded = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    json.loads(encoded.decode("utf-8"))
    return encoded


def _write_bytes_atomically(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def atomic_file_transaction(
    payloads: list[tuple[Path, bytes | None]], *, failure_environment: str = ""
) -> None:
    """Stage and atomically replace/delete a group of files, restoring all on failure."""
    paths = [path for path, _ in payloads]
    if len(paths) != len(set(paths)):
        raise RuntimeError("transaction contains duplicate target paths")
    backups = {path: path.read_bytes() if path.exists() else None for path in paths}
    staged: dict[Path, Path] = {}
    try:
        for path, content in payloads:
            if content is None:
                continue
            if path.suffix.lower() == ".json":
                json.loads(content.decode("utf-8"))
            elif path.suffix.lower() == ".toml":
                tomllib.loads(content.decode("utf-8"))
            elif path.suffix.lower() in {".md", ".txt"}:
                content.decode("utf-8")
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, raw_temp = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".transaction", dir=str(path.parent)
            )
            temp_path = Path(raw_temp)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            staged[path] = temp_path

        fail_after = 0
        if failure_environment:
            raw_fail_after = os.environ.get(failure_environment, "").strip()
            if raw_fail_after:
                fail_after = int(raw_fail_after)
        for index, (path, content) in enumerate(payloads, 1):
            if content is None:
                if path.exists():
                    path.unlink()
            else:
                os.replace(staged.pop(path), path)
            if fail_after == index:
                raise RuntimeError(f"injected transaction failure after replacement {index}")
    except BaseException:
        for temp_path in staged.values():
            if temp_path.exists():
                temp_path.unlink()
        for path, content in backups.items():
            if content is None:
                if path.exists():
                    path.unlink()
            else:
                _write_bytes_atomically(path, content)
        raise


def resolve_project_input(root: Path, supplied, default: Path | str) -> Path:
    """Validate before read/delete: local regular files, no links on any component."""
    extension, _ = context_extension()
    raw = str(default if supplied is None else supplied)
    extension.hard_file(root, raw)
    return extension.safe_path(root, raw)


def read_json(path: Path, *, default: Any = _MISSING) -> Any:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if default is not _MISSING:
            return default
        raise SystemExit(f"缺少 AI 运行文件：{path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON 格式错误：{path}：{exc}") from exc
    return data


def require_dict(data: Any, label: str) -> dict:
    if not isinstance(data, dict):
        raise SystemExit(f"{label} 顶层必须是对象。")
    return data


def require_text(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"字段 {key!r} 必须是非空字符串。")
    return value.strip()


def str_list(data: dict, key: str, required: bool = False) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise SystemExit(f"字段 {key!r} 必须是字符串数组。")
    result = [x.strip() for x in value if x.strip()]
    if required and not result:
        raise SystemExit(f"字段 {key!r} 不能为空。")
    return result


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def git_output(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def is_git_repo(root: Path) -> bool:
    return git_output(root, "rev-parse", "--is-inside-work-tree") == "true"


def git_info(root: Path) -> dict[str, str]:
    return {
        "repository": "yes" if is_git_repo(root) else "no",
        "branch": git_output(root, "branch", "--show-current") or "未检测",
        "head": git_output(root, "rev-parse", "--short", "HEAD") or "未检测",
        "status": git_output(root, "status", "--short") or "",
    }


def git_revision_is_ancestor(root: Path, ancestor: str, descendant: str = "HEAD") -> bool:
    try:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=root, check=True, capture_output=True, text=True,
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def git_implementation_tree_hash(root: Path, revision: str = "HEAD") -> str | None:
    """Hash committed non-governance files at a Git revision."""
    try:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--full-tree", revision],
            cwd=root, check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    entries: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if "\t" not in line:
            continue
        meta, rel = line.split("\t", 1)
        parts = meta.split()
        if len(parts) < 3 or is_semantic_or_runtime_path(rel):
            continue
        entries.append((rel, parts[2]))
    hasher = hashlib.sha256()
    for rel, blob in sorted(entries):
        hasher.update(rel.encode("utf-8")); hasher.update(b"\0")
        hasher.update(blob.encode("ascii")); hasher.update(b"\0")
    return hasher.hexdigest()


def git_path_is_tracked(root: Path, rel: str) -> bool:
    """Return whether Git tracks the file or any file below the directory path."""
    if not is_git_repo(root):
        return False
    try:
        result = subprocess.run(
            ["git", "ls-files", "--", rel], cwd=root, check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return bool(result.stdout.strip())


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    if path.is_dir():
        return "<directory>"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_project_artifact_path(root: Path, raw_path: str) -> tuple[str, Path]:
    """Return a normalized project-relative artifact path and its resolved target."""
    value = raw_path.strip()
    if not value:
        raise SystemExit("delivery artifact path must be non-empty and inside the project root")
    if re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith(("\\\\", "//")):
        raise SystemExit(f"delivery artifact path must be relative to the project root: {raw_path}")
    normalized_input = value.replace("\\", "/")
    candidate = Path(normalized_input)
    if candidate.is_absolute() or candidate.drive or any(part == ".." for part in candidate.parts):
        raise SystemExit(f"delivery artifact path must stay inside the project root: {raw_path}")
    try:
        project_root = root.resolve(strict=True)
        resolved = (root / candidate).resolve(strict=True)
        resolved.relative_to(project_root)
    except (OSError, ValueError):
        raise SystemExit(
            f"delivery artifact path resolves outside the project root or does not exist: {raw_path}"
        ) from None
    if resolved == project_root:
        raise SystemExit("the project root itself cannot be registered as a delivery artifact")
    return candidate.as_posix(), resolved


def path_digest(path: Path, project_root: Path | None = None) -> dict[str, Any]:
    """Deterministically fingerprint a file or directory delivery artifact."""
    if not path.exists():
        raise SystemExit(f"交付物不存在：{path}")
    containment_root = project_root.resolve(strict=True) if project_root is not None else None
    if containment_root is not None:
        try:
            path.resolve(strict=True).relative_to(containment_root)
        except (OSError, ValueError):
            raise SystemExit(f"delivery artifact resolves outside the project root: {path}") from None
    if path.is_file():
        return {
            "kind": "file",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
            "file_count": 1,
        }
    hasher = hashlib.sha256()
    total = 0
    count = 0
    artifact_files: list[Path] = []
    for current, directories, filenames in os.walk(path, followlinks=False):
        current_path = Path(current)
        for name in sorted([*directories, *filenames]):
            entry = current_path / name
            if containment_root is not None:
                try:
                    entry.resolve(strict=True).relative_to(containment_root)
                except (OSError, ValueError):
                    raise SystemExit(
                        f"delivery artifact contains a link outside the project root: {entry}"
                    ) from None
        artifact_files.extend(current_path / name for name in filenames)
    for child in sorted(artifact_files):
        rel = child.relative_to(path).as_posix().encode("utf-8")
        data = child.read_bytes()
        hasher.update(len(rel).to_bytes(8, "big")); hasher.update(rel)
        hasher.update(len(data).to_bytes(8, "big")); hasher.update(data)
        total += len(data); count += 1
    return {
        "kind": "directory",
        "sha256": hasher.hexdigest(),
        "size_bytes": total,
        "file_count": count,
    }


def memory_document_hash(root: Path, category: str) -> str | None:
    rel = MEMORY_DOCS[category]
    path = root / rel
    if not path.exists():
        return None
    if category != "project_memory":
        return file_hash(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(re.escape(MEMORY_AUTO_START) + r".*?" + re.escape(MEMORY_AUTO_END), re.S)
    semantic = pattern.sub("", text, count=1)
    return hashlib.sha256(semantic.encode("utf-8")).hexdigest()


def memory_hashes(root: Path) -> dict[str, str | None]:
    return {key: memory_document_hash(root, key) for key in MEMORY_DOCS}


def parse_porcelain_z(raw: bytes) -> list[str]:
    entries = raw.split(b"\0")
    paths: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        text = entry.decode("utf-8", errors="replace")
        if len(text) < 4:
            continue
        status = text[:2]
        path = text[3:]
        # Rename/copy records contain an extra old path in -z mode.
        if "R" in status or "C" in status:
            if index < len(entries) and entries[index]:
                index += 1
        paths.append(path)
    return paths


def is_semantic_or_runtime_path(rel: str) -> bool:
    normalized = rel.replace("\\", "/")
    return (
        normalized.startswith("docs/")
        or normalized.startswith(".ai/")
        or normalized.startswith(".githooks/")
        or normalized in {"PROJECT.toml", "AGENTS.md", "EXECUTOR_ENTRY.md", "START_HERE.md", "README.md", "PROJECT_OWNER_GUIDE.md"}
    )


def working_fingerprint(root: Path) -> dict[str, str | None]:
    """Fingerprint only changed/untracked implementation paths.

    This makes document-first validation practical even for large repositories.
    Existing dirty implementation files are captured with hashes, so further edits
    before document writeback are detectable.
    """
    if not is_git_repo(root):
        return {"__git_unavailable__": None}
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=root,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return {"__git_unavailable__": None}
    result: dict[str, str | None] = {}
    for rel in parse_porcelain_z(proc.stdout):
        if is_semantic_or_runtime_path(rel):
            continue
        result[rel] = file_hash(root / rel)
    return result


def fingerprint_changes(before: dict[str, str | None], after: dict[str, str | None]) -> list[str]:
    keys = sorted(set(before) | set(after))
    return [key for key in keys if before.get(key) != after.get(key)]


def update_auto_block(path: Path, body: str) -> None:
    text = path.read_text(encoding="utf-8")
    replacement = f"{AUTO_START}\n{body.rstrip()}\n{AUTO_END}"
    pattern = re.compile(re.escape(AUTO_START) + r".*?" + re.escape(AUTO_END), re.S)
    if not pattern.search(text):
        raise SystemExit(f"状态文件缺少自动区标记：{path}")
    path.write_text(pattern.sub(lambda _: replacement, text, count=1), encoding="utf-8", newline="\n")


def resume_priority(
    state: dict,
    changes: list[dict],
    active: dict | None,
    suspended: dict | None,
) -> str:
    if standard_baseline_status(state) == "pending":
        return "complete_standard_baseline_audit"
    if any(item.get("status") == "captured" for item in changes):
        return "complete_document_writeback"
    if changes:
        return "complete_pending_change"
    if isinstance(active, dict):
        return "resume_active_batch"
    if isinstance(suspended, dict):
        return "complete_governance_promotion"
    if state.get("pending_batch_handoff"):
        return "start_handoff_successor"
    return "continue_current_plan"


def project_memory_auto_text(
    state: dict,
    changes: list[dict],
    active: dict | None,
    suspended: dict | None,
) -> str:
    if isinstance(active, dict):
        active_text = f"`{active.get('batch_id')}` / {active.get('status', 'active')}"
    elif isinstance(suspended, dict):
        active_text = (
            f"`{suspended.get('batch_id')}` / 已挂起等待 Standard 基线审计"
        )
    else:
        active_text = "无"
    priority_code = resume_priority(state, changes, active, suspended)
    priority = {
        "complete_standard_baseline_audit": "完成 Standard 升级基线审计",
        "complete_document_writeback": "先完成文档写回",
        "complete_pending_change": "先完成未关闭变更",
        "resume_active_batch": "继续活动批次",
        "complete_governance_promotion": "完成治理模式升级",
        "continue_current_plan": "按当前规划继续",
        "start_handoff_successor": "启动具名继任批次 " + str((state.get("pending_batch_handoff") or {}).get("successor_batch_id", "")),
    }[priority_code]
    audit = state.get("last_full_audit")
    audit_text = "尚无" if not isinstance(audit, dict) else f"{audit.get('stage_id', '未标明')} / {audit.get('completed_at', '未知时间')}"
    return f"""- 当前阶段：{state.get('current_stage') or '项目探索与需求定义'}
- 活动批次：{active_text}
- 未关闭变更：{len(changes)}
- 当前优先级：{priority}
- 最近完整审计：{audit_text}"""


def replace_project_memory_auto(
    text: str,
    state: dict,
    changes: list[dict],
    active: dict | None,
    suspended: dict | None,
) -> str:
    core = project_memory_auto_text(state, changes, active, suspended)
    body = f"""## 自动运行状态

- 更新时间：{now_iso()}
{core}
"""
    pattern = re.compile(
        re.escape(MEMORY_AUTO_START) + r".*?" + re.escape(MEMORY_AUTO_END),
        re.S,
    )
    if not pattern.search(text):
        raise SystemExit("项目记忆摘要缺少自动区标记。")
    replacement = f"{MEMORY_AUTO_START}\n{body.rstrip()}\n{MEMORY_AUTO_END}"
    return pattern.sub(lambda _: replacement, text, count=1)


def update_project_memory_auto(root: Path, cfg: dict | None = None) -> None:
    cfg = cfg or load_config(root)
    state = load_project_state(root)
    changes = open_changes(root)
    active = read_json(root / ACTIVE_FILE, default=None)
    suspended = read_json(root / SUSPENDED_PROMOTION_BATCH_FILE, default=None)
    core = project_memory_auto_text(
        state,
        changes,
        active if isinstance(active, dict) else None,
        suspended if isinstance(suspended, dict) else None,
    )
    path = root / "docs/PROJECT_MEMORY.md"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(MEMORY_AUTO_START) + r"(.*?)" + re.escape(MEMORY_AUTO_END), re.S)
    match = pattern.search(text)
    if not match:
        raise SystemExit(f"项目记忆摘要缺少自动区标记：{path}")
    existing = re.sub(r"^\s*- 更新时间：.*$", "", match.group(1), flags=re.M).strip()
    desired_without_time = f"## 自动运行状态\n\n{core}".strip()
    if existing == desired_without_time:
        return
    updated = replace_project_memory_auto(
        text,
        state,
        changes,
        active if isinstance(active, dict) else None,
        suspended if isinstance(suspended, dict) else None,
    )
    path.write_text(updated, encoding="utf-8", newline="\n")


def all_context_hashes(root: Path) -> dict[str, str | None]:
    paths = set(CORE_CURRENT_DOCS)
    paths.update(rel for rel, _ in OPTIONAL_DOCS.values())
    paths.update(["START_HERE.md", "AGENTS.md", "PROJECT.toml", ".ai/AUTOMATION_CONTRACT.md"])
    return {rel: file_hash(root / rel) for rel in sorted(paths) if (root / rel).exists()}


def current_audit_hashes(root: Path) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    audit_paths = list(CORE_CURRENT_DOCS) + [p.relative_to(root).as_posix() for p in sorted((root / "docs/decisions").glob("*.md"))]
    for rel in audit_paths:
        if not (root / rel).exists():
            continue
        if rel == "docs/PROJECT_MEMORY.md":
            result[rel] = memory_document_hash(root, "project_memory")
        elif rel == "docs/CURRENT_STATE.md":
            text = (root / rel).read_text(encoding="utf-8")
            text = re.sub(re.escape(AUTO_START) + r".*?" + re.escape(AUTO_END), "", text, flags=re.S)
            result[rel] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        else:
            result[rel] = file_hash(root / rel)
    return result


def audit_is_current(root: Path, audit: dict | None) -> bool:
    if not isinstance(audit, dict) or audit.get("status") != "passed":
        return False
    recorded = audit.get("document_hashes", {})
    return isinstance(recorded, dict) and recorded == current_audit_hashes(root)


def choose_context_mode(requested: str, task: str, active: dict | None, changes: list[dict]) -> str:
    requested = (requested or "auto").lower()
    if requested in {"light", "standard", "full"}:
        return requested
    lowered = task.lower()
    full_words = ["阶段切换", "进入下一阶段", "发布", "上线", "架构重构", "完整审计", "重大变更"]
    if any(word in lowered for word in full_words):
        return "full"
    if isinstance(active, dict) or changes:
        return "light"
    return "standard"


def context_reading_plan(
    root: Path, mode: str, task: str, active: dict | None, changes: list[dict], previous: dict | None
) -> dict:
    base = ["docs/PROJECT_MEMORY.md", "docs/CURRENT_STATE.md"]
    if mode == "standard":
        base = ["START_HERE.md", "AGENTS.md", "PROJECT.toml", "docs/ROLE_BOUNDARIES.md", ".ai/AUTOMATION_CONTRACT.md", *base]
    elif mode == "full":
        base = ["START_HERE.md", "AGENTS.md", "PROJECT.toml", ".ai/AUTOMATION_CONTRACT.md", *CORE_CURRENT_DOCS]
    relevant: list[str] = []
    task_text = " ".join([task, json.dumps(active or {}, ensure_ascii=False), json.dumps(changes, ensure_ascii=False)]).lower()
    for rel, words in CONTEXT_KEYWORDS.items():
        if (root / rel).exists() and any(word.lower() in task_text for word in words):
            relevant.append(rel)
    for change in changes:
        for rel in change.get("affected_documents", []):
            if (root / rel).exists():
                relevant.append(rel)
    current_hashes = all_context_hashes(root)
    previous_hashes = previous.get("document_hashes", {}) if isinstance(previous, dict) else {}
    changed = sorted(rel for rel, value in current_hashes.items() if previous_hashes and previous_hashes.get(rel) != value)
    must_read = list(dict.fromkeys(rel for rel in [*base, *relevant] if (root / rel).exists()))
    if mode == "light":
        # 同一窗口/活动批次只需要温记忆、当前状态和实际变化的相关文档。
        must_read = list(dict.fromkeys([*base, *relevant, *changed]))
    read_if_relevant = [rel for rel in CORE_CURRENT_DOCS if rel not in must_read and (root / rel).exists()]
    for rel, _ in OPTIONAL_DOCS.values():
        if rel not in must_read and (root / rel).exists():
            read_if_relevant.append(rel)
    avoid = ["docs/logs/（除非追溯具体历史）", "完整 Git 历史（除非定位回归来源）", "与当前任务无关的扩展文档"]
    return {
        "mode": mode,
        "must_read": must_read,
        "read_if_relevant": list(dict.fromkeys(read_if_relevant)),
        "changed_since_previous_context": changed,
        "prefer_diff_for_changed_files": True,
        "do_not_read_by_default": avoid,
        "document_hashes": current_hashes,
    }


def validate_full_audit(root: Path, data: dict, cfg: dict) -> dict:
    stage_id = require_text(data, "stage_id")
    status = require_text(data, "status").lower()
    if status not in {"passed", "failed"}:
        raise SystemExit("完整审计 status 只能是 passed 或 failed。")
    docs_read = str_list(data, "documents_read", required=True)
    required = [rel for rel in CORE_CURRENT_DOCS if (root / rel).exists()]
    extension, api = context_extension()
    decision_index = extension.build_index(root, api)["decisions"]
    required += [row["locator"]["path"] for row in decision_index.values() if row["status"] in {"生效", "active", "accepted"}]
    missing = [rel for rel in required if rel not in docs_read]
    if missing:
        raise SystemExit("完整审计缺少当前事实文档：" + ", ".join(missing))
    for rel in docs_read:
        if not (root / rel).exists():
            raise SystemExit("完整审计声明读取了不存在的文件：" + rel)
    review = validate_manager_review(data, cfg)
    if status == "passed" and review.get("status") != "approved":
        raise SystemExit("完整审计通过前需要项目经理复核。")
    baseline_pending = standard_baseline_status(load_project_state(root)) == "pending"
    baseline_evidence = str_list(
        data,
        "standard_baseline_evidence",
        required=baseline_pending and status == "passed",
    )
    if (
        baseline_pending
        and status == "passed"
        and data.get("standard_baseline_completed") is not True
    ):
        raise SystemExit(
            "Lite→Standard 升级基线审计通过前必须声明 "
            "standard_baseline_completed=true。"
        )
    return {
        "stage_id": stage_id,
        "status": status,
        "documents_read": docs_read,
        "conflicts": str_list(data, "conflicts"),
        "resolutions": str_list(data, "resolutions"),
        "summary": require_text(data, "summary"),
        "manager_review": review,
        "standard_baseline_completed": bool(
            data.get("standard_baseline_completed", False)
        ),
        "standard_baseline_evidence": baseline_evidence,
    }


def update_markdown_section(path: Path, heading: str, body: str) -> None:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"(^## {re.escape(heading)}\s*\n)(.*?)(?=^## |\Z)", re.M | re.S)
    if not pattern.search(text):
        return
    updated = pattern.sub(lambda m: m.group(1) + "\n" + body.rstrip() + "\n\n", text, count=1)
    path.write_text(updated, encoding="utf-8", newline="\n")


def ensure_month_log(root: Path, project_name: str, today: date | None = None) -> Path:
    today = today or date.today()
    path = root / "docs" / "logs" / f"{today:%Y-%m}.md"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"# {project_name} 开发日志 — {today:%Y-%m}\n\n> 本文件按月追加历史批次。当前状态以 `../CURRENT_STATE.md` 为准。\n\n",
            encoding="utf-8", newline="\n"
        )
    return path


def read_limit(cfg: dict, key: str, default: int) -> int:
    return int(cfg.get("limits", {}).get(key, default))


def rotate_log_if_needed(root: Path, cfg: dict) -> str | None:
    path = ensure_month_log(root, cfg["project"]["name"])
    limit = read_limit(cfg, "monthly_log_max_kb", 100)
    size = path.stat().st_size / 1024
    if size <= limit:
        return None
    index = 1
    while path.with_name(f"{path.stem}.part{index:02d}.md").exists():
        index += 1
    archive = path.with_name(f"{path.stem}.part{index:02d}.md")
    path.rename(archive)
    ensure_month_log(root, cfg["project"]["name"])
    return str(archive.relative_to(root))


def default_project_state() -> dict:
    return {
        "schema_version": "1.9.0",
        "governance_mode": "standard",
        "governance_history": [],
        "standard_baseline": {
            "status": "not_required",
            "promoted_at": "",
            "completed_at": "",
            "summary": "",
            "suspended_batch_id": "",
        },
        "promotion_suspension": None,
        "project_status": "active",
        "current_release_version": "",
        "current_stage": "",
        "stage_acceptance": {
            "stage_id": "",
            "status": "not_started",
            "note": "",
            "updated_at": "",
        },
        "last_closed_batch": None,
        "last_manager_review": None,
        "last_full_audit": None,
        "last_release_baseline": None,
        "final_acceptance": None,
        "project_closure": None,
        "closure_history": [],
        "change_sequence": {"date": "", "last": 0},
        "updated_at": now_iso(),
    }


def load_project_state(root: Path) -> dict:
    path = root / PROJECT_STATE_FILE
    state = read_json(path, default=default_project_state())
    state = require_dict(state, str(path))
    merged = default_project_state()
    merged.update(state)
    if not isinstance(merged.get("stage_acceptance"), dict):
        merged["stage_acceptance"] = default_project_state()["stage_acceptance"]
    return merged


def save_project_state(root: Path, state: dict) -> None:
    state["updated_at"] = now_iso()
    write_json(root / PROJECT_STATE_FILE, state)


def ensure_project_open(root: Path, operation: str) -> dict:
    """Reject mutating development operations after terminal closure."""
    state = load_project_state(root)
    if state.get("project_status") == "closed":
        closure = state.get("project_closure") or {}
        raise SystemExit(
            f"项目已结案，不能执行 {operation}。如需继续开发，必须由项目所有者明确授权，"
            "并通过 ai-reopen-project 建立新的活动周期和新发布版本。"
            + (f" 最近结案：{closure.get('date')}。" if closure.get("date") else "")
        )
    return state


def empty_pending_changes() -> dict:
    return {"schema_version": "1.9.0", "changes": []}


def load_pending_changes(root: Path) -> dict:
    data = read_json(root / PENDING_CHANGES_FILE, default=empty_pending_changes())
    data = require_dict(data, str(root / PENDING_CHANGES_FILE))
    changes = data.get("changes", [])
    if not isinstance(changes, list) or any(not isinstance(item, dict) for item in changes):
        raise SystemExit("pending_changes.json 的 changes 必须是对象数组。")
    return {"schema_version": "1.9.0", "changes": changes}


def save_pending_changes(root: Path, data: dict) -> None:
    # Only unresolved changes live in runtime. Closed changes go to logs/decisions/Git.
    unresolved = [item for item in data.get("changes", []) if item.get("status") != "closed"]
    if unresolved:
        write_json(root / PENDING_CHANGES_FILE, {"schema_version": "1.9.0", "changes": unresolved})
    else:
        path = root / PENDING_CHANGES_FILE
        if path.exists():
            path.unlink()


def next_change_id(root: Path, existing: list[dict]) -> str:
    day = date.today().strftime("%Y%m%d")
    prefix = f"CHG-{day}-"
    nums = []
    for item in existing:
        match = re.fullmatch(re.escape(prefix) + r"(\d{3})", str(item.get("change_id", "")))
        if match:
            nums.append(int(match.group(1)))
    state = load_project_state(root)
    sequence = state.get("change_sequence", {})
    stored = int(sequence.get("last", 0)) if sequence.get("date") == day else 0
    number = max([stored, *nums], default=0) + 1
    state["change_sequence"] = {"date": day, "last": number}
    save_project_state(root, state)
    return prefix + f"{number:03d}"


def normalize_change_types(data: dict) -> list[str]:
    raw = data.get("change_types")
    if raw is None:
        single = str(data.get("change_type", "")).strip()
        raw = [single] if single else []
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise SystemExit("change_types 必须是字符串数组。")
    types = [item.strip() for item in raw if item.strip()]
    if not types:
        raise SystemExit("变更至少需要一个 change_type。")
    unknown = [item for item in types if item not in CHANGE_TYPE_MATRIX]
    if unknown:
        raise SystemExit("未知 change_type：" + ", ".join(unknown))
    return list(dict.fromkeys(types))


def required_categories_for(types: Iterable[str], extra: Iterable[str] = ()) -> list[str]:
    categories: list[str] = []
    for change_type in types:
        categories.extend(CHANGE_TYPE_MATRIX[change_type])
    categories.extend(extra)
    unknown = [item for item in categories if item not in MEMORY_DOCS]
    if unknown:
        raise SystemExit("未知文档类别：" + ", ".join(unknown))
    return list(dict.fromkeys(categories))


def register_change_data(root: Path, data: dict, *, source_default: str = "development") -> dict:
    pending = load_pending_changes(root)
    change_types = normalize_change_types(data)
    if governance_mode(root) == "lite":
        standard_only = sorted(set(change_types) & STANDARD_ONLY_CHANGE_TYPES)
        if standard_only:
            raise SystemExit(
                "以下变更类型表示项目已经超出 Lite 治理范围："
                + ", ".join(standard_only)
                + "。请由项目所有者授权并通过 ai-promote-standard 启用 Standard 治理。"
            )
    extra = str_list(data, "required_memory_categories")
    required = [category for category in required_categories_for(change_types, extra) if category != "project_memory" or category in extra]
    if governance_mode(root) == "lite":
        required = [
            category
            for category in required
            if (root / MEMORY_DOCS[category]).exists()
        ]
    change_id = str(data.get("change_id", "")).strip() or next_change_id(root, pending["changes"])
    if any(item.get("change_id") == change_id for item in pending["changes"]):
        raise SystemExit(f"变更 ID 已存在：{change_id}")
    active = read_json(root / ACTIVE_FILE, default={})
    if active and not isinstance(active, dict):
        active = {}
    change = {
        "change_id": change_id,
        "source": str(data.get("source", source_default)).strip() or source_default,
        "origin_batch_id": str(data.get("origin_batch_id", active.get("batch_id", ""))).strip(),
        "raw_feedback": require_text(data, "raw_feedback"),
        "change_types": change_types,
        "required_memory_categories": required,
        "affected_documents": [MEMORY_DOCS[item] for item in required],
        "affected_implementation": str_list(data, "affected_implementation"),
        "requires_reacceptance": bool(data.get("requires_reacceptance", True)),
        "status": "captured",
        "registered_at": now_iso(),
        "document_hashes_before": memory_hashes(root),
        "implementation_fingerprint_before": working_fingerprint(root),
        "document_writeback_verified_at": "",
        "implementation_submitted_at": "",
        "notes": str(data.get("notes", "")).strip(),
    }
    pending["changes"].append(change)
    save_pending_changes(root, pending)
    update_project_memory_auto(root)
    active_path = root / ACTIVE_FILE
    if active_path.exists():
        active_data = read_json(active_path, default={})
        if isinstance(active_data, dict):
            active_data["change_ids"] = sorted(set(active_data.get("change_ids", [])) | {change_id})
            write_json(active_path, active_data)
    return change


def validate_execution_threads(data: dict, execution_mode: str) -> list[dict]:
    raw = data.get("execution_threads", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise SystemExit("execution_threads 必须是对象数组。")
    normalized: list[dict] = []
    ids: set[str] = set()
    writable_paths: dict[str, str] = {}
    for item in raw:
        thread_id = str(item.get("thread_id", "")).strip()
        role = str(item.get("role", "code_executor")).strip()
        if not thread_id:
            raise SystemExit("每个 execution_thread 必须包含 thread_id。")
        if thread_id in ids:
            raise SystemExit(f"execution_threads.thread_id 重复：{thread_id}")
        ids.add(thread_id)
        if role not in {"analysis_review_agent", "code_executor"}:
            raise SystemExit("execution_threads.role 只能是 analysis_review_agent 或 code_executor。")
        scope = item.get("scope", [])
        if isinstance(scope, str):
            scope = [scope]
        if not isinstance(scope, list) or any(not isinstance(x, str) for x in scope) or not any(x.strip() for x in scope):
            raise SystemExit(f"执行线程 {thread_id} 必须包含非空 scope。")
        allowed_paths = item.get("allowed_paths", [])
        if not isinstance(allowed_paths, list) or any(not isinstance(x, str) for x in allowed_paths):
            raise SystemExit(f"执行线程 {thread_id} 的 allowed_paths 必须是字符串数组。")
        allowed_paths = [x.strip().replace("\\", "/") for x in allowed_paths if x.strip()]
        if role == "code_executor" and execution_mode == "parallel" and not allowed_paths:
            raise SystemExit(f"并行代码执行线程 {thread_id} 必须声明 allowed_paths。")
        if role == "analysis_review_agent" and allowed_paths:
            raise SystemExit(f"分析审核线程 {thread_id} 默认只读，不得声明 allowed_paths。")
        for path in allowed_paths:
            normalized_path = path.rstrip("/")
            for existing, owner in writable_paths.items():
                existing_path = existing.rstrip("/")
                if (
                    normalized_path == existing_path
                    or normalized_path.startswith(existing_path + "/")
                    or existing_path.startswith(normalized_path + "/")
                ):
                    raise SystemExit(
                        f"并行代码执行文件范围重叠：{path} 与 {existing} 分别属于 {thread_id} 和 {owner}。"
                    )
            writable_paths[path] = thread_id
        prohibited_paths = [
            x.strip().replace("\\", "/")
            for x in item.get("prohibited_paths", [])
            if isinstance(x, str) and x.strip()
        ]
        for allowed in allowed_paths:
            for prohibited in prohibited_paths:
                a = allowed.rstrip("/")
                b = prohibited.rstrip("/")
                if a == b or a.startswith(b + "/") or b.startswith(a + "/"):
                    raise SystemExit(f"执行线程 {thread_id} 的 allowed_paths 与 prohibited_paths 冲突：{allowed} / {prohibited}")
        normalized.append({
            "thread_id": thread_id,
            "role": role,
            "scope": [x.strip() for x in scope if x.strip()],
            "allowed_paths": allowed_paths,
            "prohibited_paths": prohibited_paths,
        })
    if execution_mode == "parallel" and len(normalized) < 2:
        raise SystemExit("parallel 执行模式至少需要两个 execution_threads。")
    if execution_mode == "single" and len(normalized) > 1:
        raise SystemExit("single 执行模式最多只能声明一个 execution_thread。")
    return normalized


def validate_request(data: dict) -> dict:
    execution_mode = str(data.get("execution_mode", "single")).strip().lower()
    if execution_mode not in {"single", "parallel"}:
        raise SystemExit("execution_mode 只能是 single 或 parallel。")
    out = {
        "batch_id": require_text(data, "batch_id"),
        "stage_id": require_text(data, "stage_id"),
        "stage_transition": bool(data.get("stage_transition", False)),
        "title": require_text(data, "title"),
        "goal": require_text(data, "goal"),
        "scope": str_list(data, "scope", required=True),
        "acceptance_criteria": str_list(data, "acceptance_criteria", required=True),
        "change_ids": str_list(data, "change_ids"),
        "risk_level": data.get("risk_level", "normal"),
        "requires_user_authorization": bool(data.get("requires_user_authorization", False)),
        "authorization_granted": bool(data.get("authorization_granted", False)),
        "authorization_note": str(data.get("authorization_note", "")).strip(),
        "execution_mode": execution_mode,
    }
    extension, api = context_extension()
    out.update(extension.batch_fields(find_root(), api, data))
    out["execution_threads"] = validate_execution_threads(data, execution_mode)
    if out["risk_level"] not in {"normal", "high"}:
        raise SystemExit("risk_level 只能是 normal 或 high。")
    if out["requires_user_authorization"] and not out["authorization_granted"]:
        raise SystemExit("本批需要用户授权，但批次请求未记录 authorization_granted=true。")
    if out["requires_user_authorization"] and not out["authorization_note"]:
        raise SystemExit("需要授权的批次必须记录 authorization_note。")
    return out


def validate_tests(data: dict) -> list[dict]:
    tests = data.get("tests", [])
    if not isinstance(tests, list) or any(not isinstance(x, dict) for x in tests):
        raise SystemExit("tests 必须是对象数组。")
    normalized = []
    for item in tests:
        name = str(item.get("name", "")).strip()
        status = str(item.get("status", "")).strip().lower()
        details = str(item.get("details", "")).strip()
        if not name:
            raise SystemExit("每个测试必须包含非空 name。")
        if status not in {"pass", "fail", "not_run", "blocked"}:
            raise SystemExit(f"测试 {name} 的状态无效：{status or '<missing>'}；只允许 pass/fail/not_run/blocked。")
        normalized.append({"name": name, "status": status, "details": details})
    return normalized


def validate_manager_review(data: dict, cfg: dict) -> dict:
    raw = data.get("manager_review", {})
    if not isinstance(raw, dict):
        raise SystemExit("manager_review 必须是对象。")
    status = str(raw.get("status", "")).strip().lower()
    required = bool(cfg.get("workflow", {}).get("require_manager_review", True))
    if required and status != "approved":
        raise SystemExit("批次关闭前需要项目经理复核并记录 manager_review.status=approved。")
    if status and status not in {"approved", "rejected", "not_required"}:
        raise SystemExit("manager_review.status 值无效。")
    reviewer = str(raw.get("reviewer", "")).strip()
    if status == "approved" and reviewer != "project_manager_agent":
        raise SystemExit("批准批次或完整审计时，manager_review.reviewer 必须声明角色 project_manager_agent。")
    return {
        "status": status or ("not_required" if not required else ""),
        "reviewer": reviewer,
        "note": str(raw.get("note", "")).strip(),
    }


def validate_integration_review(data: dict, execution_mode: str, cfg: dict) -> dict:
    raw = data.get("integration_review", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SystemExit("integration_review 必须是对象。")
    required = execution_mode == "parallel" and bool(
        cfg.get("role_policy", {}).get("integration_review_required_for_parallel_execution", True)
    )
    status = str(raw.get("status", "")).strip().lower()
    if required and status != "approved":
        raise SystemExit("并行代码执行必须记录 integration_review.status=approved。")
    if status and status not in {"approved", "rejected", "not_required"}:
        raise SystemExit("integration_review.status 值无效。")
    reviewer_role = str(raw.get("reviewer_role", "")).strip()
    if required and status == "approved" and reviewer_role != "integration_reviewer":
        raise SystemExit(
            "并行集成审核必须由 integration_reviewer 角色批准，"
            f"当前 reviewer_role={reviewer_role or '<missing>'}。"
        )
    if not required and status == "approved" and reviewer_role not in {"integration_reviewer", "project_manager_agent"}:
        raise SystemExit("integration_review.reviewer_role 必须是 integration_reviewer 或 project_manager_agent。")
    tests = validate_tests({"tests": raw.get("tests", [])})
    if required and not tests:
        raise SystemExit("integration_review 必须至少记录一项已实际执行的集成测试或检查。")
    if status == "approved":
        non_pass = [item for item in tests if item["status"] != "pass"]
        if non_pass:
            details = ", ".join(f"{item['name']}={item['status']}" for item in non_pass)
            raise SystemExit(
                "integration_review 只有在全部集成测试均为 pass 时才能批准；"
                f"当前未通过：{details}"
            )
    return {
        "status": status or ("not_required" if not required else ""),
        "reviewer_role": reviewer_role,
        "note": str(raw.get("note", "")).strip(),
        "tests": tests,
    }


def validate_result(data: dict, cfg: dict, execution_mode: str = "single") -> dict:
    status = require_text(data, "status").lower()
    if status not in {"pass", "partial", "blocked"}:
        raise SystemExit("status 只能是 pass、partial 或 blocked。")
    tests = validate_tests(data)
    blockers = str_list(data, "blockers")
    if status == "pass":
        if not tests:
            raise SystemExit("PASS 批次必须至少记录一项真实执行的测试或检查。")
        non_pass = [item for item in tests if item["status"] != "pass"]
        if non_pass:
            details = ", ".join(f"{item['name']}={item['status']}" for item in non_pass)
            raise SystemExit("PASS 批次的全部测试或检查必须为 pass；当前：" + details)
        if blockers:
            raise SystemExit("PASS 批次不得保留 blockers。")
    else:
        if not blockers:
            raise SystemExit(f"{status.upper()} 批次必须记录至少一个 blocker 或未完成原因。")
    memory = str_list(data, "memory_changes")
    unknown = [x for x in memory if x not in MEMORY_DOCS]
    if unknown:
        raise SystemExit("未知 memory_changes：" + ", ".join(unknown))
    manual = str(data.get("manual_acceptance", "not_required")).strip().lower()
    if manual not in {"not_required", "pending"}:
        raise SystemExit("batch_result.manual_acceptance 只能是 not_required 或 pending；用户通过必须经 ai-acceptance 单独记录。")
    if status != "pass" and manual != "not_required":
        raise SystemExit("PARTIAL/BLOCKED 只表示本次执行尚未完成，不能进入人工验收。")
    return {
        "batch_id": require_text(data, "batch_id"),
        "stage_id": require_text(data, "stage_id"),
        "title": require_text(data, "title"),
        "status": status,
        "summary": require_text(data, "summary"),
        "tests": tests,
        "next_task": str(data.get("next_task", "继续当前批次")).strip() or "继续当前批次",
        "blockers": blockers,
        "memory_changes": memory,
        "manual_acceptance": manual,
        "changed_files": str_list(data, "changed_files"),
        "change_ids": str_list(data, "change_ids"),
        "manager_review": validate_manager_review(data, cfg),
        "integration_review": validate_integration_review(data, execution_mode, cfg),
        "evidence_refs": str_list(data, "evidence_refs"),
        "checks": data.get("checks", {}),
    }


def format_tests(tests: list[dict]) -> str:
    if not tests:
        return "- 未运行（批次状态不要求）"
    return "\n".join(
        f"- {item['name']}：{item['status'].upper()}" + (f" — {item['details']}" if item["details"] else "")
        for item in tests
    )


def open_changes(root: Path) -> list[dict]:
    return load_pending_changes(root)["changes"]


def change_by_id(changes: list[dict], change_id: str) -> dict | None:
    return next((item for item in changes if item.get("change_id") == change_id), None)


def verify_memory_writeback(
    root: Path,
    active: dict,
    categories: Iterable[str],
    covered_categories: Iterable[str] = (),
) -> list[str]:
    warnings = []
    before = active.get("memory_hashes", {})
    covered = set(covered_categories)
    for category in categories:
        rel = MEMORY_DOCS[category]
        if memory_document_hash(root, category) == before.get(category) and category not in covered:
            warnings.append(f"声明影响 {category}，但 {rel} 未发生变化，也没有通过待处理变更的文档哈希验证。")
    return warnings


def handoff_text(
    root: Path,
    cfg: dict,
    snapshot: str,
    *,
    state: dict | None = None,
    changes: list[dict] | None = None,
    active: dict | None | object = _MISSING,
    suspended: dict | None | object = _MISSING,
) -> str:
    state = state or load_project_state(root)
    changes = open_changes(root) if changes is None else changes
    if active is _MISSING:
        active = read_json(root / ACTIVE_FILE, default=None)
    if suspended is _MISSING:
        suspended = read_json(root / SUSPENDED_PROMOTION_BATCH_FILE, default=None)
    mode = governance_mode(root, cfg)
    change_lines = "\n".join(
        f"- `{item.get('change_id')}`：{item.get('status')} — {item.get('raw_feedback')}"
        for item in changes
    ) or "- 无"
    active_line = "无" if not isinstance(active, dict) else f"`{active.get('batch_id')}` / {active.get('status', 'active')}"
    suspended_line = (
        "无"
        if not isinstance(suspended, dict)
        else f"`{suspended.get('batch_id')}` / 等待 Standard 基线审计后恢复"
    )
    baseline = standard_baseline_status(state)
    baseline_line = (
        "等待补全并审核"
        if baseline == "pending"
        else "已通过"
        if baseline == "passed"
        else "不适用"
    )
    reading = (
        "按 Lite 模式读取当前状态、需求、验收和决定，再读取当前任务相关代码"
        if mode == "lite"
        else "按 Standard 接管模式读取项目记忆摘要、当前状态和相关权威文档"
    )
    prompt = f"""# {cfg['project']['name']} 新窗口接管摘要

当前治理模式：`{mode}`。请读取项目根目录 `START_HERE.md`，{reading}。不要一次性加载全部历史。旧聊天可作为参考，但本地权威文档、代码、测试和 Git 状态负责校准事实。用户不负责输入维护命令。

## 优先恢复检查

- 活动批次：{active_line}
- 因治理升级挂起的批次：{suspended_line}
- Standard 升级基线：{baseline_line}
- 未关闭变更：
{change_lines}

Standard 升级基线为“等待补全并审核”时，必须先更新架构、开发计划和项目记忆，并完成一次 `ai-audit`；审计通过前不得继续批次。其他情况下，存在 `captured` 变更时必须先完成文档写回验证；存在其他未关闭变更时必须优先完成其实现、测试和重新验收。不得直接开始无关批次或进入下一阶段。

{snapshot}
"""
    return prompt


def make_handoff(root: Path, cfg: dict, snapshot: str) -> str:
    prompt = handoff_text(root, cfg, snapshot)
    path = root / HANDOFF_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prompt, encoding="utf-8", newline="\n")
    return prompt


def snapshot_text(result: dict, git: dict, blockers: str, pending_count: int) -> str:
    return f"""## 自动状态快照

- 更新时间：{now_iso()}
- 最近批次：`{result['batch_id']}` — {result['title']}
- 最近结果：{result['status'].upper()}
- 人工验收：{result['manual_acceptance'].upper()}
- Git 分支：{git['branch']}
- Git HEAD：{git['head']}
- 未关闭变更：{pending_count}
- 当前阻塞：{blockers}
- 下一批：{result['next_task']}
"""


def log_entry_payload(
    root: Path, cfg: dict, title: str, body: str, when: datetime | None = None
) -> tuple[Path, bytes]:
    when = when or datetime.now().astimezone()
    log = root / "docs" / "logs" / f"{when:%Y-%m}.md"
    if log.exists():
        current = log.read_text(encoding="utf-8")
    else:
        current = (
            f"# {cfg['project']['name']} 开发日志 — {when:%Y-%m}\n\n"
            "> 本文件按月追加历史批次。当前状态以 `../CURRENT_STATE.md` 为准。\n"
        )
    updated = current.rstrip() + f"\n\n## {when:%Y-%m-%d} — {title}\n\n{body.rstrip()}\n"
    return log, updated.encode("utf-8")


def append_log_entry(root: Path, cfg: dict, title: str, body: str, when: datetime | None = None) -> None:
    log, payload = log_entry_payload(root, cfg, title, body, when)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(payload)


def ai_resume(args: argparse.Namespace) -> int:
    root = find_root()
    cfg = load_config(root)
    state = load_project_state(root)
    changes = open_changes(root)
    active = read_json(root / ACTIVE_FILE, default=None)
    suspended = read_json(root / SUSPENDED_PROMOTION_BATCH_FILE, default=None)
    previous = read_json(root / CONTEXT_FILE, default=None)
    task = str(getattr(args, "task", "") or "").strip()
    mode = choose_context_mode(str(getattr(args, "mode", "auto") or "auto"), task, active if isinstance(active, dict) else None, changes)
    update_project_memory_auto(root, cfg)
    snapshot = extract_snapshot(root)
    plan = context_reading_plan(root, mode, task, active if isinstance(active, dict) else None, changes, previous)
    context = {
        "project": cfg["project"],
        "project_state": state,
        "git": git_info(root),
        "snapshot": snapshot,
        "active_batch": active if isinstance(active, dict) else None,
        "suspended_batch_for_promotion": (
            suspended if isinstance(suspended, dict) else None
        ),
        "pending_changes": changes,
        "priority": resume_priority(
            state,
            changes,
            active if isinstance(active, dict) else None,
            suspended if isinstance(suspended, dict) else None,
        ),
        "task": task,
        "reading_plan": plan,
        "document_hashes": plan["document_hashes"],
        "generated_at": now_iso(),
    }
    write_json(root / CONTEXT_FILE, context)
    make_handoff(root, cfg, snapshot)
    code = health(argparse.Namespace(json=False, quiet=True))
    if args.json:
        print(json.dumps(context, ensure_ascii=False, indent=2))
    else:
        print(f"AI_PROJECT_READY {cfg['project']['name']}")
        print(f"PRIORITY {context['priority']}")
        print(f"CONTEXT_MODE {mode.upper()}")
        print("MUST_READ " + " | ".join(plan["must_read"]))
        if plan["changed_since_previous_context"]:
            print("CHANGED " + " | ".join(plan["changed_since_previous_context"]))
        print(snapshot)
    return code


def ai_audit(args: argparse.Namespace) -> int:
    root = find_root()
    cfg = load_config(root)
    input_path = resolve_project_input(root, args.input, AUDIT_FILE)
    result = validate_full_audit(root, require_dict(read_json(input_path), str(input_path)), cfg)
    state = load_project_state(root)
    current_stage = str(state.get("current_stage", "")).strip()
    if current_stage and result["stage_id"] != current_stage:
        raise SystemExit("完整审计 stage_id 与当前阶段不一致。")
    record = {**result, "completed_at": now_iso(), "document_hashes": current_audit_hashes(root)}
    state["last_full_audit"] = record
    baseline_completed = (
        standard_baseline_status(state) == "pending"
        and result["status"] == "passed"
        and result.get("standard_baseline_completed") is True
    )
    suspended = read_json(root / SUSPENDED_PROMOTION_BATCH_FILE, default=None)
    if baseline_completed:
        baseline = copy.deepcopy(state.get("standard_baseline") or {})
        baseline.update(
            {
                "status": "passed",
                "completed_at": now_iso(),
                "summary": result["summary"],
                "evidence": result.get("standard_baseline_evidence", []),
            }
        )
        state["standard_baseline"] = baseline
        state["promotion_suspension"] = None
    state["updated_at"] = now_iso()
    log_path, log_payload = log_entry_payload(
        root, cfg, f"阶段 `{result['stage_id']}` 完整上下文审计",
        f"- 结果：{result['status'].upper()}\n- 摘要：{result['summary']}\n- 冲突：{'；'.join(result['conflicts']) or '无'}\n- 处理：{'；'.join(result['resolutions']) or '无'}",
    )
    payloads: list[tuple[Path, bytes | None]] = [
        (root / PROJECT_STATE_FILE, json_bytes(state)),
        (log_path, log_payload),
    ]
    if baseline_completed and isinstance(suspended, dict):
        resume_batch = suspended.get("active_batch")
        if suspended.get("resume_after_promotion", True):
            if not isinstance(resume_batch, dict):
                raise SystemExit("挂起记录缺少可恢复的 active_batch。")
            if (root / ACTIVE_FILE).exists():
                raise SystemExit("Standard 基线审计完成时发现另一个活动批次，拒绝覆盖。")
            payloads.append((root / ACTIVE_FILE, json_bytes(resume_batch)))
        payloads.append((root / SUSPENDED_PROMOTION_BATCH_FILE, None))
    atomic_file_transaction(payloads)
    update_project_memory_auto(root, cfg)
    if input_path.exists():
        input_path.unlink()
    if baseline_completed:
        # Regenerate context and handoff immediately so the next window sees the
        # completed baseline and any restored batch without a manual resume.
        ai_resume(
            argparse.Namespace(
                json=False,
                mode="full",
                task="继续 Standard 项目；优先恢复升级前挂起的批次",
            )
        )
        print(f"AI_STANDARD_BASELINE_READY {result['stage_id']}")
    print(f"AI_FULL_AUDIT_RECORDED {result['stage_id']} {result['status'].upper()}")
    return 0 if result["status"] == "passed" else 2


def ai_register_change(args: argparse.Namespace) -> int:
    root = find_root()
    ensure_project_open(root, "登记需求或验收变更")
    path = resolve_project_input(root, args.input, CHANGE_REQUEST_FILE)
    data = require_dict(read_json(path), str(path))
    change = register_change_data(root, data)
    if path.exists():
        path.unlink()
    print(f"AI_CHANGE_CAPTURED {change['change_id']} {'+'.join(change['change_types'])}")
    return 0


def ai_change_ready(args: argparse.Namespace) -> int:
    root = find_root()
    ensure_project_open(root, "验证文档写回")
    pending = load_pending_changes(root)
    change = change_by_id(pending["changes"], args.change_id)
    if not change:
        raise SystemExit(f"未找到待处理变更：{args.change_id}")
    if change.get("status") != "captured":
        raise SystemExit(f"变更 {args.change_id} 当前状态不是 captured：{change.get('status')}")

    current_impl = working_fingerprint(root)
    before_impl = change.get("implementation_fingerprint_before", {})
    if "__git_unavailable__" in before_impl or "__git_unavailable__" in current_impl:
        raise SystemExit("严格文档优先检查需要 Git 仓库。请由 AI 初始化 Git 后重试。")
    implementation_changes = fingerprint_changes(before_impl, current_impl)
    if implementation_changes:
        preview = ", ".join(implementation_changes[:12])
        raise SystemExit(
            "文档优先协议失败：登记变更后，以下实现文件已先发生变化：" + preview
            + "。请先恢复这些新增实现改动，完成文档写回验证后再修改代码。"
        )

    failures = []
    before_hashes = change.get("document_hashes_before", {})
    for category in change.get("required_memory_categories", []):
        rel = MEMORY_DOCS[category]
        current = memory_document_hash(root, category)
        if current is None:
            failures.append(f"缺少必需文档：{rel}")
        elif current == before_hashes.get(category):
            failures.append(f"文档未更新：{rel}")
    if failures:
        raise SystemExit("文档写回验证失败：\n- " + "\n- ".join(failures))

    change["status"] = "docs_ready"
    change["document_writeback_verified_at"] = now_iso()
    change["document_hashes_after"] = memory_hashes(root)
    change["implementation_fingerprint_after_docs"] = current_impl
    save_pending_changes(root, pending)
    update_project_memory_auto(root)
    print(f"AI_CHANGE_DOCS_READY {args.change_id}")
    return 0


def ai_start(args: argparse.Namespace) -> int:
    root = find_root()
    ensure_project_open(root, "启动开发批次")
    cfg = load_config(root)
    require_standard_baseline_ready(root, "启动开发批次")
    active_path = root / ACTIVE_FILE
    if active_path.exists():
        active = require_dict(read_json(active_path), str(active_path))
        raise SystemExit(f"已有活动批次：{active.get('batch_id', '未知')}。必须先通过唯一关闭流程完成，禁止强制覆盖。")

    request_path = resolve_project_input(root, args.request, REQUEST_FILE)
    request = validate_request(require_dict(read_json(request_path), str(request_path)))
    if request.get("execution_mode") == "parallel":
        require_standard_governance(root, "Parallel execution")
    if request.get("stage_transition") and governance_mode(root, cfg) == "lite":
        require_standard_governance(root, "Formal stage transition")
    pending_handoff = checked_pending_handoff(root)
    if pending_handoff:
        marker, record = pending_handoff
        if request["batch_id"] != marker["successor_batch_id"]:
            raise SystemExit("STANDARD_BATCH_HANDOFF_SUCCESSOR_REQUIRED: named successor is pending: " + marker["successor_batch_id"])
        contract = checked_successor_contract(root, {"path":record["successor_contract_path"], "sha256":record["successor_contract_sha256"], "successor_batch_id":marker["successor_batch_id"]}, record["source_batch_id"])
        if request != validate_request(contract):
            raise SystemExit("STANDARD_BATCH_HANDOFF_SUCCESSOR_CONTRACT_MISMATCH")
    changes = open_changes(root)
    captured = [item for item in changes if item.get("status") == "captured"]
    if captured:
        raise SystemExit("存在尚未完成文档写回的变更：" + ", ".join(item["change_id"] for item in captured))
    if changes:
        open_ids = {str(item.get("change_id")) for item in changes}
        requested = set(request["change_ids"])
        if requested != open_ids:
            raise SystemExit(
                "存在未关闭变更时，下一批必须优先处理全部变更。"
                f" 当前={sorted(open_ids)}，批次声明={sorted(requested)}"
            )
        not_ready = [item["change_id"] for item in changes if item.get("status") not in {"docs_ready", "rework_ready"}]
        if not_ready:
            raise SystemExit("以下变更尚未进入可实现状态：" + ", ".join(not_ready))

    state = load_project_state(root)
    current_stage = str(state.get("current_stage", "")).strip()
    if not current_stage:
        state["current_stage"] = request["stage_id"]
        state["stage_acceptance"] = {
            "stage_id": request["stage_id"], "status": "pending", "note": "", "updated_at": now_iso()
        }
    elif request["stage_id"] != current_stage:
        if not request["stage_transition"]:
            raise SystemExit("批次 stage_id 与当前阶段不同，必须显式声明 stage_transition=true。")
        if changes:
            raise SystemExit("存在未关闭变更，禁止进入下一阶段。")
        acceptance = state.get("stage_acceptance", {})
        if cfg.get("workflow", {}).get("manual_acceptance_before_stage_advance", True) and acceptance.get("status") != "passed":
            raise SystemExit(f"当前阶段 {current_stage} 尚未通过人工验收，禁止进入 {request['stage_id']}。")
        if cfg.get("context", {}).get("require_full_audit_before_stage_transition", True):
            audit = state.get("last_full_audit")
            if not isinstance(audit, dict) or audit.get("stage_id") != current_stage or not audit_is_current(root, audit):
                raise SystemExit(f"当前阶段 {current_stage} 尚未完成有效且未过期的完整上下文审计，禁止进入 {request['stage_id']}。")
        state["current_stage"] = request["stage_id"]
        state["stage_acceptance"] = {
            "stage_id": request["stage_id"], "status": "pending", "note": "", "updated_at": now_iso()
        }
    if not pending_handoff:
        save_project_state(root, state)

    active = {
        **request,
        "status": "active",
        "started_at": now_iso(),
        "git": git_info(root),
        "memory_hashes": memory_hashes(root),
        "implementation_fingerprint": working_fingerprint(root),
    }
    if pending_handoff:
        consume_batch_handoff(root, cfg, state, active, marker, record, request_path)
        args._handoff_transaction_complete = True
        print(f"AI_BATCH_STARTED {request['batch_id']} {request['title']}")
        return 0
    write_json(active_path, active)
    update_project_memory_auto(root, cfg)
    if request_path.exists():
        request_path.unlink()
    print(f"AI_BATCH_STARTED {request['batch_id']} {request['title']}")
    return 0


def mark_changes_submitted(root: Path, change_ids: list[str], manual_acceptance: str) -> None:
    if not change_ids:
        return
    pending = load_pending_changes(root)
    for change_id in change_ids:
        change = change_by_id(pending["changes"], change_id)
        if not change:
            raise SystemExit(f"批次结果引用了不存在的变更：{change_id}")
        if change.get("status") not in {"docs_ready", "rework_ready"}:
            raise SystemExit(f"变更 {change_id} 尚未完成文档优先验证：{change.get('status')}")
        change["implementation_submitted_at"] = now_iso()
        change["status"] = "awaiting_reacceptance" if change.get("requires_reacceptance", True) and manual_acceptance == "pending" else "implemented"
    save_pending_changes(root, pending)


def close_changes(root: Path, change_ids: list[str], note: str, manual_acceptance: str) -> list[str]:
    if not change_ids:
        return []
    pending = load_pending_changes(root)
    closed = []
    for change_id in change_ids:
        change = change_by_id(pending["changes"], change_id)
        if not change:
            raise SystemExit(f"准备关闭的变更不存在：{change_id}")
        status = change.get("status")
        allowed = status == "implemented" or (status == "awaiting_reacceptance" and manual_acceptance == "passed")
        if not allowed:
            raise SystemExit(f"变更 {change_id} 仍处于 {status}，没有完成实现和必要的重新验收，不能关闭。")
        change["status"] = "closed"
        change["closed_at"] = now_iso()
        change["closure_note"] = note
        closed.append(change_id)
    extension, api = context_extension()
    for change_id in closed:
        extension.archive(root, api, "changes", change_id, change_by_id(pending["changes"], change_id))
    save_pending_changes(root, pending)
    return closed


def record_incomplete_attempt(root: Path, cfg: dict, active: dict, result: dict, result_path: Path) -> int:
    """Record PARTIAL/BLOCKED without closing the batch or linked changes."""
    if "debug_checkpoint" in result:
        active["debug_checkpoint"] = result["debug_checkpoint"]
    active["status"] = result["status"]
    active["last_attempt_at"] = now_iso()
    active["last_attempt_summary"] = result["summary"]
    active["blockers"] = result["blockers"]
    write_json(root / ACTIVE_FILE, active)
    git = git_info(root)
    blockers = "；".join(result["blockers"])
    snapshot = snapshot_text(result, git, blockers, len(open_changes(root)))
    update_auto_block(root / "docs/CURRENT_STATE.md", snapshot)
    append_log_entry(
        root, cfg, f"`{result['batch_id']}` 未完成执行记录",
        f"- 状态：{result['status'].upper()}\n- 摘要：{result['summary']}\n- 测试：\n{format_tests(result['tests'])}\n- 阻塞：{blockers}\n- 处理：保持同一活动批次和关联变更，不得进入下一批。",
    )
    if result_path.exists():
        result_path.unlink()
    update_project_memory_auto(root, cfg)
    make_handoff(root, cfg, snapshot)
    print(f"AI_BATCH_REMAINS_OPEN {result['batch_id']} {result['status'].upper()}")
    return 1


def finalize_batch(root: Path, cfg: dict, active: dict, result: dict, *, acceptance_note: str = "") -> int:
    if result.get("status") != "pass":
        raise SystemExit("只有 PASS 批次可以进入关闭流程。")
    now = datetime.now().astimezone()
    closed_changes = close_changes(
        root, result["change_ids"], acceptance_note or "批次完成", result.get("manual_acceptance", "not_required")
    )
    remaining = open_changes(root)
    git = git_info(root)
    blockers = "；".join(result["blockers"]) if result["blockers"] else "无"
    snapshot = snapshot_text(result, git, blockers, len(remaining))
    update_auto_block(root / "docs/CURRENT_STATE.md", snapshot)
    memory_text = ", ".join(result["memory_changes"]) if result["memory_changes"] else "无"
    change_text = ", ".join(closed_changes) if closed_changes else "无"
    review = result["manager_review"]
    append_log_entry(
        root,
        cfg,
        f"`{result['batch_id']}`：{result['title']}",
        f"""- 结果：{result['status'].upper()}
- 阶段：{result['stage_id']}
- 人工验收：{result['manual_acceptance'].upper()}
- 项目经理复核：{review['status'].upper()} / {review['reviewer'] or '未注明'}
- 执行模式：{active.get('execution_mode', 'single').upper()}
- 集成审核：{result['integration_review']['status'].upper()} / {result['integration_review']['reviewer_role'] or '未注明'}
- Git 分支：{git['branch']}
- Git HEAD：{git['head']}
- 完成摘要：{result['summary']}
- 测试结果：
{format_tests(result['tests'])}
- 长期记忆影响：{memory_text}
- 已关闭变更：{change_text}
- 当前阻塞：{blockers}
- 下一批：{result['next_task']}""",
        now,
    )
    rotated = rotate_log_if_needed(root, cfg) if cfg.get("automation", {}).get("rotate_monthly_log", True) else None
    state = load_project_state(root)
    state["last_closed_batch"] = {
        "batch_id": result["batch_id"], "stage_id": result["stage_id"], "status": result["status"], "closed_at": now_iso()
    }
    state["last_manager_review"] = result["manager_review"]
    save_project_state(root, state)
    summary = {
        "batch_id": result["batch_id"],
        "stage_id": result["stage_id"],
        "title": result["title"],
        "status": result["status"],
        "manual_acceptance": result["manual_acceptance"],
        "completed_at": now_iso(),
        "git": git,
        "next_task": result["next_task"],
        "blockers": result["blockers"],
        "closed_changes": closed_changes,
        "remaining_changes": [item.get("change_id") for item in remaining],
        "rotated_log": rotated,
        "execution_mode": active.get("execution_mode", "single"),
        "integration_review": result["integration_review"],
    }
    write_json(root / LATEST_FILE, summary)
    for path in [root / ACTIVE_FILE, root / SUBMITTED_FILE, root / RESULT_FILE]:
        if path.exists():
            path.unlink()
    update_project_memory_auto(root, cfg)
    make_handoff(root, cfg, snapshot)
    code = health(argparse.Namespace(json=False, quiet=True))
    print(f"AI_BATCH_CLOSED {result['batch_id']} {result['status'].upper()}")
    return code


def ai_finish(args: argparse.Namespace) -> int:
    root = find_root()
    ensure_project_open(root, "提交批次结果")
    cfg = load_config(root)
    active = require_dict(read_json(root / ACTIVE_FILE), str(root / ACTIVE_FILE))
    result_path = resolve_project_input(root, args.result, RESULT_FILE)
    result = validate_result(
        require_dict(read_json(result_path), str(result_path)),
        cfg,
        str(active.get("execution_mode", "single")),
    )
    raw_result = require_dict(read_json(result_path), str(result_path))
    if "debug_checkpoint" in raw_result:
        extension, api = context_extension()
        result["debug_checkpoint"] = extension.checkpoint_fields(root, api, raw_result["debug_checkpoint"])
    if result["batch_id"] != active.get("batch_id") or result["title"] != active.get("title"):
        raise SystemExit("批次结果与活动批次不一致。")
    if result["stage_id"] != active.get("stage_id"):
        raise SystemExit("批次结果 stage_id 与活动批次不一致。")
    if set(result["change_ids"]) != set(active.get("change_ids", [])):
        raise SystemExit("批次结果 change_ids 必须与批次开始声明完全一致。")

    pending_now = load_pending_changes(root)
    covered_categories: set[str] = set()
    reacceptance_required = []
    for change_id in result["change_ids"]:
        change = change_by_id(pending_now["changes"], change_id)
        if change:
            covered_categories.update(change.get("required_memory_categories", []))
            if change.get("requires_reacceptance", True):
                reacceptance_required.append(change_id)
    memory_warnings = verify_memory_writeback(root, active, result["memory_changes"], covered_categories)
    if memory_warnings:
        raise SystemExit("长期记忆写回验证失败：\n- " + "\n- ".join(memory_warnings))
    if any(item["status"] == "fail" for item in result["tests"]) and result["status"] == "pass":
        raise SystemExit("存在失败测试时不能将批次标记为 PASS。")
    if result["status"] in {"partial", "blocked"}:
        return record_incomplete_attempt(root, cfg, active, result, result_path)
    if reacceptance_required and result["manual_acceptance"] != "pending":
        raise SystemExit("以下变更要求用户重新验收，manual_acceptance 必须为 pending：" + ", ".join(reacceptance_required))

    mark_changes_submitted(root, result["change_ids"], result["manual_acceptance"])
    if result["manual_acceptance"] == "pending":
        if "debug_checkpoint" in result:
            active["debug_checkpoint"] = result["debug_checkpoint"]
        active["status"] = "awaiting_acceptance"
        active["submitted_at"] = now_iso()
        write_json(root / ACTIVE_FILE, active)
        write_json(root / SUBMITTED_FILE, result)
        if result_path.exists():
            result_path.unlink()
        git = git_info(root)
        blockers = "；".join(result["blockers"]) if result["blockers"] else "等待用户人工验收"
        snapshot = snapshot_text(result, git, blockers, len(open_changes(root)))
        update_auto_block(root / "docs/CURRENT_STATE.md", snapshot)
        append_log_entry(
            root,
            cfg,
            f"`{result['batch_id']}` 提交人工验收",
            f"- 摘要：{result['summary']}\n- 测试：\n{format_tests(result['tests'])}\n- 待重新验收变更：{', '.join(result['change_ids']) or '无'}",
        )
        make_handoff(root, cfg, snapshot)
        update_project_memory_auto(root, cfg)
        print(f"AI_BATCH_AWAITING_ACCEPTANCE {result['batch_id']}")
        return 1

    # If no manual acceptance is needed, changes marked as implemented may close here.
    return finalize_batch(root, cfg, active, result, acceptance_note="批次无需人工验收或已记录通过")


def normalize_acceptance_changes(data: dict, note: str, active: dict | None) -> list[dict]:
    raw = data.get("changes", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise SystemExit("acceptance.changes 必须是对象数组。")
    if raw:
        return raw
    status = str(data.get("status", "")).lower()
    if status in {"failed", "pass_with_changes"}:
        return [{
            "source": "manual_acceptance",
            "origin_batch_id": active.get("batch_id", "") if active else "",
            "raw_feedback": note,
            "change_types": ["bug_fix" if status == "failed" else "requirement_change"],
            "affected_implementation": [],
            "requires_reacceptance": True,
        }]
    return []


def ai_acceptance(args: argparse.Namespace) -> int:
    root = find_root()
    ensure_project_open(root, "登记人工验收")
    cfg = load_config(root)
    path = resolve_project_input(root, args.input, ACCEPTANCE_FILE)
    data = require_dict(read_json(path), str(path))
    scope = str(data.get("scope", "batch")).strip().lower()
    status_value = require_text(data, "status").lower()
    if status_value not in {"passed", "failed", "pass_with_changes"}:
        raise SystemExit("验收 status 只能是 passed、failed 或 pass_with_changes。")
    note = require_text(data, "note")
    state = load_project_state(root)

    if scope == "stage":
        stage_id = require_text(data, "stage_id")
        if stage_id != state.get("current_stage"):
            raise SystemExit("stage_id 与当前阶段不一致。")
        if (root / ACTIVE_FILE).exists():
            raise SystemExit("存在活动批次，不能单独关闭阶段验收。")
        if status_value == "passed" and open_changes(root):
            raise SystemExit("存在未关闭变更，阶段验收不能通过。")
        if status_value != "passed":
            for item in normalize_acceptance_changes(data, note, None):
                register_change_data(root, item, source_default="stage_acceptance")
        state["stage_acceptance"] = {
            "stage_id": stage_id,
            "status": status_value,
            "note": note,
            "updated_at": now_iso(),
        }
        save_project_state(root, state)
        append_log_entry(root, cfg, f"阶段 `{stage_id}` 人工验收", f"- 结果：{status_value.upper()}\n- 说明：{note}")
        if path.exists():
            path.unlink()
        print(f"AI_STAGE_ACCEPTANCE_RECORDED {stage_id} {status_value.upper()}")
        return health(argparse.Namespace(json=False, quiet=True))

    if scope != "batch":
        raise SystemExit("acceptance.scope 只能是 batch 或 stage。")
    active = require_dict(read_json(root / ACTIVE_FILE), str(root / ACTIVE_FILE))
    if active.get("status") != "awaiting_acceptance":
        raise SystemExit("当前批次尚未进入 awaiting_acceptance 状态。")
    batch_id = require_text(data, "batch_id")
    if batch_id != active.get("batch_id"):
        raise SystemExit("人工验收 batch_id 与活动批次不一致。")
    submitted = require_dict(read_json(root / SUBMITTED_FILE), str(root / SUBMITTED_FILE))

    if status_value == "passed":
        submitted["manual_acceptance"] = "passed"
        stage_complete = bool(data.get("stage_complete", False))
        if path.exists():
            path.unlink()
        code = finalize_batch(root, cfg, active, submitted, acceptance_note=note)
        if stage_complete:
            if open_changes(root):
                raise SystemExit("仍有未关闭变更，不能将阶段标记为通过。")
            state = load_project_state(root)
            state["stage_acceptance"] = {
                "stage_id": active["stage_id"], "status": "passed", "note": note, "updated_at": now_iso()
            }
            save_project_state(root, state)
            update_project_memory_auto(root, cfg)
        print(f"AI_ACCEPTANCE_RECORDED {batch_id} PASSED")
        return code

    # Failed or pass-with-changes: capture feedback before any implementation rework.
    created = []
    for item in normalize_acceptance_changes(data, note, active):
        created.append(register_change_data(root, item, source_default="manual_acceptance"))
    active["status"] = "feedback_received"
    active["feedback_status"] = status_value
    active["feedback_received_at"] = now_iso()
    active["change_ids"] = sorted(set(active.get("change_ids", [])) | {item["change_id"] for item in created})
    write_json(root / ACTIVE_FILE, active)
    if (root / SUBMITTED_FILE).exists():
        (root / SUBMITTED_FILE).unlink()
    state["stage_acceptance"] = {
        "stage_id": active["stage_id"], "status": status_value, "note": note, "updated_at": now_iso()
    }
    save_project_state(root, state)
    append_log_entry(
        root,
        cfg,
        f"`{batch_id}` 人工验收反馈",
        f"- 结果：{status_value.upper()}\n- 说明：{note}\n- 已登记变更：{', '.join(item['change_id'] for item in created)}",
    )
    update_project_memory_auto(root, cfg)
    if path.exists():
        path.unlink()
    print(f"AI_ACCEPTANCE_CHANGES_CAPTURED {batch_id} {status_value.upper()} {' '.join(item['change_id'] for item in created)}")
    return 1


def ai_rework_ready(args: argparse.Namespace) -> int:
    """After acceptance feedback, verify all new changes reached docs_ready and reopen the same batch for implementation."""
    root = find_root()
    ensure_project_open(root, "开始验收返工")
    active = require_dict(read_json(root / ACTIVE_FILE), str(root / ACTIVE_FILE))
    if active.get("status") != "feedback_received":
        raise SystemExit("当前活动批次不是 feedback_received 状态。")
    pending = load_pending_changes(root)
    missing = []
    for change_id in active.get("change_ids", []):
        change = change_by_id(pending["changes"], change_id)
        if change and change.get("status") == "docs_ready":
            change["status"] = "rework_ready"
        elif change and change.get("status") in {"rework_ready", "implemented"}:
            continue
        elif change:
            missing.append(f"{change_id}:{change.get('status')}")
    if missing:
        raise SystemExit("以下验收变更尚未完成文档写回：" + ", ".join(missing))
    save_pending_changes(root, pending)
    active["status"] = "active"
    active["rework_started_at"] = now_iso()
    active["implementation_fingerprint"] = working_fingerprint(root)
    write_json(root / ACTIVE_FILE, active)
    update_project_memory_auto(root)
    print(f"AI_BATCH_REWORK_READY {active['batch_id']}")
    return 0


def pre_commit_check(_: argparse.Namespace) -> int:
    root = find_root()
    failures = []
    changes = open_changes(root)
    captured = [item for item in changes if item.get("status") == "captured"]
    if captured:
        failures.append("存在未完成文档写回的变更：" + ", ".join(item["change_id"] for item in captured))
    active = read_json(root / ACTIVE_FILE, default=None)
    if isinstance(active, dict) and active.get("status") == "feedback_received":
        failures.append("人工验收反馈已登记，但尚未完成文档优先验证。")
    if not is_git_repo(root):
        failures.append("未检测到 Git 仓库，无法执行严格提交前检查。")
    try:
        registry = load_requirement_registry(root)
        synced, mismatch = requirement_docs_are_synced(root, registry)
        if not synced:
            failures.append("需求登记表与生成文档不一致：" + "; ".join(mismatch))
    except SystemExit as exc:
        failures.append("需求登记或追踪机制错误：" + str(exc))
    if failures:
        print("PRE_COMMIT_REJECTED")
        for item in failures:
            print("FAIL", item)
        return 2
    print("PRE_COMMIT_OK")
    return 0


def install_hooks(_: argparse.Namespace) -> int:
    root = find_root()
    if not is_git_repo(root):
        raise SystemExit("未检测到 Git 仓库，无法安装 Hook。")
    try:
        subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=root, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Git Hook 配置失败：{exc}") from exc
    hook = root / ".githooks" / "pre-commit"
    if hook.exists():
        try:
            hook.chmod(hook.stat().st_mode | 0o111)
        except OSError:
            pass
    print("AI_GIT_HOOKS_INSTALLED .githooks")
    return 0


def file_stats(path: Path) -> tuple[int, float]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return len(text.splitlines()), path.stat().st_size / 1024


def markdown_links(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return re.findall(r"\[[^\]]+\]\(([^)]+\.md(?:#[^)]+)?)\)", text)


def health(args: argparse.Namespace) -> int:
    root = find_root()
    cfg = load_config(root)
    mode = governance_mode(root, cfg)
    passes: list[str] = []
    warnings: list[str] = []
    failures: list[str] = []
    try:
        checked_pending_handoff(root)
    except (SystemExit, OSError, ValueError, TypeError, KeyError) as exc:
        failures.append("STANDARD_BATCH_HANDOFF_INCONSISTENT: " + str(exc))
    passes.append("Lite 治理模式已启用" if mode == "lite" else "Standard 治理模式已启用")
    for rel in required_project_documents(cfg):
        if (root / rel).exists():
            passes.append("必需文件存在：" + rel)
        else:
            failures.append("缺少必需文件：" + rel)
    try:
        validate_standard_template_bundle(root, cfg)
        passes.append("Standard 治理扩展模板包结构、标记和哈希有效")
    except SystemExit as exc:
        failures.append("Standard 治理扩展模板包错误：" + str(exc))
    expected_mode_values = {
        "parallel_code_execution_allowed": mode == "standard",
        "release_baseline_required": mode == "standard",
        "require_final_acceptance_before_closure": mode == "standard",
    }
    actual_mode_values = {
        "parallel_code_execution_allowed": cfg.get("role_policy", {}).get(
            "parallel_code_execution_allowed"
        ),
        "release_baseline_required": cfg.get("requirement_policy", {}).get(
            "release_baseline_required"
        ),
        "require_final_acceptance_before_closure": cfg.get("automation", {}).get(
            "require_final_acceptance_before_closure"
        ),
    }
    inconsistent_mode_values = [
        key
        for key, expected_value in expected_mode_values.items()
        if actual_mode_values.get(key) is not expected_value
    ]
    expected_entry = "standard" if mode == "standard" else "light"
    if str(cfg.get("context", {}).get("default_entry_mode", "")) != expected_entry:
        inconsistent_mode_values.append("context.default_entry_mode")
    if inconsistent_mode_values:
        failures.append(
            "PROJECT.toml 治理模式能力口径不一致："
            + ", ".join(inconsistent_mode_values)
        )
    else:
        passes.append("PROJECT.toml 治理模式能力口径一致")
    ensure_month_log(root, cfg["project"]["name"])
    checks = [
        ("AGENTS.md", "agents_max_lines", "agents_max_kb", 120, 20),
        ("docs/ROLE_BOUNDARIES.md", "role_boundaries_max_lines", "role_boundaries_max_kb", 260, 35),
        ("docs/CURRENT_STATE.md", "current_state_max_lines", "current_state_max_kb", 250, 30),
        ("docs/PROJECT_MEMORY.md", "project_memory_max_lines", "project_memory_max_kb", 300, 30),
    ]
    for rel, line_key, kb_key, line_default, kb_default in checks:
        path = root / rel
        if not path.exists():
            continue
        lines, size = file_stats(path)
        (warnings if lines > read_limit(cfg, line_key, line_default) else passes).append(f"{rel} 行数：{lines}")
        if size > read_limit(cfg, kb_key, kb_default):
            warnings.append(f"{rel} 容量超限：{size:.1f} KB")
    sizes = {
        "docs/PROJECT_RULES.md": ("project_rules_max_kb", 60),
        "docs/PRODUCT_REQUIREMENTS.md": ("requirements_max_kb", 100),
        "docs/REQUIREMENT_CHANGELOG.md": ("requirement_changelog_max_kb", 100),
        "docs/REQUIREMENT_TRACEABILITY_MATRIX.md": ("traceability_max_kb", 100),
        "docs/ARCHITECTURE.md": ("architecture_max_kb", 80),
        "docs/DECISIONS.md": ("decisions_max_kb", 80),
        "docs/PITFALLS.md": ("pitfalls_max_kb", 60),
    }
    for rel, (key, default) in sizes.items():
        path = root / rel
        if not path.exists():
            continue
        size, limit = path.stat().st_size / 1024, read_limit(cfg, key, default)
        if size > limit:
            warnings.append(f"{rel} 容量超限：{size:.1f}/{limit} KB")
        elif size > limit * .8:
            warnings.append(f"{rel} 接近上限：{size:.1f}/{limit} KB")
        else:
            passes.append(f"{rel} 容量正常：{size:.1f} KB")
    placeholders = []
    for path in root.rglob("*.md"):
        if any(part.startswith(".git") for part in path.parts):
            continue
        if re.search(r"\{\{[A-Z0-9_]+\}\}", path.read_text(encoding="utf-8", errors="replace")):
            placeholders.append(str(path.relative_to(root)))
    if placeholders:
        failures.append("存在未替换模板变量：" + ", ".join(placeholders))
    else:
        passes.append("未发现未替换模板变量")
    expected_mode_label = (
        "治理模式：Lite 极简治理（`lite`）"
        if mode == "lite"
        else "治理模式：Standard 标准治理（`standard`）"
    )
    mode_label_mismatches = [
        rel
        for rel in ["START_HERE.md", "AGENTS.md", "README.md"]
        if not (root / rel).exists()
        or expected_mode_label not in (root / rel).read_text(
            encoding="utf-8", errors="replace"
        )
    ]
    if mode_label_mismatches:
        failures.append(
            "入口文档治理模式标签与 PROJECT.toml 不一致："
            + ", ".join(mode_label_mismatches)
        )
    else:
        passes.append("入口文档治理模式标签一致")
    role_doc = root / "docs/ROLE_BOUNDARIES.md"
    role_policy = cfg.get("role_policy", {})
    permission_cfg = cfg.get("permissions", {})
    if role_doc.exists() and all(label in role_doc.read_text(encoding="utf-8", errors="replace") for label in ["项目所有者", "项目经理主智能体", "分析／审核智能体", "代码执行器", "集成审核角色"]):
        passes.append("角色边界文档包含全部核心角色")
    elif mode == "standard":
        failures.append("ROLE_BOUNDARIES.md 缺少一个或多个核心角色定义")
    else:
        passes.append("Lite 模式使用 AGENTS.md 中的精简角色边界")
    if role_policy.get("single_active_project_manager") is True:
        passes.append("单一活跃项目经理规则已启用")
    else:
        failures.append("role_policy.single_active_project_manager 必须为 true")
    code_permissions = permission_cfg.get("code_executor", {}) if isinstance(permission_cfg, dict) else {}
    if code_permissions.get("may_change_requirements") is False and code_permissions.get("may_modify_shared_semantic_documents") is False:
        passes.append("代码执行器需求与共享语义文档越权已禁用")
    else:
        failures.append("代码执行器不得改变需求或直接修改共享语义文档")
    if role_policy.get("integration_review_required_for_parallel_execution") is True:
        passes.append("并行代码执行集成审核规则已启用")
    else:
        failures.append("并行代码执行必须要求集成审核")

    state_path = root / "docs/CURRENT_STATE.md"
    if state_path.exists() and AUTO_START in state_path.read_text(encoding="utf-8") and AUTO_END in state_path.read_text(encoding="utf-8"):
        passes.append("当前状态自动区标记完整")
    else:
        failures.append("CURRENT_STATE.md 自动区标记缺失")
    memory_path = root / "docs/PROJECT_MEMORY.md"
    if memory_path.exists() and MEMORY_AUTO_START in memory_path.read_text(encoding="utf-8") and MEMORY_AUTO_END in memory_path.read_text(encoding="utf-8"):
        passes.append("项目记忆摘要自动区标记完整")
    elif mode == "standard":
        failures.append("PROJECT_MEMORY.md 自动区标记缺失")
    else:
        passes.append("Lite 模式以 CURRENT_STATE.md 作为快速恢复入口")
    broken = []
    for path in root.rglob("*.md"):
        if any(part.startswith(".git") for part in path.parts):
            continue
        for link in markdown_links(path):
            raw = link.split("#", 1)[0]
            if raw.startswith(("http://", "https://", "mailto:")):
                continue
            if raw and not (path.parent / raw).resolve().exists():
                broken.append(f"{path.relative_to(root)} -> {link}")
    if broken:
        warnings.append("失效 Markdown 链接：" + "; ".join(broken[:10]))
    else:
        passes.append("Markdown 本地链接有效")
    runtime = root / RUNTIME_DIR
    runtime_files = [p for p in runtime.glob("*") if p.is_file() and p.name != ".gitkeep"] if runtime.exists() else []
    runtime_kb = sum(p.stat().st_size for p in runtime_files) / 1024
    runtime_max_files = read_limit(cfg, "runtime_max_files", 12)
    runtime_max_kb = read_limit(cfg, "runtime_max_kb", 1024)
    if len(runtime_files) > runtime_max_files or runtime_kb > runtime_max_kb:
        warnings.append(f"AI 临时区异常增长：{len(runtime_files)} 个文件 / {runtime_kb:.1f} KB")
    else:
        passes.append(f"AI 临时区正常：{len(runtime_files)} 个文件 / {runtime_kb:.1f} KB")

    changes = open_changes(root)
    captured = [item for item in changes if item.get("status") == "captured"]
    unresolved = [item for item in changes if item.get("status") != "captured"]
    if captured:
        failures.append("存在未完成文档写回的变更：" + ", ".join(item["change_id"] for item in captured))
    if unresolved:
        warnings.append("存在未关闭变更：" + ", ".join(f"{item['change_id']}:{item.get('status')}" for item in unresolved))
    if not changes:
        passes.append("无未关闭变更")

    active = read_json(root / ACTIVE_FILE, default=None)
    if isinstance(active, dict):
        warnings.append(f"存在活动批次：{active.get('batch_id')} / {active.get('status')}")
    git = git_info(root)
    if git["repository"] == "no":
        failures.append("未检测到 Git 仓库；V1.9.0 严格写回验证依赖 Git 工作区指纹。")
    else:
        passes.append("Git 仓库可用")
        hook_path = git_output(root, "config", "--get", "core.hooksPath")
        if hook_path == ".githooks":
            passes.append("Git Hook 路径已启用")
        else:
            warnings.append("Git Hook 尚未启用为 .githooks")
    project_state = load_project_state(root)
    if project_state.get("governance_mode") != mode:
        failures.append(
            "PROJECT.toml 与 project_state.json 的治理模式不一致："
            f"{mode} != {project_state.get('governance_mode')}"
        )
    else:
        passes.append(f"治理模式状态一致：{mode}")
    stage = project_state.get("current_stage") or "未设置"
    acceptance = project_state.get("stage_acceptance", {})
    passes.append(f"当前阶段：{stage}")
    if stage != "未设置" and acceptance.get("status") != "passed":
        warnings.append(f"当前阶段人工验收状态：{acceptance.get('status', '未知')}")
    audit = project_state.get("last_full_audit")
    if project_state.get("project_status") == "closed":
        passes.append("项目已结案；完整审计以最终发布基线中的冻结记录为准")
    elif mode == "lite":
        passes.append("Lite 模式不要求阶段切换完整审计；扩大项目前应先升级 Standard")
    elif standard_baseline_status(project_state) == "pending":
        warnings.append(
            "Lite→Standard 升级基线审计尚未完成；补全架构、开发计划和项目记忆前禁止启动批次。"
        )
    elif isinstance(audit, dict) and audit_is_current(root, audit):
        passes.append(f"最近完整审计有效：{audit.get('stage_id')} / {audit.get('completed_at')}")
    elif isinstance(audit, dict) and audit.get("status") == "passed":
        warnings.append("最近完整上下文审计已因当前事实文档变化而过期；阶段切换前必须重新审计。")
    else:
        warnings.append("当前尚无通过的完整上下文审计；仅在阶段切换前必须完成。")

    # V1.9.0 requirement registry and generated document consistency.
    try:
        registry = load_requirement_registry(root)
        requirement_count = len(registry.get("requirements", []))
        passes.append(f"需求登记表有效：{requirement_count} 项")
        synced, mismatches = requirement_docs_are_synced(root, registry)
        if synced:
            passes.append("需求、验收、修订台账和追踪矩阵与登记表一致")
        else:
            failures.extend(mismatches)
        active_incomplete = [
            req["current_version"]
            for req in registry.get("requirements", [])
            if req.get("status") == "active" and trace_state(req) != "COMPLETE"
        ]
        if mode == "lite" and requirement_count >= 6:
            warnings.append(
                f"Lite 项目已有 {requirement_count} 项正式需求；建议由项目所有者评估升级 Standard。"
            )
        if active_incomplete:
            warnings.append("尚未达到发布完成状态的 active 需求：" + ", ".join(active_incomplete))
        elif registry.get("requirements"):
            passes.append("当前所有 active 需求追踪完整")
        else:
            warnings.append("尚未登记正式需求；项目仍处于探索或基线建立阶段。")
    except SystemExit as exc:
        failures.append("需求登记或追踪机制错误：" + str(exc))

    state_release = project_state.get("last_release_baseline")
    if isinstance(state_release, dict):
        try:
            _, baseline = load_release_baseline(
                root, str(state_release.get("release_version", "")),
                allow_closed=project_state.get("project_status") == "closed",
            )
            passes.append(f"最近发布基线有效：{baseline.get('release_version')}")
            if delivery_verification_is_current(root, baseline):
                passes.append("最近客户交付文档验证有效")
            elif baseline.get("delivery_verification"):
                warnings.append("最近客户交付文档验证已过期或失败")
            else:
                warnings.append("发布基线已建立，但客户交付文档尚未验证")
        except SystemExit as exc:
            warnings.append("最近发布基线已失效：" + str(exc))

    result = {"pass": passes, "warn": warnings, "fail": failures}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif not args.quiet:
        print("\nProject Health Check")
        for item in passes:
            print("PASS ", item)
        for item in warnings:
            print("WARN ", item)
        for item in failures:
            print("FAIL ", item)
        print(f"\nSUMMARY PASS={len(passes)} WARN={len(warnings)} FAIL={len(failures)}")
    return 2 if failures else (1 if warnings else 0)


def extract_snapshot(root: Path) -> str:
    text = (root / "docs/CURRENT_STATE.md").read_text(encoding="utf-8")
    match = re.search(re.escape(AUTO_START) + r"(.*?)" + re.escape(AUTO_END), text, re.S)
    return match.group(1).strip() if match else "状态自动区无法解析。"


def status(_: argparse.Namespace) -> int:
    print(extract_snapshot(find_root()))
    return 0


def next_decision_id(text: str) -> str:
    prefix = f"DEC-{date.today():%Y%m%d}-"
    nums = [int(n) for n in re.findall(re.escape(prefix) + r"(\d{3})", text)]
    return prefix + f"{max(nums, default=0)+1:03d}"


def new_decision(args: argparse.Namespace) -> int:
    root = find_root()
    ensure_project_open(root, "新增项目决策")
    input_path = resolve_project_input(root, args.input, RUNTIME_DIR / "decision.json")
    data = require_dict(read_json(input_path), str(input_path))
    title, current, reason, impact = [require_text(data, k) for k in ["title", "current", "reason", "impact"]]
    old = str(data.get("old", "无")).strip() or "无"
    supersedes = str(data.get("supersedes", "无")).strip() or "无"
    path = root / "docs/DECISIONS.md"
    decision_id = next_decision_id(path.read_text(encoding="utf-8"))
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(f"\n\n## {decision_id}：{title}\n\n- 日期：{date.today().isoformat()}\n- 状态：生效\n- 原方案：{old}\n- 当前方案：{current}\n- 原因：{reason}\n- 影响范围：{impact}\n- 替代关系：{supersedes}\n")
    if input_path.exists():
        input_path.unlink()
    print(f"AI_DECISION_CREATED {decision_id}")
    return 0


def enable_doc(args: argparse.Namespace) -> int:
    root = find_root()
    ensure_project_open(root, "启用项目文档")
    cfg = load_config(root)
    names = PROFILE_DOCS.get(cfg["project"].get("profile", "generic"), []) if args.profile else (args.names or [])
    if args.list:
        for name, (path, _) in OPTIONAL_DOCS.items():
            print(f"{name:24} {path}")
        return 0
    if not names:
        return 0
    bad = [x for x in names if x not in OPTIONAL_DOCS]
    if bad:
        raise SystemExit("未知文档：" + ", ".join(bad))
    for name in names:
        rel, content = OPTIONAL_DOCS[name]
        path = root / rel
        if path.exists() and not args.force:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"AI_DOC_ENABLED {rel}")
    return 0


def rotate_log(_: argparse.Namespace) -> int:
    root = find_root()
    ensure_project_open(root, "轮转项目日志")
    cfg = load_config(root)
    archive = rotate_log_if_needed(root, cfg)
    print(f"AI_LOG_ROTATED {archive}" if archive else "AI_LOG_OK")
    return 0


def checked_evidence_ref(root: Path, value: dict) -> tuple[Path, dict]:
    """Local file/hash reference, not a claim of authenticated owner identity."""
    value = require_dict(value, "evidence reference")
    extension, _ = context_extension()
    rel = require_text(value, "path")
    extension.hard_file(root, rel)
    path = extension.safe_path(root, rel)
    if file_hash(path) != require_text(value, "sha256"):
        raise SystemExit("STANDARD_BATCH_HANDOFF_REFERENCE_HASH_MISMATCH")
    return path, {"path":path.relative_to(root).as_posix(), "sha256":file_hash(path)}


def checked_owner_authorization(root: Path, value: dict, source: str, successor: str) -> dict:
    value = require_dict(value, "owner_authorization")
    if value.get("granted") is not True or value.get("source_batch_id") != source or value.get("successor_batch_id") != successor:
        raise SystemExit("STANDARD_BATCH_HANDOFF_OWNER_BINDING_REQUIRED")
    _, ref = checked_evidence_ref(root, value.get("source_ref"))
    return {"source_batch_id":source, "successor_batch_id":successor, "granted":True,
            "source_ref":ref, "note":require_text(value, "note")}


def checked_successor_contract(root: Path, value: dict, source: str) -> dict:
    value = require_dict(value, "successor_contract")
    successor = require_text(value, "successor_batch_id")
    if successor == source:
        raise SystemExit("STANDARD_BATCH_HANDOFF_DISTINCT_SUCCESSOR_REQUIRED")
    path, _ = checked_evidence_ref(root, value)
    contract = require_dict(read_json(path), "successor batch request")
    if contract.get("batch_id") != successor or contract.get("status") != "planned":
        raise SystemExit("STANDARD_BATCH_HANDOFF_SUCCESSOR_IDENTITY_OR_STATUS")
    validate_request(contract)  # Reuse existing formal batch/task/context/risk contract.
    return contract


def checked_pending_handoff(root: Path):
    state = load_project_state(root)
    marker = read_json(root / PENDING_BATCH_HANDOFF_FILE, default=None)
    expected = state.get("pending_batch_handoff")
    if marker is None and not expected:
        return None
    marker = require_dict(marker, "pending named successor marker")
    if marker != expected or (root / ACTIVE_FILE).exists() or governance_mode(root) != "standard":
        raise SystemExit("STANDARD_BATCH_HANDOFF_MARKER_STATE_CONFLICT")
    hid = require_text(marker, "handoff_id")
    if not re.fullmatch(r"[0-9a-f]{32}", hid):
        raise SystemExit("STANDARD_BATCH_HANDOFF_INVALID_ID")
    expected_path = (BATCH_HANDOFF_HISTORY / hid / "record.json").as_posix()
    if marker.get("record_path") != expected_path:
        raise SystemExit("STANDARD_BATCH_HANDOFF_RECORD_PATH_MISMATCH")
    record_path, _ = checked_evidence_ref(root, {"path":expected_path, "sha256":marker.get("record_sha256")})
    record = require_dict(read_json(record_path), "batch_handoff/1")
    if record.get("schema") != "batch_handoff/1" or record.get("status") != "handed_off" or record.get("activation_status") != "pending_successor" or record.get("consumed_at") is not None or record.get("consumed_by_batch_id") is not None:
        raise SystemExit("STANDARD_BATCH_HANDOFF_NOT_PENDING")
    for key in ["handoff_id", "source_batch_id", "successor_batch_id", "source_active_snapshot_sha256"]:
        if record.get(key) != marker.get(key):
            raise SystemExit("STANDARD_BATCH_HANDOFF_IDENTITY_MISMATCH: " + key)
    snapshot_path, _ = checked_evidence_ref(root, {"path":(BATCH_HANDOFF_HISTORY / hid / "source_active.json").as_posix(), "sha256":record["source_active_snapshot_sha256"]})
    snapshot = require_dict(read_json(snapshot_path), "source snapshot")
    if snapshot.get("batch_id") != record["source_batch_id"] or snapshot.get("status") != record.get("source_status") or record.get("source_status") not in {"blocked", "partial"}:
        raise SystemExit("STANDARD_BATCH_HANDOFF_SOURCE_IDENTITY_MISMATCH")
    checked_owner_authorization(root, record["owner_authorization"], record["source_batch_id"], record["successor_batch_id"])
    checked_successor_contract(root, {"path":record["successor_contract_path"], "sha256":record["successor_contract_sha256"], "successor_batch_id":record["successor_batch_id"]}, record["source_batch_id"])
    return marker, record


def handoff_state_payloads(root: Path, cfg: dict, state: dict, active: dict | None) -> list:
    payloads = []
    memory = root / "docs/PROJECT_MEMORY.md"
    text = replace_project_memory_auto(memory.read_text(encoding="utf-8"), state, open_changes(root), active, None)
    payloads.append((memory, text.encode("utf-8")))
    extension, api = context_extension()
    extension.refresh(root, api, preview={"state":state, "active":active}, payloads=payloads)
    return payloads


def ai_handoff_batch(args: argparse.Namespace) -> int:
    root = find_root()
    require_standard_governance(root, "Standard non-success batch handoff")
    ensure_project_open(root, "Standard batch handoff")
    if (root / PENDING_BATCH_HANDOFF_FILE).exists() or load_project_state(root).get("pending_batch_handoff"):
        raise SystemExit("STANDARD_BATCH_HANDOFF_ALREADY_PENDING")
    active_path = root / ACTIVE_FILE
    active = require_dict(read_json(active_path), "active batch")
    if active.get("status") not in {"blocked", "partial"}:
        raise SystemExit("STANDARD_BATCH_HANDOFF_REQUIRES_BLOCKED_OR_PARTIAL")
    if open_changes(root):
        raise SystemExit("STANDARD_BATCH_HANDOFF_OPEN_CHANGES_BLOCKED")
    extension, api = context_extension()
    input_path = resolve_project_input(root, args.input, BATCH_HANDOFF_INPUT_FILE)
    if input_path.parent != (root / RUNTIME_DIR).resolve() or input_path.name in {ACTIVE_FILE.name, PENDING_BATCH_HANDOFF_FILE.name, CONTEXT_FILE.name, SUBMITTED_FILE.name}:
        raise SystemExit("STANDARD_BATCH_HANDOFF_INPUT_MUST_BE_RUNTIME_REQUEST")
    data = require_dict(read_json(input_path), "batch handoff request")
    source, successor = require_text(data, "source_batch_id"), require_text(data, "successor_batch_id")
    if require_text(data, "actor_role") != "project_manager_agent" or source != active.get("batch_id"):
        raise SystemExit("STANDARD_BATCH_HANDOFF_SOURCE_OR_ROLE_MISMATCH")
    state = load_project_state(root)
    if any(row.get("source_batch_id") == source for row in state.get("handoff_history", [])):
        raise SystemExit("STANDARD_BATCH_HANDOFF_SOURCE_ALREADY_TRANSFERRED")
    ref = require_dict(data.get("successor_contract"), "successor_contract")
    if ref.get("successor_batch_id") != successor:
        raise SystemExit("STANDARD_BATCH_HANDOFF_SUCCESSOR_IDENTITY_MISMATCH")
    checked_successor_contract(root, ref, source)
    _, ref = checked_evidence_ref(root, ref)
    authorization = checked_owner_authorization(root, data.get("owner_authorization"), source, successor)
    hid, stamp = uuid.uuid4().hex, now_iso()
    directory = root / BATCH_HANDOFF_HISTORY / hid
    if directory.exists():
        raise SystemExit("STANDARD_BATCH_HANDOFF_HISTORY_EXISTS")
    snapshot = active_path.read_bytes()
    git = git_info(root)
    record = {"schema":"batch_handoff/1", "handoff_id":hid, "status":"handed_off",
        "source_batch_id":source, "source_status":active["status"], "source_stage_id":active["stage_id"],
        "source_title":active["title"], "source_started_at":active["started_at"],
        "source_blockers":active.get("blockers", []), "source_active_snapshot_sha256":hashlib.sha256(snapshot).hexdigest(),
        "successor_batch_id":successor, "successor_contract_path":ref["path"], "successor_contract_sha256":ref["sha256"],
        "reason":require_text(data, "reason"), "unfinished_work":str_list(data, "unfinished_work", required=True),
        "transferred_obligations":str_list(data, "transferred_obligations", required=True),
        "owner_authorization":authorization, "git_head":git["head"], "git_branch":git["branch"],
        "handed_off_at":stamp, "activation_status":"pending_successor", "consumed_at":None, "consumed_by_batch_id":None}
    record_bytes = json_bytes(record)
    marker = {k:record[k] for k in ["handoff_id", "source_batch_id", "successor_batch_id", "source_active_snapshot_sha256"]}
    marker.update(record_path=(directory / "record.json").relative_to(root).as_posix(), record_sha256=hashlib.sha256(record_bytes).hexdigest())
    state["last_handed_off_batch"] = {"batch_id":source, "status":"handed_off", "source_status":active["status"], **marker}
    state.setdefault("handoff_history", []).append(dict(marker))
    state["pending_batch_handoff"] = marker
    state["updated_at"] = stamp
    log, content = log_entry_payload(root, cfg=load_config(root), title=f"{source} handed_off to {successor}", body=f"Source remains {active['status']}; not PASS / not acceptance.\nRecord: {marker['record_path']}")
    payloads = [(directory / "source_active.json", snapshot), (directory / "record.json", record_bytes),
                (root / PROJECT_STATE_FILE, json_bytes(state)), (log, content),
                (root / PENDING_BATCH_HANDOFF_FILE, json_bytes(marker))]
    payloads.extend(handoff_state_payloads(root, load_config(root), state, None))
    payloads.extend([(active_path, None), (input_path, None)])
    try:
        atomic_file_transaction(payloads, failure_environment="AI_STARTER_TEST_FAIL_BATCH_HANDOFF_AFTER")
    except BaseException as exc:
        raise SystemExit("STANDARD_BATCH_HANDOFF_TRANSACTION_FAILED; all files restored: " + str(exc)) from exc
    args._handoff_transaction_complete = True
    print("AI_BATCH_HANDED_OFF", source, successor, marker["record_path"])
    return 0


def consume_batch_handoff(root: Path, cfg: dict, state: dict, active: dict, marker: dict, record: dict, request_path: Path) -> None:
    request_path = request_path.resolve()
    contract_path = (root / record["successor_contract_path"]).resolve()
    if request_path != contract_path and request_path.parent != (root / RUNTIME_DIR).resolve():
        raise SystemExit("STANDARD_BATCH_HANDOFF_START_INPUT_MUST_BE_RUNTIME_OR_CONTRACT")
    checked_pending_handoff(root)  # Recheck immediately before preparing consumption.
    if open_changes(root):
        raise SystemExit("STANDARD_BATCH_HANDOFF_OPEN_CHANGES_BLOCKED")
    active["inherited_handoff"] = {"handoff_id":record["handoff_id"], "source_batch_id":record["source_batch_id"], "record_path":marker["record_path"],
        "unfinished_work":record["unfinished_work"], "transferred_obligations":record["transferred_obligations"], "source_blockers":record["source_blockers"],
        "source_evidence_ref":record["owner_authorization"]["source_ref"]}
    record = {**record, "activation_status":"consumed", "consumed_at":now_iso(), "consumed_by_batch_id":active["batch_id"]}
    record_bytes = json_bytes(record)
    record_hash = hashlib.sha256(record_bytes).hexdigest()
    # Keep durable navigation hashes current as activation metadata transitions.
    for entry in [state.get("last_handed_off_batch", {})] + state.get("handoff_history", []):
        if entry.get("handoff_id") == record["handoff_id"]:
            entry["record_sha256"] = record_hash
    state.pop("pending_batch_handoff", None)
    state["updated_at"] = now_iso()
    if active.get("layered_test_contract"):
        state["layered_test_contract"] = True
    log, content = log_entry_payload(root, cfg, "Named successor started: " + active["batch_id"], "Consumed handoff " + record["handoff_id"] + "; no PASS or acceptance inherited.")
    payloads = [(root / ACTIVE_FILE, json_bytes(active)), (root / marker["record_path"], record_bytes),
                (root / PROJECT_STATE_FILE, json_bytes(state)), (log, content)]
    payloads.extend(handoff_state_payloads(root, cfg, state, active))
    payloads.append((root / PENDING_BATCH_HANDOFF_FILE, None))
    if request_path.resolve() != (root / record["successor_contract_path"]).resolve():
        payloads.append((request_path, None))
    try:
        atomic_file_transaction(payloads, failure_environment="AI_STARTER_TEST_FAIL_HANDOFF_START_AFTER")
    except BaseException as exc:
        raise SystemExit("STANDARD_BATCH_HANDOFF_START_TRANSACTION_FAILED; all files restored: " + str(exc)) from exc


def ai_suspend_for_promotion(args: argparse.Namespace) -> int:
    root = find_root()
    cfg = load_config(root)
    if governance_mode(root, cfg) != "lite":
        raise SystemExit("只有 Lite 项目可以为治理升级挂起批次。")
    ensure_project_open(root, "为 Standard 升级挂起 Lite 批次")
    if (root / SUSPENDED_PROMOTION_BATCH_FILE).exists():
        raise SystemExit("已经存在等待治理升级的挂起批次，不能重复挂起。")
    active = require_dict(read_json(root / ACTIVE_FILE), str(root / ACTIVE_FILE))
    if str(active.get("status", "")).lower() not in {"blocked", "partial"}:
        raise SystemExit(
            "只有已经如实记录为 BLOCKED 或 PARTIAL 的 Lite 批次才能因治理升级挂起。"
        )
    input_path = resolve_project_input(root, args.input, GOVERNANCE_SUSPENSION_INPUT_FILE)
    data = require_dict(read_json(input_path), str(input_path))
    if require_text(data, "actor_role") != "project_manager_agent":
        raise SystemExit("治理升级挂起只能由项目经理主智能体执行。")
    if data.get("owner_authorization") is not True:
        raise SystemExit("挂起活动批次必须记录项目所有者 owner_authorization=true。")
    owner_note = require_text(data, "owner_note")
    reason = require_text(data, "reason")
    unfinished_work = str_list(data, "unfinished_work", required=True)
    test_status = require_text(data, "test_status")
    resume_after = data.get("resume_after_promotion", True)
    if not isinstance(resume_after, bool):
        raise SystemExit("resume_after_promotion 必须为布尔值。")
    changes = open_changes(root)
    active_change_ids = set(str(item) for item in active.get("change_ids", []))
    open_change_ids = set(str(item.get("change_id")) for item in changes)
    if open_change_ids != active_change_ids:
        raise SystemExit(
            "活动批次与未关闭变更集合不一致，拒绝挂起："
            f"batch={sorted(active_change_ids)}, open={sorted(open_change_ids)}"
        )
    suspended_at = now_iso()
    record = {
        "schema_version": "1.9.0",
        "batch_id": str(active.get("batch_id", "")),
        "batch_status": str(active.get("status", "")),
        "suspended_at": suspended_at,
        "reason": reason,
        "owner_note": owner_note,
        "recorded_by_role": "project_manager_agent",
        "unfinished_work": unfinished_work,
        "test_status": test_status,
        "resume_after_promotion": resume_after,
        "pending_change_ids": sorted(open_change_ids),
        "git": git_info(root),
        "implementation_fingerprint": working_fingerprint(root),
        "active_batch": active,
    }
    state = load_project_state(root)
    state["promotion_suspension"] = {
        key: record[key]
        for key in [
            "batch_id",
            "batch_status",
            "suspended_at",
            "reason",
            "owner_note",
            "unfinished_work",
            "test_status",
            "resume_after_promotion",
            "pending_change_ids",
        ]
    }
    state["updated_at"] = suspended_at
    log_path, log_payload = log_entry_payload(
        root,
        cfg,
        f"`{record['batch_id']}` 为 Standard 升级安全挂起",
        f"- 原状态：{record['batch_status'].upper()}\n"
        f"- 项目所有者授权：{owner_note}\n"
        f"- 原因：{reason}\n"
        f"- 未完成内容：{'；'.join(unfinished_work)}\n"
        f"- 测试状态：{test_status}\n"
        f"- 升级审计后恢复：{'是' if resume_after else '否'}\n"
        "- 处理：保留当前实现、Git 指纹、未关闭变更和原批次记录，不宣称完成。",
    )
    try:
        atomic_file_transaction(
            [
                (root / SUSPENDED_PROMOTION_BATCH_FILE, json_bytes(record)),
                (root / PROJECT_STATE_FILE, json_bytes(state)),
                (log_path, log_payload),
                (root / ACTIVE_FILE, None),
            ],
            failure_environment="AI_STARTER_TEST_FAIL_GOVERNANCE_SUSPENSION_AFTER",
        )
    except BaseException as exc:
        raise SystemExit(
            f"governance suspension transaction failed; all files were restored: {exc}"
        ) from exc
    if input_path.exists():
        input_path.unlink()
    snapshot = extract_snapshot(root)
    make_handoff(root, cfg, snapshot)
    print(f"AI_BATCH_SUSPENDED_FOR_PROMOTION {record['batch_id']}")
    return 0


def promoted_project_toml_bytes(path: Path, promoted_at: str) -> bytes:
    text = path.read_text(encoding="utf-8")
    section_pattern = re.compile(r"(^\[governance\]\s*\n)(.*?)(?=^\[|\Z)", re.M | re.S)
    match = section_pattern.search(text)
    if not match:
        raise SystemExit("PROJECT.toml 缺少 [governance] 配置。")
    section = match.group(2)
    if not re.search(r'^mode\s*=\s*"lite"\s*$', section, re.M):
        raise SystemExit("PROJECT.toml 当前不是 lite 治理模式。")
    section = re.sub(r'^mode\s*=\s*"lite"\s*$', 'mode = "standard"', section, count=1, flags=re.M)
    if re.search(r'^promoted_at\s*=.*$', section, re.M):
        section = re.sub(
            r'^promoted_at\s*=.*$',
            f"promoted_at = {json.dumps(promoted_at)}",
            section,
            count=1,
            flags=re.M,
        )
    else:
        section += f"promoted_at = {json.dumps(promoted_at)}\n"
    updated = text[:match.start(2)] + section + text[match.end(2):]
    replacements = {
        r'(?m)^parallel_code_execution_allowed\s*=\s*false\s*$':
            "parallel_code_execution_allowed = true",
        r'(?m)^default_entry_mode\s*=\s*"light"\s*$':
            'default_entry_mode = "standard"',
        r'(?m)^release_baseline_required\s*=\s*false\s*$':
            "release_baseline_required = true",
        r'(?m)^require_final_acceptance_before_closure\s*=\s*false\s*$':
            "require_final_acceptance_before_closure = true",
    }
    for pattern, replacement in replacements.items():
        updated, count = re.subn(pattern, replacement, updated, count=1)
        if count != 1:
            raise SystemExit(
                "PROJECT.toml Lite 能力配置缺失，无法安全切换为 Standard："
                + replacement.split("=", 1)[0].strip()
            )
    tomllib.loads(updated)
    return updated.encode("utf-8")


def promoted_mode_document_bytes(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r"(?m)^- 治理模式：.*$",
        "- 治理模式：Standard 标准治理（`standard`）",
        text,
        count=1,
    )
    if count != 1:
        raise SystemExit("入口文档缺少治理模式标签：" + path.name)
    return updated.encode("utf-8")


def ai_promote_standard(args: argparse.Namespace) -> int:
    root = find_root()
    cfg = load_config(root)
    if governance_mode(root, cfg) != "lite":
        raise SystemExit("Project already uses Standard governance; downgrade is not supported.")
    ensure_project_open(root, "升级为 Standard 治理")
    if isinstance(read_json(root / ACTIVE_FILE, default=None), dict):
        raise SystemExit(
            "存在活动批次。若批次已因治理复杂度 BLOCKED/PARTIAL，"
            "请先由项目所有者授权并执行 ai-suspend-for-promotion；"
            "不得伪造 PASS 或手工删除运行状态。"
        )
    suspended = read_json(root / SUSPENDED_PROMOTION_BATCH_FILE, default=None)
    if suspended is not None and not isinstance(suspended, dict):
        raise SystemExit("治理升级挂起记录必须是对象。")
    changes = open_changes(root)
    if changes and not isinstance(suspended, dict):
        raise SystemExit(
            "存在未关闭变更，必须先处理后再升级 Standard："
            + ", ".join(str(item.get("change_id")) for item in changes)
        )
    if isinstance(suspended, dict):
        expected_change_ids = set(
            str(item) for item in suspended.get("pending_change_ids", [])
        )
        actual_change_ids = set(str(item.get("change_id")) for item in changes)
        if actual_change_ids != expected_change_ids:
            raise SystemExit(
                "挂起后未关闭变更集合发生漂移，拒绝升级："
                f"suspended={sorted(expected_change_ids)}, "
                f"current={sorted(actual_change_ids)}"
            )

    input_path = resolve_project_input(root, args.input, GOVERNANCE_PROMOTION_INPUT_FILE)
    data = require_dict(read_json(input_path), str(input_path))
    if require_text(data, "actor_role") != "project_manager_agent":
        raise SystemExit("治理模式升级只能由项目经理主智能体执行。")
    if data.get("owner_authorization") is not True:
        raise SystemExit("升级 Standard 必须记录项目所有者 owner_authorization=true。")
    owner_note = require_text(data, "owner_note")
    reason = require_text(data, "reason")

    bundle = validate_standard_template_bundle(root, cfg)
    files = bundle["files"]
    expected = set(str(item) for item in cfg.get("documents", {}).get("standard_required", []))

    promoted_at = now_iso()
    state = load_project_state(root)
    history = state.get("governance_history", [])
    if not isinstance(history, list):
        raise SystemExit("project_state.json governance_history 必须为数组。")
    updated_state = copy.deepcopy(state)
    updated_state["governance_mode"] = "standard"
    updated_state["standard_baseline"] = {
        "status": "pending",
        "promoted_at": promoted_at,
        "completed_at": "",
        "summary": "",
        "suspended_batch_id": (
            str(suspended.get("batch_id", ""))
            if isinstance(suspended, dict)
            else ""
        ),
    }
    updated_state["last_full_audit"] = None
    updated_state["governance_history"] = [
        *history,
        {
            "from": "lite",
            "to": "standard",
            "at": promoted_at,
            "reason": reason,
            "owner_note": owner_note,
            "recorded_by_role": "project_manager_agent",
        },
    ]
    updated_state["updated_at"] = promoted_at

    project_toml_path = root / "PROJECT.toml"
    promoted_toml = promoted_project_toml_bytes(project_toml_path, promoted_at)
    promoted_cfg = tomllib.loads(promoted_toml.decode("utf-8"))
    payloads: list[tuple[Path, bytes | None]] = []
    for rel in sorted(expected):
        relative = Path(rel)
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit("Standard 治理扩展模板包含不安全路径：" + rel)
        target = (root / relative).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as exc:
            raise SystemExit("Standard 治理扩展模板路径逃出项目根目录：" + rel) from exc
        content = files[rel]
        if rel == "docs/PROJECT_MEMORY.md":
            source_text = (
                target.read_text(encoding="utf-8")
                if target.exists()
                else content
            )
            content = replace_project_memory_auto(
                source_text,
                updated_state,
                changes,
                None,
                suspended if isinstance(suspended, dict) else None,
            )
            payloads.append((target, content.encode("utf-8")))
        elif not target.exists():
            payloads.append((target, content.encode("utf-8")))

    for rel in ["START_HERE.md", "AGENTS.md", "README.md"]:
        payloads.append((root / rel, promoted_mode_document_bytes(root / rel)))

    log_path, log_payload = log_entry_payload(
        root,
        cfg,
        "治理模式升级为 Standard",
        f"- 项目所有者授权：{owner_note}\n"
        f"- 原因：{reason}\n"
        "- 处理：保留原 Git、需求编号、需求历史和项目目录，启用 Standard 文档与门禁。\n"
        "- 后续：项目进入 Standard 基线待审计状态；架构、计划、记忆和当前代码完成核对前不得继续批次。",
    )
    snapshot = extract_snapshot(root)
    handoff = handoff_text(
        root,
        promoted_cfg,
        snapshot,
        state=updated_state,
        changes=changes,
        active=None,
        suspended=suspended if isinstance(suspended, dict) else None,
    )
    must_read = list(
        dict.fromkeys(
            [
                "START_HERE.md",
                "AGENTS.md",
                "PROJECT.toml",
                ".ai/AUTOMATION_CONTRACT.md",
                *[
                    rel
                    for rel in CORE_CURRENT_DOCS
                    if (root / rel).exists() or rel in expected
                ],
            ]
        )
    )
    context = {
        "project": promoted_cfg["project"],
        "project_state": updated_state,
        "git": git_info(root),
        "snapshot": snapshot,
        "active_batch": None,
        "suspended_batch_for_promotion": (
            suspended if isinstance(suspended, dict) else None
        ),
        "pending_changes": changes,
        "priority": "complete_standard_baseline_audit",
        "task": "补全并审核 Lite→Standard 升级基线",
        "reading_plan": {
            "mode": "full",
            "must_read": must_read,
            "read_if_relevant": [],
            "changed_since_previous_context": sorted(expected),
            "prefer_diff_for_changed_files": True,
            "do_not_read_by_default": [
                "docs/logs/（除非追溯具体历史）",
                "完整 Git 历史（除非定位回归来源）",
            ],
            "document_hashes": {},
        },
        "document_hashes": {},
        "generated_at": promoted_at,
    }
    payloads.extend([
        (project_toml_path, promoted_toml),
        (root / PROJECT_STATE_FILE, json_bytes(updated_state)),
        (log_path, log_payload),
        (root / CONTEXT_FILE, json_bytes(context)),
        (root / HANDOFF_FILE, handoff.encode("utf-8")),
    ])
    try:
        atomic_file_transaction(
            payloads,
            failure_environment="AI_STARTER_TEST_FAIL_GOVERNANCE_PROMOTION_AFTER",
        )
    except BaseException as exc:
        raise SystemExit(
            f"governance promotion transaction failed; all files were restored: {exc}"
        ) from exc

    if input_path.exists():
        input_path.unlink()
    print("AI_GOVERNANCE_PROMOTED standard")
    return 0



# ---------------------------------------------------------------------------
# V1.9.0 requirement versioning, traceability, release and delivery
# ---------------------------------------------------------------------------

REQ_ID_RE = re.compile(r"^R-(\d{3,})$")
REQ_VERSION_RE = re.compile(r"^R-(\d{3,})\.(\d+)$")
ALLOWED_REQUIREMENT_STATUS = {"draft", "active", "deferred", "removed"}
ALLOWED_PRIORITY = {"must", "should", "could"}
ALLOWED_CATEGORY = {"functional", "nonfunctional", "constraint", "ui", "data", "security", "operations"}
ALLOWED_CRITERION_METHOD = {"manual", "automatic", "both"}
ALLOWED_CRITERION_STATUS = {"draft", "pending", "pass", "fail", "waived"}
ALLOWED_MANUAL_STATUS = {"not_started", "pending", "passed", "rejected", "not_required", "waived"}
LINK_ALLOWED_FIELDS = {
    "actor_role",
    "action",
    "requirement_id",
    "expected_current_version",
    "implementation_refs",
    "test_refs",
    "manual_acceptance",
    "acceptance_criteria",
}
LINK_CRITERION_ALLOWED_FIELDS = {"id", "status", "evidence", "note"}
LINK_MANUAL_ACCEPTANCE_ALLOWED_FIELDS = {"status", "date", "note"}
REVISION_SNAPSHOT_FIELDS = {
    "version", "date", "title", "status", "category", "priority", "description",
    "rationale", "source", "reason", "change_id", "customer_visible",
    "release_blocking", "release_target", "acceptance_criteria",
    "user_instructions", "user_instructions_verified", "help_notes",
    "known_limitations", "notes",
}
REVISION_CRITERION_FIELDS = {"id", "description", "method", "status", "evidence", "note"}
DELIVERY_REQUIRED_FILES = [
    "USER_MANUAL.md",
    "HELP_AND_FAQ.md",
    "FINAL_ACCEPTANCE_REPORT.md",
    "PROJECT_CLOSURE_REPORT.md",
    "DELIVERY_CHECKLIST.md",
    "RELEASE_NOTES.md",
]
CUSTOMER_DOC_INTERNAL_TERMS = [
    "项目经理主智能体", "分析／审核智能体", "代码执行器", "集成审核角色",
    ".ai/runtime", "Git Hook", "pre-commit", "batch_request.json", "pending_changes.json",
]
PLACEHOLDER_PATTERNS = [r"待补充", r"TODO", r"TBD", r"\{\{[A-Z0-9_]+\}\}", r"\[待[^\]]*\]"]


def auto_region_bytes(path: Path, start: str, end: str, body: str) -> bytes:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        raise SystemExit(f"自动生成区标记缺失：{path}")
    replacement = f"{start}\n{body.rstrip()}\n{end}"
    updated = pattern.sub(lambda _: replacement, text, count=1)
    updated.encode("utf-8").decode("utf-8")
    return updated.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def replace_auto_region(path: Path, start: str, end: str, body: str) -> None:
    _write_bytes_atomically(path, auto_region_bytes(path, start, end, body))


def md_cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, list):
        value = "<br>".join(str(x) for x in value if str(x).strip())
    text = str(value).strip() or "—"
    return text.replace("|", "\\|").replace("\n", "<br>")


def requirement_semantic_projection(data: dict) -> dict:
    """Return fields that may change only through a numbered requirement revision."""
    return {
        "title": data.get("title", ""),
        "status": data.get("status", ""),
        "category": data.get("category", ""),
        "priority": data.get("priority", ""),
        "module": data.get("module", ""),
        "summary": data.get("summary", ""),
        "architecture_refs": data.get("architecture_refs", []),
        "decision_refs": data.get("decision_refs", []),
        "description": data.get("description", ""),
        "rationale": data.get("rationale", ""),
        "customer_visible": bool(data.get("customer_visible", True)),
        "release_blocking": bool(data.get("release_blocking", True)),
        "release_target": data.get("release_target", ""),
        "acceptance_criteria": [
            {
                "id": item.get("id", ""),
                "description": item.get("description", ""),
                "method": item.get("method", ""),
            }
            for item in data.get("acceptance_criteria", [])
            if isinstance(item, dict)
        ],
        "user_instructions": data.get("user_instructions", ""),
        "user_instructions_verified": bool(data.get("user_instructions_verified", False)),
        "help_notes": data.get("help_notes", []),
        "known_limitations": data.get("known_limitations", []),
        "notes": data.get("notes", []),
    }


def load_requirement_registry(root: Path) -> dict:
    data = require_dict(read_json(root / REQUIREMENT_REGISTRY_FILE), str(root / REQUIREMENT_REGISTRY_FILE))
    if data.get("schema_version") != "1.9.0":
        raise SystemExit("需求登记表 schema_version 必须为 1.9.0。")
    if not isinstance(data.get("next_requirement_number"), int) or data["next_requirement_number"] < 1:
        raise SystemExit("next_requirement_number 必须是正整数。")
    requirements = data.get("requirements")
    if not isinstance(requirements, list):
        raise SystemExit("requirements 必须是数组。")
    validate_requirement_registry(data)
    return data


def validate_requirement_registry(data: dict) -> None:
    ids: set[str] = set()
    versions: set[str] = set()
    criterion_ids: set[str] = set()
    max_num = 0
    for req in data.get("requirements", []):
        if not isinstance(req, dict):
            raise SystemExit("需求登记项必须是对象。")
        req_id = str(req.get("requirement_id", ""))
        match = REQ_ID_RE.fullmatch(req_id)
        if not match:
            raise SystemExit(f"非法需求永久编号：{req_id}")
        num = int(match.group(1)); max_num = max(max_num, num)
        if req_id in ids:
            raise SystemExit(f"重复需求永久编号：{req_id}")
        ids.add(req_id)
        revision = req.get("current_revision")
        current_version = str(req.get("current_version", ""))
        if not isinstance(revision, int) or revision < 1 or current_version != f"{req_id}.{revision}":
            raise SystemExit(f"需求版本字段不一致：{req_id}")
        if current_version in versions:
            raise SystemExit(f"重复需求版本：{current_version}")
        versions.add(current_version)
        if req.get("status") not in ALLOWED_REQUIREMENT_STATUS:
            raise SystemExit(f"需求 {current_version} 状态非法：{req.get('status')}")
        if req.get("priority") not in ALLOWED_PRIORITY:
            raise SystemExit(f"需求 {current_version} 优先级非法：{req.get('priority')}")
        if req.get("category") not in ALLOWED_CATEGORY:
            raise SystemExit(f"需求 {current_version} 类别非法：{req.get('category')}")
        release_target = str(req.get("release_target", "")).strip()
        if release_target:
            try:
                parse_release_version(release_target)
            except SystemExit as exc:
                raise SystemExit(
                    f"需求 {current_version} release_target 非法，必须是 SemVer：{release_target}；{exc}"
                ) from exc
        revisions = req.get("revisions", [])
        if not isinstance(revisions, list) or len(revisions) != revision:
            raise SystemExit(f"需求 {req_id} 修订历史数量与当前修订号不一致。")
        expected = [f"{req_id}.{n}" for n in range(1, revision + 1)]
        actual = [str(item.get("version", "")) for item in revisions if isinstance(item, dict)]
        if actual != expected:
            raise SystemExit(f"需求 {req_id} 修订历史版本不连续：{actual}")
        for snapshot in revisions:
            if not isinstance(snapshot, dict):
                raise SystemExit(f"需求 {req_id} 修订历史项必须是对象。")
            missing_snapshot_fields = sorted(REVISION_SNAPSHOT_FIELDS - set(snapshot))
            if missing_snapshot_fields:
                raise SystemExit(
                    f"需求 {snapshot.get('version', req_id)} 修订快照缺少完整语义字段："
                    + ", ".join(missing_snapshot_fields)
                )
            if not isinstance(snapshot.get("acceptance_criteria"), list):
                raise SystemExit(
                    f"需求 {snapshot.get('version')} 修订快照 acceptance_criteria 必须是数组。"
                )
            for historical_criterion in snapshot["acceptance_criteria"]:
                if not isinstance(historical_criterion, dict):
                    raise SystemExit(
                        f"需求 {snapshot.get('version')} 历史验收条件必须是对象。"
                    )
                missing_criterion_fields = sorted(
                    REVISION_CRITERION_FIELDS - set(historical_criterion)
                )
                if missing_criterion_fields:
                    raise SystemExit(
                        f"需求 {snapshot.get('version')} 历史验收条件缺少字段："
                        + ", ".join(missing_criterion_fields)
                    )
            for list_field in ["help_notes", "known_limitations", "notes"]:
                if not isinstance(snapshot.get(list_field), list):
                    raise SystemExit(
                        f"需求 {snapshot.get('version')} 修订快照 {list_field} 必须是数组。"
                    )
        if requirement_semantic_projection(req) != requirement_semantic_projection(revisions[-1]):
            raise SystemExit(
                f"需求 {current_version} current semantic fields differ from the latest revision snapshot; "
                "register a real change and use revise instead of editing the registry directly."
            )
        criteria = req.get("acceptance_criteria", [])
        if not isinstance(criteria, list):
            raise SystemExit(f"需求 {current_version} acceptance_criteria 必须是数组。")
        for item in criteria:
            if not isinstance(item, dict):
                raise SystemExit(f"需求 {current_version} 验收条件必须是对象。")
            cid = str(item.get("id", ""))
            if not re.fullmatch(rf"AC-R{re.escape(req_id[2:])}-\d{{2}}", cid):
                raise SystemExit(f"需求 {current_version} 验收编号非法：{cid}")
            if cid in criterion_ids:
                raise SystemExit(f"重复验收编号：{cid}")
            criterion_ids.add(cid)
            if item.get("method") not in ALLOWED_CRITERION_METHOD:
                raise SystemExit(f"验收条件 {cid} method 非法。")
            if item.get("status") not in ALLOWED_CRITERION_STATUS:
                raise SystemExit(f"验收条件 {cid} status 非法。")
            if item.get("status") == "waived" and not str(item.get("note", "")).strip():
                raise SystemExit(f"验收条件 {cid} 标记为 waived 时必须填写批准理由 note。")
        manual = req.get("manual_acceptance", {})
        if not isinstance(manual, dict) or manual.get("status", "not_started") not in ALLOWED_MANUAL_STATUS:
            raise SystemExit(f"需求 {current_version} manual_acceptance 非法。")
    if data.get("next_requirement_number", 1) <= max_num:
        raise SystemExit("next_requirement_number 必须大于已使用的最大需求编号。")


def save_requirement_registry(root: Path, data: dict) -> None:
    data["updated_at"] = now_iso()
    validate_requirement_registry(data)
    payloads = [(root / REQUIREMENT_REGISTRY_FILE, json_bytes(data))]
    payloads.extend(requirement_document_payloads(root, data))
    extension, api = context_extension()
    index = extension.build_index(root, api, registry=data)
    if governance_mode(root) == "standard":
        payloads.append((root / extension.INDEX, extension.encoded(index)))
    try:
        atomic_file_transaction(
            payloads,
            failure_environment="AI_STARTER_TEST_FAIL_REQUIREMENT_TRANSACTION_AFTER",
        )
    except BaseException as exc:
        raise SystemExit(
            f"requirement transaction failed; registry and generated documents were restored: {exc}"
        ) from exc


def requirement_sort_key(req: dict) -> tuple[int, int]:
    match = REQ_ID_RE.fullmatch(req["requirement_id"])
    return (int(match.group(1)) if match else 999999, int(req.get("current_revision", 0)))


def normalize_criteria(req_id: str, raw: Any, existing: list[dict] | None = None) -> list[dict]:
    if raw is None:
        return [dict(item) for item in (existing or [])]
    if not isinstance(raw, list):
        raise SystemExit("acceptance_criteria 必须是数组。")
    existing_by_id = {str(item.get("id")): dict(item) for item in (existing or [])}
    used: set[str] = set()
    result: list[dict] = []
    next_no = 1
    for item in raw:
        if isinstance(item, str):
            item = {"description": item}
        if not isinstance(item, dict):
            raise SystemExit("验收条件必须是字符串或对象。")
        cid = str(item.get("id", "")).strip()
        if cid:
            if cid not in existing_by_id and not re.fullmatch(rf"AC-R{re.escape(req_id[2:])}-\d{{2}}", cid):
                raise SystemExit(f"验收编号格式错误：{cid}")
        else:
            while f"AC-R{req_id[2:]}-{next_no:02d}" in used or f"AC-R{req_id[2:]}-{next_no:02d}" in existing_by_id:
                next_no += 1
            cid = f"AC-R{req_id[2:]}-{next_no:02d}"
            next_no += 1
        if cid in used:
            raise SystemExit(f"本次输入重复验收编号：{cid}")
        used.add(cid)
        base = existing_by_id.get(cid, {})
        description = str(item.get("description", base.get("description", ""))).strip()
        if not description:
            raise SystemExit(f"验收条件 {cid} 缺少 description。")
        method = str(item.get("method", base.get("method", "both"))).strip().lower()
        status = str(item.get("status", base.get("status", "pending"))).strip().lower()
        if method not in ALLOWED_CRITERION_METHOD or status not in ALLOWED_CRITERION_STATUS:
            raise SystemExit(f"验收条件 {cid} 的 method/status 非法。")
        evidence = str(item.get("evidence", base.get("evidence", ""))).strip()
        note = str(item.get("note", base.get("note", ""))).strip()
        if status == "waived" and not note:
            raise SystemExit(f"验收条件 {cid} 标记为 waived 时必须填写批准理由 note。")
        result.append({
            "id": cid,
            "description": description,
            "method": method,
            "status": status,
            "evidence": evidence,
            "note": note,
        })
    return result


def normalize_link_criteria(raw: Any, existing: list[dict]) -> list[dict]:
    """Update only acceptance evidence fields while preserving semantic definitions."""
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise SystemExit("link.acceptance_criteria 必须是对象数组。")
    existing_by_id = {str(item.get("id", "")): copy.deepcopy(item) for item in existing}
    updated = [copy.deepcopy(item) for item in existing]
    updated_by_id = {str(item.get("id", "")): item for item in updated}
    seen: set[str] = set()
    for item in raw:
        forbidden = sorted(set(item) - LINK_CRITERION_ALLOWED_FIELDS)
        if forbidden:
            names = ", ".join(f"acceptance_criteria.{name}" for name in forbidden)
            raise SystemExit(f"link 禁止修改语义字段：{names}；请登记真实变更并使用 revise。")
        cid = require_text(item, "id")
        if cid in seen:
            raise SystemExit(f"link.acceptance_criteria 重复引用验收编号：{cid}")
        seen.add(cid)
        if cid not in existing_by_id:
            raise SystemExit(f"link 只能更新现有验收条件的证据，不能新增验收条件：{cid}；请使用 revise。")
        target = updated_by_id[cid]
        if "status" in item:
            status = str(item.get("status", "")).strip().lower()
            if status not in ALLOWED_CRITERION_STATUS:
                raise SystemExit(f"验收条件 {cid} 的 status 非法：{status}")
            target["status"] = status
        if "evidence" in item:
            target["evidence"] = str(item.get("evidence", "")).strip()
        if "note" in item:
            target["note"] = str(item.get("note", "")).strip()
        if target.get("status") == "waived" and not str(target.get("note", "")).strip():
            raise SystemExit(f"验收条件 {cid} 标记为 waived 时必须填写批准理由 note。")
    return updated


def normalized_manual_acceptance(raw: Any, existing: dict | None = None) -> dict:
    base = dict(existing or {"status": "not_started", "date": "", "note": ""})
    if raw is None:
        return base
    if not isinstance(raw, dict):
        raise SystemExit("manual_acceptance 必须是对象。")
    status = str(raw.get("status", base.get("status", "not_started"))).strip().lower()
    if status not in ALLOWED_MANUAL_STATUS:
        raise SystemExit("manual_acceptance.status 非法。")
    note = str(raw.get("note", base.get("note", ""))).strip()
    if status in {"waived", "rejected"} and not note:
        raise SystemExit(f"manual_acceptance.status={status} 时必须提供 note。")
    return {
        "status": status,
        "date": str(raw.get("date", base.get("date", ""))).strip(),
        "note": note,
    }


def revision_snapshot(req: dict, *, version: str, source: str, reason: str, change_id: str) -> dict:
    snapshot = {
        "version": version,
        "date": date.today().isoformat(),
        "title": req["title"],
        "status": req["status"],
        "category": req["category"],
        "priority": req["priority"],
        "module": req.get("module", ""),
        "summary": req.get("summary", ""),
        "architecture_refs": req.get("architecture_refs", []),
        "decision_refs": req.get("decision_refs", []),
        "description": req["description"],
        "rationale": req.get("rationale", ""),
        "source": source,
        "reason": reason,
        "change_id": change_id,
        "customer_visible": bool(req.get("customer_visible", True)),
        "release_blocking": bool(req.get("release_blocking", True)),
        "release_target": req.get("release_target", ""),
        "acceptance_criteria": req.get("acceptance_criteria", []),
        "user_instructions": req.get("user_instructions", ""),
        "user_instructions_verified": bool(req.get("user_instructions_verified", False)),
        "help_notes": req.get("help_notes", []),
        "known_limitations": req.get("known_limitations", []),
        "notes": req.get("notes", []),
    }
    return copy.deepcopy(snapshot)


def find_requirement(
    registry: dict, identifier: str, *, expected_current_version: str | None = None, require_exact_version: bool = False
) -> dict:
    identifier = identifier.strip()
    base = identifier.split(".", 1)[0]
    requested_version = identifier if "." in identifier else ""
    for req in registry.get("requirements", []):
        if req.get("requirement_id") != base:
            continue
        expected = (expected_current_version or requested_version).strip()
        if require_exact_version and not expected:
            raise SystemExit(
                f"修改需求 {base} 时必须提供 expected_current_version，防止旧窗口覆盖较新的需求版本。"
            )
        if expected and expected != req.get("current_version"):
            raise SystemExit(
                f"需求版本冲突：调用方预期 {expected}，当前实际为 {req.get('current_version')}。"
                "请重新读取最新需求后再操作。"
            )
        return req
    raise SystemExit(f"未找到需求：{identifier}")


def require_open_requirement_change(root: Path, change_id: str) -> dict:
    if not change_id:
        raise SystemExit("需求语义修订必须关联真实存在的未关闭 change_id。")
    pending = load_pending_changes(root)
    change = change_by_id(pending["changes"], change_id)
    if not change:
        raise SystemExit(f"需求修订引用的变更不存在或已经关闭：{change_id}")
    if change.get("status") not in {"captured", "docs_ready", "rework_ready"}:
        raise SystemExit(f"需求修订引用的变更状态不允许写入：{change_id}={change.get('status')}")
    required = set(change.get("required_memory_categories", []))
    if not required.intersection({"requirements", "acceptance", "requirement_changelog", "traceability"}):
        raise SystemExit(f"变更 {change_id} 未声明会影响正式需求或验收，不能用于需求语义修订。")
    return change


def trace_state(req: dict) -> str:
    status = req.get("status")
    if status == "deferred":
        return "DEFERRED"
    if status == "removed":
        return "REMOVED"
    if status == "draft":
        return "DRAFT"
    criteria = req.get("acceptance_criteria", [])
    if not criteria:
        return "DRAFT"
    if not req.get("implementation_refs"):
        return "UNIMPLEMENTED"
    if any(item.get("status") == "fail" for item in criteria):
        return "BLOCKED"
    if not req.get("test_refs") or any(item.get("status") not in {"pass", "waived"} for item in criteria):
        return "UNTESTED"
    manual = req.get("manual_acceptance", {}).get("status", "not_started")
    if manual not in {"passed", "not_required", "waived"}:
        return "AWAITING_ACCEPTANCE"
    return "COMPLETE"


def render_requirement_catalog(registry: dict) -> str:
    requirements = sorted(registry.get("requirements", []), key=requirement_sort_key)
    if not requirements:
        return "尚未登记正式需求。项目经理主智能体应在需求确认后通过需求登记流程创建 `R-001.1` 起的正式需求。"
    sections: list[str] = []
    labels = {"active": "当前生效", "draft": "待确认草案", "deferred": "已批准延期", "removed": "已移出范围"}
    for status in ["active", "draft", "deferred", "removed"]:
        group = [req for req in requirements if req.get("status") == status]
        if not group:
            continue
        sections.append(f"### {labels[status]}")
        for req in group:
            refs = ", ".join(f"`{item['id']}`" for item in req.get("acceptance_criteria", [])) or "尚未定义"
            sections.append(
                f"#### {req['current_version']}：{req['title']}\n\n"
                f"- 永久编号：`{req['requirement_id']}`\n"
                f"- 模块：{req.get('module') or req['category']}\n"
                f"- 摘要：{req.get('summary') or '—'}\n"
                f"- 架构引用：{md_cell(req.get('architecture_refs', []))}\n"
                f"- 决策引用：{md_cell(req.get('decision_refs', []))}\n"
                f"- 状态：{req['status']}\n"
                f"- 类别：{req['category']}\n"
                f"- 优先级：{req['priority']}\n"
                f"- 发布阻断：{'是' if req.get('release_blocking', True) else '否'}\n"
                f"- 客户可见：{'是' if req.get('customer_visible', True) else '否'}\n"
                f"- 目标版本：{req.get('release_target') or '未指定'}\n"
                f"- 最后变更：{req.get('change_id') or req.get('source') or '初始登记'}\n"
                f"- 验收引用：{refs}\n\n"
                f"{req['description'].strip()}"
            )
    return "\n\n".join(sections)


def render_acceptance_catalog(registry: dict) -> str:
    rows = ["| 验收 ID | 当前需求版本 | 验收条件 | 方式 | 状态 | 证据 |", "|---|---|---|---|---|---|"]
    for req in sorted(registry.get("requirements", []), key=requirement_sort_key):
        for item in req.get("acceptance_criteria", []):
            rows.append("| " + " | ".join([
                md_cell(item.get("id")), md_cell(req.get("current_version")), md_cell(item.get("description")),
                md_cell(item.get("method")), md_cell(item.get("status")), md_cell(item.get("evidence")),
            ]) + " |")
    return "\n".join(rows) if len(rows) > 2 else "尚未登记正式验收条件。"


def render_requirement_changelog(registry: dict) -> str:
    sections: list[str] = []
    for req in sorted(registry.get("requirements", []), key=requirement_sort_key):
        for rev in req.get("revisions", []):
            display_status = req.get("status") if rev.get("version") == req.get("current_version") else "superseded"
            criterion_lines = []
            for item in rev.get("acceptance_criteria", []):
                criterion_lines.append(
                    f"- `{item.get('id', '—')}`\n"
                    f"  - 描述：{item.get('description') or '—'}\n"
                    f"  - 方法：{item.get('method') or '—'}\n"
                    f"  - 当时状态：{item.get('status') or '—'}\n"
                    f"  - 当时证据：{item.get('evidence') or '—'}\n"
                    f"  - 备注：{item.get('note') or '—'}"
                )
            sections.append(
                f"### {rev.get('version')}：{rev.get('title')}\n\n"
                f"- 日期：{rev.get('date') or '—'}\n"
                f"- 历史状态：{display_status}\n"
                f"- 需求状态：{rev.get('status') or '—'}\n"
                f"- 类别／优先级：{rev.get('category') or '—'} / {rev.get('priority') or '—'}\n"
                f"- 来源：{rev.get('source') or '—'}\n"
                f"- 关联变更：{rev.get('change_id') or '—'}\n"
                f"- 修订原因：{rev.get('reason') or '—'}\n"
                f"- 模块／摘要：{rev.get('module') or '—'} / {rev.get('summary') or '—'}\n"
                f"- 架构／决策：{md_cell(rev.get('architecture_refs', []))} / {md_cell(rev.get('decision_refs', []))}\n"
                f"- 客户可见：{'是' if rev.get('customer_visible', True) else '否'}\n"
                f"- 发布阻断：{'是' if rev.get('release_blocking', True) else '否'}\n"
                f"- 发布目标：{rev.get('release_target') or '未指定'}\n\n"
                "#### 需求语义\n\n"
                f"- 正文：{rev.get('description') or '—'}\n"
                f"- 理由：{rev.get('rationale') or '—'}\n\n"
                "#### 验收语义\n\n"
                + ("\n".join(criterion_lines) if criterion_lines else "- 尚未定义验收条件")
                + "\n\n#### 用户交付语义\n\n"
                f"- 用户操作说明：{rev.get('user_instructions') or '—'}\n"
                f"- 说明已核对：{'是' if rev.get('user_instructions_verified') else '否'}\n"
                f"- 帮助说明：{md_cell(rev.get('help_notes', []))}\n"
                f"- 已知限制：{md_cell(rev.get('known_limitations', []))}\n"
                f"- 需求备注：{md_cell(rev.get('notes', []))}"
            )
    return "\n\n".join(sections) if sections else "尚无正式需求修订记录。"


def render_traceability_matrix(registry: dict) -> str:
    rows = [
        "| 当前需求 | 状态 | 优先级 | 验收条件 | 实现位置 | 测试证据 | 人工验收 | 目标版本 | 追踪状态 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for req in sorted(registry.get("requirements", []), key=requirement_sort_key):
        criteria = [f"{x.get('id')}:{x.get('status')}" for x in req.get("acceptance_criteria", [])]
        manual = req.get("manual_acceptance", {})
        rows.append("| " + " | ".join([
            md_cell(req.get("current_version")), md_cell(req.get("status")), md_cell(req.get("priority")),
            md_cell(criteria), md_cell(req.get("implementation_refs", [])), md_cell(req.get("test_refs", [])),
            md_cell(f"{manual.get('status', 'not_started')} {manual.get('date', '')}".strip()),
            md_cell(req.get("release_target") or "未指定"), md_cell(trace_state(req)),
        ]) + " |")
    return "\n".join(rows) if len(rows) > 2 else "尚无可追踪需求。"


def requirement_document_payloads(root: Path, registry: dict) -> list[tuple[Path, bytes]]:
    return [
        (
            root / "docs/PRODUCT_REQUIREMENTS.md",
            auto_region_bytes(
                root / "docs/PRODUCT_REQUIREMENTS.md",
                REQ_CATALOG_START,
                REQ_CATALOG_END,
                render_requirement_catalog(registry),
            ),
        ),
        (
            root / "docs/ACCEPTANCE_CRITERIA.md",
            auto_region_bytes(
                root / "docs/ACCEPTANCE_CRITERIA.md",
                ACCEPTANCE_CATALOG_START,
                ACCEPTANCE_CATALOG_END,
                render_acceptance_catalog(registry),
            ),
        ),
        (
            root / "docs/REQUIREMENT_CHANGELOG.md",
            auto_region_bytes(
                root / "docs/REQUIREMENT_CHANGELOG.md",
                REQ_CHANGELOG_START,
                REQ_CHANGELOG_END,
                render_requirement_changelog(registry),
            ),
        ),
        (
            root / "docs/REQUIREMENT_TRACEABILITY_MATRIX.md",
            auto_region_bytes(
                root / "docs/REQUIREMENT_TRACEABILITY_MATRIX.md",
                TRACE_MATRIX_START,
                TRACE_MATRIX_END,
                render_traceability_matrix(registry),
            ),
        ),
    ]


def sync_requirement_documents(root: Path, registry: dict | None = None) -> None:
    registry = registry or load_requirement_registry(root)
    try:
        atomic_file_transaction(
            requirement_document_payloads(root, registry),
            failure_environment="AI_STARTER_TEST_FAIL_REQUIREMENT_TRANSACTION_AFTER",
        )
    except BaseException as exc:
        raise SystemExit(
            f"requirement document sync transaction failed; all documents were restored: {exc}"
        ) from exc


def requirement_docs_are_synced(root: Path, registry: dict) -> tuple[bool, list[str]]:
    checks = [
        ("docs/PRODUCT_REQUIREMENTS.md", REQ_CATALOG_START, REQ_CATALOG_END, render_requirement_catalog(registry)),
        ("docs/ACCEPTANCE_CRITERIA.md", ACCEPTANCE_CATALOG_START, ACCEPTANCE_CATALOG_END, render_acceptance_catalog(registry)),
        ("docs/REQUIREMENT_CHANGELOG.md", REQ_CHANGELOG_START, REQ_CHANGELOG_END, render_requirement_changelog(registry)),
        ("docs/REQUIREMENT_TRACEABILITY_MATRIX.md", TRACE_MATRIX_START, TRACE_MATRIX_END, render_traceability_matrix(registry)),
    ]
    mismatches: list[str] = []
    for rel, start, end, expected in checks:
        path = root / rel
        if not path.exists():
            mismatches.append(rel + " 不存在")
            continue
        match = re.search(re.escape(start) + r"\n?(.*?)\n?" + re.escape(end), path.read_text(encoding="utf-8"), re.S)
        actual = match.group(1).strip() if match else "<missing marker>"
        if actual != expected.strip():
            mismatches.append(rel + " 自动区与需求登记表不一致")
    return (not mismatches, mismatches)


def reject_closed_requirement_target(root: Path, release_target: str) -> None:
    if not release_target:
        return
    frozen = closed_baseline_for_release(root, release_target)
    if frozen:
        raise SystemExit(
            f"release_target {release_target} has a closed baseline "
            f"{frozen[1].get('baseline_id')} and is permanently frozen; "
            "new or revised requirements must target an open, later release."
        )


def ai_requirement(args: argparse.Namespace) -> int:
    root = find_root()
    ensure_project_open(root, "写入正式需求")
    input_path = resolve_project_input(root, args.input, REQUIREMENT_UPDATE_FILE)
    data = require_dict(read_json(input_path), str(input_path))
    actor_role = require_text(data, "actor_role")
    if actor_role != "project_manager_agent":
        raise SystemExit("需求登记、修订和追踪写入只能由项目经理主智能体角色执行。")
    action = require_text(data, "action").lower()
    registry = load_requirement_registry(root)
    timestamp = now_iso()
    message = ""
    if action == "create":
        number = registry["next_requirement_number"]
        req_id = f"R-{number:03d}"
        title = require_text(data, "title")
        description = require_text(data, "description")
        status = str(data.get("status", "draft")).lower()
        priority = str(data.get("priority", "must")).lower()
        category = str(data.get("category", "functional")).lower()
        if status not in ALLOWED_REQUIREMENT_STATUS or priority not in ALLOWED_PRIORITY or category not in ALLOWED_CATEGORY:
            raise SystemExit("需求 status / priority / category 非法。")
        release_target = str(data.get("release_target", "")).strip()
        if release_target:
            parse_release_version(release_target)
            reject_closed_requirement_target(root, release_target)
        registry["next_requirement_number"] = number + 1
        req = {
            "requirement_id": req_id,
            "current_revision": 1,
            "current_version": f"{req_id}.1",
            "title": title,
            "status": status,
            "category": category,
            "priority": priority,
            "description": description,
            "module": str(data.get("module", "")).strip(),
            "summary": str(data.get("summary", "")).strip(),
            "architecture_refs": str_list(data, "architecture_refs"),
            "decision_refs": str_list(data, "decision_refs"),
            "rationale": str(data.get("rationale", "")).strip(),
            "source": str(data.get("source", "project_definition")).strip() or "project_definition",
            "change_id": str(data.get("change_id", "")).strip(),
            "customer_visible": bool(data.get("customer_visible", True)),
            "release_blocking": bool(data.get("release_blocking", priority in {"must", "should"})),
            "release_target": release_target,
            "acceptance_criteria": normalize_criteria(req_id, data.get("acceptance_criteria", [])),
            "implementation_refs": str_list(data, "implementation_refs"),
            "test_refs": str_list(data, "test_refs"),
            "manual_acceptance": normalized_manual_acceptance(data.get("manual_acceptance")),
            "user_instructions": str(data.get("user_instructions", "")).strip(),
            "user_instructions_verified": bool(data.get("user_instructions_verified", False)),
            "help_notes": str_list(data, "help_notes"),
            "known_limitations": str_list(data, "known_limitations"),
            "notes": str_list(data, "notes"),
            "created_at": timestamp,
            "updated_at": timestamp,
            "revisions": [],
        }
        req["revisions"].append(revision_snapshot(
            req, version=req["current_version"], source=req["source"],
            reason=str(data.get("reason", "初始登记")).strip() or "初始登记", change_id=req["change_id"],
        ))
        registry["requirements"].append(req)
        message = f"AI_REQUIREMENT_CREATED {req['current_version']}"
    elif action == "revise":
        identifier = require_text(data, "requirement_id")
        expected = require_text(data, "expected_current_version")
        req = find_requirement(registry, identifier, expected_current_version=expected, require_exact_version=True)
        reason = require_text(data, "reason")
        change_id = require_text(data, "change_id")
        require_open_requirement_change(root, change_id)
        working = copy.deepcopy(req)
        for key in ["title", "description", "rationale", "release_target", "user_instructions", "module", "summary"]:
            if key in data:
                working[key] = str(data.get(key, "")).strip()
        for key in ["status", "priority", "category"]:
            if key in data:
                working[key] = str(data[key]).lower().strip()
        if working["status"] not in ALLOWED_REQUIREMENT_STATUS or working["priority"] not in ALLOWED_PRIORITY or working["category"] not in ALLOWED_CATEGORY:
            raise SystemExit("修订后的 status / priority / category 非法。")
        if working.get("release_target"):
            parse_release_version(str(working["release_target"]))
            reject_closed_requirement_target(root, str(working["release_target"]))
        for key in ["customer_visible", "release_blocking", "user_instructions_verified"]:
            if key in data:
                working[key] = bool(data[key])
        if "acceptance_criteria" in data:
            working["acceptance_criteria"] = normalize_criteria(
                working["requirement_id"], data["acceptance_criteria"], working.get("acceptance_criteria")
            )
        for key in ["help_notes", "known_limitations", "notes", "architecture_refs", "decision_refs"]:
            if key in data:
                working[key] = str_list(data, key)
        working["current_revision"] += 1
        working["current_version"] = f"{working['requirement_id']}.{working['current_revision']}"
        working["source"] = str(data.get("source", "requirement_change")).strip() or "requirement_change"
        working["change_id"] = change_id
        working["updated_at"] = timestamp
        working["revisions"].append(revision_snapshot(
            working,
            version=working["current_version"],
            source=working["source"],
            reason=reason,
            change_id=working["change_id"],
        ))
        req.clear()
        req.update(working)
        message = f"AI_REQUIREMENT_REVISED {req['current_version']}"
    elif action == "link":
        forbidden = sorted(set(data) - LINK_ALLOWED_FIELDS)
        if forbidden:
            raise SystemExit(
                "link 只允许更新非语义追踪证据；禁止字段："
                + ", ".join(forbidden)
                + "；请登记真实未关闭变更、提供 change_id，并使用 revise。"
            )
        identifier = require_text(data, "requirement_id")
        expected = require_text(data, "expected_current_version")
        req = find_requirement(registry, identifier, expected_current_version=expected, require_exact_version=True)
        working = copy.deepcopy(req)
        if "implementation_refs" in data:
            working["implementation_refs"] = str_list(data, "implementation_refs")
        if "test_refs" in data:
            working["test_refs"] = str_list(data, "test_refs")
        if "manual_acceptance" in data:
            raw_manual = data["manual_acceptance"]
            if not isinstance(raw_manual, dict):
                raise SystemExit("manual_acceptance 必须是对象。")
            forbidden_manual = sorted(set(raw_manual) - LINK_MANUAL_ACCEPTANCE_ALLOWED_FIELDS)
            if forbidden_manual:
                names = ", ".join(f"manual_acceptance.{name}" for name in forbidden_manual)
                raise SystemExit(
                    f"link 禁止修改非追踪字段：{names}；请登记真实变更并使用 revise。"
                )
            working["manual_acceptance"] = normalized_manual_acceptance(
                raw_manual, req.get("manual_acceptance")
            )
        if "acceptance_criteria" in data:
            working["acceptance_criteria"] = normalize_link_criteria(
                data["acceptance_criteria"], req.get("acceptance_criteria", [])
            )
        working["updated_at"] = timestamp
        req.clear()
        req.update(working)
        message = f"AI_REQUIREMENT_LINKED {req['current_version']} {trace_state(req)}"
    elif action == "sync":
        sync_requirement_documents(root, registry)
        message = "AI_REQUIREMENTS_SYNCED"
    else:
        raise SystemExit("action 只能是 create、revise、link 或 sync。")
    if action != "sync":
        save_requirement_registry(root, registry)
    if input_path.exists():
        input_path.unlink()
    print(message)
    return 0


def release_requirement_scope(registry: dict, release_version: str) -> dict[str, list[dict]]:
    """Classify every active requirement instead of silently discarding version mismatches."""
    parse_release_version(release_version)
    scope: dict[str, list[dict]] = {
        "included": [],
        "targeted_current": [],
        "unassigned": [],
        "future": [],
        "overdue": [],
        "ambiguous": [],
    }
    for req in sorted(registry.get("requirements", []), key=requirement_sort_key):
        if req.get("status") != "active":
            continue
        target = str(req.get("release_target", "")).strip()
        if not target:
            scope["unassigned"].append(req)
            scope["included"].append(req)
            continue
        if target == release_version:
            scope["targeted_current"].append(req)
            scope["included"].append(req)
            continue
        relation = compare_release_versions(target, release_version)
        if relation > 0:
            scope["future"].append(req)
        elif relation < 0:
            scope["overdue"].append(req)
        else:
            # SemVer build metadata does not affect precedence, but release targets
            # are exact identifiers and must never be silently treated as identical.
            scope["ambiguous"].append(req)
    return scope


def release_requirement_selection(registry: dict, release_version: str) -> list[dict]:
    return release_requirement_scope(registry, release_version)["included"]


def release_requirement_scope_versions(scope: dict[str, list[dict]]) -> dict[str, list[str]]:
    return {
        key: [str(req.get("current_version", "")) for req in requirements]
        for key, requirements in scope.items()
    } | {"invalid": []}


def requirement_release_errors(req: dict) -> list[str]:
    errors: list[str] = []
    if trace_state(req) != "COMPLETE":
        errors.append(f"{req['current_version']} 追踪状态为 {trace_state(req)}")
    if req.get("customer_visible", True):
        if not str(req.get("user_instructions", "")).strip():
            errors.append(f"{req['current_version']} 缺少客户使用说明")
        if not req.get("user_instructions_verified"):
            errors.append(f"{req['current_version']} 使用说明尚未核对最终产品")
    return errors


def safe_release_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return value.strip("-.") or "release"


def release_key(value: str) -> str:
    """Collision-resistant filesystem key for arbitrary release labels."""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    bounded_name = safe_release_name(value)[:140].rstrip("-.") or "release"
    return f"{bounded_name}--{digest}"


SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def parse_release_version(value: str) -> tuple[int, int, int, tuple[str, ...] | None]:
    match = SEMVER_PATTERN.fullmatch(value.strip())
    if not match:
        raise SystemExit(
            f"发布版本必须使用 SemVer 格式 major.minor.patch，可带预发布或构建标识：{value}"
        )
    prerelease = tuple(match.group(4).split(".")) if match.group(4) else None
    if prerelease:
        for item in prerelease:
            if item.isdigit() and len(item) > 1 and item.startswith("0"):
                raise SystemExit(f"SemVer 数字预发布标识不得包含前导零：{value}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3)), prerelease


def compare_release_versions(left: str, right: str) -> int:
    """Compare SemVer values according to SemVer 2.0 precedence."""
    left_major, left_minor, left_patch, left_pre = parse_release_version(left)
    right_major, right_minor, right_patch, right_pre = parse_release_version(right)
    left_core = (left_major, left_minor, left_patch)
    right_core = (right_major, right_minor, right_patch)
    if left_core != right_core:
        return 1 if left_core > right_core else -1
    if left_pre is None and right_pre is None:
        return 0
    if left_pre is None:
        return 1
    if right_pre is None:
        return -1
    for left_item, right_item in zip(left_pre, right_pre):
        if left_item == right_item:
            continue
        left_numeric = left_item.isdigit()
        right_numeric = right_item.isdigit()
        if left_numeric and right_numeric:
            return 1 if int(left_item) > int(right_item) else -1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return 1 if left_item > right_item else -1
    if len(left_pre) == len(right_pre):
        return 0
    return 1 if len(left_pre) > len(right_pre) else -1


def baseline_records_for_release(root: Path, release_version: str) -> list[tuple[Path, dict]]:
    records: list[tuple[Path, dict]] = []
    directory = root / RELEASE_BASELINES_DIR
    if not directory.exists():
        return records
    for path in sorted(directory.glob("RB-*.json")):
        data = require_dict(read_json(path), str(path))
        if str(data.get("release_version", "")).strip() == release_version:
            records.append((path, data))
    return records


def closed_baseline_for_release(root: Path, release_version: str) -> tuple[Path, dict] | None:
    for path, baseline in baseline_records_for_release(root, release_version):
        if baseline.get("status") == "closed":
            return path, baseline
    return None


def load_baseline_index(root: Path) -> dict:
    data = read_json(root / RELEASE_BASELINE_INDEX_FILE, default={"schema_version": "1.9.0", "releases": {}})
    data = require_dict(data, str(root / RELEASE_BASELINE_INDEX_FILE))
    releases = data.get("releases", {})
    if not isinstance(releases, dict):
        raise SystemExit("发布基线索引 releases 必须是对象。")
    return {"schema_version": "1.9.0", "releases": releases}


def save_baseline_index(root: Path, data: dict) -> None:
    write_json(root / RELEASE_BASELINE_INDEX_FILE, data)


def baseline_path_by_id(root: Path, baseline_id: str) -> Path:
    if not re.fullmatch(r"RB-[0-9a-f]{12}-\d{3}", baseline_id):
        raise SystemExit(f"发布基线编号非法：{baseline_id}")
    return root / RELEASE_BASELINES_DIR / f"{baseline_id}.json"


def active_baseline_entry(root: Path, release_version: str) -> dict | None:
    index = load_baseline_index(root)
    entry = index["releases"].get(release_version)
    return entry if isinstance(entry, dict) else None


def next_baseline_id(root: Path, release_version: str) -> str:
    prefix = f"RB-{hashlib.sha256(release_version.encode('utf-8')).hexdigest()[:12]}-"
    existing = []
    directory = root / RELEASE_BASELINES_DIR
    if directory.exists():
        for path in directory.glob(prefix + "*.json"):
            match = re.fullmatch(re.escape(prefix) + r"(\d{3})\.json", path.name)
            if match:
                existing.append(int(match.group(1)))
    return prefix + f"{max(existing, default=0) + 1:03d}"


def _filter_fingerprint_paths(
    fingerprint: dict[str, str | None], ignored_paths: list[str] | None = None,
) -> dict[str, str | None]:
    """Remove explicitly frozen delivery artifacts from a worktree fingerprint.

    Delivery artifacts are integrity-checked independently through SHA-256. Ignoring
    only their declared paths here prevents an artifact replacement from being
    misreported as a source-code baseline drift while still rejecting every other
    uncommitted implementation change.
    """
    ignored = [str(x).replace("\\", "/").strip("/") for x in (ignored_paths or []) if str(x).strip()]
    if not ignored:
        return fingerprint
    result: dict[str, str | None] = {}
    for rel, value in fingerprint.items():
        normalized = rel.replace("\\", "/").strip("/")
        if any(normalized == item or normalized.startswith(item + "/") for item in ignored):
            continue
        result[rel] = value
    return result


def registered_untracked_artifact_paths(root: Path) -> list[str]:
    """Collect valid project-local build artifacts already frozen by delivery manifests."""
    paths: list[str] = []
    delivery_root = root / "docs" / "delivery"
    if not delivery_root.exists():
        return paths
    for manifest_path in sorted(delivery_root.rglob("delivery_manifest.json")):
        manifest = read_json(manifest_path, default=None)
        if not isinstance(manifest, dict):
            continue
        for item in manifest.get("artifacts", []):
            if not isinstance(item, dict):
                continue
            raw_path = str(item.get("path", "")).strip()
            try:
                normalized, _ = resolve_project_artifact_path(root, raw_path)
            except SystemExit:
                continue
            if not git_path_is_tracked(root, normalized):
                paths.append(normalized)
    return sorted(set(paths))


def git_dirty_paths(root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=root,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"无法读取 Git 工作区状态：{exc}") from exc
    return parse_porcelain_z(result.stdout)


def filter_ignored_paths(paths: Iterable[str], ignored_paths: Iterable[str]) -> list[str]:
    ignored = {item.replace("\\", "/").strip("/") for item in ignored_paths if item.strip()}
    result: list[str] = []
    for rel in paths:
        normalized = rel.replace("\\", "/").strip("/")
        if any(normalized == item or normalized.startswith(item + "/") for item in ignored):
            continue
        result.append(rel)
    return result


def baseline_is_current(
    root: Path, baseline: dict, *, ignored_worktree_paths: list[str] | None = None,
) -> bool:
    if not isinstance(baseline, dict) or baseline.get("status") not in {"active", "closed"}:
        return False
    registry = load_requirement_registry(root)
    release_version = str(baseline.get("release_version", ""))
    selected_versions = [req["current_version"] for req in release_requirement_selection(registry, release_version)]
    if selected_versions != baseline.get("requirement_versions", []):
        return False
    hashes = baseline.get("document_hashes", {})
    current = {
        ".ai/requirement_registry.json": file_hash(root / REQUIREMENT_REGISTRY_FILE),
        "docs/PRODUCT_REQUIREMENTS.md": file_hash(root / "docs/PRODUCT_REQUIREMENTS.md"),
        "docs/ACCEPTANCE_CRITERIA.md": file_hash(root / "docs/ACCEPTANCE_CRITERIA.md"),
        "docs/REQUIREMENT_CHANGELOG.md": file_hash(root / "docs/REQUIREMENT_CHANGELOG.md"),
        "docs/REQUIREMENT_TRACEABILITY_MATRIX.md": file_hash(root / "docs/REQUIREMENT_TRACEABILITY_MATRIX.md"),
    }
    if hashes != current:
        return False
    if not is_git_repo(root):
        return False
    baseline_head = str(baseline.get("git_head", ""))
    current_head = git_output(root, "rev-parse", "HEAD") or ""
    if not baseline_head or not current_head or not git_revision_is_ancestor(root, baseline_head, current_head):
        return False
    if git_implementation_tree_hash(root, "HEAD") != baseline.get("implementation_tree_hash"):
        return False
    # Uncommitted implementation changes invalidate the baseline. Declared delivery
    # artifacts may be ignored here only because their content hashes are checked by
    # the delivery verifier itself.
    all_ignored = sorted(set(registered_untracked_artifact_paths(root)) | set(ignored_worktree_paths or []))
    fingerprint = _filter_fingerprint_paths(working_fingerprint(root), all_ignored)
    return not bool(fingerprint)


def ai_release_baseline(args: argparse.Namespace) -> int:
    root = find_root()
    require_standard_governance(root, "Release baseline creation")
    ensure_project_open(root, "创建发布基线")
    require_standard_baseline_ready(root, "创建发布基线")
    cfg = load_config(root)
    input_path = resolve_project_input(root, args.input, RELEASE_BASELINE_FILE)
    data = require_dict(read_json(input_path), str(input_path))
    if require_text(data, "actor_role") != "project_manager_agent":
        raise SystemExit("发布基线只能由项目经理主智能体角色创建。")
    release_version = require_text(data, "release_version")
    parse_release_version(release_version)
    state = load_project_state(root)
    frozen = closed_baseline_for_release(root, release_version)
    if frozen:
        raise SystemExit(
            f"release version {release_version} has a closed baseline and is permanently frozen: "
            f"{frozen[1].get('baseline_id')}"
        )
    reopened = state.get("reopened")
    if isinstance(reopened, dict):
        allowed_release = str(reopened.get("reopen_version", "")).strip()
        if allowed_release and release_version != allowed_release:
            raise SystemExit(
                f"reopened project release is locked to {allowed_release}; "
                f"cannot create baseline for {release_version}"
            )
    if open_changes(root):
        raise SystemExit("存在未关闭变更，不能创建发布基线。")
    if isinstance(read_json(root / ACTIVE_FILE, default=None), dict):
        raise SystemExit("存在活动批次，不能创建发布基线。")
    audit = state.get("last_full_audit")
    if not audit_is_current(root, audit):
        raise SystemExit("创建发布基线前必须完成且保持有效的完整审计。")
    if not is_git_repo(root) or not git_output(root, "rev-parse", "HEAD"):
        raise SystemExit("创建发布基线需要可用 Git HEAD。")
    ignored_artifacts = registered_untracked_artifact_paths(root)
    dirty_paths = filter_ignored_paths(git_dirty_paths(root), ignored_artifacts)
    if dirty_paths:
        raise SystemExit(
            "创建发布基线前必须提交或清理工作区，确保基线对应唯一 Git 状态："
            + ", ".join(dirty_paths[:20])
        )
    registry = load_requirement_registry(root)
    synced, mismatch = requirement_docs_are_synced(root, registry)
    if not synced:
        raise SystemExit("需求文档未与登记表同步：" + "; ".join(mismatch))
    scope = release_requirement_scope(registry, release_version)
    historical_closed: list[dict] = []
    unresolved_overdue: list[dict] = []
    for req in scope["overdue"]:
        target_version = str(req.get("release_target", "")).strip()
        frozen = closed_baseline_for_release(root, target_version) if target_version else None
        frozen_requirement_versions = (
            frozen[1].get("requirement_versions", []) if frozen else []
        )
        if req.get("current_version") in frozen_requirement_versions:
            historical_closed.append(req)
        else:
            unresolved_overdue.append(req)
    scope["historical_closed"] = historical_closed
    scope["overdue"] = unresolved_overdue
    if scope["overdue"] or scope["ambiguous"]:
        overdue = ", ".join(
            f"{req['current_version']}->{req.get('release_target')}"
            for req in scope["overdue"]
        )
        ambiguous = ", ".join(
            f"{req['current_version']}->{req.get('release_target')}"
            for req in scope["ambiguous"]
        )
        raise SystemExit(
            "release baseline blocked: active requirements have overdue or ambiguous "
            "release_target values and may not silently leave the release scope: "
            f"overdue=[{overdue}], ambiguous=[{ambiguous}]. "
            "Use a real requirement revision to update the target or status."
        )
    selected = scope["included"]
    if not selected:
        raise SystemExit("当前发布版本没有可纳入基线的 active 需求。")
    errors: list[str] = []
    for req in selected:
        # 所有进入当前发布范围的 active 需求都必须有完整证据；非阻断不等于可无证据交付。
        errors.extend(requirement_release_errors(req))
    if errors:
        raise SystemExit("发布基线被需求追踪门禁拒绝：\n- " + "\n- ".join(errors))

    extension, api = context_extension()
    extension.lifecycle_gate(root, api, "release", "L5")

    index = load_baseline_index(root)
    previous = active_baseline_entry(root, release_version)
    previous_path: Path | None = None
    previous_baseline: dict | None = None
    requested_supersedes = str(data.get("supersedes_baseline_id", "")).strip()
    if previous:
        previous_path = baseline_path_by_id(root, str(previous.get("baseline_id", "")))
        previous_baseline = require_dict(read_json(previous_path), str(previous_path))
        if previous_baseline.get("status") == "closed":
            raise SystemExit(
                f"closed baseline {previous_baseline.get('baseline_id')} is permanently frozen "
                "and cannot be superseded"
            )
        if requested_supersedes != previous.get("baseline_id"):
            raise SystemExit(
                f"发布版本 {release_version} 已存在活动基线 {previous.get('baseline_id')}。"
                "不得覆盖；如需替代，必须显式提供 supersedes_baseline_id。"
            )
    elif requested_supersedes:
        requested_path = baseline_path_by_id(root, requested_supersedes)
        requested_baseline = read_json(requested_path, default=None)
        if isinstance(requested_baseline, dict) and requested_baseline.get("status") == "closed":
            raise SystemExit(
                f"closed baseline {requested_supersedes} is permanently frozen and cannot be superseded"
            )
        raise SystemExit(
            "supersedes_baseline_id 只能引用同一发布版本当前未结案的活动基线；"
            f"当前版本 {release_version} 没有可替代的活动基线。"
        )
    baseline_id = next_baseline_id(root, release_version)
    doc_hashes = {
        ".ai/requirement_registry.json": file_hash(root / REQUIREMENT_REGISTRY_FILE),
        "docs/PRODUCT_REQUIREMENTS.md": file_hash(root / "docs/PRODUCT_REQUIREMENTS.md"),
        "docs/ACCEPTANCE_CRITERIA.md": file_hash(root / "docs/ACCEPTANCE_CRITERIA.md"),
        "docs/REQUIREMENT_CHANGELOG.md": file_hash(root / "docs/REQUIREMENT_CHANGELOG.md"),
        "docs/REQUIREMENT_TRACEABILITY_MATRIX.md": file_hash(root / "docs/REQUIREMENT_TRACEABILITY_MATRIX.md"),
    }
    baseline = {
        "schema_version": "1.9.0",
        "baseline_id": baseline_id,
        "status": "active",
        "release_version": release_version,
        "release_key": release_key(release_version),
        "release_name": str(data.get("release_name", release_version)).strip() or release_version,
        "scope_note": str(data.get("scope_note", "")).strip(),
        "created_at": now_iso(),
        "created_by_role": "project_manager_agent",
        "git_head": git_output(root, "rev-parse", "HEAD"),
        "git_branch": git_output(root, "branch", "--show-current") or "",
        "implementation_tree_hash": git_implementation_tree_hash(root, "HEAD"),
        "full_audit": audit,
        "requirement_versions": [req["current_version"] for req in selected],
        "requirement_scope": release_requirement_scope_versions(scope),
        "requirements": copy.deepcopy(selected),
        "document_hashes": doc_hashes,
        "supersedes_baseline_id": previous.get("baseline_id") if previous else None,
        "final_acceptance": {"status": "pending", "date": "", "note": ""},
        "delivery_verification": None,
        "project_closure": None,
    }
    target = baseline_path_by_id(root, baseline_id)
    if target.exists():
        raise SystemExit(f"发布基线文件已存在，拒绝覆盖：{target}")

    updated_previous: dict | None = None
    if previous_baseline is not None:
        updated_previous = copy.deepcopy(previous_baseline)
        updated_previous["status"] = "superseded"
        updated_previous["superseded_at"] = now_iso()
        updated_previous["superseded_by"] = baseline_id
    updated_index = copy.deepcopy(index)
    updated_index["releases"][release_version] = {
        "baseline_id": baseline_id,
        "path": str(target.relative_to(root)).replace("\\", "/"),
        "release_key": baseline["release_key"],
        "activated_at": baseline["created_at"],
    }
    updated_state = copy.deepcopy(state)
    updated_state["current_release_version"] = release_version
    updated_state["last_release_baseline"] = {
        "release_version": release_version,
        "baseline_id": baseline_id,
        "path": str(target.relative_to(root)).replace("\\", "/"),
        "created_at": baseline["created_at"],
    }
    log_path, log_payload = log_entry_payload(
        root,
        cfg,
        f"发布基线 {release_version}",
        f"- 基线编号：{baseline_id}\n"
        f"- 需求版本：{', '.join(baseline['requirement_versions'])}\n"
        f"- 未来版本需求：{', '.join(baseline['requirement_scope']['future']) or '无'}\n"
        f"- 无目标版本需求：{', '.join(baseline['requirement_scope']['unassigned']) or '无'}\n"
        f"- Git HEAD：{baseline['git_head']}\n"
        "- 完整审计：通过",
    )
    payloads = [(target, json_bytes(baseline))]
    if previous_path is not None and updated_previous is not None:
        payloads.append((previous_path, json_bytes(updated_previous)))
    payloads.extend([
        (root / RELEASE_BASELINE_INDEX_FILE, json_bytes(updated_index)),
        (root / PROJECT_STATE_FILE, json_bytes(updated_state)),
        (log_path, log_payload),
    ])
    try:
        atomic_file_transaction(
            payloads,
            failure_environment="AI_STARTER_TEST_FAIL_BASELINE_TRANSACTION_AFTER",
        )
    except BaseException as exc:
        raise SystemExit(
            f"release baseline transaction failed; all target files were restored: {exc}"
        ) from exc
    if input_path.exists(): input_path.unlink()
    print(f"AI_RELEASE_BASELINE_CREATED {release_version} {baseline_id} {target.relative_to(root)}")
    return 0


def load_release_baseline(
    root: Path, release_version: str, *, allow_closed: bool = False,
    ignored_worktree_paths: list[str] | None = None,
) -> tuple[Path, dict]:
    entry = active_baseline_entry(root, release_version)
    if not entry:
        raise SystemExit(f"发布版本 {release_version} 没有活动基线。")
    path = baseline_path_by_id(root, str(entry.get("baseline_id", "")))
    baseline = require_dict(read_json(path), str(path))
    if baseline.get("status") == "closed" and not allow_closed:
        raise SystemExit("该发布基线已经结案冻结，不能继续生成、修改或重新验证交付内容。")
    if ignored_worktree_paths is None:
        manifest_path = delivery_dir(root, release_version, str(baseline.get("baseline_id", ""))) / "delivery_manifest.json"
        manifest = read_json(manifest_path, default=None)
        if isinstance(manifest, dict):
            ignored_worktree_paths = [
                str(item.get("path", "")).strip()
                for item in manifest.get("artifacts", []) if isinstance(item, dict)
            ]
    if not baseline_is_current(root, baseline, ignored_worktree_paths=ignored_worktree_paths):
        raise SystemExit("发布基线已因需求、验收、追踪、Git HEAD 或实现状态变化而失效，必须创建新的替代基线。")
    return path, baseline

def delivery_dir(root: Path, release_version: str, baseline_id: str | None = None) -> Path:
    if baseline_id is None:
        entry = active_baseline_entry(root, release_version)
        if not entry:
            raise SystemExit(f"发布版本 {release_version} 没有活动基线，无法定位交付目录。")
        baseline_id = str(entry.get("baseline_id", ""))
    return root / "docs/delivery" / release_key(release_version) / baseline_id


def write_delivery_file(path: Path, text: str, force: bool) -> None:
    if path.exists() and not force:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def render_user_manual(project_name: str, baseline: dict) -> str:
    visible = [r for r in baseline["requirements"] if r.get("customer_visible", True)]
    sections = []
    for req in visible:
        limitations = "\n".join(f"- {x}" for x in req.get("known_limitations", [])) or "- 无已确认的功能专属限制。"
        sections.append(
            f"## {req['title']}（{req['current_version']}）\n\n"
            f"### 功能说明\n\n{req['description']}\n\n"
            f"### 使用方法\n\n{req.get('user_instructions', '').strip()}\n\n"
            f"### 注意事项\n\n{limitations}"
        )
    body = "\n\n".join(sections) or "本版本没有面向普通用户的功能项。"
    return f"""# {project_name} 用户使用说明

- 发布版本：{baseline['release_version']}
- 文档依据：发布基线、当前实现与已验证操作路径

## 开始使用

请先按照交付包中的安装或部署说明完成运行环境准备，再根据下列功能说明操作。

{body}

## 获取帮助

常见问题见同目录 `HELP_AND_FAQ.md`。超出本手册范围的问题，请联系项目交付方并提供版本号、操作步骤和错误信息。
"""


def render_help_faq(project_name: str, baseline: dict) -> str:
    items = []
    for req in baseline["requirements"]:
        if not req.get("customer_visible", True):
            continue
        notes = req.get("help_notes", [])
        if notes:
            for idx, note in enumerate(notes, 1):
                items.append(f"## {req['title']}常见问题 {idx}\n\n{note}")
        else:
            items.append(f"## 如何使用“{req['title']}”？\n\n{req.get('user_instructions', '').strip()}")
    items.append("## 出现异常时应提供哪些信息？\n\n请记录发布版本、操作步骤、输入数据、完整错误提示和发生时间；涉及数据问题时先备份当前数据。")
    return f"# {project_name} 帮助与常见问题\n\n- 发布版本：{baseline['release_version']}\n\n" + "\n\n".join(items) + "\n"


def render_final_acceptance(project_name: str, baseline: dict) -> str:
    rows = ["| 需求版本 | 需求摘要 | 验收条件 | 实现证据 | 测试证据 | 人工验收 | 结论 |", "|---|---|---|---|---|---|---|"]
    for req in baseline["requirements"]:
        criteria = [f"{x.get('id')}:{x.get('status')}" for x in req.get("acceptance_criteria", [])]
        manual = req.get("manual_acceptance", {})
        rows.append("| " + " | ".join([
            md_cell(req["current_version"]), md_cell(req["title"]), md_cell(criteria),
            md_cell(req.get("implementation_refs", [])), md_cell(req.get("test_refs", [])),
            md_cell(manual.get("status")), md_cell("通过" if trace_state(req) == "COMPLETE" else trace_state(req)),
        ]) + " |")
    final = baseline.get("final_acceptance", {})
    status_block = f"## 最终验收状态\n\n- 状态：{final.get('status', 'pending')}\n- 日期：{final.get('date') or '—'}\n- 项目所有者意见：{final.get('note') or '等待最终确认'}"
    return f"""# {project_name} 最终验收报告

- 发布版本：{baseline['release_version']}
- 发布基线时间：{baseline['created_at']}
- Git 提交：`{baseline['git_head']}`

## 逐项需求验收

{chr(10).join(rows)}

{FINAL_ACCEPTANCE_START}
{status_block}
{FINAL_ACCEPTANCE_END}

## 验收结论规则

发布基线中的全部 active 需求均应具有实现、测试和必要人工验收证据；`release_blocking`
需求是强制阻断子集，但不是唯一需要完整追踪的需求。最终项目结论以项目所有者确认状态为准。
"""


def render_release_notes(project_name: str, baseline: dict) -> str:
    added, changed, limitations = [], [], []
    for req in baseline["requirements"]:
        if req.get("current_revision", 1) == 1:
            added.append(f"- {req['current_version']}：{req['title']}")
        else:
            changed.append(f"- {req['current_version']}：{req['title']}（相对初版修订 {max(0, int(req.get('current_revision', 1)) - 1)} 次）")
        limitations.extend(f"- {req['current_version']}：{x}" for x in req.get("known_limitations", []))
    return f"""# {project_name} 发布说明

- 版本：{baseline['release_version']}
- 发布名称：{baseline.get('release_name', baseline['release_version'])}

## 新增

{chr(10).join(added) or '- 无。'}

## 调整

{chr(10).join(changed) or '- 无。'}

## 已知限制

{chr(10).join(limitations) or '- 无已确认限制。'}

## 发布依据

本版本内容以发布基线中的需求版本、测试证据和最终验收报告为准。
"""


def render_delivery_checklist(project_name: str, baseline: dict, artifacts: list[dict]) -> str:
    rows = ["| 交付物 | 位置 | 版本 | 状态 | SHA-256 | 大小（字节） |", "|---|---|---|---|---|---|"]
    for item in artifacts:
        rows.append("| " + " | ".join([
            md_cell(item.get("name")), md_cell(item.get("path")), md_cell(item.get("version")),
            md_cell(item.get("status")), md_cell(item.get("sha256")), md_cell(item.get("size_bytes")),
        ]) + " |")
    for filename in ["USER_MANUAL.md", "HELP_AND_FAQ.md", "FINAL_ACCEPTANCE_REPORT.md", "PROJECT_CLOSURE_REPORT.md", "RELEASE_NOTES.md"]:
        rows.append(f"| {filename} | 当前交付文档目录 | {baseline['release_version']} | ready |")
    return f"# {project_name} 交付物清单\n\n- 发布版本：{baseline['release_version']}\n\n" + "\n".join(rows) + "\n"


def render_closure_report(project_name: str, baseline: dict, customer_name: str, maintenance_note: str) -> str:
    requirement_count = len(baseline["requirements"])
    revision_count = sum(max(0, int(req.get("current_revision", 1)) - 1) for req in baseline["requirements"])
    closure = baseline.get("project_closure") or {"status": "open", "date": "", "note": ""}
    status_block = f"## 结案状态\n\n- 状态：{closure.get('status', 'open')}\n- 日期：{closure.get('date') or '—'}\n- 结案说明：{closure.get('note') or '等待最终验收与交付确认'}"
    return f"""# {project_name} 项目结案报告

- 客户／使用方：{customer_name or '项目所有者'}
- 发布版本：{baseline['release_version']}
- 发布基线：{baseline['created_at']}
- Git 提交：`{baseline['git_head']}`

## 项目目标

{baseline.get('scope_note') or '以发布基线中的当前需求版本为最终交付范围。'}

## 完成范围

- 纳入发布基线的需求：{requirement_count} 项；
- 需求语义修订：{revision_count} 次；
- 全部纳入发布范围的 active 需求均已达到追踪完成状态；
- 详细证据见 `FINAL_ACCEPTANCE_REPORT.md`。

## 维护与后续

{maintenance_note or '后续维护安排以双方确认内容为准。'}

{PROJECT_CLOSURE_START}
{status_block}
{PROJECT_CLOSURE_END}
"""


def ai_generate_delivery(args: argparse.Namespace) -> int:
    root = find_root()
    require_standard_governance(root, "Customer delivery generation")
    ensure_project_open(root, "生成客户交付材料")
    cfg = load_config(root)
    input_path = resolve_project_input(root, args.input, DELIVERY_REQUEST_FILE)
    data = require_dict(read_json(input_path), str(input_path))
    if require_text(data, "actor_role") != "project_manager_agent":
        raise SystemExit("客户交付文档只能由项目经理主智能体角色生成。")
    release_version = require_text(data, "release_version")
    artifacts = data.get("artifacts", [])
    if not isinstance(artifacts, list) or not artifacts:
        raise SystemExit("生成交付材料必须提供非空 artifacts 交付物数组。")
    validated_artifacts: list[tuple[dict, str, Path]] = []
    artifact_paths: list[str] = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise SystemExit("artifacts 项必须是对象。")
        require_text(item, "name")
        normalized_path, resolved_path = resolve_project_artifact_path(root, require_text(item, "path"))
        artifact_paths.append(normalized_path)
        validated_artifacts.append((item, normalized_path, resolved_path))
    # Build outputs created after the source baseline are commonly untracked. They
    # are allowed only as explicitly declared artifacts and are frozen separately
    # by SHA-256. Tracked source paths remain subject to the implementation baseline.
    untracked_artifacts = [path for path in artifact_paths if not git_path_is_tracked(root, path)]
    baseline_file, baseline = load_release_baseline(
        root, release_version, ignored_worktree_paths=untracked_artifacts,
    )
    normalized_artifacts: list[dict] = []
    for item, artifact_path, resolved_path in validated_artifacts:
        name = require_text(item, "name")
        digest = path_digest(resolved_path, root)
        normalized_artifacts.append({
            "name": name, "path": artifact_path,
            "version": str(item.get("version", release_version)).strip() or release_version,
            "status": str(item.get("status", "ready")).strip() or "ready",
            **digest,
        })
    target = delivery_dir(root, release_version)
    force = bool(data.get("force", False))
    if target.exists() and any(target.iterdir()) and not force:
        raise SystemExit(
            f"delivery directory already exists for {release_version}; "
            "refusing a partial regeneration. Set force=true to regenerate the "
            "documents, manifest and baseline link as one transaction."
        )
    project_name = cfg["project"]["name"]
    customer_name = str(data.get("customer_name", "项目所有者")).strip()
    maintenance_note = str(data.get("maintenance_note", "")).strip()
    contents = {
        "USER_MANUAL.md": render_user_manual(project_name, baseline),
        "HELP_AND_FAQ.md": render_help_faq(project_name, baseline),
        "FINAL_ACCEPTANCE_REPORT.md": render_final_acceptance(project_name, baseline),
        "PROJECT_CLOSURE_REPORT.md": render_closure_report(project_name, baseline, customer_name, maintenance_note),
        "DELIVERY_CHECKLIST.md": render_delivery_checklist(project_name, baseline, normalized_artifacts),
        "RELEASE_NOTES.md": render_release_notes(project_name, baseline),
    }
    manifest = {
        "schema_version": "1.9.0", "release_version": release_version, "baseline_id": baseline["baseline_id"],
        "generated_at": now_iso(), "customer_name": customer_name, "maintenance_note": maintenance_note,
        "artifacts": normalized_artifacts, "files": DELIVERY_REQUIRED_FILES,
        "verification": None,
    }
    updated_baseline = copy.deepcopy(baseline)
    updated_baseline["delivery_verification"] = None
    log_path, log_payload = log_entry_payload(
        root,
        cfg,
        f"客户交付材料生成 {release_version}",
        f"- 目录：{target.relative_to(root)}\n- 文件：{', '.join(DELIVERY_REQUIRED_FILES)}",
    )
    payloads = [
        (target / filename, (content.rstrip() + "\n").encode("utf-8"))
        for filename, content in contents.items()
    ]
    payloads.extend([
        (target / "delivery_manifest.json", json_bytes(manifest)),
        (baseline_file, json_bytes(updated_baseline)),
        (log_path, log_payload),
    ])
    try:
        atomic_file_transaction(
            payloads,
            failure_environment="AI_STARTER_TEST_FAIL_DELIVERY_TRANSACTION_AFTER",
        )
    except BaseException as exc:
        raise SystemExit(
            f"delivery generation transaction failed; documents, manifest, "
            f"baseline and log were restored: {exc}"
        ) from exc
    if input_path.exists(): input_path.unlink()
    print(f"AI_DELIVERY_GENERATED {release_version} {target.relative_to(root)}")
    return 0


def delivery_verification_details(
    root: Path, release_version: str, *, allow_closed: bool = False
) -> tuple[list[str], list[str], dict, Path, dict]:
    target = delivery_dir(root, release_version)
    manifest = require_dict(read_json(target / "delivery_manifest.json"), str(target / "delivery_manifest.json"))
    errors: list[str] = []
    warnings: list[str] = []
    manifest_artifacts = manifest.get("artifacts", [])
    if not isinstance(manifest_artifacts, list):
        errors.append("交付清单 artifacts 必须是数组。")
        manifest_artifacts = []
    artifact_paths: list[str] = []
    resolved_artifacts: dict[str, Path] = {}
    for item in manifest_artifacts:
        if not isinstance(item, dict):
            errors.append("交付清单 artifacts 包含非对象条目。")
            continue
        raw_path = str(item.get("path", "")).strip()
        try:
            normalized, resolved = resolve_project_artifact_path(root, raw_path)
        except SystemExit as exc:
            errors.append(str(exc))
            continue
        artifact_paths.append(normalized)
        resolved_artifacts[normalized] = resolved
    baseline_file, baseline = load_release_baseline(
        root, release_version, allow_closed=allow_closed, ignored_worktree_paths=artifact_paths,
    )
    for filename in DELIVERY_REQUIRED_FILES:
        if not (target / filename).exists():
            errors.append("缺少客户交付文档：" + filename)
    for filename in DELIVERY_REQUIRED_FILES:
        doc = target / filename
        if not doc.exists(): continue
        content = doc.read_text(encoding="utf-8", errors="replace")
        for pattern in PLACEHOLDER_PATTERNS:
            if re.search(pattern, content, re.I):
                errors.append(f"{filename} 存在占位内容：{pattern}")
                break
        for term in CUSTOMER_DOC_INTERNAL_TERMS:
            if term in content:
                errors.append(f"{filename} 暴露内部项目机制：{term}")
    acceptance_text = (target / "FINAL_ACCEPTANCE_REPORT.md").read_text(encoding="utf-8", errors="replace") if (target / "FINAL_ACCEPTANCE_REPORT.md").exists() else ""
    manual_text = (target / "USER_MANUAL.md").read_text(encoding="utf-8", errors="replace") if (target / "USER_MANUAL.md").exists() else ""
    for req in baseline.get("requirements", []):
        if req["current_version"] not in acceptance_text:
            errors.append(f"最终验收报告缺少需求：{req['current_version']}")
        if req.get("customer_visible", True) and req["current_version"] not in manual_text:
            errors.append(f"用户手册缺少客户可见需求：{req['current_version']}")
    if manifest.get("baseline_id") != baseline.get("baseline_id"):
        errors.append("交付清单关联的发布基线与当前活动基线不一致。")
    if manifest.get("files") != DELIVERY_REQUIRED_FILES:
        errors.append("交付清单文件列表与必需客户文档集合不一致。")
    checklist_path = target / "DELIVERY_CHECKLIST.md"
    if checklist_path.exists():
        project_name = load_config(root)["project"]["name"]
        expected_checklist = render_delivery_checklist(
            project_name, baseline, manifest_artifacts
        ).replace("\r\n", "\n").rstrip() + "\n"
        actual_checklist = checklist_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if actual_checklist != expected_checklist:
            errors.append("DELIVERY_CHECKLIST.md 与 delivery_manifest.json 不一致。")
    for artifact in manifest_artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_path = str(artifact.get("path", "")).strip().replace("\\", "/")
        resolved = resolved_artifacts.get(artifact_path)
        if resolved is None:
            errors.append("交付物不存在：" + artifact_path)
            continue
        current = path_digest(resolved, root)
        for key in ["kind", "sha256", "size_bytes", "file_count"]:
            if artifact.get(key) != current.get(key):
                errors.append(f"交付物内容已变化：{artifact_path}（{key} 不一致）")
                break
    return errors, warnings, baseline, baseline_file, manifest


def ai_delivery_verify(args: argparse.Namespace) -> int:
    root = find_root()
    require_standard_governance(root, "Customer delivery verification")
    ensure_project_open(root, "更新客户交付验证")
    release_version = args.release
    errors, warnings, baseline, baseline_file, manifest = delivery_verification_details(root, release_version)
    target = delivery_dir(root, release_version)
    verification = {
        "status": "passed" if not errors else "failed",
        "verified_at": now_iso(),
        "errors": errors,
        "warnings": warnings,
        "document_hashes": {filename: file_hash(target / filename) for filename in DELIVERY_REQUIRED_FILES if (target / filename).exists()},
        "artifact_hashes": {
            str(item.get("path")): {k: item.get(k) for k in ["kind", "sha256", "size_bytes", "file_count"]}
            for item in manifest.get("artifacts", []) if isinstance(item, dict)
        },
        "git_head": baseline.get("git_head"),
        "baseline_id": baseline.get("baseline_id"),
    }
    updated_manifest = copy.deepcopy(manifest)
    updated_manifest["verification"] = verification
    updated_baseline = copy.deepcopy(baseline)
    updated_baseline["delivery_verification"] = verification
    try:
        atomic_file_transaction([
            (target / "delivery_manifest.json", json_bytes(updated_manifest)),
            (baseline_file, json_bytes(updated_baseline)),
        ])
    except BaseException as exc:
        raise SystemExit(
            f"delivery verification transaction failed; manifest and baseline were restored: {exc}"
        ) from exc
    if errors:
        print("AI_DELIVERY_VERIFICATION_FAILED")
        for item in errors: print("FAIL", item)
        return 2
    print(f"AI_DELIVERY_VERIFIED {release_version}")
    return 0


def update_final_acceptance_report(root: Path, baseline: dict) -> None:
    path = delivery_dir(root, baseline["release_version"]) / "FINAL_ACCEPTANCE_REPORT.md"
    final = baseline.get("final_acceptance", {})
    body = f"## 最终验收状态\n\n- 状态：{final.get('status', 'pending')}\n- 日期：{final.get('date') or '—'}\n- 项目所有者意见：{final.get('note') or '等待最终确认'}"
    replace_auto_region(path, FINAL_ACCEPTANCE_START, FINAL_ACCEPTANCE_END, body)


def update_closure_report(root: Path, baseline: dict) -> None:
    path = delivery_dir(root, baseline["release_version"]) / "PROJECT_CLOSURE_REPORT.md"
    closure = baseline.get("project_closure") or {"status": "open", "date": "", "note": ""}
    body = f"## 结案状态\n\n- 状态：{closure.get('status', 'open')}\n- 日期：{closure.get('date') or '—'}\n- 结案说明：{closure.get('note') or '等待最终验收与交付确认'}"
    replace_auto_region(path, PROJECT_CLOSURE_START, PROJECT_CLOSURE_END, body)


def ai_final_acceptance(args: argparse.Namespace) -> int:
    root = find_root()
    require_standard_governance(root, "Final acceptance")
    ensure_project_open(root, "登记最终验收")
    cfg = load_config(root)
    input_path = resolve_project_input(root, args.input, FINAL_ACCEPTANCE_INPUT_FILE)
    data = require_dict(read_json(input_path), str(input_path))
    if require_text(data, "recorder_role") != "project_manager_agent":
        raise SystemExit("最终验收只能由项目经理主智能体根据项目所有者真实反馈登记。")
    release_version = require_text(data, "release_version")
    decision = require_text(data, "owner_decision").lower()
    if decision not in {"passed", "rejected"}:
        raise SystemExit("owner_decision 只能是 passed 或 rejected。")
    note = require_text(data, "owner_note")
    baseline_file, baseline = load_release_baseline(root, release_version)
    target = delivery_dir(root, release_version)
    if not (target / "FINAL_ACCEPTANCE_REPORT.md").exists():
        raise SystemExit("请先生成客户交付文档和最终验收报告。")
    final_acceptance = {
        "status": decision,
        "date": str(data.get("date", date.today().isoformat())).strip() or date.today().isoformat(),
        "note": note,
        "recorded_at": now_iso(),
        "recorded_by_role": "project_manager_agent",
    }
    updated_baseline = copy.deepcopy(baseline)
    updated_baseline["final_acceptance"] = final_acceptance
    updated_baseline["delivery_verification"] = None
    report_path = target / "FINAL_ACCEPTANCE_REPORT.md"
    report_body = (
        "## 最终验收状态\n\n"
        f"- 状态：{final_acceptance['status']}\n"
        f"- 日期：{final_acceptance['date']}\n"
        f"- 项目所有者意见：{final_acceptance['note']}"
    )
    updated_state = copy.deepcopy(load_project_state(root))
    updated_state["final_acceptance"] = final_acceptance
    log_path, log_payload = log_entry_payload(
        root,
        cfg,
        f"最终验收 {release_version}",
        f"- 项目所有者结论：{decision}\n- 说明：{note}",
    )
    try:
        atomic_file_transaction([
            (baseline_file, json_bytes(updated_baseline)),
            (
                report_path,
                auto_region_bytes(
                    report_path,
                    FINAL_ACCEPTANCE_START,
                    FINAL_ACCEPTANCE_END,
                    report_body,
                ),
            ),
            (root / PROJECT_STATE_FILE, json_bytes(updated_state)),
            (log_path, log_payload),
        ], failure_environment="AI_STARTER_TEST_FAIL_FINAL_ACCEPTANCE_TRANSACTION_AFTER")
    except BaseException as exc:
        raise SystemExit(
            f"final acceptance transaction failed; baseline, report, state and log "
            f"were restored: {exc}"
        ) from exc
    if input_path.exists(): input_path.unlink()
    print(f"AI_FINAL_ACCEPTANCE_RECORDED {release_version} {decision}")
    return 0


def delivery_verification_is_current(root: Path, baseline: dict) -> bool:
    verification = baseline.get("delivery_verification")
    if not isinstance(verification, dict) or verification.get("status") != "passed":
        return False
    if verification.get("baseline_id") != baseline.get("baseline_id"):
        return False
    if verification.get("git_head") != baseline.get("git_head"):
        return False
    target = delivery_dir(root, baseline["release_version"])
    manifest = read_json(target / "delivery_manifest.json", default=None)
    if not isinstance(manifest, dict):
        return False
    artifact_paths: list[str] = []
    resolved_artifacts: dict[str, Path] = {}
    for item in manifest.get("artifacts", []):
        if not isinstance(item, dict):
            return False
        try:
            normalized, resolved = resolve_project_artifact_path(root, str(item.get("path", "")))
        except SystemExit:
            return False
        artifact_paths.append(normalized)
        resolved_artifacts[normalized] = resolved
    if not baseline_is_current(root, baseline, ignored_worktree_paths=artifact_paths):
        return False
    recorded_docs = verification.get("document_hashes", {})
    current_docs = {filename: file_hash(target / filename) for filename in DELIVERY_REQUIRED_FILES if (target / filename).exists()}
    if recorded_docs != current_docs:
        return False
    recorded_artifacts = verification.get("artifact_hashes", {})
    current_artifacts = {}
    for item in manifest.get("artifacts", []):
        rel = str(item.get("path", "")).strip().replace("\\", "/")
        resolved = resolved_artifacts.get(rel)
        if resolved is None:
            return False
        current_artifacts[rel] = path_digest(resolved, root)
    return recorded_artifacts == current_artifacts


def _capture_file_bytes(paths: list[Path]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def _restore_file_bytes(backups: dict[Path, bytes | None]) -> None:
    for path, content in backups.items():
        if content is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def ai_close_project(args: argparse.Namespace) -> int:
    root = find_root()
    require_standard_governance(root, "Project closure")
    ensure_project_open(root, "项目结案")
    cfg = load_config(root)
    input_path = resolve_project_input(root, args.input, PROJECT_CLOSE_INPUT_FILE)
    data = require_dict(read_json(input_path), str(input_path))
    if require_text(data, "actor_role") != "project_manager_agent":
        raise SystemExit("项目结案只能由项目经理主智能体角色登记。")
    release_version = require_text(data, "release_version")
    closure_note = require_text(data, "closure_note")
    baseline_file, baseline = load_release_baseline(root, release_version)
    if open_changes(root) or isinstance(read_json(root / ACTIVE_FILE, default=None), dict):
        raise SystemExit("存在活动批次或未关闭变更，不能结案。")
    if baseline.get("final_acceptance", {}).get("status") != "passed":
        raise SystemExit("项目所有者最终验收尚未通过。")
    if not delivery_verification_is_current(root, baseline):
        raise SystemExit("客户交付文档、交付物、Git HEAD 或基线状态尚未通过当前版本验证。")

    target = delivery_dir(root, release_version)
    closure_report = target / "PROJECT_CLOSURE_REPORT.md"
    manifest_path = target / "delivery_manifest.json"
    state_path = root / PROJECT_STATE_FILE
    current_state_path = root / "docs/CURRENT_STATE.md"
    project_memory_path = root / "docs/PROJECT_MEMORY.md"
    log_path = root / "docs/logs" / f"{date.today():%Y-%m}.md"
    index_path = root / RELEASE_BASELINE_INDEX_FILE
    backups = _capture_file_bytes([
        baseline_file, closure_report, manifest_path, state_path, current_state_path,
        project_memory_path, log_path, index_path,
    ])

    closure = {
        "status": "closed",
        "date": str(data.get("date", date.today().isoformat())).strip() or date.today().isoformat(),
        "note": closure_note,
        "closed_at": now_iso(),
        "closed_by_role": "project_manager_agent",
    }
    try:
        working = copy.deepcopy(baseline)
        working["status"] = "closed"
        working["project_closure"] = closure
        working["delivery_verification"] = None
        write_json(baseline_file, working)
        update_closure_report(root, working)

        errors, warnings, refreshed, refreshed_file, manifest = delivery_verification_details(root, release_version, allow_closed=True)
        if errors:
            raise RuntimeError("结案报告更新后客户交付验证失败：\n- " + "\n- ".join(errors))
        verification = {
            "status": "passed",
            "verified_at": now_iso(),
            "errors": [],
            "warnings": warnings,
            "document_hashes": {
                filename: file_hash(target / filename)
                for filename in DELIVERY_REQUIRED_FILES if (target / filename).exists()
            },
            "artifact_hashes": {
                str(item.get("path")): {k: item.get(k) for k in ["kind", "sha256", "size_bytes", "file_count"]}
                for item in manifest.get("artifacts", [])
            },
            "git_head": refreshed.get("git_head"),
            "baseline_id": refreshed.get("baseline_id"),
        }
        manifest["verification"] = verification
        write_json(manifest_path, manifest)
        refreshed["status"] = "closed"
        refreshed["project_closure"] = closure
        refreshed["delivery_verification"] = verification
        write_json(refreshed_file, refreshed)

        index = load_baseline_index(root)
        entry = index["releases"].get(release_version, {})
        if isinstance(entry, dict):
            entry["status"] = "closed"
            entry["closed_at"] = closure["closed_at"]
        save_baseline_index(root, index)

        state = load_project_state(root)
        state["project_status"] = "closed"
        state["current_release_version"] = release_version
        state["current_stage"] = "项目已结案"
        state["stage_acceptance"] = {
            "stage_id": "FINAL", "status": "passed",
            "note": "项目所有者最终验收通过", "updated_at": now_iso(),
        }
        state["project_closure"] = {**closure, "release_version": release_version, "baseline_id": refreshed["baseline_id"]}
        save_project_state(root, state)
        update_project_memory_auto(root, cfg)
        update_auto_block(root / "docs/CURRENT_STATE.md", f"""## 自动状态快照

- 更新时间：{now_iso()}
- 最近批次：项目结案
- 最近结果：CLOSED
- 人工验收：PASSED
- Git 分支：{git_info(root)['branch']}
- Git HEAD：{git_info(root)['head']}
- 未关闭变更：0
- 当前阻塞：无
- 下一批：无，项目已结案""")
        append_log_entry(root, cfg, f"项目结案 {release_version}", f"- 基线编号：{refreshed['baseline_id']}\n- 状态：closed\n- 说明：{closure_note}")
    except BaseException as exc:
        _restore_file_bytes(backups)
        if isinstance(exc, SystemExit):
            raise
        raise SystemExit(f"项目结案事务失败，所有已写文件均已恢复：{exc}") from exc

    if input_path.exists(): input_path.unlink()
    print(f"AI_PROJECT_CLOSED {release_version} {baseline.get('baseline_id')}")
    return 0


def ai_reopen_project(args: argparse.Namespace) -> int:
    root = find_root()
    require_standard_governance(root, "Project reopen")
    cfg = load_config(root)
    input_path = resolve_project_input(root, args.input, PROJECT_REOPEN_INPUT_FILE)
    data = require_dict(read_json(input_path), str(input_path))
    if require_text(data, "actor_role") != "project_manager_agent":
        raise SystemExit("项目重新打开只能由项目经理主智能体角色登记。")
    if data.get("owner_authorization") is not True:
        raise SystemExit("重新打开已结案项目必须记录 owner_authorization=true。")
    owner_note = require_text(data, "owner_note")
    reopen_reason = require_text(data, "reopen_reason")
    new_stage = require_text(data, "new_stage")
    closed_version = require_text(data, "closed_version")
    reopen_version = require_text(data, "reopen_version")
    state = load_project_state(root)
    if state.get("project_status") != "closed":
        raise SystemExit("项目当前不是已结案状态，无需重新打开。")
    previous = copy.deepcopy(state.get("project_closure") or {})
    actual_closed_version = str(previous.get("release_version", "")).strip()
    if closed_version != actual_closed_version:
        raise SystemExit(
            f"closed_version 与最近结案版本不一致：expected={actual_closed_version}, actual={closed_version}"
        )
    frozen = closed_baseline_for_release(root, closed_version)
    if not frozen:
        raise SystemExit(f"未找到已冻结的 closed 发布基线：{closed_version}")
    if compare_release_versions(reopen_version, closed_version) <= 0:
        raise SystemExit(
            f"reopen_version must be higher than closed_version under SemVer ordering: "
            f"{reopen_version} <= {closed_version}"
        )
    history = state.get("closure_history", [])
    if not isinstance(history, list):
        history = []
    history.append(previous)
    state["closure_history"] = history
    state["project_status"] = "active"
    state["current_stage"] = new_stage
    state["current_release_version"] = reopen_version
    state["stage_acceptance"] = {
        "stage_id": new_stage, "status": "pending", "note": owner_note, "updated_at": now_iso(),
    }
    state["project_closure"] = None
    state["final_acceptance"] = None
    state["reopened"] = {
        "reopened_at": now_iso(),
        "owner_note": owner_note,
        "reopen_reason": reopen_reason,
        "new_stage": new_stage,
        "closed_version": closed_version,
        "reopen_version": reopen_version,
        "recorded_by_role": "project_manager_agent",
    }
    save_project_state(root, state)
    update_project_memory_auto(root, cfg)
    append_log_entry(
        root,
        cfg,
        "项目重新打开",
        f"- 项目所有者授权：{owner_note}\n"
        f"- 重开原因：{reopen_reason}\n"
        f"- 原结案版本：{closed_version}\n"
        f"- 新阶段：{new_stage}\n"
        f"- 新目标版本：{reopen_version}",
    )
    if input_path.exists(): input_path.unlink()
    print(f"AI_PROJECT_REOPENED {new_stage} {reopen_version}")
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="V1.9.0 工具无关双模式内部维护引擎；用户不应手动执行。")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ai-resume"); p.add_argument("--json", action="store_true"); p.add_argument("--mode", choices=["auto", "light", "standard", "full"], default="standard"); p.add_argument("--task", default=""); p.add_argument("--full-reason", default=""); p.set_defaults(func=ai_resume)
    p = sub.add_parser("ai-audit"); p.add_argument("--input"); p.set_defaults(func=ai_audit)
    p = sub.add_parser("ai-register-change"); p.add_argument("--input"); p.set_defaults(func=ai_register_change)
    p = sub.add_parser("ai-change-ready"); p.add_argument("change_id"); p.set_defaults(func=ai_change_ready)
    p = sub.add_parser("ai-rework-ready"); p.set_defaults(func=ai_rework_ready)
    p = sub.add_parser("ai-start"); p.add_argument("--request"); p.set_defaults(func=ai_start)
    p = sub.add_parser("ai-handoff-batch", help="Standard only; BLOCKED/PARTIAL only; owner-authorized responsibility handoff, not PASS / not acceptance", description="Standard only; BLOCKED/PARTIAL only; owner-authorized responsibility handoff, not PASS / not acceptance")
    p.add_argument("--input", help="Project-local runtime JSON; default .ai/runtime/batch_handoff.json"); p.set_defaults(func=ai_handoff_batch)
    p = sub.add_parser("ai-finish"); p.add_argument("--result"); p.set_defaults(func=ai_finish)
    p = sub.add_parser("ai-acceptance"); p.add_argument("--input"); p.set_defaults(func=ai_acceptance)
    p = sub.add_parser("pre-commit-check"); p.set_defaults(func=pre_commit_check)
    p = sub.add_parser("install-hooks"); p.set_defaults(func=install_hooks)
    p = sub.add_parser("health"); p.add_argument("--json", action="store_true"); p.add_argument("--quiet", action="store_true"); p.set_defaults(func=health)
    p = sub.add_parser("status"); p.set_defaults(func=status)
    p = sub.add_parser("new-decision"); p.add_argument("--input"); p.set_defaults(func=new_decision)
    p = sub.add_parser("enable-doc"); p.add_argument("names", nargs="*"); p.add_argument("--profile", action="store_true"); p.add_argument("--list", action="store_true"); p.add_argument("--force", action="store_true"); p.set_defaults(func=enable_doc)
    p = sub.add_parser("rotate-log"); p.set_defaults(func=rotate_log)
    p = sub.add_parser("ai-suspend-for-promotion"); p.add_argument("--input"); p.set_defaults(func=ai_suspend_for_promotion)
    p = sub.add_parser("ai-promote-standard"); p.add_argument("--input"); p.set_defaults(func=ai_promote_standard)
    p = sub.add_parser("ai-requirement"); p.add_argument("--input"); p.set_defaults(func=ai_requirement)
    p = sub.add_parser("ai-release-baseline"); p.add_argument("--input"); p.set_defaults(func=ai_release_baseline)
    p = sub.add_parser("ai-generate-delivery"); p.add_argument("--input"); p.set_defaults(func=ai_generate_delivery)
    p = sub.add_parser("ai-delivery-verify"); p.add_argument("--release", required=True); p.set_defaults(func=ai_delivery_verify)
    p = sub.add_parser("ai-final-acceptance"); p.add_argument("--input"); p.set_defaults(func=ai_final_acceptance)
    p = sub.add_parser("ai-close-project"); p.add_argument("--input"); p.set_defaults(func=ai_close_project)
    p = sub.add_parser("ai-reopen-project"); p.add_argument("--input"); p.set_defaults(func=ai_reopen_project)
    extension, _ = context_extension()
    extension.add_parsers(sub)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    extension, api = context_extension()
    return int(extension.run(args, api))


if __name__ == "__main__":
    raise SystemExit(main())
