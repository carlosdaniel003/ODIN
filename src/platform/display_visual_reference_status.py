from __future__ import annotations

import base64
import json
import re
import tkinter as tk
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox

import cv2

import src.platform.display_auto_check_runtime as display_auto_runtime_module
import src.platform.display_production_f3 as display_production_f3_module
import src.platform.display_project_config as display_project_config_module
from src.platform.display_check_presence_reference import (
    DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD,
    DisplayCheckPresenceReferenceStore,
    calcular_similaridade_presenca_display,
)
from src.platform.display_production_f3_window import DisplayProductionF3Window
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_IGNORE,
    DisplayProjectRepository,
    normalizar_mascaras_display,
    normalizar_nome_projeto_display,
    normalizar_resolucao_display,
)
from src.platform.display_f3_window_geometry import fit_f3_toplevel


DISPLAY_PROJECT_PRESENCE_SCHEMA_VERSION = 1
DISPLAY_PROJECT_PRESENCE_CONFIG_FILENAME = "odin_display_project_presence.json"
DISPLAY_PROJECT_PRESENCE_IMAGE_DIRNAME = "display_project_presence"
DISPLAY_PROJECT_REFERENCE_BOARD_OFF = "board_off"
DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT = "empty_support"
DISPLAY_PROJECT_REFERENCE_TYPES = (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT,
)
DISPLAY_PROJECT_REFERENCE_LABELS = {
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF: "PLACA DESLIGADA NO SUPORTE",
    DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT: "PLACA FORA DO SUPORTE",
}
DISPLAY_VISUAL_STATUS_COMPARE_WIDTH = 220
DISPLAY_VISUAL_STATUS_MIN_MARGIN = 0.025
DISPLAY_VISUAL_STATUS_REFRESH_EVERY_FRAMES = 5


def _valid_frame(frame) -> bool:
    return frame is not None and getattr(frame, "size", 0) > 0


def _slug(texto: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", str(texto or "").strip()).strip("_")
    return value.lower() or "display"


def _prepare_bgr(frame, resolution: tuple[int, int] | None = None):
    if not _valid_frame(frame):
        return None
    image = frame.copy()
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.ndim == 3 and image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    elif image.ndim != 3 or image.shape[2] != 3:
        return None

    if resolution is not None:
        width, height = int(resolution[0]), int(resolution[1])
        if width > 0 and height > 0 and image.shape[:2] != (height, width):
            interpolation = (
                cv2.INTER_AREA
                if image.shape[1] > width or image.shape[0] > height
                else cv2.INTER_LINEAR
            )
            image = cv2.resize(image, (width, height), interpolation=interpolation)
    return image


def _small_image(frame):
    image = _prepare_bgr(frame)
    if image is None:
        return None
    height, width = image.shape[:2]
    if width <= DISPLAY_VISUAL_STATUS_COMPARE_WIDTH:
        return image
    target_width = DISPLAY_VISUAL_STATUS_COMPARE_WIDTH
    target_height = max(1, int(round(height * target_width / float(width))))
    return cv2.resize(
        image,
        (target_width, target_height),
        interpolation=cv2.INTER_AREA,
    )


def _photo_from_image(image, width: int, height: int):
    if not _valid_frame(image):
        return None
    image_height, image_width = image.shape[:2]
    scale = min(width / float(image_width), height / float(image_height))
    target_width = max(1, int(round(image_width * scale)))
    target_height = max(1, int(round(image_height * scale)))
    resized = cv2.resize(
        image,
        (target_width, target_height),
        interpolation=cv2.INTER_AREA,
    )
    ok, buffer = cv2.imencode(".png", resized)
    if not ok:
        return None
    return tk.PhotoImage(data=base64.b64encode(buffer).decode("ascii"))


class DisplayProjectPresenceReferenceStore:
    """Duas referências de presença pertencentes somente ao Projeto Display/F3."""

    def __init__(self, repository: DisplayProjectRepository) -> None:
        self.repository = repository
        config_file = Path(
            getattr(repository, "config_file", "data/config/odin_display_projects.json")
        )
        self.config_file = config_file.parent / DISPLAY_PROJECT_PRESENCE_CONFIG_FILENAME
        self.image_dir = config_file.parent / DISPLAY_PROJECT_PRESENCE_IMAGE_DIRNAME

    @staticmethod
    def _empty() -> dict:
        return {
            "schema_version": DISPLAY_PROJECT_PRESENCE_SCHEMA_VERSION,
            "projects": {},
        }

    def _load(self) -> dict:
        if not self.config_file.exists():
            return self._empty()
        try:
            data = json.loads(self.config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return self._empty()

        projects_source = data.get("projects", {}) if isinstance(data, dict) else {}
        if not isinstance(projects_source, dict):
            projects_source = {}
        projects: dict[str, dict] = {}
        for raw_name, references in projects_source.items():
            project_name = normalizar_nome_projeto_display(raw_name)
            if not project_name or not isinstance(references, dict):
                continue
            normalized_refs = {}
            for kind in DISPLAY_PROJECT_REFERENCE_TYPES:
                value = references.get(kind)
                if not isinstance(value, dict):
                    continue
                image_path = str(value.get("image_path") or "").strip()
                if not image_path:
                    continue
                try:
                    threshold = float(
                        value.get(
                            "threshold",
                            DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD,
                        )
                    )
                except (TypeError, ValueError):
                    threshold = DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD
                normalized = {
                    "image_path": image_path,
                    "threshold": max(0.10, min(0.99, threshold)),
                    "width": int(value.get("width", 0) or 0),
                    "height": int(value.get("height", 0) or 0),
                    "captured_at": str(value.get("captured_at") or ""),
                }
                board = []
                for point in value.get("board_points_reference", []) or []:
                    if not isinstance(point, (list, tuple)) or len(point) < 2:
                        continue
                    try:
                        board.append([float(point[0]), float(point[1])])
                    except (TypeError, ValueError):
                        pass
                if len(board) >= 3:
                    normalized["board_points_reference"] = board

                raw_overrides = value.get("mask_overrides_reference", {})
                overrides = {}
                if isinstance(raw_overrides, dict):
                    for mask_id, raw_mask in raw_overrides.items():
                        if not isinstance(raw_mask, dict):
                            continue
                        items = normalizar_mascaras_display(
                            [{**deepcopy(raw_mask), "id": str(mask_id)}]
                        )
                        if items:
                            overrides[str(mask_id)] = items[0]
                if overrides:
                    normalized["mask_overrides_reference"] = overrides
                normalized_refs[kind] = normalized
            if normalized_refs:
                projects[project_name] = normalized_refs
        return {
            "schema_version": DISPLAY_PROJECT_PRESENCE_SCHEMA_VERSION,
            "projects": projects,
        }

    def _write(self, data: dict) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_file.with_suffix(self.config_file.suffix + ".tmp")
        temporary.write_text(
            json.dumps(data, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.config_file)

    def get(self, project_name: str, kind: str) -> dict | None:
        project = normalizar_nome_projeto_display(project_name)
        ref_kind = str(kind or "").strip().lower()
        if ref_kind not in DISPLAY_PROJECT_REFERENCE_TYPES:
            return None
        value = self._load()["projects"].get(project, {}).get(ref_kind)
        return deepcopy(value) if isinstance(value, dict) else None

    def get_all(self, project_name: str) -> dict[str, dict]:
        project = normalizar_nome_projeto_display(project_name)
        values = self._load()["projects"].get(project, {})
        return deepcopy(values) if isinstance(values, dict) else {}

    def capture(
        self,
        project_name: str,
        kind: str,
        frame,
        master_resolution,
    ) -> dict | None:
        project = normalizar_nome_projeto_display(project_name)
        ref_kind = str(kind or "").strip().lower()
        resolution = normalizar_resolucao_display(master_resolution)
        if (
            not project
            or ref_kind not in DISPLAY_PROJECT_REFERENCE_TYPES
            or resolution is None
            or not _valid_frame(frame)
        ):
            return None

        image = _prepare_bgr(frame, resolution)
        if image is None:
            return None
        self.image_dir.mkdir(parents=True, exist_ok=True)
        path = self.image_dir / f"{_slug(project)}_{ref_kind}.jpg"
        ok = cv2.imwrite(
            str(path),
            image,
            [cv2.IMWRITE_JPEG_QUALITY, 92],
        )
        if not ok:
            return None

        data = self._load()
        previous = data["projects"].get(project, {}).get(ref_kind, {})
        metadata = {
            "image_path": str(path),
            "threshold": DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD,
            "width": int(resolution[0]),
            "height": int(resolution[1]),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
        if isinstance(previous, dict):
            for key in ("board_points_reference", "mask_overrides_reference"):
                if previous.get(key):
                    metadata[key] = deepcopy(previous[key])
        data["projects"].setdefault(project, {})[ref_kind] = metadata
        self._write(data)
        return deepcopy(metadata)

    def save_geometry(
        self,
        project_name: str,
        kind: str,
        board_points,
        masks,
    ) -> bool:
        project = normalizar_nome_projeto_display(project_name)
        ref_kind = str(kind or "").strip().lower()
        if ref_kind != DISPLAY_PROJECT_REFERENCE_BOARD_OFF:
            return False
        data = self._load()
        metadata = data["projects"].get(project, {}).get(ref_kind)
        if not isinstance(metadata, dict):
            return False

        board = []
        for point in (board_points or []):
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                board.append([float(point[0]), float(point[1])])
            except (TypeError, ValueError):
                pass

        overrides = {}
        for raw in (masks or []):
            if not isinstance(raw, dict):
                continue
            mask_id = str(raw.get("id") or "")
            if not mask_id:
                continue
            normalized = normalizar_mascaras_display(
                [{**deepcopy(raw), "id": mask_id}]
            )
            if normalized:
                overrides[mask_id] = normalized[0]

        if len(board) >= 3:
            metadata["board_points_reference"] = board
        else:
            metadata.pop("board_points_reference", None)
        if overrides:
            metadata["mask_overrides_reference"] = overrides
        else:
            metadata.pop("mask_overrides_reference", None)
        data["projects"].setdefault(project, {})[ref_kind] = metadata
        self._write(data)
        return True

    def remove(self, project_name: str, kind: str) -> bool:
        project = normalizar_nome_projeto_display(project_name)
        ref_kind = str(kind or "").strip().lower()
        data = self._load()
        project_refs = data["projects"].get(project)
        if not isinstance(project_refs, dict):
            return False
        metadata = project_refs.pop(ref_kind, None)
        if metadata is None:
            return False
        if not project_refs:
            data["projects"].pop(project, None)
        self._write(data)
        path = Path(str(metadata.get("image_path") or ""))
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
        return True

    def rename_project(self, old_name: str, new_name: str) -> None:
        old_project = normalizar_nome_projeto_display(old_name)
        new_project = normalizar_nome_projeto_display(new_name)
        if not old_project or not new_project or old_project == new_project:
            return
        data = self._load()
        values = data["projects"].pop(old_project, None)
        if isinstance(values, dict):
            data["projects"][new_project] = values
            self._write(data)

    def remove_project(self, project_name: str) -> None:
        project = normalizar_nome_projeto_display(project_name)
        if not project:
            return
        data = self._load()
        values = data["projects"].pop(project, None)
        if not isinstance(values, dict):
            return
        self._write(data)
        for metadata in values.values():
            if not isinstance(metadata, dict):
                continue
            path = Path(str(metadata.get("image_path") or ""))
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass


class DisplayVisualReferenceMatcher:
    """Identifica estado/presença usando somente imagens de referência completas."""

    def __init__(self, repository: DisplayProjectRepository) -> None:
        self.repository = repository
        self.check_store = DisplayCheckPresenceReferenceStore(repository)
        self.project_store = DisplayProjectPresenceReferenceStore(repository)
        self._image_cache: dict[str, tuple[tuple[int, int], object]] = {}

    def _reference_image(self, metadata: dict | None):
        if not isinstance(metadata, dict):
            return None
        path = Path(str(metadata.get("image_path") or ""))
        if not path.exists() or not path.is_file():
            return None
        try:
            stat = path.stat()
            signature = (int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            return None
        key = str(path)
        cached = self._image_cache.get(key)
        if cached is not None and cached[0] == signature:
            return cached[1]
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        image = _small_image(image)
        if image is None:
            return None
        self._image_cache[key] = (signature, image)
        return image

    def _score(self, current_small, metadata: dict | None) -> float | None:
        reference = self._reference_image(metadata)
        if reference is None or current_small is None:
            return None
        return calcular_similaridade_presenca_display(reference, current_small)

    @staticmethod
    def _threshold(metadata: dict | None) -> float:
        try:
            return max(
                0.10,
                min(
                    0.99,
                    float(
                        (metadata or {}).get(
                            "threshold",
                            DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD,
                        )
                    ),
                ),
            )
        except (TypeError, ValueError):
            return DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD

    @staticmethod
    def _choose(candidates: list[dict]) -> dict:
        valid = [item for item in candidates if item.get("score") is not None]
        passing = [
            item
            for item in valid
            if float(item["score"]) >= float(item["threshold"])
        ]
        passing.sort(key=lambda item: float(item["score"]), reverse=True)
        if not passing:
            best = max(valid, key=lambda item: float(item["score"]), default=None)
            return {
                "matched": False,
                "ambiguous": False,
                "best": deepcopy(best),
            }
        if (
            len(passing) >= 2
            and float(passing[0]["score"]) - float(passing[1]["score"])
            < DISPLAY_VISUAL_STATUS_MIN_MARGIN
        ):
            return {
                "matched": False,
                "ambiguous": True,
                "best": deepcopy(passing[0]),
                "second": deepcopy(passing[1]),
            }
        return {
            "matched": True,
            "ambiguous": False,
            "best": deepcopy(passing[0]),
        }

    def identify_check_state(self, frame, project_name: str) -> dict:
        current = _small_image(frame)
        if current is None:
            return {"configured_count": 0, "matched": False, "camera": False}
        candidates = []
        checks = self.repository.listar_checks(project_name)
        for check in checks:
            check_id = str(check.get("id") or "")
            metadata = self.check_store.get(project_name, check_id)
            if metadata is None:
                continue
            candidates.append(
                {
                    "kind": "check",
                    "check_id": check_id,
                    "name": str(check.get("name") or check_id),
                    "score": self._score(current, metadata),
                    "threshold": self._threshold(metadata),
                }
            )
        result = self._choose(candidates)
        result["configured_count"] = len(candidates)
        result["camera"] = True
        return result

    def identify_board_presence(self, frame, project_name: str) -> dict:
        current = _small_image(frame)
        references = self.project_store.get_all(project_name)
        configured_count = sum(
            1 for kind in DISPLAY_PROJECT_REFERENCE_TYPES if kind in references
        )
        if current is None:
            return {
                "configured_count": configured_count,
                "matched": False,
                "camera": False,
            }
        candidates = []
        for kind in DISPLAY_PROJECT_REFERENCE_TYPES:
            metadata = references.get(kind)
            if metadata is None:
                continue
            candidates.append(
                {
                    "kind": kind,
                    "name": DISPLAY_PROJECT_REFERENCE_LABELS[kind],
                    "score": self._score(current, metadata),
                    "threshold": self._threshold(metadata),
                }
            )
        result = self._choose(candidates)
        result["configured_count"] = configured_count
        result["required_count"] = len(DISPLAY_PROJECT_REFERENCE_TYPES)
        result["camera"] = True
        if configured_count < len(DISPLAY_PROJECT_REFERENCE_TYPES):
            result["matched"] = False
            result["incomplete"] = True
        return result


def display_check_cards_structure_key(snapshot: dict | None) -> tuple[tuple[str, str], ...]:
    """Estados não entram na chave: aprovar CHECK não deve reconstruir widgets."""
    data = dict(snapshot or {})
    return tuple(
        (
            str(check.get("id") or ""),
            str(check.get("name") or check.get("id") or "CHECK"),
        )
        for check in (data.get("checks", []) or [])
        if isinstance(check, dict)
    )


def _render_check_cards_stable(
    self,
    snapshot: dict,
    force_all_completed: bool = False,
) -> None:
    checks = list(snapshot.get("checks", []) or [])
    structure_key = display_check_cards_structure_key(snapshot)
    cached_key = getattr(self, "_display_stable_cards_key", None)
    cards = getattr(self, "_display_stable_cards", None)

    if cached_key != structure_key or not isinstance(cards, list):
        for child in self.check_flow_frame.winfo_children():
            child.destroy()
        cards = []
        if not checks:
            label = tk.Label(
                self.check_flow_frame,
                text="Nenhum CHECK configurado no Projeto Display.",
                font=("DejaVu Sans", 11, "bold"),
                bg=self.COLOR_WAITING,
                fg="#FCA5A5",
                anchor="center",
                justify="center",
            )
            label.grid(row=0, column=0, sticky="nsew", pady=8)
            self._display_stable_cards = cards
            self._display_stable_cards_key = structure_key
            return

        for index, check in enumerate(checks):
            card = tk.Frame(self.check_flow_frame)
            card.grid(row=index, column=0, sticky="ew", pady=(0, 5))
            card.grid_columnconfigure(1, weight=1)
            number = tk.Label(card, width=3)
            number.grid(row=0, column=0, padx=(7, 3), pady=7)
            name = tk.Label(card, anchor="w")
            name.grid(row=0, column=1, sticky="ew", padx=4, pady=7)
            state_label = tk.Label(card, anchor="e")
            state_label.grid(row=0, column=2, padx=(6, 9), pady=7)
            cards.append(
                {
                    "frame": card,
                    "number": number,
                    "name": name,
                    "state": state_label,
                }
            )
        self._display_stable_cards = cards
        self._display_stable_cards_key = structure_key

    if not checks:
        return

    for index, check in enumerate(checks):
        state = "completed" if force_all_completed else str(check.get("state", "pending"))
        if state == "completed":
            bg = self.CHECK_COMPLETED
            border = "#22C55E"
            status = "CONCLUÍDO"
            fg = "#FFFFFF"
        elif state == "current":
            bg = "#3B3205"
            border = self.CHECK_CURRENT
            status = "AGUARDANDO"
            fg = "#FDE68A"
        else:
            bg = self.CHECK_PENDING
            border = self.CHECK_BORDER
            status = "PRÓXIMO"
            fg = "#94A3B8"

        widgets = cards[index]
        widgets["frame"].configure(
            bg=bg,
            highlightbackground=border,
            highlightthickness=2 if state == "current" else 1,
        )
        widgets["number"].configure(
            text=str(index + 1),
            font=("DejaVu Sans", 10, "bold"),
            bg=bg,
            fg=fg,
        )
        widgets["name"].configure(
            text=str(check.get("name") or check.get("id") or "CHECK"),
            font=("DejaVu Sans", 11, "bold"),
            bg=bg,
            fg="#FFFFFF",
        )
        widgets["state"].configure(
            text=status,
            font=("DejaVu Sans", 8, "bold"),
            bg=bg,
            fg=fg,
        )


def _set_visual_reference_status(
    self,
    display_text: str,
    display_color: str,
    board_text: str,
    board_color: str,
) -> None:
    display_label = getattr(self, "visual_reference_state_label", None)
    board_label = getattr(self, "board_reference_state_label", None)
    if display_label is not None:
        if (
            str(display_label.cget("text")) != str(display_text)
            or str(display_label.cget("fg")) != str(display_color)
        ):
            display_label.configure(text=str(display_text), fg=str(display_color))
    if board_label is not None:
        if (
            str(board_label.cget("text")) != str(board_text)
            or str(board_label.cget("fg")) != str(board_color)
        ):
            board_label.configure(text=str(board_text), fg=str(board_color))


def _install_window_visual_status_and_stable_rendering() -> None:
    cls = DisplayProductionF3Window
    if bool(getattr(cls, "_display_visual_status_installed", False)):
        return

    original_init = cls.__init__

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._display_stable_cards_key = None
        self._display_stable_cards = None
        status_box = tk.Frame(self.project_frame, bg="#0B1220")
        status_box.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            padx=10,
            pady=(2, 7),
        )
        status_box.grid_columnconfigure(0, weight=1)
        self.visual_reference_state_label = tk.Label(
            status_box,
            text="ESTADO DO DISPLAY: aguardando referências dos CHECKS",
            font=("DejaVu Sans", 8, "bold"),
            bg="#0B1220",
            fg="#94A3B8",
            anchor="w",
        )
        self.visual_reference_state_label.grid(row=0, column=0, sticky="ew")
        self.board_reference_state_label = tk.Label(
            status_box,
            text="PRESENÇA DA PLACA: configure as 2 referências do projeto",
            font=("DejaVu Sans", 8, "bold"),
            bg="#0B1220",
            fg="#94A3B8",
            anchor="w",
        )
        self.board_reference_state_label.grid(row=1, column=0, sticky="ew", pady=(2, 0))

    cls.__init__ = init
    cls._render_check_cards = _render_check_cards_stable
    cls.set_visual_reference_status = _set_visual_reference_status
    cls._display_visual_status_installed = True


class DisplayProjectConfigPresenceWindow(
    display_project_config_module.DisplayProjectConfigWindow
):
    """Projeto Display com duas referências completas de presença física."""

    def __init__(self, *args, **kwargs) -> None:
        self._project_presence_store = None
        self._project_presence_photos: dict[str, object] = {}
        self._project_presence_canvases: dict[str, tk.Canvas] = {}
        self._project_presence_status: dict[str, tk.Label] = {}
        super().__init__(*args, **kwargs)
        self._project_presence_store = DisplayProjectPresenceReferenceStore(
            self.repository
        )
        fit_f3_toplevel(
            self.window,
            self.root,
            preferred_width=820,
            preferred_height=820,
            min_width=760,
            min_height=620,
        )
        self._install_project_presence_panel()
        self._update_project_presence_detail()

    def _install_project_presence_panel(self) -> None:
        parent = self.activate_button.master
        box = tk.Frame(parent, bg="#0F1B2C")
        box.pack(
            fill=tk.X,
            padx=16,
            pady=(0, 9),
            before=self.activate_button,
        )
        tk.Label(
            box,
            text="PRESENÇA DA PLACA • REFERÊNCIAS DO PROJETO",
            font=("Segoe UI", 9, "bold"),
            fg=self.MUTED,
            bg="#0F1B2C",
            anchor="w",
        ).pack(fill=tk.X, padx=12, pady=(9, 3))
        tk.Label(
            box,
            text=(
                "Estas imagens não pertencem a um CHECK: servem para distinguir "
                "placa desligada no suporte de suporte vazio."
            ),
            font=("Segoe UI", 8),
            fg=self.MUTED,
            bg="#0F1B2C",
            justify=tk.LEFT,
            wraplength=400,
            anchor="w",
        ).pack(fill=tk.X, padx=12, pady=(0, 7))

        slots = tk.Frame(box, bg="#0F1B2C")
        slots.pack(fill=tk.X, padx=9, pady=(0, 9))
        for column, kind in enumerate(DISPLAY_PROJECT_REFERENCE_TYPES):
            slot = tk.Frame(slots, bg="#0B1728")
            slot.grid(row=0, column=column, sticky="nsew", padx=3)
            slots.grid_columnconfigure(column, weight=1)
            tk.Label(
                slot,
                text=DISPLAY_PROJECT_REFERENCE_LABELS[kind],
                font=("Segoe UI", 7, "bold"),
                fg="#E2E8F0",
                bg="#0B1728",
                anchor="center",
            ).pack(fill=tk.X, padx=5, pady=(6, 4))
            canvas = tk.Canvas(
                slot,
                width=174,
                height=82,
                bg="#020617",
                bd=0,
                highlightthickness=1,
                highlightbackground="#253247",
            )
            canvas.pack(padx=6, pady=(0, 4))
            status = tk.Label(
                slot,
                text="SEM REFERÊNCIA",
                font=("Segoe UI", 7, "bold"),
                fg=self.MUTED,
                bg="#0B1728",
            )
            status.pack(fill=tk.X, padx=6, pady=(0, 4))
            actions = tk.Frame(slot, bg="#0B1728")
            actions.pack(fill=tk.X, padx=6, pady=(0, 6))
            self._button(
                actions,
                "CAPTURAR",
                lambda k=kind: self.capture_project_presence_reference(k),
                primary=True,
            ).pack(side=tk.LEFT, padx=(0, 4))
            self._button(
                actions,
                "Remover",
                lambda k=kind: self.remove_project_presence_reference(k),
                danger=True,
            ).pack(side=tk.LEFT)
            if kind == DISPLAY_PROJECT_REFERENCE_BOARD_OFF:
                self._button(
                    slot,
                    "Desenhar placa / máscaras",
                    self.edit_board_off_geometry,
                ).pack(fill=tk.X, padx=6, pady=(0, 6))
            self._project_presence_canvases[kind] = canvas
            self._project_presence_status[kind] = status

    def _load_selected(self) -> None:
        super()._load_selected()
        if self._project_presence_store is not None:
            self._update_project_presence_detail()

    def _update_project_presence_detail(self) -> None:
        store = self._project_presence_store
        if store is None:
            return
        project_name = self._selected_name()
        self._project_presence_photos.clear()
        for kind in DISPLAY_PROJECT_REFERENCE_TYPES:
            canvas = self._project_presence_canvases.get(kind)
            status = self._project_presence_status.get(kind)
            if canvas is None or status is None:
                continue
            canvas.delete("all")
            metadata = store.get(project_name or "", kind) if project_name else None
            if metadata is None:
                canvas.create_text(
                    87,
                    41,
                    text="SEM FOTO",
                    fill="#64748B",
                    font=("Segoe UI", 8, "bold"),
                )
                status.configure(text="SEM REFERÊNCIA", fg=self.MUTED)
                continue
            path = Path(str(metadata.get("image_path") or ""))
            image = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.exists() else None
            if image is None:
                canvas.create_text(
                    87,
                    41,
                    text="ARQUIVO AUSENTE",
                    fill="#FCA5A5",
                    font=("Segoe UI", 7, "bold"),
                )
                status.configure(text="ARQUIVO AUSENTE", fg="#FCA5A5")
                continue
            photo = _photo_from_image(image, 170, 78)
            if photo is not None:
                self._project_presence_photos[kind] = photo
                canvas.create_image(87, 41, image=photo, anchor=tk.CENTER)
            status.configure(
                text=(
                    f"ATIVA • {int(metadata.get('width', 0))}x"
                    f"{int(metadata.get('height', 0))}"
                ),
                fg="#86EFAC",
            )

    def edit_board_off_geometry(self) -> None:
        store = self._project_presence_store
        project_name = self._selected_name()
        if store is None or not project_name:
            return
        metadata = store.get(
            project_name,
            DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
        )
        if not isinstance(metadata, dict):
            messagebox.showwarning(
                "Referência necessária",
                "Capture primeiro a PLACA DESLIGADA NO SUPORTE.",
                parent=self.window,
            )
            return
        project = self.repository.carregar_projeto(project_name)
        resolution = normalizar_resolucao_display(
            (project or {}).get("master_resolution")
        )
        if project is None or resolution is None:
            return
        path = Path(str(metadata.get("image_path") or ""))
        image = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.exists() else None
        if not _valid_frame(image):
            messagebox.showwarning(
                "Imagem indisponível",
                "A foto da placa desligada não pôde ser carregada.",
                parent=self.window,
            )
            return

        try:
            from src.platform.display_f3_object_tracking import (
                F3TrackingConfigStore,
                canonical_board_points,
            )
            board_default = canonical_board_points(
                project,
                F3TrackingConfigStore(self.repository),
            )
        except Exception:
            board_default = []

        board = metadata.get("board_points_reference") or board_default
        overrides = metadata.get("mask_overrides_reference", {})
        angle = 0
        try:
            from src.platform.display_visual_rotation import (
                obter_rotacao_visual_do_frame_provider,
                preparar_frame_visual_display,
                preparar_mascara_visual_display,
                preparar_pontos_visuais_display,
                restaurar_mascara_original_display,
                restaurar_pontos_originais_display,
            )
            angle = obter_rotacao_visual_do_frame_provider(self.frame_provider)
            visual_image = preparar_frame_visual_display(image, angle)
            visual_resolution = (
                (resolution[1], resolution[0])
                if int(angle) in (90, 270)
                else resolution
            )
            visual_masks = [
                preparar_mascara_visual_display(
                    (overrides or {}).get(str(mask.get("id") or ""), mask),
                    resolution[0],
                    resolution[1],
                    angle,
                )
                for mask in project.get("masks", [])
                if isinstance(mask, dict)
            ]
            visual_board = preparar_pontos_visuais_display(
                board,
                resolution[0],
                resolution[1],
                angle,
            )
        except Exception:
            visual_image = image
            visual_resolution = resolution
            visual_masks = list(project.get("masks", []) or [])
            visual_board = board

        def save_geometry(board_points, masks) -> None:
            try:
                from src.platform.display_visual_rotation import (
                    restaurar_mascara_original_display,
                    restaurar_pontos_originais_display,
                )
                original_board = restaurar_pontos_originais_display(
                    board_points,
                    resolution[0],
                    resolution[1],
                    angle,
                )
                original_masks = [
                    restaurar_mascara_original_display(
                        mask,
                        resolution[0],
                        resolution[1],
                        angle,
                    )
                    for mask in (masks or [])
                    if isinstance(mask, dict)
                ]
            except Exception:
                original_board = board_points
                original_masks = masks
            if store.save_geometry(
                project_name,
                DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                original_board,
                original_masks,
            ):
                self._update_project_presence_detail()
                self._notify_change()

        from src.platform.display_f3_reference_geometry_editor import (
            F3ReferenceGeometryEditor,
        )

        F3ReferenceGeometryEditor(
            parent=self.window,
            image=visual_image,
            width=int(visual_resolution[0]),
            height=int(visual_resolution[1]),
            board_points=visual_board,
            masks=visual_masks,
            on_save=save_geometry,
            title="ODIN • F3 • Placa desligada no suporte",
            header_title=(
                "F3 • PLACA DESLIGADA NO SUPORTE • CONTORNO + MÁSCARAS"
            ),
        )

    def capture_project_presence_reference(self, kind: str) -> None:
        store = self._project_presence_store
        project_name = self._selected_name()
        if store is None or not project_name:
            return
        project = self.repository.carregar_projeto(project_name)
        if project is None:
            return
        resolution = normalizar_resolucao_display(project.get("master_resolution"))
        if resolution is None:
            messagebox.showwarning(
                "Sem resolução mestre",
                "Defina a resolução mestre antes de capturar a referência.",
                parent=self.window,
            )
            return
        try:
            frame = self.frame_provider()
        except Exception:
            frame = None
        if not _valid_frame(frame):
            messagebox.showwarning(
                "Câmera sem imagem",
                "Não há imagem válida da câmera para esta referência.",
                parent=self.window,
            )
            return
        metadata = store.capture(project_name, kind, frame, resolution)
        if metadata is None:
            messagebox.showerror(
                "Falha na captura",
                "Não foi possível salvar a referência do Projeto Display.",
                parent=self.window,
            )
            return
        self._update_project_presence_detail()
        self._notify_change()
        self.status.configure(
            text=f"Referência '{DISPLAY_PROJECT_REFERENCE_LABELS[kind]}' atualizada."
        )

    def remove_project_presence_reference(self, kind: str) -> None:
        store = self._project_presence_store
        project_name = self._selected_name()
        if store is None or not project_name or store.get(project_name, kind) is None:
            return
        if not messagebox.askyesno(
            "Remover referência",
            f"Remover '{DISPLAY_PROJECT_REFERENCE_LABELS[kind]}'?",
            parent=self.window,
        ):
            return
        store.remove(project_name, kind)
        self._update_project_presence_detail()
        self._notify_change()


def _install_project_reference_lifecycle_hooks() -> None:
    cls = DisplayProjectRepository
    if bool(getattr(cls, "_display_project_presence_hooks_installed", False)):
        return
    original_rename = cls.renomear_projeto
    original_remove = cls.remover_projeto

    def rename_project(self, nome_atual: str, novo_nome: str) -> bool:
        old_name = normalizar_nome_projeto_display(nome_atual)
        new_name = normalizar_nome_projeto_display(novo_nome)
        changed = original_rename(self, nome_atual, novo_nome)
        if changed:
            DisplayProjectPresenceReferenceStore(self).rename_project(old_name, new_name)
        return changed

    def remove_project(self, nome: str) -> bool:
        project_name = normalizar_nome_projeto_display(nome)
        removed = original_remove(self, nome)
        if removed:
            DisplayProjectPresenceReferenceStore(self).remove_project(project_name)
        return removed

    cls.renomear_projeto = rename_project
    cls.remover_projeto = remove_project
    cls._display_project_presence_hooks_installed = True


def _format_display_status(result: dict) -> tuple[str, str]:
    configured = int(result.get("configured_count", 0) or 0)
    if configured <= 0:
        return "ESTADO DO DISPLAY: sem referências de CHECK", "#94A3B8"
    if not bool(result.get("camera", True)):
        return "ESTADO DO DISPLAY: aguardando câmera", "#94A3B8"
    if bool(result.get("ambiguous")):
        return "ESTADO DO DISPLAY: IDENTIFICANDO...", "#FDE68A"
    best = result.get("best") if isinstance(result.get("best"), dict) else None
    if bool(result.get("matched")) and best is not None:
        score = float(best.get("score", 0.0) or 0.0)
        name = str(best.get("name") or "CHECK")
        return f"DISPLAY EM {name} • {score * 100:.0f}%", "#7DD3FC"
    best_score = float((best or {}).get("score", 0.0) or 0.0)
    return f"ESTADO DO DISPLAY: NÃO IDENTIFICADO • melhor {best_score * 100:.0f}%", "#FDE68A"


def _format_board_status(result: dict) -> tuple[str, str]:
    configured = int(result.get("configured_count", 0) or 0)
    required = int(result.get("required_count", 2) or 2)
    if configured < required:
        return f"PRESENÇA DA PLACA: referências {configured}/{required}", "#94A3B8"
    if not bool(result.get("camera", True)):
        return "PRESENÇA DA PLACA: aguardando câmera", "#94A3B8"
    if bool(result.get("ambiguous")):
        return "PRESENÇA DA PLACA: IDENTIFICANDO...", "#FDE68A"
    best = result.get("best") if isinstance(result.get("best"), dict) else None
    if bool(result.get("matched")) and best is not None:
        score = float(best.get("score", 0.0) or 0.0)
        kind = str(best.get("kind") or "")
        if kind == DISPLAY_PROJECT_REFERENCE_BOARD_OFF:
            return f"PLACA NO SUPORTE • DESLIGADA • {score * 100:.0f}%", "#86EFAC"
        if kind == DISPLAY_PROJECT_REFERENCE_EMPTY_SUPPORT:
            return f"PLACA FORA DO SUPORTE • {score * 100:.0f}%", "#CBD5E1"
    best_score = float((best or {}).get("score", 0.0) or 0.0)
    return f"PRESENÇA DA PLACA: IDENTIFICANDO... • melhor {best_score * 100:.0f}%", "#FDE68A"


def _install_runtime_visual_status() -> None:
    cls = display_auto_runtime_module.DisplayAutomaticCheckF3Mixin
    if bool(getattr(cls, "_display_visual_reference_status_runtime_installed", False)):
        return
    original_preview = cls._atualizar_preview_display_f3

    def update_preview(self):
        result = original_preview(self)
        if not bool(getattr(self, "display_f3_ativo", False)):
            return result
        counter = int(getattr(self, "_display_visual_status_frame_counter", 0) or 0) + 1
        self._display_visual_status_frame_counter = counter
        if counter % DISPLAY_VISUAL_STATUS_REFRESH_EVERY_FRAMES != 0:
            return result

        repository = getattr(self, "display_project_repository", None)
        window = getattr(self, "display_f3_window", None)
        frame = getattr(self, "camera_frame_atual", None)
        if repository is None or window is None:
            return result
        matcher = getattr(self, "_display_visual_reference_matcher", None)
        if matcher is None or getattr(matcher, "repository", None) is not repository:
            matcher = DisplayVisualReferenceMatcher(repository)
            self._display_visual_reference_matcher = matcher

        project_name = repository.obter_projeto_ativo()
        if not project_name:
            try:
                window.set_visual_reference_status(
                    "ESTADO DO DISPLAY: selecione um Projeto Display",
                    "#94A3B8",
                    "PRESENÇA DA PLACA: selecione um Projeto Display",
                    "#94A3B8",
                )
            except Exception:
                pass
            return result

        display_result = matcher.identify_check_state(frame, project_name)
        board_result = matcher.identify_board_presence(frame, project_name)
        display_text, display_color = _format_display_status(display_result)
        board_text, board_color = _format_board_status(board_result)
        try:
            window.set_visual_reference_status(
                display_text,
                display_color,
                board_text,
                board_color,
            )
        except Exception:
            pass
        return result

    cls._atualizar_preview_display_f3 = update_preview
    cls._display_visual_reference_status_runtime_installed = True


_DISPLAY_VISUAL_REFERENCE_STATUS_INSTALLED = False


def instalar_status_referencias_visuais_display() -> None:
    """Instala status, 2 referências de projeto e renderer estável apenas no F3."""
    global _DISPLAY_VISUAL_REFERENCE_STATUS_INSTALLED
    if _DISPLAY_VISUAL_REFERENCE_STATUS_INSTALLED:
        return

    _install_window_visual_status_and_stable_rendering()
    _install_project_reference_lifecycle_hooks()
    _install_runtime_visual_status()

    # DisplayProductionF3Mixin importou a classe da configuração por valor;
    # atualizamos a referência no próprio módulo antes da janela ser criada.
    display_production_f3_module.DisplayProjectConfigWindow = (
        DisplayProjectConfigPresenceWindow
    )
    _DISPLAY_VISUAL_REFERENCE_STATUS_INSTALLED = True
