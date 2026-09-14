from __future__ import annotations

"""Visualização ampliada da foto capturada em CHECKS do Display F3.

A miniatura já existente em "CHECKS do Display" passa a ser clicável. A foto
persistida do CHECK é aberta em uma janela maximizada, responsiva e com zoom por
roda do mouse/botões. O renderer trabalha por recorte do viewport para não criar
uma imagem gigante em memória quando o operador aplica zoom alto — importante no
Raspberry Pi.

Esta camada é exclusivamente visual. Não captura novas referências, não altera o
arquivo persistido, não participa de OK/NG, não avança CHECK e não toca no F2.
"""

import base64
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import messagebox

import cv2

import src.platform.display_check_presence_reference as check_module
from src.platform.display_project_repository import normalizar_resolucao_display
from src.platform.display_visual_rotation import preparar_check_visual_display


F3_CHECK_REFERENCE_ZOOM_MIN = 0.10
F3_CHECK_REFERENCE_ZOOM_MAX = 8.0
F3_CHECK_REFERENCE_ZOOM_STEP = 1.25
F3_CHECK_REFERENCE_RENDER_DEBOUNCE_MS = 12

F3_CHECK_REFERENCE_VIEWER_BG = "#020617"
F3_CHECK_REFERENCE_VIEWER_PANEL = "#0B1220"
F3_CHECK_REFERENCE_VIEWER_BORDER = "#253247"
F3_CHECK_REFERENCE_VIEWER_TEXT = "#E2E8F0"
F3_CHECK_REFERENCE_VIEWER_MUTED = "#94A3B8"
F3_CHECK_REFERENCE_VIEWER_ACTION = "#0E7490"
F3_CHECK_REFERENCE_VIEWER_ACTION_ACTIVE = "#0891B2"


def limitar_zoom_referencia_f3(value: float) -> float:
    try:
        scale = float(value)
    except (TypeError, ValueError):
        scale = 1.0
    return max(F3_CHECK_REFERENCE_ZOOM_MIN, min(F3_CHECK_REFERENCE_ZOOM_MAX, scale))


def calcular_escala_ajuste_referencia_f3(
    image_width: int,
    image_height: int,
    viewport_width: int,
    viewport_height: int,
) -> float:
    width = max(1, int(image_width or 1))
    height = max(1, int(image_height or 1))
    available_width = max(1, int(viewport_width or 1))
    available_height = max(1, int(viewport_height or 1))
    return limitar_zoom_referencia_f3(
        min(
            available_width / float(width),
            available_height / float(height),
        )
    )


def calcular_centro_zoom_ancorado_referencia_f3(
    *,
    center_x: float,
    center_y: float,
    old_scale: float,
    new_scale: float,
    pointer_x: float,
    pointer_y: float,
    viewport_width: int,
    viewport_height: int,
) -> tuple[float, float]:
    """Mantém sob o ponteiro o mesmo pixel lógico durante a troca de zoom."""
    old_value = max(1e-9, float(old_scale))
    new_value = max(1e-9, float(new_scale))
    half_width = max(1, int(viewport_width or 1)) / 2.0
    half_height = max(1, int(viewport_height or 1)) / 2.0

    source_x = float(center_x) + (float(pointer_x) - half_width) / old_value
    source_y = float(center_y) + (float(pointer_y) - half_height) / old_value
    return (
        source_x - (float(pointer_x) - half_width) / new_value,
        source_y - (float(pointer_y) - half_height) / new_value,
    )


def _valid_image(image) -> bool:
    return image is not None and getattr(image, "size", 0) > 0


def _photo_from_bgr(image):
    if not _valid_image(image):
        return None
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        return None
    return tk.PhotoImage(data=base64.b64encode(buffer).decode("ascii"))


def _current_rotation(owner) -> int:
    try:
        from src.platform.display_f3_reference_preview_rotation import _rotation

        return int(_rotation(owner)) % 360
    except Exception:
        return 0


def preparar_imagem_ampliada_check_f3(owner, image_raw, metadata: dict | None):
    """Usa a mesma orientação/máscaras da miniatura sem reduzir a foto primeiro."""
    if not _valid_image(image_raw):
        return image_raw, 0, 0

    angle = _current_rotation(owner)
    project_name = str(getattr(owner, "project_name", "") or "")
    repository = getattr(owner, "repository", None)
    project = None
    if repository is not None and project_name:
        try:
            project = repository.carregar_projeto(project_name)
        except Exception:
            project = None

    resolution = (
        normalizar_resolucao_display(project.get("master_resolution"))
        if isinstance(project, dict)
        else None
    )
    masks = [
        deepcopy(mask)
        for mask in ((project or {}).get("masks", []) or [])
        if isinstance(mask, dict) and mask.get("id") is not None
    ]

    if resolution is None:
        return image_raw.copy(), angle, 0

    try:
        image_visual, visual_resolution, visual_masks = preparar_check_visual_display(
            image_raw,
            resolution,
            masks,
            angle,
        )
    except Exception:
        return image_raw.copy(), angle, 0

    if not _valid_image(image_visual):
        return image_raw.copy(), angle, 0

    if not visual_masks:
        return image_visual, angle, 0

    # O preview pequeno dos CHECKS já mostra as máscaras. Reutilizamos o mesmo
    # decorador na imagem de tela cheia para que clicar na miniatura preserve o
    # mesmo referencial visual, agora sem a redução para 326x88.
    try:
        import src.platform.display_reference_roi as roi_module

        decorated_metadata = deepcopy(metadata) if isinstance(metadata, dict) else {}
        decorated_metadata["_display_master_resolution"] = tuple(visual_resolution)
        decorated_metadata["_display_mask_regions"] = list(visual_masks)
        decorated_metadata["mask_region_count"] = len(visual_masks)
        image_visual = roi_module._decorate_reference_image(
            image_visual,
            decorated_metadata,
        )
    except Exception:
        pass

    return image_visual, angle, len(visual_masks)


class DisplayCheckReferenceZoomWindow:
    """Viewer de viewport: zoom alto sem alocar a foto inteira ampliada."""

    def __init__(
        self,
        parent,
        image,
        *,
        check_name: str,
        rotation: int = 0,
        mask_count: int = 0,
    ) -> None:
        if not _valid_image(image):
            raise ValueError("Imagem de referência inválida")

        self.image = image.copy()
        self.image_height, self.image_width = self.image.shape[:2]
        self.check_name = str(check_name or "CHECK").strip().upper()
        self.rotation = int(rotation or 0) % 360
        self.mask_count = max(0, int(mask_count or 0))

        self.scale = 1.0
        self.center_x = self.image_width / 2.0
        self.center_y = self.image_height / 2.0
        self.fit_mode = True
        self._photo = None
        self._image_item = None
        self._render_after_id = None
        self._drag_origin = None

        self.window = tk.Toplevel(parent)
        self.window.title(f"CHECK {self.check_name} • FOTO CAPTURADA")
        self.window.configure(bg=F3_CHECK_REFERENCE_VIEWER_BG)
        self.window.minsize(720, 480)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        self._build_ui()
        self._bind_events()
        self._maximize()
        self.window.after_idle(self.fit_to_window)

    def _build_ui(self) -> None:
        root = self.window
        root.grid_rowconfigure(1, weight=1)
        root.grid_columnconfigure(0, weight=1)

        toolbar = tk.Frame(
            root,
            bg=F3_CHECK_REFERENCE_VIEWER_PANEL,
            highlightthickness=1,
            highlightbackground=F3_CHECK_REFERENCE_VIEWER_BORDER,
        )
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.grid_columnconfigure(1, weight=1)

        tk.Label(
            toolbar,
            text=f"CHECK {self.check_name}",
            font=("Segoe UI", 12, "bold"),
            fg=F3_CHECK_REFERENCE_VIEWER_TEXT,
            bg=F3_CHECK_REFERENCE_VIEWER_PANEL,
        ).grid(row=0, column=0, padx=(16, 10), pady=10, sticky="w")

        detail = (
            f"{self.image_width}x{self.image_height} • VISUAL {self.rotation}°"
            + (f" • {self.mask_count} MÁSCARA(S)" if self.mask_count else "")
        )
        tk.Label(
            toolbar,
            text=detail,
            font=("Segoe UI", 9),
            fg=F3_CHECK_REFERENCE_VIEWER_MUTED,
            bg=F3_CHECK_REFERENCE_VIEWER_PANEL,
        ).grid(row=0, column=1, padx=8, pady=10, sticky="w")

        self.zoom_label = tk.Label(
            toolbar,
            text="100%",
            width=7,
            font=("Segoe UI", 9, "bold"),
            fg=F3_CHECK_REFERENCE_VIEWER_TEXT,
            bg=F3_CHECK_REFERENCE_VIEWER_PANEL,
        )
        self.zoom_label.grid(row=0, column=2, padx=(8, 4), pady=8)

        self._button(toolbar, "−", self.zoom_out, width=3).grid(
            row=0, column=3, padx=2, pady=7
        )
        self._button(toolbar, "100%", self.actual_size, width=6).grid(
            row=0, column=4, padx=2, pady=7
        )
        self._button(toolbar, "AJUSTAR", self.fit_to_window, width=8).grid(
            row=0, column=5, padx=2, pady=7
        )
        self._button(toolbar, "+", self.zoom_in, width=3).grid(
            row=0, column=6, padx=2, pady=7
        )
        self._button(toolbar, "FECHAR", self.close, width=7).grid(
            row=0, column=7, padx=(8, 14), pady=7
        )

        viewer = tk.Frame(root, bg=F3_CHECK_REFERENCE_VIEWER_BG)
        viewer.grid(row=1, column=0, sticky="nsew")
        viewer.grid_rowconfigure(0, weight=1)
        viewer.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            viewer,
            bg=F3_CHECK_REFERENCE_VIEWER_BG,
            bd=0,
            highlightthickness=0,
            cursor="fleur",
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")

        hint = tk.Label(
            root,
            text=(
                "RODA DO MOUSE: ZOOM  •  ARRASTE: MOVER  •  DUPLO CLIQUE: AJUSTAR  •  ESC: FECHAR"
            ),
            font=("Segoe UI", 8, "bold"),
            fg=F3_CHECK_REFERENCE_VIEWER_MUTED,
            bg=F3_CHECK_REFERENCE_VIEWER_PANEL,
            anchor="center",
        )
        hint.grid(row=2, column=0, sticky="ew", ipady=5)

    @staticmethod
    def _button(parent, text: str, command, width: int):
        return tk.Button(
            parent,
            text=text,
            command=command,
            width=width,
            font=("Segoe UI", 9, "bold"),
            bg=F3_CHECK_REFERENCE_VIEWER_ACTION,
            fg="#F8FAFC",
            activebackground=F3_CHECK_REFERENCE_VIEWER_ACTION_ACTIVE,
            activeforeground="#F8FAFC",
            relief="flat",
            bd=0,
            padx=5,
            pady=5,
            cursor="hand2",
        )

    def _maximize(self) -> None:
        try:
            self.window.state("zoomed")
            return
        except Exception:
            pass
        try:
            self.window.attributes("-zoomed", True)
            return
        except Exception:
            pass
        try:
            width = self.window.winfo_screenwidth()
            height = self.window.winfo_screenheight()
            self.window.geometry(f"{width}x{height}+0+0")
        except Exception:
            self.window.geometry("1280x720")

    def _bind_events(self) -> None:
        self.window.bind("<Escape>", lambda _event: self.close())
        self.window.bind("<Control-0>", lambda _event: self.actual_size())
        self.window.bind("<Control-plus>", lambda _event: self.zoom_in())
        self.window.bind("<Control-equal>", lambda _event: self.zoom_in())
        self.window.bind("<Control-minus>", lambda _event: self.zoom_out())

        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", lambda event: self._zoom_at(event.x, event.y, True))
        self.canvas.bind("<Button-5>", lambda event: self._zoom_at(event.x, event.y, False))
        self.canvas.bind("<Double-Button-1>", lambda _event: self.fit_to_window())
        self.canvas.bind("<ButtonPress-1>", self._start_pan)
        self.canvas.bind("<B1-Motion>", self._pan)
        self.canvas.bind("<ButtonRelease-1>", self._end_pan)

    def _viewport_size(self) -> tuple[int, int]:
        try:
            return (
                max(1, int(self.canvas.winfo_width())),
                max(1, int(self.canvas.winfo_height())),
            )
        except Exception:
            return 1, 1

    def _constrain_center(self) -> None:
        viewport_width, viewport_height = self._viewport_size()
        visible_width = viewport_width / max(self.scale, 1e-9)
        visible_height = viewport_height / max(self.scale, 1e-9)

        if visible_width >= self.image_width:
            self.center_x = self.image_width / 2.0
        else:
            half = visible_width / 2.0
            self.center_x = max(half, min(self.image_width - half, self.center_x))

        if visible_height >= self.image_height:
            self.center_y = self.image_height / 2.0
        else:
            half = visible_height / 2.0
            self.center_y = max(half, min(self.image_height - half, self.center_y))

    def _schedule_render(self) -> None:
        if self._render_after_id is not None:
            try:
                self.window.after_cancel(self._render_after_id)
            except Exception:
                pass
        self._render_after_id = self.window.after(
            F3_CHECK_REFERENCE_RENDER_DEBOUNCE_MS,
            self._render,
        )

    def _render(self) -> None:
        self._render_after_id = None
        if not self.window.winfo_exists():
            return

        viewport_width, viewport_height = self._viewport_size()
        if viewport_width <= 2 or viewport_height <= 2:
            return
        self._constrain_center()

        scale = max(self.scale, 1e-9)
        half_source_width = viewport_width / (2.0 * scale)
        half_source_height = viewport_height / (2.0 * scale)
        left_f = max(0.0, self.center_x - half_source_width)
        right_f = min(float(self.image_width), self.center_x + half_source_width)
        top_f = max(0.0, self.center_y - half_source_height)
        bottom_f = min(float(self.image_height), self.center_y + half_source_height)

        left = max(0, min(self.image_width - 1, int(left_f)))
        top = max(0, min(self.image_height - 1, int(top_f)))
        right = max(left + 1, min(self.image_width, int(right_f + 0.9999)))
        bottom = max(top + 1, min(self.image_height, int(bottom_f + 0.9999)))

        crop = self.image[top:bottom, left:right]
        if not _valid_image(crop):
            return

        target_width = max(1, int(round((right - left) * scale)))
        target_height = max(1, int(round((bottom - top) * scale)))
        interpolation = (
            cv2.INTER_AREA
            if target_width < crop.shape[1] or target_height < crop.shape[0]
            else cv2.INTER_LINEAR
        )
        rendered = cv2.resize(
            crop,
            (target_width, target_height),
            interpolation=interpolation,
        )
        photo = _photo_from_bgr(rendered)
        if photo is None:
            return

        x = viewport_width / 2.0 + (left - self.center_x) * scale
        y = viewport_height / 2.0 + (top - self.center_y) * scale

        self.canvas.delete("image")
        self._photo = photo
        self._image_item = self.canvas.create_image(
            int(round(x)),
            int(round(y)),
            image=photo,
            anchor=tk.NW,
            tags=("image",),
        )
        self.zoom_label.configure(text=f"{self.scale * 100:.0f}%")

    def _on_canvas_configure(self, _event=None) -> None:
        if self.fit_mode:
            self.fit_to_window()
        else:
            self._constrain_center()
            self._schedule_render()

    def fit_to_window(self) -> None:
        viewport_width, viewport_height = self._viewport_size()
        self.fit_mode = True
        self.scale = calcular_escala_ajuste_referencia_f3(
            self.image_width,
            self.image_height,
            viewport_width,
            viewport_height,
        )
        self.center_x = self.image_width / 2.0
        self.center_y = self.image_height / 2.0
        self._schedule_render()

    def actual_size(self) -> None:
        self.fit_mode = False
        self.scale = 1.0
        self.center_x = self.image_width / 2.0
        self.center_y = self.image_height / 2.0
        self._constrain_center()
        self._schedule_render()

    def _zoom_at(self, x: float, y: float, zoom_in: bool) -> None:
        old_scale = self.scale
        factor = F3_CHECK_REFERENCE_ZOOM_STEP if zoom_in else 1.0 / F3_CHECK_REFERENCE_ZOOM_STEP
        new_scale = limitar_zoom_referencia_f3(old_scale * factor)
        if abs(new_scale - old_scale) < 1e-9:
            return

        viewport_width, viewport_height = self._viewport_size()
        new_center_x, new_center_y = calcular_centro_zoom_ancorado_referencia_f3(
            center_x=self.center_x,
            center_y=self.center_y,
            old_scale=old_scale,
            new_scale=new_scale,
            pointer_x=x,
            pointer_y=y,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
        )
        self.fit_mode = False
        self.scale = new_scale
        self.center_x = new_center_x
        self.center_y = new_center_y
        self._constrain_center()
        self._schedule_render()

    def zoom_in(self) -> None:
        width, height = self._viewport_size()
        self._zoom_at(width / 2.0, height / 2.0, True)

    def zoom_out(self) -> None:
        width, height = self._viewport_size()
        self._zoom_at(width / 2.0, height / 2.0, False)

    def _on_mousewheel(self, event) -> str:
        delta = int(getattr(event, "delta", 0) or 0)
        if delta:
            self._zoom_at(event.x, event.y, delta > 0)
        return "break"

    def _start_pan(self, event) -> None:
        self._drag_origin = (
            float(event.x),
            float(event.y),
            float(self.center_x),
            float(self.center_y),
        )

    def _pan(self, event) -> None:
        if self._drag_origin is None:
            return
        start_x, start_y, start_center_x, start_center_y = self._drag_origin
        self.fit_mode = False
        self.center_x = start_center_x - (float(event.x) - start_x) / max(self.scale, 1e-9)
        self.center_y = start_center_y - (float(event.y) - start_y) / max(self.scale, 1e-9)
        self._constrain_center()
        self._schedule_render()

    def _end_pan(self, _event=None) -> None:
        self._drag_origin = None

    def close(self) -> None:
        if self._render_after_id is not None:
            try:
                self.window.after_cancel(self._render_after_id)
            except Exception:
                pass
            self._render_after_id = None
        try:
            self.window.destroy()
        except Exception:
            pass


def abrir_foto_check_tela_cheia_f3(owner) -> bool:
    store = getattr(owner, "_presence_store", None)
    if store is None:
        return False
    try:
        check_id = str(owner._selected_id() or "")
    except Exception:
        check_id = ""
    if not check_id:
        return False

    metadata = store.get(str(getattr(owner, "project_name", "") or ""), check_id)
    if not isinstance(metadata, dict):
        return False

    path = Path(str(metadata.get("image_path") or ""))
    image_raw = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.is_file() else None
    if not _valid_image(image_raw):
        try:
            messagebox.showwarning(
                "Imagem indisponível",
                "A foto capturada deste CHECK não foi encontrada.",
                parent=getattr(owner, "window", None),
            )
        except Exception:
            pass
        return False

    image, rotation, mask_count = preparar_imagem_ampliada_check_f3(
        owner,
        image_raw,
        metadata,
    )
    if not _valid_image(image):
        return False

    check_name = check_id
    repository = getattr(owner, "repository", None)
    if repository is not None:
        try:
            check = repository.carregar_check(owner.project_name, check_id)
        except Exception:
            check = None
        if isinstance(check, dict):
            check_name = str(check.get("name") or check_id)

    previous = getattr(owner, "_display_f3_check_reference_zoom_window", None)
    if previous is not None:
        try:
            previous.close()
        except Exception:
            pass

    try:
        viewer = DisplayCheckReferenceZoomWindow(
            getattr(owner, "window", None),
            image,
            check_name=check_name,
            rotation=rotation,
            mask_count=mask_count,
        )
    except Exception as exc:
        try:
            messagebox.showerror(
                "Falha ao ampliar imagem",
                f"Não foi possível abrir a foto deste CHECK.\n\n{type(exc).__name__}: {exc}",
                parent=getattr(owner, "window", None),
            )
        except Exception:
            pass
        return False

    owner._display_f3_check_reference_zoom_window = viewer
    return True


def _install_clickable_check_preview() -> None:
    cls = check_module.DisplayCheckManagerPresenceWindow
    if bool(getattr(cls, "_display_f3_check_reference_zoom_installed", False)):
        return

    original_panel = cls._install_presence_panel

    def install_panel(self) -> None:
        original_panel(self)
        canvas = getattr(self, "reference_canvas", None)
        if canvas is None:
            return

        try:
            canvas.configure(cursor="hand2", takefocus=1)
        except Exception:
            pass
        canvas.bind(
            "<Button-1>",
            lambda _event: "break" if abrir_foto_check_tela_cheia_f3(self) else None,
            add="+",
        )
        canvas.bind(
            "<Return>",
            lambda _event: "break" if abrir_foto_check_tela_cheia_f3(self) else None,
            add="+",
        )

        try:
            hint = tk.Label(
                canvas.master,
                text="Clique na foto para ampliar • zoom e movimentação na tela cheia",
                font=("Segoe UI", 8),
                fg=F3_CHECK_REFERENCE_VIEWER_MUTED,
                bg="#0F1B2C",
                anchor="w",
            )
            # O canvas já foi empacotado. Inserir o hint logo depois mantém o
            # botão CAPTURAR FOTO abaixo e não interfere nos wrappers de preview.
            hint.pack(fill=tk.X, padx=12, pady=(0, 5), after=canvas)
            self.reference_zoom_hint = hint
        except Exception:
            pass

    cls._install_presence_panel = install_panel
    cls.open_presence_reference_zoom = abrir_foto_check_tela_cheia_f3
    cls._display_f3_check_reference_zoom_installed = True


_INSTALLED = False


def instalar_zoom_foto_check_display_f3() -> None:
    """Instala somente a interação visual da miniatura dos CHECKS do F3."""
    global _INSTALLED
    if _INSTALLED:
        return
    _install_clickable_check_preview()
    _INSTALLED = True
