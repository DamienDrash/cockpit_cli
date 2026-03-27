"""Helpers for deterministic release artifact preparation."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tomllib
from pathlib import Path
from typing import Iterable, Sequence


def sync_directory(source: Path, destination: Path) -> None:
    """Replace destination with the contents of source."""

    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"Source directory does not exist: {source}")
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def export_runtime_requirements(pyproject_path: Path, output_path: Path) -> list[str]:
    """Export core project dependencies as a requirements-style file."""

    document = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = document.get("project", {})
    dependencies = list(dict.fromkeys(project.get("dependencies", [])))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(dependencies)
    if payload:
        payload = f"{payload}\n"
    output_path.write_text(payload, encoding="utf-8")
    return dependencies


def collect_release_files(
    root: Path,
    *,
    exclude_names: Sequence[str] = (),
    exclude_suffixes: Sequence[str] = (),
) -> list[Path]:
    """Collect release files in stable order."""

    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in exclude_names:
            continue
        if any(path.name.endswith(suffix) for suffix in exclude_suffixes):
            continue
        files.append(path)
    return files


def write_sha256_manifest(
    paths: Iterable[Path], output_path: Path, *, root: Path | None = None
) -> None:
    """Write a sha256 checksum manifest."""

    lines: list[str] = []
    for path in paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        label = path.relative_to(root).as_posix() if root else path.name
        lines.append(f"{digest}  {label}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_release_manifest(
    paths: Iterable[Path],
    output_path: Path,
    *,
    root: Path,
    version: str,
    git_ref: str,
    workflow_ref: str | None = None,
) -> None:
    """Write a JSON release manifest with deterministic file metadata."""

    artifacts: list[dict[str, object]] = []
    for path in paths:
        artifacts.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    payload = {
        "version": version,
        "git_ref": git_ref,
        "workflow_ref": workflow_ref,
        "artifacts": artifacts,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cockpit release tooling helpers.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync-layout-editor")
    sync_parser.add_argument(
        "--source", type=Path, default=Path("web/layout-editor/dist")
    )
    sync_parser.add_argument(
        "--destination",
        type=Path,
        default=Path("src/cockpit/infrastructure/web/layout_editor/static"),
    )

    requirements_parser = subparsers.add_parser("export-runtime-requirements")
    requirements_parser.add_argument(
        "--pyproject", type=Path, default=Path("pyproject.toml")
    )
    requirements_parser.add_argument("--output", type=Path, required=True)

    manifest_parser = subparsers.add_parser("manifest")
    manifest_parser.add_argument("--root", type=Path, required=True)
    manifest_parser.add_argument("--output", type=Path, required=True)
    manifest_parser.add_argument("--version", required=True)
    manifest_parser.add_argument("--git-ref", required=True)
    manifest_parser.add_argument("--workflow-ref")

    checksums_parser = subparsers.add_parser("checksums")
    checksums_parser.add_argument("--root", type=Path, required=True)
    checksums_parser.add_argument("--output", type=Path, required=True)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "sync-layout-editor":
        sync_directory(args.source, args.destination)
        return 0

    if args.command == "export-runtime-requirements":
        export_runtime_requirements(args.pyproject, args.output)
        return 0

    if args.command == "manifest":
        files = collect_release_files(
            args.root,
            exclude_names=(args.output.name, "SHA256SUMS.txt"),
            exclude_suffixes=(".sigstore.json",),
        )
        write_release_manifest(
            files,
            args.output,
            root=args.root,
            version=args.version,
            git_ref=args.git_ref,
            workflow_ref=args.workflow_ref,
        )
        return 0

    if args.command == "checksums":
        files = collect_release_files(
            args.root,
            exclude_names=(args.output.name,),
            exclude_suffixes=(".sigstore.json",),
        )
        write_sha256_manifest(files, args.output, root=args.root)
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
