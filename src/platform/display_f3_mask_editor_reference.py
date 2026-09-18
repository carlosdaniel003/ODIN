from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import cv2

from src.platform.display_project_repository import (
    DisplayProjectRepository,
    normalizar_nome_projeto_display,
    normalizar_resolucao_display,
)


F3_MASK_EDITOR_REFERENCE_CONFIG = "odin_display_mask_editor_reference.json"
F3_MASK_EDITOR_REFERENCE_DIR = "display_mask_editor_reference"


def _slug(text: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", str(text or "").strip()).strip("_")
    return value.lower() or "display"


def _valid_frame(frame) -> bool:
    return frame is not None and getattr(frame, "size", 0) > 0


class DisplayMaskEditorReferenceStore:
    """Foto estática usada como fundo canônico do editor de máscaras F3."""

    def __init__(self, repository: DisplayProjectRepository) -> None:
        self.repository = repository
        config_file = Path(
            getattr(repository, "config_file", "data/config/odin_display_projects.json")
        )
        self.config_file = config_file.parent / F3_MASK_EDITOR_REFERENCE_CONFIG
        self.image_dir = config_file.parent / F3_MASK_EDITOR_REFERENCE_DIR

    @staticmethod
    def _empty() -> dict:
        return {"schema_version": 1, "projects": {}}

    def _load(self) -> dict:
        if not self.config_file.exists():
            return self._empty()
        try:
            data = json.loads(self.config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return self._empty()
        if not isinstance(data, dict):
            return self._empty()
        projects = data.get("projects", {})
        if not isinstance(projects, dict):
            projects = {}
        return {"schema_version": 1, "projects": deepcopy(projects)}

    def _write(self, data: dict) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_file.with_suffix(self.config_file.suffix + ".tmp")
        temporary.write_text(
            json.dumps(data, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.config_file)

    def get(self, project_name: str) -> dict | None:
        name = normalizar_nome_projeto_display(project_name)
        value = self._load().get("projects", {}).get(name)
        return deepcopy(value) if isinstance(value, dict) else None

    def load_frame(self, project_name: str):
        metadata = self.get(project_name)
        if not isinstance(metadata, dict):
            return None
        path = Path(str(metadata.get("image_path") or ""))
        if not path.is_file():
            return None
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        return image if _valid_frame(image) else None

    def save_frame(
        self,
        project_name: str,
        frame,
        master_resolution,
    ) -> dict | None:
        name = normalizar_nome_projeto_display(project_name)
        resolution = normalizar_resolucao_display(master_resolution)
        if not name or resolution is None or not _valid_frame(frame):
            return None

        width, height = int(resolution[0]), int(resolution[1])
        image = frame.copy()
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.ndim == 3 and image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        if image.ndim != 3 or image.shape[2] != 3:
            return None
        if image.shape[:2] != (height, width):
            image = cv2.resize(
                image,
                (width, height),
                interpolation=(
                    cv2.INTER_AREA
                    if image.shape[1] > width or image.shape[0] > height
                    else cv2.INTER_LINEAR
                ),
            )

        self.image_dir.mkdir(parents=True, exist_ok=True)
        path = self.image_dir / f"{_slug(name)}.png"
        if not cv2.imwrite(
            str(path),
            image,
            [cv2.IMWRITE_PNG_COMPRESSION, 2],
        ):
            return None

        metadata = {
            "image_path": str(path),
            "width": width,
            "height": height,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        data = self._load()
        data.setdefault("projects", {})[name] = metadata
        self._write(data)
        return deepcopy(metadata)

    def remove_project(self, project_name: str) -> None:
        name = normalizar_nome_projeto_display(project_name)
        data = self._load()
        metadata = data.get("projects", {}).pop(name, None)
        if metadata is None:
            return
        self._write(data)
        try:
            path = Path(str((metadata or {}).get("image_path") or ""))
            if path.is_file():
                path.unlink()
        except OSError:
            pass

    def rename_project(self, old_name: str, new_name: str) -> None:
        old = normalizar_nome_projeto_display(old_name)
        new = normalizar_nome_projeto_display(new_name)
        if not old or not new or old == new:
            return
        data = self._load()
        metadata = data.get("projects", {}).pop(old, None)
        if not isinstance(metadata, dict):
            return
        data.setdefault("projects", {})[new] = metadata
        self._write(data)
