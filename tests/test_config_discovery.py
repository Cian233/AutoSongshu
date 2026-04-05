from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autosongshu_agent.config_discovery import (
    DiscoveredFile,
    DiscoveredConfig,
    compute_content_hash,
    discover_files,
    discover_instructions,
    build_merged_system_prompt,
    ConfigDiscovery,
    DEFAULT_INSTRUCTION_FILENAMES,
    DEFAULT_CONFIG_FILENAMES,
)


class ComputeContentHashTests(unittest.TestCase):
    def test_hash_consistency(self) -> None:
        content = "test content"
        hash1 = compute_content_hash(content)
        hash2 = compute_content_hash(content)
        self.assertEqual(hash1, hash2)

    def test_hash_different_for_different_content(self) -> None:
        hash1 = compute_content_hash("content 1")
        hash2 = compute_content_hash("content 2")
        self.assertNotEqual(hash1, hash2)


class DiscoveredFileTests(unittest.TestCase):
    def test_to_dict(self) -> None:
        file = DiscoveredFile(
            path=Path("/tmp/test.md"),
            content="test",
            content_hash="abc123",
            priority=5,
        )
        d = file.to_dict()
        self.assertEqual(d["path"], str(Path("/tmp/test.md")))
        self.assertEqual(d["priority"], 5)


class DiscoverFilesTests(unittest.TestCase):
    def test_discover_no_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            files = discover_files(Path(tmpdir), ("nonexistent.md",))
            self.assertEqual(len(files), 0)

    def test_discover_single_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".autosongshu").mkdir()
            (root / ".autosongshu" / "instructions.md").write_text("test instructions")
            files = discover_files(root, (".autosongshu/instructions.md",))
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].content, "test instructions")

    def test_discover_dedup_by_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".autosongshu").mkdir()
            (root / ".autosongshu" / "instructions.md").write_text("same content")
            files = discover_files(
                root, (".autosongshu/instructions.md", ".autosongshu/instructions.md")
            )
            self.assertEqual(len(files), 1)

    def test_discover_max_depth(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".autosongshu").mkdir()
            (root / ".autosongshu" / "instructions.md").write_text("root content")
            files = discover_files(root, (".autosongshu/instructions.md",), max_depth=1)
            self.assertEqual(len(files), 1)


class DiscoverInstructionsTests(unittest.TestCase):
    def test_discover_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = discover_instructions(Path(tmpdir))
            self.assertEqual(len(config.instructions), 0)

    def test_discover_with_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".autosongshu").mkdir()
            (root / ".autosongshu" / "instructions.md").write_text(
                "# Instructions\nTest content"
            )
            config = discover_instructions(root)
            self.assertGreater(len(config.instructions), 0)

    def test_discover_respects_max_chars(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".autosongshu").mkdir()
            long_content = "x" * 1000
            (root / ".autosongshu" / "instructions.md").write_text(long_content)
            config = discover_instructions(root, max_chars=100)
            merged = config.merged_instructions(max_chars=100)
            self.assertLessEqual(len(merged), 150)


class DiscoveredConfigTests(unittest.TestCase):
    def test_merged_instructions_empty(self) -> None:
        config = DiscoveredConfig()
        merged = config.merged_instructions()
        self.assertEqual(merged, "")

    def test_merged_instructions_single(self) -> None:
        config = DiscoveredConfig(
            instructions=[
                DiscoveredFile(
                    path=Path("/tmp/test.md"),
                    content="Test content",
                    content_hash="abc",
                    priority=0,
                )
            ]
        )
        merged = config.merged_instructions()
        self.assertIn("Test content", merged)

    def test_as_dict(self) -> None:
        config = DiscoveredConfig(
            instructions=[
                DiscoveredFile(
                    path=Path("/tmp/test.md"),
                    content="Test",
                    content_hash="abc",
                    priority=0,
                )
            ]
        )
        d = config.as_dict()
        self.assertIn("instructions", d)


class BuildMergedSystemPromptTests(unittest.TestCase):
    def test_empty_base_prompt(self) -> None:
        result = build_merged_system_prompt("", None)
        self.assertEqual(result, "")

    def test_base_prompt_without_start_dir(self) -> None:
        result = build_merged_system_prompt("Test prompt", None)
        self.assertEqual(result, "Test prompt")

    def test_injects_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".autosongshu").mkdir()
            (root / ".autosongshu" / "instructions.md").write_text(
                "Custom instructions"
            )
            result = build_merged_system_prompt("Base prompt", root)
            self.assertIn("<project_instructions>", result)
            self.assertIn("Custom instructions", result)


class ConfigDiscoveryTests(unittest.TestCase):
    def test_service_caches_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = ConfigDiscovery(start_dir=Path(tmpdir))
            config1 = service.discover()
            config2 = service.discover()
            self.assertIs(config1, config2)

    def test_service_force_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            service = ConfigDiscovery(start_dir=root)
            config1 = service.discover()
            (root / ".autosongshu").mkdir()
            (root / ".autosongshu" / "instructions.md").write_text("New content")
            service.clear_cache()
            config2 = service.discover()
            self.assertIsNot(config1, config2)

    def test_get_merged_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".autosongshu").mkdir()
            (root / ".autosongshu" / "instructions.md").write_text("Test instructions")
            service = ConfigDiscovery(start_dir=root)
            merged = service.get_merged_instructions()
            self.assertIn("Test instructions", merged)

    def test_inject_into_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".autosongshu").mkdir()
            (root / ".autosongshu" / "instructions.md").write_text(
                "Project specific rules"
            )
            service = ConfigDiscovery(start_dir=root)
            result = service.inject_into_prompt("Base system prompt")
            self.assertIn("<project_instructions>", result)

    def test_list_discovered_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".autosongshu").mkdir()
            (root / ".autosongshu" / "instructions.md").write_text("Content")
            service = ConfigDiscovery(start_dir=root)
            files = service.list_discovered_files()
            self.assertEqual(len(files), 1)


if __name__ == "__main__":
    unittest.main()
