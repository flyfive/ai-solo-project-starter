#!/usr/bin/env python3
"""Build and verify a deterministic, cross-platform starter-template ZIP."""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import re
import tempfile
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True
from path_safety import ordinary_tree_files, reject_link_ancestors

EXCLUDED_DIRECTORIES = {
    ".git", ".test-runtime", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "__pycache__",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def package_files(source: Path, excluded_paths: set[Path]) -> list[Path]:
    files: list[Path] = []
    for path in ordinary_tree_files(source, EXCLUDED_DIRECTORIES, EXCLUDED_SUFFIXES):
        relative = path.relative_to(source)
        if any(part in EXCLUDED_DIRECTORIES for part in relative.parts):
            continue
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(source)
        except (OSError, ValueError):
            raise SystemExit(
                f"package source entry resolves outside the source root: {relative.as_posix()}"
            ) from None
        if not path.is_file():
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        if resolved in excluded_paths:
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(source).as_posix())


def write_bytes_atomically(path: Path, content: bytes) -> None:
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".restore", dir=path.parent)
    temporary = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def publish_transaction(staged_files: list[tuple[Path, Path]]) -> None:
    targets = [target for target, _ in staged_files]
    backups = {target: target.read_bytes() if target.exists() else None for target in targets}
    fail_after = int(os.environ.get(
        "AI_STARTER_TEST_FAIL_PACKAGE_TRANSACTION_AFTER", "0"
    ).strip() or "0")
    try:
        for index, (target, staged) in enumerate(staged_files, 1):
            os.replace(staged, target)
            if fail_after == index:
                raise RuntimeError(
                    f"injected package transaction failure after replacement {index}"
                )
    except BaseException:
        for target, content in backups.items():
            if content is None:
                if target.exists():
                    target.unlink()
            else:
                write_bytes_atomically(target, content)
        raise


def zip_info(arcname: str, executable: bool) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    mode = 0o100755 if executable else 0o100644
    info.external_attr = mode << 16
    return info


def verify_archive(archive: Path, source: Path, package_name: str, files: list[Path]) -> None:
    expected = {
        f"{package_name}/{path.relative_to(source).as_posix()}": hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        if any("\\" in name for name in names):
            raise RuntimeError("ZIP contains a Windows backslash entry")
        if any(name.startswith("/") or "/../" in f"/{name}/" for name in names):
            raise RuntimeError("ZIP contains an unsafe entry path")
        if package.testzip() is not None:
            raise RuntimeError("ZIP CRC verification failed")
        actual = {
            info.filename: hashlib.sha256(package.read(info.filename)).hexdigest()
            for info in package.infolist()
            if not info.is_dir()
        }
    if expected != actual:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(name for name in set(expected) & set(actual) if expected[name] != actual[name])
        raise RuntimeError(
            f"ZIP content mismatch; missing={missing}, extra={extra}, changed={changed}"
        )


def build(source: Path, output_dir: Path, *, force: bool) -> tuple[Path, Path, str, int]:
    reject_link_ancestors(source)
    source = source.resolve()
    output_dir = output_dir.resolve()
    if not source.is_dir():
        raise SystemExit(f"source directory does not exist: {source}")
    version_path = source / "VERSION"
    reject_link_ancestors(version_path)
    if not version_path.is_file():
        raise SystemExit(f"VERSION is missing: {version_path}")
    version = version_path.read_text(encoding="utf-8").strip()
    if not VERSION_PATTERN.fullmatch(version):
        raise SystemExit(f"VERSION must use major.minor.patch: {version}")

    package_name = f"AI_Solo_Developer_Project_Starter_V{version}"
    archive = output_dir / f"{package_name}.zip"
    checksum = output_dir / f"{package_name}_SHA256.txt"
    if not force and (archive.exists() or checksum.exists()):
        raise SystemExit(
            f"refusing to overwrite an existing package; remove it explicitly or pass --force: {archive}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    excluded_paths = {archive.resolve(), checksum.resolve()}
    files = package_files(source, excluded_paths)
    if not files:
        raise SystemExit("source package contains no files")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{package_name}.", suffix=".tmp", dir=output_dir
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    checksum_temporary: Path | None = None
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
            for path in files:
                relative = path.relative_to(source).as_posix()
                arcname = f"{package_name}/{relative}"
                executable = relative in {"scaffold/.githooks/pre-commit"} or path.suffix == ".sh"
                package.writestr(zip_info(arcname, executable), path.read_bytes())
        verify_archive(temporary, source, package_name, files)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        checksum_descriptor, checksum_temporary_name = tempfile.mkstemp(
            prefix=f".{checksum.name}.", suffix=".tmp", dir=output_dir
        )
        checksum_temporary = Path(checksum_temporary_name)
        with os.fdopen(checksum_descriptor, "wb") as handle:
            handle.write(f"{digest}  {archive.name}\n".encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        publish_transaction([
            (archive, temporary),
            (checksum, checksum_temporary),
        ])
    finally:
        if temporary.exists():
            temporary.unlink()
        if checksum_temporary is not None and checksum_temporary.exists():
            checksum_temporary.unlink()

    return archive, checksum, digest, len(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    archive, checksum, digest, count = build(args.source, args.output_dir, force=args.force)
    print(f"PACKAGE_CREATED {archive}")
    print(f"PACKAGE_FILES {count}")
    print(f"PACKAGE_SHA256 {digest}")
    print(f"CHECKSUM_FILE {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
