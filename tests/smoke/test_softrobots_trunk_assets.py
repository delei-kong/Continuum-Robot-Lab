import hashlib
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRUNK_ROOT = PROJECT_ROOT / "src" / "simulation" / "examples" / "softrobots_trunk"

EXPECTED_SHA256 = {
    "trunk.py": "6541114f90f3ede9d76ae204767b7fe63c94b11ec23c70cd157ddca85c0ec59e",
    "mesh/trunk.stl": "05a3ff3c32634131e3fd44e3ce45eeeb0ed1c0d091356cf751079ffde5cc7888",
    "mesh/trunk.vtk": "69ab9e47ddf701733f7020cc65991fe20bf2eed36f3d8fa8ebdb406a7c2b5fa6",
    "mesh/trunk_colli1.stl": "61947f5e8d712204a5c5e66ed4de10a3038f5f544dc4ecf1da1ec6a8878f03cc",
    "mesh/trunk_colli2.stl": "c04e40804dbbf0cc7378b209eb8ce9123f18cf5afc14f12e4169b82093845332",
}


class SoftRobotsTrunkAssetsTest(unittest.TestCase):
    def test_upstream_files_match_pinned_checksums(self) -> None:
        for relative_path, expected_digest in EXPECTED_SHA256.items():
            with self.subTest(path=relative_path):
                payload = (TRUNK_ROOT / relative_path).read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_digest)

    def test_license_is_included(self) -> None:
        license_text = (TRUNK_ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("GNU LESSER GENERAL PUBLIC LICENSE", license_text)
        self.assertIn("Version 3, 29 June 2007", license_text)


if __name__ == "__main__":
    unittest.main()
