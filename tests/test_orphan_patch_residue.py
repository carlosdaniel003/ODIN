from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PATCHLIKE = re.compile(
    r"(_fix|_v2|_final|_guard|_compat|authority|reconciliation|responsiveness)",
    re.IGNORECASE,
)


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT).with_suffix("")
    return ".".join(relative.parts)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = str(node.module or "")
            if module:
                result.add(module)
    return result


class OrphanPatchResidueAuditTests(unittest.TestCase):
    maxDiff = None

    def test_patchlike_platform_modules_have_production_consumers(self):
        source_files = sorted(SRC.rglob("*.py"))
        roots = source_files + [ROOT / "main.py", ROOT / "main_desktop.py"]

        importers: dict[str, set[str]] = defaultdict(set)
        for path in roots:
            if not path.exists():
                continue
            importer = str(path.relative_to(ROOT))
            for module in _imports(path):
                importers[module].add(importer)

        candidates: dict[str, list[str]] = {}
        for path in source_files:
            if path.parent != ROOT / "src/platform":
                continue
            if path.name == "__init__.py" or not PATCHLIKE.search(path.stem):
                continue
            module = _module_name(path)
            consumers = sorted(importers.get(module, set()))
            if not consumers:
                candidates[str(path.relative_to(ROOT))] = consumers

        self.assertEqual({}, candidates)


if __name__ == "__main__":
    unittest.main()
