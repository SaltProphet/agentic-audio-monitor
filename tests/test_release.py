"""Release contracts: one version, one dependency list, packaged web page."""

from __future__ import annotations

import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from monitor import __version__  # noqa: E402  (needs the repository root on sys.path)


def pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


class ReleaseTests(unittest.TestCase):
    def test_version_is_declared_once(self):
        project = pyproject()["project"]
        self.assertEqual(project["version"], __version__)
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## {__version__}", changelog)

    def test_requirements_match_the_packaging_metadata(self):
        declared = sorted(pyproject()["project"]["dependencies"])
        lines = sorted(
            line.strip()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
        self.assertEqual(lines, declared)

    def test_web_page_is_packaged_with_the_monitor(self):
        data = pyproject()["tool"]["setuptools"]["package-data"]["monitor"]
        self.assertIn("web/*.html", data)
        self.assertTrue((ROOT / "monitor" / "web" / "index.html").is_file())

    def test_license_is_declared_and_packaged(self):
        self.assertEqual(pyproject()["project"]["license"], {"file": "LICENSE"})
        license_file = ROOT / "LICENSE"
        self.assertTrue(license_file.is_file())
        text = license_file.read_text(encoding="utf-8")
        self.assertIn("PolyForm Noncommercial License 1.0.0", text)
        self.assertIn("Noncommercial Purposes", text)

    def test_supported_python_matches_the_installer(self):
        project = pyproject()["project"]
        self.assertEqual(project["requires-python"], ">=3.11,<3.14")
        preflight = (ROOT / "preflight.ps1").read_text(encoding="utf-8")
        self.assertIn("$minor -lt 11", preflight)
        self.assertIn("$minor -gt 13", preflight)


if __name__ == "__main__":
    unittest.main()
