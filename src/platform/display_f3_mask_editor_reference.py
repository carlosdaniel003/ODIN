from __future__ import annotations

import base64
import json
import re
import tkinter as tk
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import cv2

from src.platform.display_f3_window_geometry import fit_f3_toplevel
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

class F3MaskReferenceCaptureWindow:
    """Captura visível da foto estática usada pelo editor de placa/máscaras."""

    UPDATE_MS = 80

    def __init__(
        self,
        *,
        parent,
        frame_provider,
        store: DisplayMaskEditorReferenceStore,
        project_name: str,
        master_resolution,
        on_captured=None,
    ) -> None:
        self.parent = parent
        self.frame_provider = frame_provider
        self.store = store
        self.project_name = normalizar_nome_projeto_display(project_name)
        self.resolution = normalizar_resolucao_display(master_resolution)
        self.on_captured = on_captured
        self._latest_frame = None
        self._photo = None
        self._after_id = None
        self._closing = False

        self.window = tk.Toplevel(parent)
        self.window.title("ODIN • F3 • Capturar referência de placa e máscaras")
        self.window.configure(bg="#08111F")
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        fit_f3_toplevel(
            self.window,
            parent,
            preferred_width=980,
            preferred_height=700,
            min_width=760,
            min_height=520,
        )

        header = tk.Frame(self.window, bg="#111827")
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text="F3 • FOTO DE REFERÊNCIA • PLACA + MÁSCARAS",
            font=("Segoe UI", 12, "bold"),
            fg="#E5E7EB",
            bg="#111827",
            anchor="w",
        ).pack(fill=tk.X, padx=16, pady=(11, 2))
        tk.Label(
            header,
            text=(
                "Posicione a placa exatamente como deseja calibrar. A imagem abaixo "
                "é a câmera ao vivo; CAPTURAR congela esse frame e ele passa a ser "
                "o fundo fixo de todas as próximas edições."
            ),
            font=("Segoe UI", 8),
            fg="#94A3B8",
            bg="#111827",
            anchor="w",
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=16, pady=(0, 9))

        self.canvas = tk.Canvas(
            self.window,
            bg="#020617",
            bd=0,
            highlightthickness=0,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=12, pady=(10, 6))
        self.canvas.bind("<Configure>", lambda _event: self._render_latest())

        footer = tk.Frame(self.window, bg="#111827")
        footer.pack(fill=tk.X, padx=12, pady=(0, 12))
        self.status = tk.Label(
            footer,
            text="AGUARDANDO FRAME DA CÂMERA...",
            font=("Segoe UI", 9, "bold"),
            fg="#FBBF24",
            bg="#111827",
            anchor="w",
        )
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, pady=8)

        tk.Button(
            footer,
            text="CANCELAR",
            command=self.close,
            font=("Segoe UI", 9, "bold"),
            bg="#3A151A",
            fg="#FCA5A5",
            relief=tk.FLAT,
            bd=0,
            padx=16,
            pady=8,
        ).pack(side=tk.RIGHT, padx=(4, 8), pady=6)

        self.capture_button = tk.Button(
            footer,
            text="CAPTURAR",
            command=self.capture,
            state=tk.DISABLED,
            font=("Segoe UI", 9, "bold"),
            bg="#0F3A2B",
            fg="#86EFAC",
            disabledforeground="#64748B",
            relief=tk.FLAT,
            bd=0,
            padx=18,
            pady=8,
        )
        self.capture_button.pack(side=tk.RIGHT, padx=4, pady=6)

        self.window.bind("<Return>", lambda _event: self.capture())
        self.window.bind("<Escape>", lambda _event: self.close())
        try:
            self.window.grab_set()
            self.window.focus_force()
        except Exception:
            pass
        self._schedule(True)

    def _schedule(self, immediate: bool = False) -> None:
        if self._closing:
            return
        try:
            self._after_id = self.window.after(
                1 if immediate else self.UPDATE_MS,
                self._update,
            )
        except Exception:
            self._after_id = None

    def _frame(self):
        try:
            return self.frame_provider()
        except Exception:
            return None

    def _update(self) -> None:
        self._after_id = None
        if self._closing:
            return

        frame = self._frame()
        if not _valid_frame(frame):
            self._latest_frame = None
            self.capture_button.configure(state=tk.DISABLED)
            self.status.configure(
                text=(
                    "CÂMERA SEM FRAME • mantenha a câmera ativa e aguarde. "
                    "A captura será habilitada assim que chegar um frame."
                ),
                fg="#FBBF24",
            )
            self._schedule()
            return

        self._latest_frame = frame.copy()
        camera_h, camera_w = self._latest_frame.shape[:2]
        project_w, project_h = self.resolution or (camera_w, camera_h)
        self.capture_button.configure(state=tk.NORMAL)

        if (camera_w, camera_h) == (project_w, project_h):
            detail = f"CÂMERA {camera_w}x{camera_h} • pressione CAPTURAR"
            color = "#86EFAC"
        else:
            detail = (
                f"CÂMERA {camera_w}x{camera_h} • projeto {project_w}x{project_h} • "
                "a foto será normalizada para a resolução mestre ao capturar"
            )
            color = "#FBBF24"
        self.status.configure(text=detail, fg=color)
        self._render_latest()
        self._schedule()

    def _render_latest(self) -> None:
        if not _valid_frame(self._latest_frame):
            return
        canvas_w = max(120, int(self.canvas.winfo_width()))
        canvas_h = max(120, int(self.canvas.winfo_height()))
        image = self._latest_frame
        h, w = image.shape[:2]
        scale = min(
            canvas_w / max(1.0, float(w)),
            canvas_h / max(1.0, float(h)),
        )
        tw = max(1, int(round(w * scale)))
        th = max(1, int(round(h * scale)))
        interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        preview = cv2.resize(image, (tw, th), interpolation=interpolation)
        ok, encoded = cv2.imencode(
            ".png",
            preview,
            [cv2.IMWRITE_PNG_COMPRESSION, 1],
        )
        if not ok:
            return
        try:
            self._photo = tk.PhotoImage(
                data=base64.b64encode(encoded).decode("ascii")
            )
        except Exception:
            return

        self.canvas.delete("all")
        self.canvas.create_image(
            canvas_w / 2.0,
            canvas_h / 2.0,
            image=self._photo,
            anchor=tk.CENTER,
        )

    def capture(self) -> None:
        if not _valid_frame(self._latest_frame) or self.resolution is None:
            self.status.configure(
                text="AGUARDE UM FRAME VÁLIDO DA CÂMERA.",
                fg="#FBBF24",
            )
            return

        metadata = self.store.save_frame(
            self.project_name,
            self._latest_frame.copy(),
            self.resolution,
        )
        if metadata is None:
            self.status.configure(
                text="FALHA AO SALVAR A FOTO DE REFERÊNCIA.",
                fg="#FCA5A5",
            )
            return

        callback = self.on_captured
        self.close()
        if callable(callback):
            try:
                callback(metadata)
            except Exception:
                pass

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._after_id is not None:
            try:
                self.window.after_cancel(self._after_id)
            except Exception:
                pass
        try:
            self.window.grab_release()
        except Exception:
            pass
        try:
            self.window.destroy()
        except Exception:
            pass

