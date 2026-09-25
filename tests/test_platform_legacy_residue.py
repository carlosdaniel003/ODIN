from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (ROOT / "src",)
LEGACY_MODULES = {
    "src.platform.gpio_raspberry_app",
    "src.platform.raspberry_camera_service",
    "src.platform.raspberry_enter_trigger",
    "src.platform.raspberry_pi3_production_app",
    "src.platform.raspberry_pi3_profile",
    "src.platform.raspberry_pi3_settings",
    "src.platform.raspberry_runtime_fixes",
    "src.ui.operation_window_raspberry",
}
COMPATIBILITY_SHIMS = {
    ROOT / "src/platform/raspberry_camera_service.py",
    ROOT / "src/platform/raspberry_pi3_production_app.py",
    ROOT / "src/platform/raspberry_pi3_profile.py",
}
OBSOLETE_RUNTIME_MODULES = {
    "src.platform.display_f3_tk_responsiveness",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            values.add(str(node.module or ""))
    return values


class PlatformLegacyResidueAuditTests(unittest.TestCase):
    maxDiff = None
    def test_production_source_does_not_depend_on_legacy_platform_modules(self):
        offenders: dict[str, list[str]] = {}
        for root in SOURCE_ROOTS:
            for path in sorted(root.rglob("*.py")):
                if path in COMPATIBILITY_SHIMS:
                    continue
                imports = _imports(path)
                legacy = sorted(imports & LEGACY_MODULES)
                if legacy:
                    offenders[str(path.relative_to(ROOT))] = legacy
        self.assertEqual({}, offenders)

    def test_tests_do_not_import_legacy_platform_modules(self):
        offenders: dict[str, list[str]] = {}
        for path in sorted((ROOT / "tests").rglob("*.py")):
            if path.name == Path(__file__).name:
                continue
            imports = _imports(path)
            legacy = sorted(imports & LEGACY_MODULES)
            if legacy:
                offenders[str(path.relative_to(ROOT))] = legacy
        self.assertEqual({}, offenders)

    def test_workflows_do_not_reference_legacy_platform_artifacts(self):
        forbidden = (
            "main_rpi.py",
            "raspberry_pi3_production_app.py",
            "raspberry_pi3_profile.py",
            "raspberry_pi3_settings.py",
            "raspberry_camera_service.py",
            "raspberry_enter_trigger.py",
            "raspberry_runtime_fixes.py",
            "gpio_raspberry_app.py",
            "operation_window_raspberry.py",
            "gpiozero",
        )
        offenders: dict[str, list[str]] = {}
        for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
            content = path.read_text(encoding="utf-8")
            hits = sorted(token for token in forbidden if token in content)
            if hits:
                offenders[str(path.relative_to(ROOT))] = hits
        self.assertEqual({}, offenders)

    def test_production_source_does_not_import_obsolete_f3_scheduler(self):
        offenders: dict[str, list[str]] = {}
        for root in SOURCE_ROOTS:
            for path in sorted(root.rglob("*.py")):
                imports = _imports(path)
                obsolete = sorted(imports & OBSOLETE_RUNTIME_MODULES)
                if obsolete:
                    offenders[str(path.relative_to(ROOT))] = obsolete
        self.assertEqual({}, offenders)

    def test_desktop_bootstrap_does_not_install_obsolete_scheduler_layers(self):
        main = (ROOT / "main_desktop.py").read_text(encoding="utf-8")
        self.assertNotIn("instalar_responsividade_tk_display_f3", main)
        self.assertNotIn("_install_adaptive_preview_cadence", main)


if __name__ == "__main__":
    unittest.main()
