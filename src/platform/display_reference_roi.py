from __future__ import annotations

import base64
import json
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import messagebox

import cv2

import src.platform.display_check_presence_reference as check_module
import src.platform.display_visual_reference_status as visual_module


DISPLAY_REFERENCE_ROI_MIN_FRACTION = 0.015
DISPLAY_REFERENCE_ROI_COLOR = "#38BDF8"
DISPLAY_REFERENCE_ROI_VERTICAL_UI_RESERVE = 320
DISPLAY_REFERENCE_ROI_MIN_DRAW_HEIGHT = 220


def normalizar_roi_referencia(roi) -> dict | None:
    """Normaliza ROI retangular em coordenadas relativas [0..1]."""
    if not isinstance(roi, dict):
        return None
    try:
        x = float(roi.get("x", 0.0))
        y = float(roi.get("y", 0.0))
        width = float(roi.get("width", roi.get("w", 0.0)))
        height = float(roi.get("height", roi.get("h", 0.0)))
    except (TypeError, ValueError):
        return None

    x1 = max(0.0, min(1.0, x))
    y1 = max(0.0, min(1.0, y))
    x2 = max(0.0, min(1.0, x + width))
    y2 = max(0.0, min(1.0, y + height))
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    width = x2 - x1
    height = y2 - y1
    if width < DISPLAY_REFERENCE_ROI_MIN_FRACTION or height < DISPLAY_REFERENCE_ROI_MIN_FRACTION:
        return None
    if x1 <= 0.000001 and y1 <= 0.000001 and x2 >= 0.999999 and y2 >= 0.999999:
        return None
    return {
        "x": round(x1, 6),
        "y": round(y1, 6),
        "width": round(width, 6),
        "height": round(height, 6),
    }


def recortar_roi_referencia(image, roi):
    normalized = normalizar_roi_referencia(roi)
    if image is None or getattr(image, "size", 0) == 0 or normalized is None:
        return image
    image_height, image_width = image.shape[:2]
    x1 = max(0, min(image_width - 1, int(round(normalized["x"] * image_width))))
    y1 = max(0, min(image_height - 1, int(round(normalized["y"] * image_height))))
    x2 = max(x1 + 1, min(image_width, int(round((normalized["x"] + normalized["width"]) * image_width))))
    y2 = max(y1 + 1, min(image_height, int(round((normalized["y"] + normalized["height"]) * image_height))))
    return image[y1:y2, x1:x2]


def descricao_roi_referencia(metadata: dict | None) -> str:
    roi = normalizar_roi_referencia((metadata or {}).get("roi"))
    return "RECORTE ATIVO" if roi is not None else "IMAGEM TODA"


def _canvas_roi_rect(image, roi, target_width: int, target_height: int, center_x: float, center_y: float):
    normalized = normalizar_roi_referencia(roi)
    if normalized is None or image is None or getattr(image, "size", 0) == 0:
        return None
    image_height, image_width = image.shape[:2]
    scale = min(target_width / float(image_width), target_height / float(image_height))
    draw_width = image_width * scale
    draw_height = image_height * scale
    left = center_x - draw_width / 2.0
    top = center_y - draw_height / 2.0
    return (
        left + normalized["x"] * draw_width,
        top + normalized["y"] * draw_height,
        left + (normalized["x"] + normalized["width"]) * draw_width,
        top + (normalized["y"] + normalized["height"]) * draw_height,
    )


def _tk_photo(image):
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        return None
    return tk.PhotoImage(data=base64.b64encode(buffer).decode("ascii"))


class DisplayReferenceRoiDialog:
    """Seleção retangular simples sobre a própria imagem de referência."""

    def __init__(self, parent, image, current_roi, on_apply, title: str) -> None:
        self.parent = parent
        self.original = image.copy()
        self.on_apply = on_apply
        self.current_roi = normalizar_roi_referencia(current_roi)
        self.start = None
        self.selection_rect = None
        self.selected_roi = self.current_roi
        self.photo = None

        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.configure(bg="#0B1220")
        self.window.transient(parent)
        self.window.grab_set()

        screen_w = max(640, int(self.window.winfo_screenwidth()))
        screen_h = max(480, int(self.window.winfo_screenheight()))
        max_w = min(980, screen_w - 80)
        # Em telas 1366x768 a imagem antiga podia consumir altura demais e deixar
        # os botões inferiores atrás da barra do sistema. A imagem agora é
        # dimensionada somente depois de reservar título, instruções, status,
        # ações e a área segura inferior do workspace F3.
        max_h = min(
            650,
            max(
                DISPLAY_REFERENCE_ROI_MIN_DRAW_HEIGHT,
                screen_h - DISPLAY_REFERENCE_ROI_VERTICAL_UI_RESERVE,
            ),
        )
        image_h, image_w = self.original.shape[:2]
        scale = min(max_w / float(image_w), max_h / float(image_h), 1.0)
        self.draw_w = max(220, int(round(image_w * scale)))
        self.draw_h = max(160, int(round(image_h * scale)))
        self.display_image = cv2.resize(
            self.original,
            (self.draw_w, self.draw_h),
            interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR,
        )

        tk.Label(
            self.window,
            text="Arraste sobre a imagem para escolher a área considerada pela referência.",
            font=("Segoe UI", 10, "bold"),
            bg="#0B1220",
            fg="#E2E8F0",
            anchor="w",
        ).pack(fill=tk.X, padx=14, pady=(12, 5))
        tk.Label(
            self.window,
            text="Se usar IMAGEM TODA, o comportamento permanece igual ao atual.",
            font=("Segoe UI", 9),
            bg="#0B1220",
            fg="#94A3B8",
            anchor="w",
        ).pack(fill=tk.X, padx=14, pady=(0, 8))

        self.canvas = tk.Canvas(
            self.window,
            width=self.draw_w,
            height=self.draw_h,
            bg="#020617",
            bd=0,
            highlightthickness=1,
            highlightbackground="#334155",
            cursor="crosshair",
        )
        self.canvas.pack(padx=14, pady=(0, 8))
        self.photo = _tk_photo(self.display_image)
        if self.photo is not None:
            self.canvas.create_image(0, 0, image=self.photo, anchor=tk.NW)

        self.info = tk.Label(
            self.window,
            text="IMAGEM TODA" if self.selected_roi is None else "RECORTE ATIVO",
            font=("Segoe UI", 9, "bold"),
            bg="#0B1220",
            fg=DISPLAY_REFERENCE_ROI_COLOR,
            anchor="w",
        )
        self.info.pack(fill=tk.X, padx=14, pady=(0, 8))

        actions = tk.Frame(self.window, bg="#0B1220")
        actions.pack(fill=tk.X, padx=14, pady=(0, 14))
        tk.Button(
            actions,
            text="APLICAR RECORTE",
            command=self._apply,
            bg="#2563EB",
            fg="#FFFFFF",
            activebackground="#1D4ED8",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=12,
            pady=7,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(
            actions,
            text="USAR IMAGEM TODA",
            command=self._use_full_image,
            bg="#172033",
            fg="#E2E8F0",
            activebackground="#253247",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=12,
            pady=7,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(
            actions,
            text="Cancelar",
            command=self.window.destroy,
            bg="#172033",
            fg="#94A3B8",
            activebackground="#253247",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=12,
            pady=7,
            cursor="hand2",
        ).pack(side=tk.RIGHT)

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self._draw_current_roi()

    def _draw_current_roi(self) -> None:
        if self.selection_rect is not None:
            self.canvas.delete(self.selection_rect)
            self.selection_rect = None
        roi = normalizar_roi_referencia(self.selected_roi)
        if roi is None:
            return
        x1 = roi["x"] * self.draw_w
        y1 = roi["y"] * self.draw_h
        x2 = (roi["x"] + roi["width"]) * self.draw_w
        y2 = (roi["y"] + roi["height"]) * self.draw_h
        self.selection_rect = self.canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            outline=DISPLAY_REFERENCE_ROI_COLOR,
            width=3,
        )

    def _press(self, event) -> None:
        self.start = (
            max(0, min(self.draw_w, int(event.x))),
            max(0, min(self.draw_h, int(event.y))),
        )

    def _drag(self, event) -> None:
        if self.start is None:
            return
        x = max(0, min(self.draw_w, int(event.x)))
        y = max(0, min(self.draw_h, int(event.y)))
        if self.selection_rect is not None:
            self.canvas.delete(self.selection_rect)
        self.selection_rect = self.canvas.create_rectangle(
            self.start[0],
            self.start[1],
            x,
            y,
            outline=DISPLAY_REFERENCE_ROI_COLOR,
            width=3,
        )

    def _release(self, event) -> None:
        if self.start is None:
            return
        x2 = max(0, min(self.draw_w, int(event.x)))
        y2 = max(0, min(self.draw_h, int(event.y)))
        x1, y1 = self.start
        self.start = None
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        roi = normalizar_roi_referencia(
            {
                "x": left / float(self.draw_w),
                "y": top / float(self.draw_h),
                "width": (right - left) / float(self.draw_w),
                "height": (bottom - top) / float(self.draw_h),
            }
        )
        if roi is None:
            self.info.configure(text="Recorte muito pequeno. Selecione uma área maior.", fg="#FCA5A5")
            self.selected_roi = None
            self._draw_current_roi()
            return
        self.selected_roi = roi
        self.info.configure(text="RECORTE ATIVO", fg=DISPLAY_REFERENCE_ROI_COLOR)
        self._draw_current_roi()

    def _apply(self) -> None:
        roi = normalizar_roi_referencia(self.selected_roi)
        if roi is None:
            messagebox.showwarning(
                "Selecione uma área",
                "Arraste um retângulo sobre a imagem ou use IMAGEM TODA.",
                parent=self.window,
            )
            return
        self.on_apply(deepcopy(roi))
        self.window.destroy()

    def _use_full_image(self) -> None:
        self.on_apply(None)
        self.window.destroy()


def _read_raw_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _install_check_store_roi() -> None:
    cls = check_module.DisplayCheckPresenceReferenceStore
    if bool(getattr(cls, "_display_reference_roi_installed", False)):
        return
    original_load = cls._load
    original_capture = cls.capture

    def load(self):
        data = original_load(self)
        raw = _read_raw_json(Path(self.config_file))
        raw_refs = raw.get("references", {}) if isinstance(raw.get("references"), dict) else {}
        for key, metadata in data.get("references", {}).items():
            raw_meta = raw_refs.get(key)
            if isinstance(raw_meta, dict):
                roi = normalizar_roi_referencia(raw_meta.get("roi"))
                if roi is not None:
                    metadata["roi"] = roi
        return data

    def set_roi(self, project_name: str, check_id: str, roi) -> bool:
        data = self._load()
        key = check_module._reference_key(project_name, check_id)
        metadata = data.get("references", {}).get(key)
        if not isinstance(metadata, dict):
            return False
        normalized = normalizar_roi_referencia(roi)
        if normalized is None:
            metadata.pop("roi", None)
        else:
            metadata["roi"] = normalized
        self._write(data)
        return True

    def capture(self, project_name, check_id, frame, master_resolution):
        previous = self.get(project_name, check_id)
        previous_roi = normalizar_roi_referencia((previous or {}).get("roi"))
        result = original_capture(self, project_name, check_id, frame, master_resolution)
        if result is not None and previous_roi is not None:
            self.set_roi(project_name, check_id, previous_roi)
            return self.get(project_name, check_id)
        return result

    cls._load = load
    cls.set_roi = set_roi
    cls.capture = capture
    cls._display_reference_roi_installed = True


def _install_project_store_roi() -> None:
    cls = visual_module.DisplayProjectPresenceReferenceStore
    if bool(getattr(cls, "_display_reference_roi_installed", False)):
        return
    original_load = cls._load
    original_capture = cls.capture

    def load(self):
        data = original_load(self)
        raw = _read_raw_json(Path(self.config_file))
        raw_projects = raw.get("projects", {}) if isinstance(raw.get("projects"), dict) else {}
        for project_name, references in data.get("projects", {}).items():
            raw_refs = raw_projects.get(project_name)
            if not isinstance(raw_refs, dict):
                continue
            for kind, metadata in references.items():
                raw_meta = raw_refs.get(kind)
                if isinstance(raw_meta, dict):
                    roi = normalizar_roi_referencia(raw_meta.get("roi"))
                    if roi is not None:
                        metadata["roi"] = roi
        return data

    def set_roi(self, project_name: str, kind: str, roi) -> bool:
        data = self._load()
        project = visual_module.normalizar_nome_projeto_display(project_name)
        metadata = data.get("projects", {}).get(project, {}).get(str(kind or "").strip().lower())
        if not isinstance(metadata, dict):
            return False
        normalized = normalizar_roi_referencia(roi)
        if normalized is None:
            metadata.pop("roi", None)
        else:
            metadata["roi"] = normalized
        self._write(data)
        return True

    def capture(self, project_name, kind, frame, master_resolution):
        previous = self.get(project_name, kind)
        previous_roi = normalizar_roi_referencia((previous or {}).get("roi"))
        result = original_capture(self, project_name, kind, frame, master_resolution)
        if result is not None and previous_roi is not None:
            self.set_roi(project_name, kind, previous_roi)
            return self.get(project_name, kind)
        return result

    cls._load = load
    cls.set_roi = set_roi
    cls.capture = capture
    cls._display_reference_roi_installed = True


def _install_matchers_roi() -> None:
    if not bool(getattr(check_module, "_display_reference_roi_matcher_installed", False)):
        original_check_eval = check_module.avaliar_referencia_presenca_display

        def avaliar(frame, metadata):
            normalized = deepcopy(metadata) if isinstance(metadata, dict) else metadata
            roi = normalizar_roi_referencia((normalized or {}).get("roi"))
            if roi is None:
                return original_check_eval(frame, normalized)
            path = Path(str((normalized or {}).get("image_path") or ""))
            reference = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.exists() else None
            if reference is None or frame is None or getattr(frame, "size", 0) == 0:
                return original_check_eval(frame, normalized)
            reference_crop = recortar_roi_referencia(reference, roi)
            current = check_module._prepare_bgr(frame, (reference.shape[1], reference.shape[0]))
            current_crop = recortar_roi_referencia(current, roi)
            score = check_module.calcular_similaridade_presenca_display(reference_crop, current_crop)
            threshold = float((normalized or {}).get("threshold", check_module.DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD))
            return {
                "configured": True,
                "available": True,
                "matched": bool(score >= threshold),
                "score": score,
                "threshold": round(threshold, 4),
                "image_path": str(path),
                "roi": roi,
            }

        check_module.avaliar_referencia_presenca_display = avaliar
        check_module._display_reference_roi_matcher_installed = True

    matcher_cls = visual_module.DisplayVisualReferenceMatcher
    if not bool(getattr(matcher_cls, "_display_reference_roi_matcher_installed", False)):
        original_score = matcher_cls._score

        def score(self, current_frame, metadata):
            roi = normalizar_roi_referencia((metadata or {}).get("roi"))
            if roi is None:
                return original_score(self, current_frame, metadata)
            path = Path(str((metadata or {}).get("image_path") or ""))
            reference = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.exists() else None
            if reference is None or current_frame is None or getattr(current_frame, "size", 0) == 0:
                return None
            current = visual_module._prepare_bgr(current_frame, (reference.shape[1], reference.shape[0]))
            reference_crop = recortar_roi_referencia(reference, roi)
            current_crop = recortar_roi_referencia(current, roi)
            reference_small = visual_module._small_image(reference_crop)
            current_small = visual_module._small_image(current_crop)
            return check_module.calcular_similaridade_presenca_display(reference_small, current_small)

        matcher_cls._score = score
        matcher_cls._display_reference_roi_matcher_installed = True


def _open_selector(parent, metadata: dict, on_apply, title: str) -> None:
    path = Path(str(metadata.get("image_path") or ""))
    image = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.exists() else None
    if image is None:
        messagebox.showwarning(
            "Sem imagem de referência",
            "Capture primeiro a foto de referência antes de selecionar a área.",
            parent=parent,
        )
        return
    DisplayReferenceRoiDialog(
        parent,
        image,
        metadata.get("roi"),
        on_apply,
        title,
    )


def _install_check_window_roi() -> None:
    cls = check_module.DisplayCheckManagerPresenceWindow
    if bool(getattr(cls, "_display_reference_roi_installed", False)):
        return
    original_install = cls._install_presence_panel
    original_update = cls._update_presence_detail

    def install_panel(self):
        original_install(self)
        box = getattr(self.reference_canvas, "master", None)
        if box is None:
            return
        row = tk.Frame(box, bg="#0F1B2C")
        row.pack(fill=tk.X, padx=12, pady=(0, 7))
        self._button(
            row,
            "SELECIONAR ÁREA",
            self.select_presence_reference_roi,
        ).pack(side=tk.LEFT, padx=(0, 6))
        self.reference_roi_status = tk.Label(
            row,
            text="IMAGEM TODA",
            font=("Segoe UI", 8, "bold"),
            fg="#94A3B8",
            bg="#0F1B2C",
            anchor="w",
        )
        self.reference_roi_status.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def update_detail(self):
        original_update(self)
        label = getattr(self, "reference_roi_status", None)
        store = getattr(self, "_presence_store", None)
        check_id = self._selected_id()
        if label is None or store is None or not check_id:
            return
        metadata = store.get(self.project_name, check_id)
        if metadata is None:
            label.configure(text="IMAGEM TODA", fg="#94A3B8")
            return
        roi = normalizar_roi_referencia(metadata.get("roi"))
        label.configure(
            text=descricao_roi_referencia(metadata),
            fg=DISPLAY_REFERENCE_ROI_COLOR if roi is not None else "#94A3B8",
        )
        if roi is None or self.reference_canvas is None:
            return
        path = Path(str(metadata.get("image_path") or ""))
        image = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.exists() else None
        rect = _canvas_roi_rect(image, roi, 326, 88, 165, 46)
        if rect is not None:
            self.reference_canvas.create_rectangle(
                *rect,
                outline=DISPLAY_REFERENCE_ROI_COLOR,
                width=2,
            )

    def select_roi(self) -> None:
        store = getattr(self, "_presence_store", None)
        check_id = self._selected_id()
        if store is None or not check_id:
            return
        metadata = store.get(self.project_name, check_id)
        if metadata is None:
            messagebox.showwarning(
                "Sem referência",
                "Capture primeiro a foto deste CHECK.",
                parent=self.window,
            )
            return

        def apply(roi):
            store.set_roi(self.project_name, check_id, roi)
            self._update_presence_detail()
            self._notify_change()
            self.status.configure(
                text="Área da referência visual atualizada."
            )

        _open_selector(
            self.window,
            metadata,
            apply,
            f"Área analisada • {check_id}",
        )

    cls._install_presence_panel = install_panel
    cls._update_presence_detail = update_detail
    cls.select_presence_reference_roi = select_roi
    cls._display_reference_roi_installed = True


def _install_project_window_roi() -> None:
    cls = visual_module.DisplayProjectConfigPresenceWindow
    if bool(getattr(cls, "_display_reference_roi_installed", False)):
        return
    original_install = cls._install_project_presence_panel
    original_update = cls._update_project_presence_detail

    def install_panel(self):
        original_install(self)
        self._project_presence_roi_labels = {}
        for kind, canvas in self._project_presence_canvases.items():
            slot = getattr(canvas, "master", None)
            if slot is None:
                continue
            row = tk.Frame(slot, bg="#0B1728")
            row.pack(fill=tk.X, padx=6, pady=(0, 6))
            self._button(
                row,
                "SELECIONAR ÁREA",
                lambda k=kind: self.select_project_presence_reference_roi(k),
            ).pack(side=tk.LEFT)
            label = tk.Label(
                slot,
                text="IMAGEM TODA",
                font=("Segoe UI", 7, "bold"),
                fg="#94A3B8",
                bg="#0B1728",
                anchor="center",
            )
            label.pack(fill=tk.X, padx=6, pady=(0, 5))
            self._project_presence_roi_labels[kind] = label

    def update_detail(self):
        original_update(self)
        store = getattr(self, "_project_presence_store", None)
        labels = getattr(self, "_project_presence_roi_labels", {})
        project_name = self._selected_name()
        if store is None:
            return
        for kind in visual_module.DISPLAY_PROJECT_REFERENCE_TYPES:
            label = labels.get(kind)
            canvas = self._project_presence_canvases.get(kind)
            metadata = store.get(project_name or "", kind) if project_name else None
            if label is not None:
                roi = normalizar_roi_referencia((metadata or {}).get("roi"))
                label.configure(
                    text=descricao_roi_referencia(metadata),
                    fg=DISPLAY_REFERENCE_ROI_COLOR if roi is not None else "#94A3B8",
                )
            if metadata is None or canvas is None:
                continue
            roi = normalizar_roi_referencia(metadata.get("roi"))
            if roi is None:
                continue
            path = Path(str(metadata.get("image_path") or ""))
            image = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.exists() else None
            rect = _canvas_roi_rect(image, roi, 170, 78, 87, 41)
            if rect is not None:
                canvas.create_rectangle(
                    *rect,
                    outline=DISPLAY_REFERENCE_ROI_COLOR,
                    width=2,
                )

    def select_roi(self, kind: str) -> None:
        store = getattr(self, "_project_presence_store", None)
        project_name = self._selected_name()
        if store is None or not project_name:
            return
        metadata = store.get(project_name, kind)
        if metadata is None:
            messagebox.showwarning(
                "Sem referência",
                "Capture primeiro esta foto de presença da placa.",
                parent=self.window,
            )
            return

        def apply(roi):
            store.set_roi(project_name, kind, roi)
            self._update_project_presence_detail()
            self._notify_change()
            self.status.configure(
                text=f"Área analisada de '{visual_module.DISPLAY_PROJECT_REFERENCE_LABELS[kind]}' atualizada."
            )

        _open_selector(
            self.window,
            metadata,
            apply,
            f"Área analisada • {visual_module.DISPLAY_PROJECT_REFERENCE_LABELS[kind]}",
        )

    cls._install_project_presence_panel = install_panel
    cls._update_project_presence_detail = update_detail
    cls.select_project_presence_reference_roi = select_roi
    cls._display_reference_roi_installed = True


def instalar_roi_referencias_display_f3() -> None:
    _install_check_store_roi()
    _install_project_store_roi()
    _install_matchers_roi()
    _install_check_window_roi()
    _install_project_window_roi()
