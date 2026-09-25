from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class DesktopCompositionTests(unittest.TestCase):
    def test_main_uses_canonical_desktop_launcher(self):
        main = source("main.py")
        self.assertIn("from main_desktop import main", main)
        self.assertNotIn("main_rpi", main)

    def test_desktop_launcher_builds_desktop_production_app(self):
        launcher = source("main_desktop.py")
        self.assertIn(
            "from src.platform.desktop_production_app import",
            launcher,
        )
        self.assertIn("DesktopProductionApp", launcher)
        self.assertIn("app = DesktopProductionApp(root)", launcher)
        self.assertNotIn("RaspberryPi3ProductionApp", launcher)

    def test_canonical_production_composition_has_no_gpio_base(self):
        production = source("src/platform/desktop_production_app.py")
        tree = ast.parse(production)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported.append(str(node.module or ""))
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)

        self.assertNotIn("src.platform.gpio_raspberry_app", imported)
        self.assertIn("DesktopBaseODINApp", production)
        self.assertNotIn("GPIOEnabledRaspberryPi3ODINApp", production)
        self.assertIn(
            "CAMERA_SERVICE_CLASS = LiveFixedFullHdCameraService",
            production,
        )

    def test_desktop_profile_uses_explicit_camera_service_class(self):
        profile = source("src/platform/desktop_profile.py")
        self.assertIn("class DesktopODINApp", profile)
        self.assertIn("CAMERA_SERVICE_CLASS = DesktopCameraService", profile)
        self.assertIn("self.CAMERA_SERVICE_CLASS(", profile)
        self.assertNotIn(
            "raspberry_pi3_profile.RaspberryPi3CameraService =",
            profile,
        )

    def test_legacy_raspberry_modules_are_only_compatibility_shims(self):
        profile = source("src/platform/raspberry_pi3_profile.py")
        production = source("src/platform/raspberry_pi3_production_app.py")
        self.assertIn("RaspberryPi3ODINApp = DesktopODINApp", profile)
        self.assertIn(
            "RaspberryPi3ProductionApp = DesktopProductionApp",
            production,
        )
        self.assertNotIn("class RaspberryPi3ODINApp", profile)
        self.assertNotIn("class RaspberryPi3ProductionApp", production)

    def test_canonical_desktop_path_has_no_raspberry_or_gpio_dependencies(self):
        canonical_files = (
            "main_desktop.py",
            "src/platform/desktop_production_app.py",
            "src/platform/desktop_profile.py",
            "src/platform/desktop_camera_service.py",
            "src/platform/desktop_enter_trigger.py",
            "src/platform/desktop_runtime_compatibility.py",
        )
        for path in canonical_files:
            content = source(path)
            tree = ast.parse(content)
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    imports.append(str(node.module or ""))
                elif isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
            self.assertFalse(
                any("raspberry" in name.lower() for name in imports),
                (path, imports),
            )
            self.assertFalse(
                any("gpio" in name.lower() for name in imports),
                (path, imports),
            )

    def test_linux_launcher_runs_canonical_main(self):
        launcher = source("scripts/iniciar_odin_linux.sh")
        self.assertIn('"$PROJECT_DIR/main.py"', launcher)
        self.assertNotIn('"$PROJECT_DIR/main_rpi.py"', launcher)


if __name__ == "__main__":
    unittest.main()
