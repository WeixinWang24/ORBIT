from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orbit.runtime.diagnostics.path_utils import (
    resolve_workspace_child_path,
    resolve_workspace_child_paths,
    resolve_workspace_optional_file,
    resolve_workspace_root,
)


class DiagnosticsPathUtilsTests(unittest.TestCase):
    def test_resolve_workspace_root_accepts_valid_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = resolve_workspace_root(tmpdir)
            self.assertEqual(root, Path(tmpdir).resolve())

    def test_resolve_workspace_child_path_with_relative_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            child = Path(tmpdir) / "foo.py"
            child.write_text("x = 1\n", encoding="utf-8")
            resolved = resolve_workspace_child_path(workspace_root=Path(tmpdir), raw_path="foo.py")
            self.assertEqual(resolved, child.resolve())
            resolved.relative_to(Path(tmpdir).resolve())

    def test_resolve_workspace_child_paths_filters_empty_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            child = Path(tmpdir) / "foo.py"
            child.write_text("x = 1\n", encoding="utf-8")
            resolved = resolve_workspace_child_paths(workspace_root=Path(tmpdir), raw_paths=["", "foo.py", "  "])
            self.assertEqual(resolved, [child.resolve()])

    def test_resolve_workspace_child_path_rejects_escape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError):
                resolve_workspace_child_path(workspace_root=Path(tmpdir), raw_path="../../etc/passwd")

    def test_resolve_workspace_optional_file_none_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertIsNone(resolve_workspace_optional_file(workspace_root=Path(tmpdir), raw_path=None))


if __name__ == "__main__":
    unittest.main()
