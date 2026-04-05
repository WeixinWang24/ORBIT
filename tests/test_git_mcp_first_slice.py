from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from src.mcp_servers.system.core.git.stdio_server import _git_add_result, _git_changed_files_result, _git_checkout_branch_result, _git_commit_result, _git_diff_result, _git_log_result, _git_restore_result, _git_show_result, _git_status_result, _git_unstage_result


class GitMcpFirstSliceTests(unittest.TestCase):
    def test_git_status_reports_untracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / "notes.txt").write_text("hello\n", encoding="utf-8")

            result = _git_status_result(cwd=str(repo))

            self.assertFalse(result["clean"])
            self.assertEqual(result["untracked"], ["notes.txt"])
            self.assertEqual(result["untracked_count"], 1)
            self.assertEqual(result["staged_count"], 0)
            self.assertEqual(result["unstaged_count"], 0)

    def test_git_diff_returns_working_tree_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "ORBIT Test"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "orbit@example.com"], cwd=repo, check=True, capture_output=True, text=True)
            target = repo / "notes.txt"
            target.write_text("alpha\nbeta\n", encoding="utf-8")
            subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
            target.write_text("alpha\nBETA\n", encoding="utf-8")

            result = _git_diff_result(cwd=str(repo), path="notes.txt", staged=False, max_chars=4000)

            self.assertTrue(result["has_diff"])
            self.assertFalse(result["truncated"])
            self.assertIn("diff --git", result["diff"])
            self.assertIn("-beta", result["diff"])
            self.assertIn("+BETA", result["diff"])

    def test_git_diff_can_read_staged_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "ORBIT Test"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "orbit@example.com"], cwd=repo, check=True, capture_output=True, text=True)
            target = repo / "notes.txt"
            target.write_text("alpha\nbeta\n", encoding="utf-8")
            subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
            target.write_text("alpha\nBETA\n", encoding="utf-8")
            subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True, capture_output=True, text=True)

            result = _git_diff_result(cwd=str(repo), path="notes.txt", staged=True, max_chars=4000)

            self.assertTrue(result["has_diff"])
            self.assertTrue(result["staged"])
            self.assertIn("+BETA", result["diff"])

    def test_git_log_returns_recent_commit_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "ORBIT Test"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "orbit@example.com"], cwd=repo, check=True, capture_output=True, text=True)
            target = repo / "notes.txt"
            target.write_text("alpha\n", encoding="utf-8")
            subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
            target.write_text("alpha\nbeta\n", encoding="utf-8")
            subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "expand note"], cwd=repo, check=True, capture_output=True, text=True)

            result = _git_log_result(cwd=str(repo), limit=2)

            self.assertEqual(result["commit_count"], 2)
            self.assertEqual(result["commits"][0]["subject"], "expand note")
            self.assertEqual(result["commits"][1]["subject"], "init")

    def test_git_show_returns_bounded_commit_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "ORBIT Test"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "orbit@example.com"], cwd=repo, check=True, capture_output=True, text=True)
            target = repo / "notes.txt"
            target.write_text("alpha\n", encoding="utf-8")
            subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

            result = _git_show_result("HEAD", cwd=str(repo), path="notes.txt", max_chars=4000)

            self.assertIn("commit ", result["output"])
            self.assertIn("notes.txt", result["output"])
            self.assertFalse(result["truncated"])

    def test_git_add_stages_requested_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            target = repo / "notes.txt"
            target.write_text("hello\n", encoding="utf-8")

            result = _git_add_result(paths=["notes.txt"], cwd=str(repo))
            status = _git_status_result(cwd=str(repo))

            self.assertTrue(result["ok"])
            self.assertEqual(result["mutation_kind"], "git_add")
            self.assertEqual(status["staged_count"], 1)

    def test_git_changed_files_returns_split_file_sets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "ORBIT Test"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "orbit@example.com"], cwd=repo, check=True, capture_output=True, text=True)
            tracked = repo / "tracked.txt"
            staged = repo / "staged.txt"
            untracked = repo / "untracked.txt"
            tracked.write_text("alpha\n", encoding="utf-8")
            staged.write_text("beta\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt", "staged.txt"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
            tracked.write_text("ALPHA\n", encoding="utf-8")
            staged.write_text("BETA\n", encoding="utf-8")
            subprocess.run(["git", "add", "staged.txt"], cwd=repo, check=True, capture_output=True, text=True)
            untracked.write_text("gamma\n", encoding="utf-8")

            result = _git_changed_files_result(cwd=str(repo))

            self.assertIn("staged.txt", result["staged_files"])
            self.assertIn("tracked.txt", result["unstaged_files"])
            self.assertIn("untracked.txt", result["untracked_files"])
            self.assertEqual(result["total_changed_files"], 3)

    def test_git_restore_discards_worktree_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "ORBIT Test"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "orbit@example.com"], cwd=repo, check=True, capture_output=True, text=True)
            target = repo / "notes.txt"
            target.write_text("alpha\n", encoding="utf-8")
            subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
            target.write_text("BETA\n", encoding="utf-8")

            result = _git_restore_result(paths="notes.txt", cwd=str(repo))

            self.assertTrue(result["ok"])
            self.assertEqual(target.read_text(encoding="utf-8"), "alpha\n")

    def test_git_unstage_removes_path_from_index_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "ORBIT Test"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "orbit@example.com"], cwd=repo, check=True, capture_output=True, text=True)
            target = repo / "notes.txt"
            target.write_text("alpha\n", encoding="utf-8")
            subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
            target.write_text("BETA\n", encoding="utf-8")
            subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True, capture_output=True, text=True)

            result = _git_unstage_result(paths="notes.txt", cwd=str(repo))
            status = _git_status_result(cwd=str(repo))

            self.assertTrue(result["ok"])
            self.assertEqual(status["staged_count"], 0)
            self.assertEqual(status["unstaged_count"], 1)

    def test_git_commit_creates_commit_from_staged_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "ORBIT Test"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "orbit@example.com"], cwd=repo, check=True, capture_output=True, text=True)
            target = repo / "notes.txt"
            target.write_text("alpha\n", encoding="utf-8")
            subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True, capture_output=True, text=True)

            result = _git_commit_result("init", cwd=str(repo))

            self.assertTrue(result["ok"])
            self.assertEqual(result["mutation_kind"], "git_commit")
            self.assertEqual(result["subject"], "init")
            self.assertTrue(result["commit"])

    def test_git_commit_fails_cleanly_when_nothing_is_staged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "ORBIT Test"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "orbit@example.com"], cwd=repo, check=True, capture_output=True, text=True)

            result = _git_commit_result("noop", cwd=str(repo))

            self.assertFalse(result["ok"])
            self.assertEqual(result["failure_kind"], "git_commit_failed")

    def test_git_checkout_branch_switches_to_existing_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "ORBIT Test"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "orbit@example.com"], cwd=repo, check=True, capture_output=True, text=True)
            target = repo / "notes.txt"
            target.write_text("alpha\n", encoding="utf-8")
            subprocess.run(["git", "add", "notes.txt"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "checkout", "-b", "feature/test"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "checkout", "master"], cwd=repo, check=True, capture_output=True, text=True)

            result = _git_checkout_branch_result("feature/test", cwd=str(repo))
            status = _git_status_result(cwd=str(repo))

            self.assertTrue(result["ok"])
            self.assertEqual(result["mutation_kind"], "git_checkout_branch")
            self.assertEqual(status["branch"], "feature/test")

    def test_git_checkout_branch_fails_for_missing_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "ORBIT Test"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "orbit@example.com"], cwd=repo, check=True, capture_output=True, text=True)

            result = _git_checkout_branch_result("does-not-exist", cwd=str(repo))

            self.assertFalse(result["ok"])
            self.assertEqual(result["failure_kind"], "branch_not_found")


if __name__ == "__main__":
    unittest.main()
