from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.employee_names import (
    normalize_employee_name,
    require_path_inside_tenant_roots,
    tenant_employee_directory,
)


class EmployeeFilesystemIsolationTests(unittest.TestCase):
    def test_employee_names_are_safe_on_windows_and_posix(self):
        self.assertEqual(normalize_employee_name(" 小游 "), "小游")
        for value in ("", ".", "..", "a/b", r"a\b", "CON", "name."):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_employee_name(value)

    def test_employee_directory_cannot_escape_tenant_root(self):
        with tempfile.TemporaryDirectory() as root:
            target = tenant_employee_directory(root, "tenant-a", "小游")
            expected_parent = (Path(root) / "tenant-a").resolve()

            self.assertEqual(target.parent, expected_parent)
            with self.assertRaises(ValueError):
                tenant_employee_directory(root, "tenant-a", "..")

    def test_server_photo_paths_cannot_cross_tenants(self):
        with tempfile.TemporaryDirectory() as root:
            uploads = Path(root) / "uploads"
            own_photo = uploads / "tenant-a" / "小游" / "face.jpg"
            other_photo = uploads / "tenant-b" / "小游" / "face.jpg"
            own_photo.parent.mkdir(parents=True)
            other_photo.parent.mkdir(parents=True)
            own_photo.write_bytes(b"own")
            other_photo.write_bytes(b"other")

            self.assertEqual(
                require_path_inside_tenant_roots(
                    own_photo,
                    tenant_id="tenant-a",
                    roots=[uploads],
                ),
                own_photo.resolve(),
            )
            with self.assertRaises(ValueError):
                require_path_inside_tenant_roots(
                    other_photo,
                    tenant_id="tenant-a",
                    roots=[uploads],
                )


if __name__ == "__main__":
    unittest.main()
