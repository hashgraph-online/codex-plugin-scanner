"""OpenCode ecosystem adapter."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .types import Ecosystem, NormalizedPackage, PackageCandidate

IGNORED_DIRS = {"node_modules", ".git", ".venv", "venv", "dist", "__pycache__"}
BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", flags=re.DOTALL)


def _iter_files(root: Path, pattern: str) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob(pattern):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.is_file():
            files.append(path)
    return files


def _strip_jsonc(text: str) -> str:
    without_blocks = BLOCK_COMMENT_RE.sub("", text)
    output: list[str] = []
    in_string = False
    escape = False
    in_line_comment = False

    for char in without_blocks:
        if in_line_comment:
            if char == "\n":
                in_line_comment = False
                output.append(char)
            continue

        if in_string:
            output.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            output.append(char)
            continue

        if char == "/":
            if output and output[-1] == "/":
                output.pop()
                in_line_comment = True
                continue
            output.append(char)
            continue

        output.append(char)

    return "".join(output)


def _load_json_or_jsonc(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if path.suffix == ".jsonc":
        text = _strip_jsonc(text)
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        return {}
    return {}


class OpenCodeAdapter:
    """Adapter for OpenCode plugin repositories."""

    ecosystem_id = Ecosystem.OPENCODE

    def detect(self, root: Path) -> list[PackageCandidate]:
        candidates: list[PackageCandidate] = []
        seen_roots: set[Path] = set()
        for config_name in ("opencode.json", "opencode.jsonc"):
            for manifest_path in _iter_files(root, config_name):
                package_root = manifest_path.parent
                if package_root in seen_roots:
                    continue
                seen_roots.add(package_root)
                candidates.append(
                    PackageCandidate(
                        ecosystem=Ecosystem.OPENCODE,
                        package_kind="workspace-bundle",
                        root_path=package_root,
                        manifest_path=manifest_path,
                        detection_reason=f"found {config_name}",
                    )
                )

        for opencode_dir in (path for path in root.rglob(".opencode") if path.is_dir()):
            if any(part in IGNORED_DIRS for part in opencode_dir.parts):
                continue
            package_root = opencode_dir.parent
            if package_root in seen_roots:
                continue
            seen_roots.add(package_root)
            candidates.append(
                PackageCandidate(
                    ecosystem=Ecosystem.OPENCODE,
                    package_kind="workspace-bundle",
                    root_path=package_root,
                    manifest_path=None,
                    detection_reason="found .opencode workspace directory",
                )
            )
        return candidates

    def parse(self, candidate: PackageCandidate) -> NormalizedPackage:
        manifest = _load_json_or_jsonc(candidate.manifest_path) if candidate.manifest_path else {}
        root = candidate.root_path
        components: dict[str, tuple[str, ...]] = {}
        commands_dir = root / ".opencode" / "commands"
        plugins_dir = root / ".opencode" / "plugins"
        if commands_dir.is_dir():
            components["commands"] = tuple(
                sorted(str(path.relative_to(root)) for path in commands_dir.rglob("*.md") if path.is_file())
            )
        if plugins_dir.is_dir():
            components["plugin_modules"] = tuple(
                sorted(
                    str(path.relative_to(root))
                    for path in plugins_dir.rglob("*")
                    if path.is_file() and path.suffix in {".js", ".ts", ".mjs", ".cjs"}
                )
            )
        mcp_config = manifest.get("mcp")
        if isinstance(mcp_config, dict):
            components["mcp_servers"] = tuple(sorted(str(key) for key in mcp_config))

        return NormalizedPackage(
            ecosystem=Ecosystem.OPENCODE,
            package_kind=candidate.package_kind,
            root_path=root,
            manifest_path=candidate.manifest_path,
            name=manifest.get("name") if isinstance(manifest.get("name"), str) else None,
            version=manifest.get("version") if isinstance(manifest.get("version"), str) else None,
            metadata={
                key: value for key in ("description", "repository") if isinstance((value := manifest.get(key)), str)
            },
            components=components,
            raw_manifest=manifest,
        )
