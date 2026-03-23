from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from cockpit.tooling.release import (
    collect_release_files,
    export_runtime_requirements,
    sync_directory,
    write_release_manifest,
    write_sha256_manifest,
)


class ReleaseToolingTests(unittest.TestCase):
    def test_export_runtime_requirements_reads_project_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pyproject = root / "pyproject.toml"
            output = root / "requirements.txt"
            pyproject.write_text(
                textwrap.dedent(
                    """
                    [project]
                    name = "demo"
                    dependencies = ["textual>=0.58.0", "PyYAML>=6.0"]
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            dependencies = export_runtime_requirements(pyproject, output)

            self.assertEqual(dependencies, ["textual>=0.58.0", "PyYAML>=6.0"])
            self.assertEqual(output.read_text(encoding="utf-8"), "textual>=0.58.0\nPyYAML>=6.0\n")

    def test_sync_directory_replaces_stale_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            (source / "index.html").write_text("fresh", encoding="utf-8")
            (destination / "stale.txt").write_text("stale", encoding="utf-8")

            sync_directory(source, destination)

            self.assertTrue((destination / "index.html").exists())
            self.assertFalse((destination / "stale.txt").exists())

    def test_manifest_and_checksums_use_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_root = root / "release-assets"
            (release_root / "dist").mkdir(parents=True)
            wheel = release_root / "dist" / "cockpit-0.1.0-py3-none-any.whl"
            sbom = release_root / "sbom.json"
            wheel.write_text("wheel", encoding="utf-8")
            sbom.write_text("sbom", encoding="utf-8")
            manifest = release_root / "release-manifest.json"
            checksums = release_root / "SHA256SUMS.txt"

            files = collect_release_files(release_root)
            write_release_manifest(files, manifest, root=release_root, version="0.1.0", git_ref="refs/tags/v0.1.0")
            write_sha256_manifest(collect_release_files(release_root, exclude_names=(checksums.name,), exclude_suffixes=(".sigstore.json",)), checksums, root=release_root)

            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
            paths = [artifact["path"] for artifact in manifest_payload["artifacts"]]
            self.assertIn("dist/cockpit-0.1.0-py3-none-any.whl", paths)
            self.assertIn("sbom.json", paths)
            checksum_lines = checksums.read_text(encoding="utf-8").splitlines()
            self.assertTrue(any(line.endswith("  dist/cockpit-0.1.0-py3-none-any.whl") for line in checksum_lines))


if __name__ == "__main__":
    unittest.main()
