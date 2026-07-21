import importlib
import unittest


class CompatibilityEntrypointTests(unittest.TestCase):
    def test_root_cli_delegates_to_canonical_interface(self) -> None:
        legacy = importlib.import_module("adaptive_orchestrator.cli")
        canonical = importlib.import_module("adaptive_orchestrator.interfaces.cli")

        self.assertIs(legacy.main, canonical.main)
        self.assertIs(legacy.build_parser, canonical.build_parser)

    def test_interactive_entrypoints_delegate_to_canonical_interfaces(self) -> None:
        for name in ("shell", "tui", "example"):
            with self.subTest(name=name):
                legacy = importlib.import_module(f"adaptive_orchestrator.{name}")
                canonical = importlib.import_module(f"adaptive_orchestrator.interfaces.{name}")

                self.assertIs(legacy.main, canonical.main)


if __name__ == "__main__":
    unittest.main()
