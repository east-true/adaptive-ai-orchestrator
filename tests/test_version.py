from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.infrastructure import version as version_module


class PackageVersionTests(unittest.TestCase):
    def test_source_checkout_version_takes_priority_over_stale_installed_metadata(self) -> None:
        with (
            patch.object(version_module, "source_tree_version", return_value="1.2.3"),
            patch.object(version_module.metadata, "version", return_value="0.0.1") as installed_version,
        ):
            self.assertEqual(version_module.package_version(), "1.2.3")
        installed_version.assert_not_called()

    def test_installed_version_is_used_outside_a_source_checkout(self) -> None:
        with (
            patch.object(version_module, "source_tree_version", return_value=None),
            patch.object(version_module.metadata, "version", return_value="2.3.4"),
        ):
            self.assertEqual(version_module.package_version(), "2.3.4")

    def test_development_version_is_used_without_source_or_installed_metadata(self) -> None:
        with (
            patch.object(version_module, "source_tree_version", return_value=None),
            patch.object(
                version_module.metadata,
                "version",
                side_effect=version_module.metadata.PackageNotFoundError,
            ),
        ):
            self.assertEqual(version_module.package_version(), "dev")

    def test_source_tree_version_reads_this_checkout(self) -> None:
        # The helper moved one package deeper; this pins the relative path to
        # pyproject.toml so a future move cannot silently return None.
        self.assertIsNotNone(version_module.source_tree_version())


if __name__ == "__main__":
    unittest.main()
