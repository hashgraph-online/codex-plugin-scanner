"""Tests for multi-ecosystem adapter detection and scanning."""

import json
import shutil
from pathlib import Path

from codex_plugin_scanner.cli import main
from codex_plugin_scanner.ecosystems.detect import detect_packages
from codex_plugin_scanner.ecosystems.types import Ecosystem
from codex_plugin_scanner.models import ScanOptions
from codex_plugin_scanner.scanner import scan_plugin

FIXTURES = Path(__file__).parent / "fixtures"


def test_detect_claude_package() -> None:
    packages = detect_packages(FIXTURES / "claude-plugin-good")
    ecosystems = {package.ecosystem for package in packages}
    assert Ecosystem.CLAUDE in ecosystems


def test_detect_gemini_package() -> None:
    packages = detect_packages(FIXTURES / "gemini-extension-good")
    ecosystems = {package.ecosystem for package in packages}
    assert Ecosystem.GEMINI in ecosystems


def test_detect_opencode_package() -> None:
    packages = detect_packages(FIXTURES / "opencode-good")
    ecosystems = {package.ecosystem for package in packages}
    assert Ecosystem.OPENCODE in ecosystems


def test_scan_claude_with_explicit_ecosystem() -> None:
    result = scan_plugin(
        FIXTURES / "claude-plugin-good",
        ScanOptions(ecosystem="claude", cisco_skill_scan="off"),
    )
    assert "claude" in result.ecosystems
    assert any(category.name.endswith("Claude Plugin") for category in result.categories)
    assert result.score > 0


def test_scan_gemini_with_explicit_ecosystem() -> None:
    result = scan_plugin(
        FIXTURES / "gemini-extension-good",
        ScanOptions(ecosystem="gemini", cisco_skill_scan="off"),
    )
    assert "gemini" in result.ecosystems
    assert any(category.name.endswith("Gemini Extension") for category in result.categories)
    assert result.score > 0


def test_scan_opencode_with_explicit_ecosystem() -> None:
    result = scan_plugin(
        FIXTURES / "opencode-good",
        ScanOptions(ecosystem="opencode", cisco_skill_scan="off"),
    )
    assert "opencode" in result.ecosystems
    assert any(category.name.endswith("OpenCode Plugin") for category in result.categories)
    assert result.score > 0


def test_scan_auto_detects_multiple_packages() -> None:
    result = scan_plugin(
        FIXTURES / "multi-ecosystem-repo",
        ScanOptions(ecosystem="auto", cisco_skill_scan="off"),
    )
    assert set(result.ecosystems) >= {"codex", "gemini"}
    assert len(result.packages) >= 2
    assert any(category.name.startswith("[codex:") for category in result.categories)
    assert any(category.name.startswith("[gemini:") for category in result.categories)


def test_scan_auto_repository_includes_non_codex_packages(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    shutil.copytree(FIXTURES / "multi-plugin-repo", repo_root)
    gemini_root = repo_root / "gemini-ext"
    gemini_root.mkdir(parents=True, exist_ok=True)
    (gemini_root / "README.md").write_text("Gemini extension", encoding="utf-8")
    (gemini_root / "gemini-extension.json").write_text(
        json.dumps(
            {
                "name": "demo-gemini",
                "version": "1.0.0",
                "commands": [{"name": "echo", "description": "Echo command", "prompt": "hi"}],
            }
        ),
        encoding="utf-8",
    )

    result = scan_plugin(repo_root, ScanOptions(ecosystem="auto", cisco_skill_scan="off"))

    assert set(result.ecosystems) >= {"codex", "gemini"}
    assert any(category.name.startswith("[gemini:") for category in result.categories)


def test_mixed_scan_rebases_findings_to_scan_root() -> None:
    result = scan_plugin(
        FIXTURES / "multi-ecosystem-repo",
        ScanOptions(ecosystem="auto", cisco_skill_scan="off"),
    )
    file_paths = {finding.file_path for finding in result.findings if finding.file_path}

    assert any(path.startswith("codex-plugin/") for path in file_paths)
    assert ".codex-plugin/plugin.json" not in file_paths
    assert "SECURITY.md" not in file_paths


def test_cli_lists_supported_ecosystems(capsys) -> None:
    rc = main(["--list-ecosystems"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "codex" in captured.out
    assert "claude" in captured.out
    assert "gemini" in captured.out
    assert "opencode" in captured.out


def test_opencode_jsonc_allows_inline_comments(tmp_path: Path) -> None:
    (tmp_path / ".opencode" / "commands").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".opencode" / "commands" / "hello.md").write_text(
        "---\nname: hello\ndescription: test\n---\nrun\n",
        encoding="utf-8",
    )
    (tmp_path / "opencode.jsonc").write_text(
        '{\n  "name": "demo", // inline comment\n  "version": "1.0.0"\n}\n',
        encoding="utf-8",
    )

    result = scan_plugin(tmp_path, ScanOptions(ecosystem="opencode", cisco_skill_scan="off"))

    assert "opencode" in result.ecosystems
    assert all(finding.rule_id != "OPENCODE_CONFIG_INVALID" for finding in result.findings)


def test_opencode_empty_object_config_is_not_marked_invalid(tmp_path: Path) -> None:
    (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")

    result = scan_plugin(tmp_path, ScanOptions(ecosystem="opencode", cisco_skill_scan="off"))

    assert all(finding.rule_id != "OPENCODE_CONFIG_INVALID" for finding in result.findings)
