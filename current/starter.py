#!/usr/bin/env python3
"""个人 AI 开发项目启动器 V1.9.0。

用户通过自然语言把项目名称、目录、类型和简介告诉具备本地权限的项目角色，
由该角色内部调用本工具。备用双击入口仍保留，但不属于日常工作流。

V1.9.0 使用临时目录完成渲染、配置解析、Git 初始化、初始提交、Hook 安装和健康检查；
全部成功后才原子替换目标目录，避免留下半初始化项目。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit("需要 Python 3.11 或更高版本。") from exc

BASE_DIR = Path(__file__).resolve().parent
SCAFFOLD_DIR = BASE_DIR / "scaffold"
PROFILES_FILE = BASE_DIR / "profiles.toml"
GOVERNANCE_MODES = {"lite", "standard", "auto"}
STANDARD_ONLY_FILES = {
    "docs/AI_EXECUTION_RULES.md",
    "docs/CONTEXT_LOADING_PROTOCOL.md",
    "PROJECT_OWNER_GUIDE.md",
    "EXECUTOR_ENTRY.md",
    ".ai/AUTOMATION_CONTRACT.md",
    "docs/PROJECT_RULES.md",
    "docs/ROLE_BOUNDARIES.md",
    "docs/PROJECT_MEMORY.md",
    "docs/DEVELOPMENT_PLAN.md",
    "docs/ARCHITECTURE.md",
    "docs/PITFALLS.md",
    "docs/DELIVERY_AND_CLOSURE.md",
}
COMMON_REQUIRED_FILES = [
    "START_HERE.md",
    "AGENTS.md",
    "README.md",
    "PROJECT.toml",
    ".ai/project_state.json",
    ".ai/requirement_registry.json",
    ".ai/standard_mode_templates.json",
    ".githooks/pre-commit",
    ".githooks/python-path",
    "docs/PRODUCT_REQUIREMENTS.md",
    "docs/REQUIREMENT_CHANGELOG.md",
    "docs/REQUIREMENT_TRACEABILITY_MATRIX.md",
    "docs/ACCEPTANCE_CRITERIA.md",
    "docs/CURRENT_STATE.md",
    "docs/DECISIONS.md",
    "tools/project.py",
    "tools/context_engine.py",
]


def load_profiles() -> dict:
    with PROFILES_FILE.open("rb") as fh:
        return tomllib.load(fh)


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value)
    return value.strip("-") or "project"


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or (default or "")


def toml_string(value: str) -> str:
    """Return a TOML-compatible quoted basic string.

    JSON string escaping is a valid subset for TOML basic strings and safely handles
    quotes, backslashes, control characters and newlines.
    """
    return json.dumps(value, ensure_ascii=False)


def toml_string_array(values: list[str]) -> str:
    return "[\n" + "".join(f"  {toml_string(value)},\n" for value in values) + "]"


def recommend_governance_mode(description: str, profile: str) -> tuple[str, str]:
    """Choose a conservative governance mode from a short project description."""
    text = description.casefold()
    hard_standard_signals = [
        "customer",
        "client",
        "external delivery",
        "formal delivery",
        "sensitive data",
        "credential",
        "account",
        "authentication",
        "authorization",
        "permission",
        "payment",
        "data migration",
        "production deployment",
        "deploy to production",
        "multi-platform",
        "multiple platforms",
        "hardware",
        "pcb",
        "irreversible",
        "客户",
        "正式交付",
        "外部交付",
        "敏感数据",
        "凭据",
        "账户",
        "账号",
        "认证",
        "权限",
        "支付",
        "数据迁移",
        "生产部署",
        "正式部署",
        "多平台",
        "硬件",
        "不可逆",
    ]
    matched_hard = [signal for signal in hard_standard_signals if signal in text]
    if profile == "hardware-pcb":
        matched_hard.append("hardware-pcb profile")
    if matched_hard:
        visible = "、".join(dict.fromkeys(matched_hard))
        return "standard", f"检测到不可由短周期抵消的 Standard 硬触发条件：{visible}"

    standard_signals = {
        "multi-stage": 2,
        "multiple stages": 2,
        "deployment": 2,
        "production": 2,
        "multi-user": 2,
        "团队": 2,
        "多阶段": 2,
        "部署": 2,
        "上线": 2,
        "多用户": 2,
    }
    lite_signals = [
        "one day",
        "two days",
        "1 day",
        "2 days",
        "tiny",
        "small script",
        "personal helper",
        "personal script",
        "prototype",
        "一天",
        "两天",
        "1天",
        "2天",
        "极小",
        "小脚本",
        "个人小工具",
        "快速验证",
    ]
    score = sum(weight for signal, weight in standard_signals.items() if signal in text)
    score -= sum(1 for signal in lite_signals if signal in text)
    if profile == "data-platform":
        score += 2
    elif profile in {"web-fullstack", "android"}:
        score += 1
    if score >= 2:
        return "standard", f"检测到正式交付、长期协作或较高工程风险信号（评分 {score}）"
    return "lite", f"未检测到必须启用完整治理的风险信号（评分 {score}）"


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


def render(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def target_path_for(relative: Path, month: str) -> Path:
    parts = list(relative.parts)
    if parts[-1] == "MONTH.md.tpl":
        parts[-1] = f"{month}.md"
    elif parts[-1].endswith(".tpl"):
        parts[-1] = parts[-1][:-4]
    return Path(*parts)


def run_internal(target: Path, *args: str) -> int:
    result = subprocess.run([sys.executable, str(target / "tools" / "project.py"), *args], cwd=target)
    return int(result.returncode)


def validate_generated_project(target: Path) -> None:
    project_toml = target / "PROJECT.toml"
    with project_toml.open("rb") as fh:
        data = tomllib.load(fh)
    if data.get("template_version") != "1.9.0":
        raise RuntimeError("PROJECT.toml 模板版本校验失败。")
    mode = data.get("governance", {}).get("mode")
    if mode not in {"lite", "standard"}:
        raise RuntimeError("PROJECT.toml governance.mode 必须为 lite 或 standard。")
    documents = data.get("documents", {})
    required = list(documents.get("required", []))
    if mode == "standard":
        required.extend(documents.get("standard_required", []))
    missing = [str(item) for item in required if not (target / str(item)).exists()]
    if missing:
        raise RuntimeError("初始化后缺少必需文件：" + ", ".join(missing))
    bundle_path = target / ".ai" / "standard_mode_templates.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    files = bundle.get("files")
    if bundle.get("schema_version") != "1.9.0" or not isinstance(files, dict):
        raise RuntimeError("Standard promotion template bundle schema validation failed.")
    file_hashes, content_hash = standard_template_hashes(files)
    if bundle.get("file_sha256") != file_hashes or bundle.get("content_sha256") != content_hash:
        raise RuntimeError("Standard promotion template bundle hash validation failed.")
    if data.get("governance", {}).get("standard_mode_templates_sha256") != content_hash:
        raise RuntimeError("PROJECT.toml Standard promotion template hash does not match.")

    # Compile in memory so validation never publishes __pycache__ or .pyc files.
    project_tool = target / "tools" / "project.py"
    compile(project_tool.read_text(encoding="utf-8"), str(project_tool), "exec")


def require_git() -> str:
    try:
        result = subprocess.run(
            ["git", "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("Git is required for the formal governance workflow and is not available.") from exc
    version = result.stdout.strip()
    if not version:
        raise RuntimeError("Git is required, but its version could not be read.")
    return version


def initialize_git(target: Path) -> None:
    try:
        subprocess.run(["git", "init"], cwd=target, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"Git 初始化失败；V1.9.0 项目治理模式要求 Git：{exc}") from exc


def create_initial_commit(target: Path) -> str:
    def config_value(name: str) -> str:
        result = subprocess.run(
            ["git", "config", "--get", name],
            cwd=target,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    try:
        if not config_value("user.name"):
            subprocess.run(
                ["git", "config", "user.name", "AI Project Starter"],
                cwd=target,
                check=True,
                capture_output=True,
                text=True,
            )
        if not config_value("user.email"):
            subprocess.run(
                ["git", "config", "user.email", "ai-project-starter@example.invalid"],
                cwd=target,
                check=True,
                capture_output=True,
                text=True,
            )
        subprocess.run(["git", "add", "-A"], cwd=target, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "commit", "-m", "Initialize project from template V1.9.0"],
            cwd=target,
            check=True,
            capture_output=True,
            text=True,
        )
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=target,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or "").strip()
        suffix = f"；{detail}" if detail else ""
        raise RuntimeError(f"Git 初始提交失败：{exc}{suffix}") from exc
    if not head:
        raise RuntimeError("Git 初始提交失败：未生成 HEAD。")
    return head


def publish_atomically(staging: Path, target: Path, force: bool) -> Path | None:
    backup: Path | None = None
    if target.exists():
        if any(target.iterdir()) and not force:
            raise RuntimeError(f"目标目录非空：{target}。只有显式 --force 才允许安全替换。")
        if any(target.iterdir()):
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = target.with_name(f"{target.name}.backup-{stamp}")
            suffix = 1
            while backup.exists():
                backup = target.with_name(f"{target.name}.backup-{stamp}-{suffix}")
                suffix += 1
            target.rename(backup)
        else:
            target.rmdir()
    try:
        staging.rename(target)
    except Exception:
        if backup and backup.exists() and not target.exists():
            backup.rename(target)
        raise
    return backup


def create_project(args: argparse.Namespace) -> int:
    profiles = load_profiles()
    profile_names = sorted(profiles)
    interactive = not all([args.target, args.name, args.description, args.profile])
    if interactive:
        print("\n个人 AI 开发项目启动模板 V1.9.0（备用人工入口）\n")
        target = Path(args.target or ask("项目目标目录", str(Path.cwd() / "new-project"))).expanduser()
        name = args.name or ask("项目名称")
        description = args.description or ask("一句话项目简介")
        print("可用项目类型：" + ", ".join(profile_names))
        profile = args.profile or ask("项目类型", "generic")
        requested_governance = args.governance_mode or ask(
            "治理模式（lite/standard/auto）", "auto"
        )
    else:
        target = Path(args.target).expanduser()
        name = args.name
        description = args.description
        profile = args.profile
        requested_governance = args.governance_mode or "standard"

    if profile not in profiles:
        print(f"错误：未知项目类型 {profile!r}。可用值：{', '.join(profile_names)}", file=sys.stderr)
        return 2
    requested_governance = str(requested_governance).strip().lower()
    if requested_governance not in GOVERNANCE_MODES:
        print("错误：治理模式只能是 lite、standard 或 auto。", file=sys.stderr)
        return 2
    if not name.strip() or not description.strip():
        print("错误：项目名称和简介不能为空。", file=sys.stderr)
        return 2

    try:
        require_git()
    except RuntimeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not target.is_dir():
        print(f"错误：目标路径不是目录：{target}", file=sys.stderr)
        return 2
    if target.exists() and any(target.iterdir()) and not args.force:
        print(f"错误：目标目录非空：{target}\n使用 --force 才允许先备份再原子替换。", file=sys.stderr)
        return 2

    today = date.today()
    month = today.strftime("%Y-%m")
    profile_data = profiles[profile]
    suggested = profile_data.get("suggested_docs", [])
    if requested_governance == "auto":
        governance_mode, governance_reason = recommend_governance_mode(description, profile)
    else:
        governance_mode = requested_governance
        governance_reason = "由项目所有者或项目经理主智能体明确选择"
    values = {
        "PROJECT_NAME": name.strip(),
        "PROJECT_NAME_TOML": toml_string(name.strip()),
        "PROJECT_SLUG": slugify(args.slug or name),
        "PROJECT_SLUG_TOML": toml_string(slugify(args.slug or name)),
        "PROJECT_DESCRIPTION": description.strip(),
        "PROJECT_DESCRIPTION_TOML": toml_string(description.strip()),
        "PROJECT_PROFILE": profile,
        "PROJECT_PROFILE_TOML": toml_string(profile),
        "PROFILE_LABEL": str(profile_data["label"]),
        "PROFILE_GUIDANCE": str(profile_data["guidance"]),
        "PROFILE_SUGGESTED_DOCS": ", ".join(suggested) if suggested else "无",
        "GOVERNANCE_MODE": governance_mode,
        "GOVERNANCE_MODE_TOML": toml_string(governance_mode),
        "GOVERNANCE_MODE_LABEL": "Lite 极简治理" if governance_mode == "lite" else "Standard 标准治理",
        "GOVERNANCE_REASON": governance_reason,
        "GOVERNANCE_REASON_TOML": toml_string(governance_reason),
        "COMMON_REQUIRED_DOCUMENTS_TOML": toml_string_array(COMMON_REQUIRED_FILES),
        "STANDARD_REQUIRED_DOCUMENTS_TOML": toml_string_array(sorted(STANDARD_ONLY_FILES)),
        "PARALLEL_CODE_EXECUTION_ALLOWED": "true" if governance_mode == "standard" else "false",
        "RELEASE_BASELINE_REQUIRED": "true" if governance_mode == "standard" else "false",
        "FINAL_ACCEPTANCE_REQUIRED": "true" if governance_mode == "standard" else "false",
        "DEFAULT_ENTRY_MODE": "standard" if governance_mode == "standard" else "light",
        "CREATED_DATE": today.isoformat(),
        "CREATED_DATE_COMPACT": today.strftime("%Y%m%d"),
        "CURRENT_MONTH": month,
        "PROJECT_ROOT_TOML": toml_string(str(target)),
    }

    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.init-", dir=str(target.parent)))
    backup: Path | None = None
    try:
        created: list[Path] = []
        standard_templates: dict[str, str] = {}
        for source in sorted(SCAFFOLD_DIR.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(SCAFFOLD_DIR)
            output_relative = target_path_for(relative, month)
            output_name = output_relative.as_posix()
            if output_name not in STANDARD_ONLY_FILES:
                continue
            if source.suffix != ".tpl":
                raise RuntimeError(f"Standard promotion source must be a text template: {relative}")
            standard_templates[output_name] = render(
                source.read_text(encoding="utf-8"), values
            )
        if set(standard_templates) != STANDARD_ONLY_FILES:
            missing_templates = sorted(STANDARD_ONLY_FILES - set(standard_templates))
            raise RuntimeError(
                "Standard promotion templates are incomplete: " + ", ".join(missing_templates)
            )
        standard_file_hashes, standard_content_hash = standard_template_hashes(
            standard_templates
        )
        values["STANDARD_MODE_TEMPLATES_SHA256"] = standard_content_hash

        for source in sorted(SCAFFOLD_DIR.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(SCAFFOLD_DIR)
            if "__pycache__" in relative.parts or source.suffix in {".pyc", ".pyo"}:
                continue
            output_relative = target_path_for(relative, month)
            if governance_mode == "lite" and output_relative.as_posix() in STANDARD_ONLY_FILES:
                continue
            destination = staging / output_relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix == ".tpl":
                destination.write_text(
                    render(source.read_text(encoding="utf-8"), values),
                    encoding="utf-8",
                    newline="\n",
                )
            else:
                shutil.copy2(source, destination)
            created.append(destination)

        promotion_bundle = staging / ".ai" / "standard_mode_templates.json"
        promotion_bundle.parent.mkdir(parents=True, exist_ok=True)
        promotion_bundle.write_text(
            json.dumps(
                {
                    "schema_version": "1.9.0",
                    "from_mode": "lite",
                    "to_mode": "standard",
                    "file_sha256": standard_file_hashes,
                    "content_sha256": standard_content_hash,
                    "files": standard_templates,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        created.append(promotion_bundle)

        # Record the interpreter actually used for initialization. The hook probes it
        # before trying platform fallbacks, avoiding Microsoft Store placeholder python.
        (staging / ".githooks").mkdir(parents=True, exist_ok=True)
        (staging / ".githooks" / "python-path").write_text(
            str(Path(sys.executable).resolve()) + "\n", encoding="utf-8", newline="\n"
        )
        created.append(staging / ".githooks" / "python-path")

        validate_generated_project(staging)
        initialize_git(staging)
        hook_code = run_internal(staging, "install-hooks")
        if hook_code != 0:
            raise RuntimeError("Git Hook 安装或验证失败。")

        result_code = run_internal(staging, "ai-resume")
        if result_code not in {0, 1}:
            raise RuntimeError(f"项目接管健康检查失败，退出码 {result_code}。")
        initial_head = create_initial_commit(staging)

        backup = publish_atomically(staging, target, args.force)
        print(f"项目已创建：{target}")
        print(f"初始化项目文件数：{len(created)}")
        print(f"Git 初始提交：{initial_head}")
        print(f"项目类型：{profile}（{profile_data['label']}）")
        print(f"GOVERNANCE_MODE {governance_mode}")
        print(f"治理模式：{'Lite 极简' if governance_mode == 'lite' else 'Standard 标准'}")
        print(f"选择依据：{governance_reason}")
        if backup:
            print(f"原目录已安全备份：{backup}")
        print("\n用户下一步只需继续与项目经理主智能体讨论项目和需求；内部命令由对应角色自动执行。")
        return 0
    except Exception as exc:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        print(f"错误：项目初始化未完成，临时目录已清理：{exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="个人 AI 开发项目启动器 V1.9.0")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="创建强制文档写回项目")
    init.add_argument("--target")
    init.add_argument("--name")
    init.add_argument("--slug")
    init.add_argument("--description")
    init.add_argument("--profile", choices=sorted(load_profiles()))
    init.add_argument("--governance-mode", choices=sorted(GOVERNANCE_MODES))
    init.add_argument("--force", action="store_true", help="先备份非空目标目录，再原子替换")
    init.set_defaults(func=create_project)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
