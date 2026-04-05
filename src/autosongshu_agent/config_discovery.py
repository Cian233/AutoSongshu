from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_INSTRUCTION_FILENAMES = (
    ".autosongshu/instructions.md",
    ".autosongshu/instructions.txt",
    ".autosongshu/prompt.md",
    "AUTOSONGSHU_INSTRUCTIONS.md",
)

DEFAULT_CONFIG_FILENAMES = (
    ".autosongshu/config.yaml",
    ".autosongshu/config.yml",
    "autosongshu.yaml",
    "autosongshu.yml",
)


@dataclass
class DiscoveredFile:
    path: Path
    content: str
    content_hash: str
    priority: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "content_hash": self.content_hash,
            "priority": self.priority,
        }


@dataclass
class DiscoveredConfig:
    instructions: list[DiscoveredFile] = field(default_factory=list)
    configs: list[DiscoveredFile] = field(default_factory=list)
    root_dir: Path | None = None

    def merged_instructions(self, max_chars: int = 12000) -> str:
        sections: list[str] = []
        total_chars = 0
        for file in sorted(self.instructions, key=lambda f: f.priority, reverse=True):
            if total_chars + len(file.content) > max_chars:
                remaining = max_chars - total_chars
                if remaining > 100:
                    truncated = file.content[:remaining] + "\n...[truncated]"
                    sections.append(f"# From: {file.path}\n\n{truncated}")
                break
            sections.append(f"# From: {file.path}\n\n{file.content}")
            total_chars += len(file.content)
        return "\n\n---\n\n".join(sections)

    def as_dict(self) -> dict[str, Any]:
        return {
            "instructions": [f.to_dict() for f in self.instructions],
            "configs": [f.to_dict() for f in self.configs],
            "root_dir": str(self.root_dir) if self.root_dir else None,
        }


def compute_content_hash(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]


def discover_files(
    start_dir: Path,
    filenames: tuple[str, ...],
    max_depth: int = 10,
) -> list[DiscoveredFile]:
    discovered: list[DiscoveredFile] = []
    seen_hashes: set[str] = set()
    current = start_dir.resolve()
    depth = 0

    while current is not None and depth < max_depth:
        for filename in filenames:
            candidate = current / filename
            if candidate.is_file():
                try:
                    content = candidate.read_text(encoding="utf-8")
                except Exception:
                    continue
                content_hash = compute_content_hash(content)
                if content_hash in seen_hashes:
                    continue
                seen_hashes.add(content_hash)
                discovered.append(
                    DiscoveredFile(
                        path=candidate,
                        content=content,
                        content_hash=content_hash,
                        priority=max_depth - depth,
                    )
                )
        parent = current.parent
        if parent == current:
            break
        current = parent
        depth += 1

    return discovered


def discover_instructions(
    start_dir: Path,
    additional_filenames: list[str] | None = None,
    max_chars: int = 12000,
) -> DiscoveredConfig:
    all_filenames = list(DEFAULT_INSTRUCTION_FILENAMES)
    if additional_filenames:
        all_filenames.extend(additional_filenames)

    instructions = discover_files(start_dir, tuple(all_filenames))
    configs = discover_files(start_dir, DEFAULT_CONFIG_FILENAMES)

    root_dir = None
    if start_dir.resolve().exists():
        root_dir = start_dir.resolve()
        for parent in [root_dir] + list(root_dir.parents):
            if (parent / ".git").exists():
                root_dir = parent
                break

    return DiscoveredConfig(
        instructions=instructions,
        configs=configs,
        root_dir=root_dir,
    )


def build_merged_system_prompt(
    base_prompt: str,
    start_dir: Path | None = None,
    max_chars: int = 12000,
) -> str:
    if start_dir is None:
        return base_prompt

    config = discover_instructions(start_dir, max_chars=max_chars)
    if not config.instructions:
        return base_prompt

    merged = config.merged_instructions(max_chars=max_chars)
    if not merged.strip():
        return base_prompt

    instruction_section = f"""
<project_instructions>
{merged}
</project_instructions>
"""
    if "</system_prompt>" in base_prompt:
        return base_prompt.replace(
            "</system_prompt>", instruction_section + "\n</system_prompt>"
        )
    return base_prompt + "\n" + instruction_section


class ConfigDiscovery:
    def __init__(
        self,
        start_dir: Path | None = None,
        instruction_filenames: tuple[str, ...] | None = None,
        config_filenames: tuple[str, ...] | None = None,
        max_depth: int = 10,
        max_chars: int = 12000,
    ) -> None:
        self.start_dir = (start_dir or Path.cwd()).resolve()
        self.instruction_filenames = (
            instruction_filenames or DEFAULT_INSTRUCTION_FILENAMES
        )
        self.config_filenames = config_filenames or DEFAULT_CONFIG_FILENAMES
        self.max_depth = max_depth
        self.max_chars = max_chars
        self._cache: DiscoveredConfig | None = None

    def discover(self, force_refresh: bool = False) -> DiscoveredConfig:
        if self._cache is not None and not force_refresh:
            return self._cache
        self._cache = discover_instructions(
            self.start_dir,
            additional_filenames=list(self.instruction_filenames),
            max_chars=self.max_chars,
        )
        return self._cache

    def get_merged_instructions(self) -> str:
        config = self.discover()
        return config.merged_instructions(max_chars=self.max_chars)

    def inject_into_prompt(self, base_prompt: str) -> str:
        return build_merged_system_prompt(base_prompt, self.start_dir, self.max_chars)

    def list_discovered_files(self) -> list[str]:
        config = self.discover()
        return [str(f.path) for f in config.instructions + config.configs]

    def clear_cache(self) -> None:
        self._cache = None


__all__ = [
    "DiscoveredFile",
    "DiscoveredConfig",
    "compute_content_hash",
    "discover_files",
    "discover_instructions",
    "build_merged_system_prompt",
    "ConfigDiscovery",
    "DEFAULT_INSTRUCTION_FILENAMES",
    "DEFAULT_CONFIG_FILENAMES",
]
