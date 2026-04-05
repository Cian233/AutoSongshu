from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from autosongshu_agent.environment import (
    GitStatus,
    ProjectContext,
    detect_git_root,
    get_git_status,
    scan_project_structure,
    build_project_context,
    render_environment_context,
    inject_git_status_to_prompt,
)


class GitStatusTests(unittest.TestCase):
    def test_no_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            status = get_git_status(Path(tmpdir))
            self.assertFalse(status.has_git)

    def test_git_repo_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo_path,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=repo_path,
                capture_output=True,
            )
            status = get_git_status(repo_path)
            self.assertTrue(status.has_git)
            self.assertTrue(status.is_clean)

    def test_git_with_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo_path,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=repo_path,
                capture_output=True,
            )
            (repo_path / "test.py").write_text("print('hello')")
            status = get_git_status(repo_path)
            self.assertTrue(status.has_git)
            self.assertFalse(status.is_clean)
            self.assertEqual(len(status.untracked_files), 1)

    def test_as_summary_no_git(self) -> None:
        status = GitStatus(has_git=False)
        summary = status.as_summary()
        self.assertIn("No Git repository", summary)

    def test_as_summary_clean(self) -> None:
        status = GitStatus(branch="main", is_clean=True, has_git=True)
        summary = status.as_summary()
        self.assertIn("Branch: main", summary)
        self.assertIn("clean", summary)


class ProjectContextTests(unittest.TestCase):
    def test_project_context_creation(self) -> None:
        ctx = ProjectContext(
            root=Path("/tmp/test"),
            name="test",
            python_files=10,
            has_tests=True,
        )
        self.assertEqual(ctx.name, "test")
        self.assertEqual(ctx.python_files, 10)

    def test_as_summary(self) -> None:
        ctx = ProjectContext(
            root=Path("/tmp/test"),
            name="my-project",
            python_files=5,
            has_tests=True,
            git_status=GitStatus(branch="main", is_clean=True, has_git=True),
        )
        summary = ctx.as_summary()
        self.assertIn("my-project", summary)
        self.assertIn("Python files: 5", summary)


class ScanProjectStructureTests(unittest.TestCase):
    def test_scan_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            structure = scan_project_structure(Path(tmpdir))
            self.assertEqual(structure["python_files"], 0)
            self.assertFalse(structure["has_tests"])

    def test_scan_with_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "main.py").write_text("print('hello')")
            (root / "tests").mkdir()
            (root / "tests" / "test_main.py").write_text("def test_x(): pass")
            structure = scan_project_structure(root)
            self.assertEqual(structure["python_files"], 2)
            self.assertTrue(structure["has_tests"])


class BuildProjectContextTests(unittest.TestCase):
    def test_build_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "main.py").write_text("print('hello')")
            ctx = build_project_context(root)
            self.assertEqual(ctx.root, root)
            self.assertEqual(ctx.name, root.name)
            self.assertEqual(ctx.python_files, 1)


class RenderEnvironmentContextTests(unittest.TestCase):
    def test_render_context(self) -> None:
        ctx = ProjectContext(
            root=Path("/tmp/test"),
            name="test-project",
            python_files=3,
            git_status=GitStatus(has_git=False),
        )
        rendered = render_environment_context(ctx)
        self.assertIn("Environment Context", rendered)
        self.assertIn("test-project", rendered)


class InjectGitStatusToPromptTests(unittest.TestCase):
    def test_inject_no_git(self) -> None:
        base = "You are an assistant.\n\nAuthorization context:\n- Test"
        ctx = ProjectContext(
            root=Path("/tmp/test"),
            name="test",
            git_status=GitStatus(has_git=False),
        )
        result = inject_git_status_to_prompt(base, ctx)
        self.assertNotIn("<environment_snapshot>", result)

    def test_inject_with_git(self) -> None:
        base = "You are an assistant.\n\nAuthorization context:\n- Test"
        ctx = ProjectContext(
            root=Path("/tmp/test"),
            name="test",
            git_status=GitStatus(branch="main", is_clean=True, has_git=True),
        )
        result = inject_git_status_to_prompt(base, ctx)
        self.assertIn("<environment_snapshot>", result)
        self.assertIn("Branch: main", result)

    def test_inject_without_marker(self) -> None:
        base = "You are an assistant."
        ctx = ProjectContext(
            root=Path("/tmp/test"),
            name="test",
            git_status=GitStatus(branch="dev", is_clean=True, has_git=True),
        )
        result = inject_git_status_to_prompt(base, ctx)
        self.assertIn("<environment_snapshot>", result)


if __name__ == "__main__":
    unittest.main()
