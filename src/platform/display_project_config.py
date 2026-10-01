from __future__ import annotations

import base64
import tkinter as tk

import cv2
from collections.abc import Callable
from tkinter import messagebox, simpledialog

from src.platform.display_check_editor import DisplayCheckManagerWindow
from src.platform.display_f3_window_geometry import fit_f3_toplevel
from src.platform.display_f3_zoom import (
    aplicar_zoom_software_frame_display_f3,
    calcular_viewport_efetivo_display_f3,
    normalizar_centro_zoom_software_display_f3,
)
from src.platform.display_mask_editor import DisplayMaskEditorWindow
from src.platform.display_project_repository import (
    DISPLAY_SOFTWARE_ZOOM_MAX,
    DISPLAY_SOFTWARE_ZOOM_MIN,
    DisplayProjectRepository,
    normalizar_nome_projeto_display,
    normalizar_resolucao_display,
    normalizar_zoom_projeto_display,
)
from config import CAMERA_ZOOM_MAX, CAMERA_ZOOM_MIN


F3_CONFIG_INITIAL_LOAD_DELAY_MS = 20
F3_CONFIG_PREVIEW_POLL_MS = 24
F3_CONFIG_PREVIEW_RESIZE_DEBOUNCE_MS = 140


class DisplayProjectConfigWindow:
    """Gerencia Projeto Display, resolução mestre, máscaras e CHECKS do F3."""

    BG = "#07111F"
    PANEL = "#0B1728"
    BORDER = "#253247"
    TEXT = "#F8FAFC"
    MUTED = "#94A3B8"

    def __init__(
        self,
        root,
        repository: DisplayProjectRepository,
        frame_provider: Callable[[], object | None],
        source_frame_provider: Callable[[], object | None] | None = None,
        on_camera_zoom_preview: Callable[[bool, float, float, float], None] | None = None,
        on_software_zoom_preview: Callable[[float, float, float], None] | None = None,
        heavy_executor=None,
        on_change: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.root = root
        self.repository = repository
        self.frame_provider = frame_provider
        self.source_frame_provider = source_frame_provider or frame_provider
        self.on_camera_zoom_preview = on_camera_zoom_preview
        self.on_software_zoom_preview = on_software_zoom_preview
        self._heavy_executor = heavy_executor
        self._owns_heavy_executor = False
        self.on_change = on_change
        self.on_close = on_close
        self.mask_editor: DisplayMaskEditorWindow | None = None
        self.mask_geometry_editor = None
        self.mask_capture_window = None
        self._mask_preview_photo = None
        self.check_manager: DisplayCheckManagerWindow | None = None
        self._project_scroll_canvas: tk.Canvas | None = None
        self._project_scroll_content = None
        self._config_preview_service = None
        self._config_preview_poll_after_id = None
        self._config_preview_outstanding: set[tuple[str, int]] = set()
        self._initial_refresh_after_id = None
        self._mask_preview_resize_after_id = None
        self._mask_preview_generation = 0
        self._mask_preview_requested_size = None
        self._mask_preview_rendered_size = None
        self._current_project_snapshot = None
        self.camera_zoom_enabled_var = tk.BooleanVar(value=False)
        self.camera_zoom_var = tk.DoubleVar(value=float(CAMERA_ZOOM_MIN))
        self.camera_zoom_center_x_var = tk.DoubleVar(value=0.5)
        self.camera_zoom_center_y_var = tk.DoubleVar(value=0.5)
        self.software_zoom_var = tk.DoubleVar(value=1.0)
        self.software_zoom_center_x_var = tk.DoubleVar(value=0.5)
        self.software_zoom_center_y_var = tk.DoubleVar(value=0.5)
        self._zoom_live_source_frame = None
        self._zoom_live_overview_frame = None
        self._zoom_live_visual_rotation = 0
        self._zoom_source_photo = None
        self._zoom_final_photo = None
        self._zoom_source_mapping = None
        self._zoom_drag_active = False
        self._zoom_drag_offset_x = 0.0
        self._zoom_drag_offset_y = 0.0
        self._zoom_drag_software_zoom = None
        # Estes canvases nascem depois dos sliders. Alguns builds do Tk,
        # especialmente no Windows, podem disparar o callback do Scale durante
        # a construção. Inicializar explicitamente evita acesso prematuro.
        self.zoom_source_canvas = None
        self.zoom_final_canvas = None

        self.window = tk.Toplevel(root)
        self.window.title("ODIN • Projeto Display")
        self.window.configure(bg=self.BG)
        self.window.resizable(True, True)
        self.window.transient(root)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        fit_f3_toplevel(
            self.window,
            root,
            preferred_width=900,
            preferred_height=720,
            min_width=720,
            min_height=520,
        )

        tk.Label(
            self.window,
            text="Projeto Display",
            font=("Segoe UI", 17, "bold"),
            fg=self.TEXT,
            bg=self.BG,
        ).pack(anchor="w", padx=22, pady=(18, 3))
        tk.Label(
            self.window,
            text=(
                "Configuração exclusiva do modo F3. Cada projeto possui sua "
                "própria resolução mestre, máscaras e sequência de CHECKS."
            ),
            font=("Segoe UI", 9),
            fg=self.MUTED,
            bg=self.BG,
            justify=tk.LEFT,
            wraplength=770,
        ).pack(anchor="w", padx=22, pady=(0, 12))

        body = tk.Frame(self.window, bg=self.BG)
        body.pack(fill=tk.BOTH, expand=True, padx=22, pady=(0, 12))

        left = tk.Frame(
            body,
            bg=self.PANEL,
            highlightbackground=self.BORDER,
            highlightthickness=1,
            width=310,
        )
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left.pack_propagate(False)

        tk.Label(
            left,
            text="PROJETOS DISPLAY",
            font=("Segoe UI", 9, "bold"),
            fg=self.MUTED,
            bg=self.PANEL,
            anchor="w",
        ).pack(fill=tk.X, padx=12, pady=(12, 6))

        list_frame = tk.Frame(left, bg=self.PANEL)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))
        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.project_list = tk.Listbox(
            list_frame,
            exportselection=False,
            font=("Segoe UI", 10, "bold"),
            bg="#020617",
            fg=self.TEXT,
            selectbackground="#0E7490",
            selectforeground="#FFFFFF",
            activestyle="none",
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
            yscrollcommand=scrollbar.set,
        )
        self.project_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.configure(command=self.project_list.yview)
        self.project_list.bind("<<ListboxSelect>>", lambda _event: self._load_selected())
        self.project_list.bind("<Double-Button-1>", lambda _event: self.activate_selected())

        project_actions = tk.Frame(left, bg=self.PANEL)
        project_actions.pack(fill=tk.X, padx=10, pady=(0, 10))
        self._button(project_actions, "Adicionar", self.add_project).pack(side=tk.LEFT, padx=(0, 4))
        self._button(project_actions, "Renomear", self.rename_selected).pack(side=tk.LEFT, padx=4)
        self._button(project_actions, "Remover", self.remove_selected, danger=True).pack(side=tk.LEFT, padx=4)

        right_shell = tk.Frame(
            body,
            bg=self.PANEL,
            highlightbackground=self.BORDER,
            highlightthickness=1,
            width=450,
        )
        right_shell.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(12, 0))
        right_shell.pack_propagate(False)

        right_scrollbar = tk.Scrollbar(right_shell, orient=tk.VERTICAL)
        right_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        right_canvas = tk.Canvas(
            right_shell,
            bg=self.PANEL,
            bd=0,
            highlightthickness=0,
            yscrollcommand=right_scrollbar.set,
        )
        right_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right_scrollbar.configure(command=right_canvas.yview)

        right = tk.Frame(right_canvas, bg=self.PANEL)
        right_window = right_canvas.create_window(
            (0, 0),
            window=right,
            anchor="nw",
        )
        self._project_scroll_canvas = right_canvas
        self._project_scroll_content = right

        def update_scroll_region(_event=None) -> None:
            try:
                right_canvas.configure(scrollregion=right_canvas.bbox("all"))
            except Exception:
                pass

        def fit_scroll_width(event) -> None:
            try:
                right_canvas.itemconfigure(
                    right_window,
                    width=max(1, int(event.width)),
                )
            except Exception:
                pass

        right.bind("<Configure>", update_scroll_region, add="+")
        right_canvas.bind("<Configure>", fit_scroll_width, add="+")
        self.window.bind("<MouseWheel>", self._scroll_project_content, add="+")
        self.window.bind("<Button-4>", self._scroll_project_content, add="+")
        self.window.bind("<Button-5>", self._scroll_project_content, add="+")

        self.project_title = tk.Label(
            right,
            text="SEM PROJETO",
            font=("Segoe UI", 15, "bold"),
            fg=self.TEXT,
            bg=self.PANEL,
            anchor="w",
        )
        self.project_title.pack(fill=tk.X, padx=16, pady=(16, 3))

        self.project_state = tk.Label(
            right,
            text="Crie ou selecione um Projeto Display.",
            font=("Segoe UI", 9),
            fg=self.MUTED,
            bg=self.PANEL,
            anchor="w",
            justify=tk.LEFT,
            wraplength=390,
        )
        self.project_state.pack(fill=tk.X, padx=16, pady=(0, 12))

        resolution_box = tk.Frame(right, bg="#0F1B2C")
        resolution_box.pack(fill=tk.X, padx=16, pady=(0, 9))
        tk.Label(
            resolution_box,
            text="RESOLUÇÃO MESTRE",
            font=("Segoe UI", 9, "bold"),
            fg=self.MUTED,
            bg="#0F1B2C",
        ).pack(anchor="w", padx=12, pady=(9, 5))

        fields = tk.Frame(resolution_box, bg="#0F1B2C")
        fields.pack(fill=tk.X, padx=12, pady=(0, 8))
        self.width_var = tk.StringVar()
        self.height_var = tk.StringVar()
        self._resolution_field(fields, "Largura", self.width_var).pack(side=tk.LEFT, padx=(0, 8))
        self._resolution_field(fields, "Altura", self.height_var).pack(side=tk.LEFT)
        self.save_resolution_button = self._button(
            fields,
            "Salvar",
            self.save_resolution,
            primary=True,
        )
        self.save_resolution_button.pack(side=tk.LEFT, padx=(12, 0), pady=(16, 0))

        zoom_box = tk.Frame(right, bg="#0F1B2C")
        zoom_box.pack(fill=tk.X, padx=16, pady=(0, 9))
        tk.Label(
            zoom_box,
            text="ZOOM DA CÂMERA / ODIN",
            font=("Segoe UI", 9, "bold"),
            fg=self.MUTED,
            bg="#0F1B2C",
        ).pack(anchor="w", padx=12, pady=(9, 3))
        tk.Label(
            zoom_box,
            text=(
                "O zoom da câmera usa CAP_PROP_ZOOM (BRIO/DirectShow). "
                "O zoom ODIN usa uma janela arrastável por software mantendo a "
                "resolução do frame F3."
            ),
            font=("Segoe UI", 8),
            fg=self.MUTED,
            bg="#0F1B2C",
            justify=tk.LEFT,
            wraplength=390,
        ).pack(fill=tk.X, padx=12, pady=(0, 7))

        hardware_header = tk.Frame(zoom_box, bg="#0F1B2C")
        hardware_header.pack(fill=tk.X, padx=12)
        tk.Checkbutton(
            hardware_header,
            text="Usar zoom digital da câmera",
            variable=self.camera_zoom_enabled_var,
            font=("Segoe UI", 8, "bold"),
            fg=self.TEXT,
            bg="#0F1B2C",
            activebackground="#0F1B2C",
            activeforeground=self.TEXT,
            selectcolor="#020617",
            command=self._on_hardware_zoom_changed,
        ).pack(side=tk.LEFT)
        self.camera_zoom_value_label = tk.Label(
            hardware_header,
            text="1.00×",
            font=("Segoe UI", 8, "bold"),
            fg=self.TEXT,
            bg="#0F1B2C",
        )
        self.camera_zoom_value_label.pack(side=tk.RIGHT)

        tk.Scale(
            zoom_box,
            from_=float(CAMERA_ZOOM_MIN),
            to=float(CAMERA_ZOOM_MAX),
            resolution=10.0,
            orient=tk.HORIZONTAL,
            variable=self.camera_zoom_var,
            showvalue=False,
            command=lambda _value: self._on_hardware_zoom_changed(),
            bg="#0F1B2C",
            fg=self.TEXT,
            troughcolor="#1E293B",
            highlightthickness=0,
            bd=0,
            length=360,
        ).pack(fill=tk.X, padx=12, pady=(0, 6))

        software_header = tk.Frame(zoom_box, bg="#0F1B2C")
        software_header.pack(fill=tk.X, padx=12)
        tk.Label(
            software_header,
            text="Zoom ODIN (software)",
            font=("Segoe UI", 8, "bold"),
            fg=self.TEXT,
            bg="#0F1B2C",
        ).pack(side=tk.LEFT)
        self.software_zoom_value_label = tk.Label(
            software_header,
            text="1.00×",
            font=("Segoe UI", 8, "bold"),
            fg=self.TEXT,
            bg="#0F1B2C",
        )
        self.software_zoom_value_label.pack(side=tk.RIGHT)

        tk.Scale(
            zoom_box,
            from_=DISPLAY_SOFTWARE_ZOOM_MIN,
            to=DISPLAY_SOFTWARE_ZOOM_MAX,
            resolution=0.1,
            orient=tk.HORIZONTAL,
            variable=self.software_zoom_var,
            showvalue=False,
            command=lambda _value: self._on_software_zoom_changed(),
            bg="#0F1B2C",
            fg=self.TEXT,
            troughcolor="#1E293B",
            highlightthickness=0,
            bd=0,
            length=360,
        ).pack(fill=tk.X, padx=12, pady=(0, 5))

        tk.Label(
            zoom_box,
            text="MAPA DA CÂMERA • ARRASTE O QUADRO AZUL",
            font=("Segoe UI", 8, "bold"),
            fg=self.TEXT,
            bg="#0F1B2C",
        ).pack(anchor="w", padx=12, pady=(3, 3))
        tk.Label(
            zoom_box,
            text=(
                "A imagem abaixo é a visão completa de referência em 1×, sem "
                "rotação. O quadro azul mostra exatamente a área efetiva que o "
                "F3 usará. Arraste o quadro para reposicionar o enquadramento."
            ),
            font=("Segoe UI", 8),
            fg=self.MUTED,
            bg="#0F1B2C",
            justify=tk.LEFT,
            wraplength=390,
        ).pack(fill=tk.X, padx=12, pady=(0, 5))

        self.zoom_source_canvas = tk.Canvas(
            zoom_box,
            width=420,
            height=236,
            bg="#020617",
            highlightbackground=self.BORDER,
            highlightthickness=1,
            bd=0,
            cursor="hand2",
        )
        self.zoom_source_canvas.pack(fill=tk.X, padx=12, pady=(0, 4))
        self.zoom_source_canvas.bind(
            "<Button-1>",
            self._on_zoom_viewport_press,
            add="+",
        )
        self.zoom_source_canvas.bind(
            "<B1-Motion>",
            self._on_zoom_viewport_drag,
            add="+",
        )
        self.zoom_source_canvas.bind(
            "<ButtonRelease-1>",
            self._on_zoom_viewport_release,
            add="+",
        )
        self.zoom_center_label = tk.Label(
            zoom_box,
            text="ÁREA F3 • centro X 50.0% • Y 50.0%",
            font=("Segoe UI", 8, "bold"),
            fg="#67E8F9",
            bg="#0F1B2C",
            anchor="w",
        )
        self.zoom_center_label.pack(fill=tk.X, padx=12, pady=(0, 7))

        tk.Label(
            zoom_box,
            text="RECORTE ATUAL DO F3 • SEM ROTAÇÃO",
            font=("Segoe UI", 8, "bold"),
            fg=self.TEXT,
            bg="#0F1B2C",
        ).pack(anchor="w", padx=12, pady=(0, 3))
        self.zoom_final_canvas = tk.Canvas(
            zoom_box,
            width=300,
            height=169,
            bg="#020617",
            highlightbackground=self.BORDER,
            highlightthickness=1,
            bd=0,
        )
        self.zoom_final_canvas.pack(fill=tk.X, padx=12, pady=(0, 7))

        tk.Label(
            zoom_box,
            text=(
                "Depois de alterar zoom ou enquadramento, revise a foto de referência, o contorno "
                "e as máscaras do projeto antes da produção."
            ),
            font=("Segoe UI", 8),
            fg="#FDE68A",
            bg="#0F1B2C",
            justify=tk.LEFT,
            wraplength=390,
        ).pack(fill=tk.X, padx=12, pady=(0, 6))
        self.save_zoom_button = self._button(
            zoom_box,
            "Salvar e aplicar zoom",
            self.save_zoom,
            primary=True,
        )
        self.save_zoom_button.pack(anchor="w", padx=12, pady=(0, 9))

        masks_box = tk.Frame(right, bg="#0F1B2C")
        masks_box.pack(fill=tk.X, padx=16, pady=(0, 9))
        tk.Label(
            masks_box,
            text="MÁSCARAS",
            font=("Segoe UI", 9, "bold"),
            fg=self.MUTED,
            bg="#0F1B2C",
        ).pack(anchor="w", padx=12, pady=(9, 3))
        self.mask_summary = tk.Label(
            masks_box,
            text="0 máscaras salvas",
            font=("Segoe UI", 10, "bold"),
            fg=self.TEXT,
            bg="#0F1B2C",
            anchor="w",
        )
        self.mask_summary.pack(fill=tk.X, padx=12, pady=(0, 6))

        preview_shell = tk.Frame(
            masks_box,
            bg="#020617",
            highlightbackground=self.BORDER,
            highlightthickness=1,
        )
        preview_shell.pack(fill=tk.X, padx=12, pady=(0, 7))
        self.mask_reference_preview = tk.Canvas(
            preview_shell,
            width=360,
            height=150,
            bg="#020617",
            highlightthickness=0,
            bd=0,
        )
        self.mask_reference_preview.pack(fill=tk.X, expand=True)
        self.mask_reference_preview.bind(
            "<Configure>",
            self._on_mask_reference_preview_configure,
            add="+",
        )

        self.mask_reference_status = tk.Label(
            masks_box,
            text="Nenhuma foto de referência.",
            font=("Segoe UI", 8),
            fg=self.MUTED,
            bg="#0F1B2C",
            anchor="w",
        )
        self.mask_reference_status.pack(fill=tk.X, padx=12, pady=(0, 6))

        photo_actions = tk.Frame(masks_box, bg="#0F1B2C")
        photo_actions.pack(fill=tk.X, padx=12, pady=(0, 5))
        self.capture_masks_photo_button = self._button(
            photo_actions,
            "Tirar foto com a câmera",
            self.capture_masks_reference_photo,
            primary=True,
        )
        self.capture_masks_photo_button.pack(side=tk.LEFT, padx=(0, 4))
        self.remove_masks_photo_button = self._button(
            photo_actions,
            "Remover foto",
            self.remove_masks_reference_photo,
            danger=True,
        )
        self.remove_masks_photo_button.pack(side=tk.LEFT, padx=4)

        self.edit_masks_button = self._button(
            masks_box,
            "Desenhar placa e máscaras",
            self.draw_masks_geometry,
            primary=True,
        )
        self.edit_masks_button.pack(anchor="w", padx=12, pady=(0, 9))

        checks_box = tk.Frame(right, bg="#0F1B2C")
        checks_box.pack(fill=tk.X, padx=16, pady=(0, 9))
        tk.Label(
            checks_box,
            text="CHECKS DO DISPLAY",
            font=("Segoe UI", 9, "bold"),
            fg=self.MUTED,
            bg="#0F1B2C",
        ).pack(anchor="w", padx=12, pady=(9, 3))
        self.check_summary = tk.Label(
            checks_box,
            text="0 CHECKS configurados",
            font=("Segoe UI", 10, "bold"),
            fg=self.TEXT,
            bg="#0F1B2C",
            anchor="w",
            justify=tk.LEFT,
        )
        self.check_summary.pack(fill=tk.X, padx=12, pady=(0, 6))
        self.edit_checks_button = self._button(
            checks_box,
            "Gerenciar e editar CHECKS",
            self.manage_checks,
            primary=True,
        )
        self.edit_checks_button.pack(anchor="w", padx=12, pady=(0, 9))

        self.activate_button = self._button(
            right,
            "USAR ESTE PROJETO NO F3",
            self.activate_selected,
            primary=True,
        )
        self.activate_button.pack(fill=tk.X, padx=16, pady=(0, 8))

        self.status = tk.Label(
            self.window,
            text="",
            font=("Segoe UI", 8, "bold"),
            fg=self.MUTED,
            bg=self.BG,
            anchor="w",
        )
        self.status.pack(fill=tk.X, padx=22, pady=(0, 6))

        tk.Button(
            self.window,
            text="Fechar",
            command=self.close,
            font=("Segoe UI", 9, "bold"),
            bg="#334155",
            fg="#FFFFFF",
            activebackground="#475569",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            padx=18,
            pady=8,
            cursor="hand2",
        ).pack(anchor="e", padx=22, pady=(0, 16))

        # O shell da configuração aparece primeiro. Projeto e previews são
        # carregados depois que o Tk já teve oportunidade de pintar a janela.
        self.status.configure(text="Carregando Projetos Display...")
        self._schedule_initial_refresh()
        self.window.lift()
        self.window.focus_force()

    def _schedule_initial_refresh(self) -> None:
        def load(owner=self):
            owner._initial_refresh_after_id = None
            if owner.visible:
                owner.refresh()

        try:
            self._initial_refresh_after_id = self.window.after(
                F3_CONFIG_INITIAL_LOAD_DELAY_MS,
                load,
            )
        except Exception:
            load()

    def _get_config_preview_service(self):
        service = self._config_preview_service
        if service is None:
            from src.platform.display_f3_config_service import (
                DisplayF3ConfigPreviewService,
            )
            executor = self._heavy_executor
            if executor is None:
                from src.platform.display_f3_heavy_executor import (
                    F3HeavyVisionExecutor,
                )
                executor = F3HeavyVisionExecutor()
                self._heavy_executor = executor
                self._owns_heavy_executor = True
            service = DisplayF3ConfigPreviewService(executor)
            self._config_preview_service = service
        return service

    def _register_config_preview_request(
        self,
        key: str,
        generation: int,
    ) -> None:
        self._config_preview_outstanding.add((str(key), int(generation)))
        self._ensure_config_preview_poll()

    def _ensure_config_preview_poll(self) -> None:
        if self._config_preview_poll_after_id is not None or not self.visible:
            return
        try:
            self._config_preview_poll_after_id = self.window.after(
                F3_CONFIG_PREVIEW_POLL_MS,
                self._poll_config_preview_results,
            )
        except Exception:
            self._config_preview_poll_after_id = None

    def _poll_config_preview_results(self) -> None:
        self._config_preview_poll_after_id = None
        service = self._config_preview_service
        if service is None:
            return

        for result in service.poll_results():
            self._config_preview_outstanding.discard(
                (str(result.key), int(result.generation))
            )
            handler = getattr(
                self,
                f"_apply_{str(result.kind)}_result",
                None,
            )
            if callable(handler):
                try:
                    handler(result)
                except Exception:
                    pass

        if self._config_preview_outstanding and self.visible:
            self._ensure_config_preview_poll()

    def _mask_preview_target_size(self) -> tuple[int, int]:
        canvas = getattr(self, "mask_reference_preview", None)
        if canvas is None:
            return 360, 150
        try:
            return (
                max(120, int(canvas.winfo_width() or 360)),
                max(90, int(canvas.winfo_height() or 150)),
            )
        except Exception:
            return 360, 150

    def _on_mask_reference_preview_configure(self, event=None) -> None:
        canvas = getattr(self, "mask_reference_preview", None)
        if canvas is None:
            return
        try:
            width = max(
                120,
                int(getattr(event, "width", 0) or canvas.winfo_width() or 360),
            )
            height = max(
                90,
                int(getattr(event, "height", 0) or canvas.winfo_height() or 150),
            )
            canvas.coords("mask_preview_image", width / 2, height / 2)
            rendered = self._mask_preview_rendered_size
            if isinstance(rendered, tuple) and len(rendered) == 2:
                rw, rh = rendered
                canvas.coords(
                    "mask_preview_border",
                    (width - rw) / 2,
                    (height - rh) / 2,
                    (width + rw) / 2,
                    (height + rh) / 2,
                )
        except Exception:
            pass

        if not isinstance(self._current_project_snapshot, dict):
            return
        previous = self._mask_preview_resize_after_id
        if previous is not None:
            try:
                self.window.after_cancel(previous)
            except Exception:
                pass
        try:
            self._mask_preview_resize_after_id = self.window.after(
                F3_CONFIG_PREVIEW_RESIZE_DEBOUNCE_MS,
                self._render_mask_reference_preview,
            )
        except Exception:
            self._mask_preview_resize_after_id = None

    def _widget_inside_project_scroll(self, widget) -> bool:
        target = self._project_scroll_content
        current = widget
        while current is not None:
            if current is target or current is self._project_scroll_canvas:
                return True
            current = getattr(current, "master", None)
        return False

    def _scroll_project_content(self, event) -> str | None:
        canvas = self._project_scroll_canvas
        if canvas is None or not self._widget_inside_project_scroll(getattr(event, "widget", None)):
            return None
        try:
            if getattr(event, "num", None) == 4:
                units = -3
            elif getattr(event, "num", None) == 5:
                units = 3
            else:
                delta = int(getattr(event, "delta", 0) or 0)
                if delta == 0:
                    return None
                units = -max(1, abs(delta) // 120) if delta > 0 else max(1, abs(delta) // 120)
            canvas.yview_scroll(int(units), "units")
            return "break"
        except Exception:
            return None

    def _zoom_values(self) -> tuple[float, float, float, float]:
        try:
            camera_zoom = float(self.camera_zoom_var.get())
        except (TypeError, ValueError, tk.TclError):
            camera_zoom = float(CAMERA_ZOOM_MIN)
        try:
            software_zoom = float(self.software_zoom_var.get())
        except (TypeError, ValueError, tk.TclError):
            software_zoom = 1.0
        drag_zoom = getattr(self, "_zoom_drag_software_zoom", None)
        if bool(getattr(self, "_zoom_drag_active", False)) and drag_zoom is not None:
            try:
                software_zoom = float(drag_zoom)
            except (TypeError, ValueError):
                pass
        try:
            center_x = float(self.software_zoom_center_x_var.get())
            center_y = float(self.software_zoom_center_y_var.get())
        except (TypeError, ValueError, tk.TclError):
            center_x = center_y = 0.5

        center_x, center_y = normalizar_centro_zoom_software_display_f3(
            software_zoom,
            center_x,
            center_y,
        )
        return camera_zoom, software_zoom, center_x, center_y

    def _camera_center_values(self) -> tuple[float, float]:
        camera_zoom, _software_zoom, _sx, _sy = self._zoom_values()
        enabled = bool(self.camera_zoom_enabled_var.get())
        factor = camera_zoom / 100.0 if enabled else 1.0
        try:
            center_x = float(self.camera_zoom_center_x_var.get())
            center_y = float(self.camera_zoom_center_y_var.get())
        except (TypeError, ValueError, tk.TclError):
            center_x = center_y = 0.5
        return normalizar_centro_zoom_software_display_f3(
            factor,
            center_x,
            center_y,
        )

    def _effective_zoom_view(self, frame_shape=None):
        camera_zoom, software_zoom, software_x, software_y = self._zoom_values()
        camera_enabled = bool(self.camera_zoom_enabled_var.get())
        camera_factor = camera_zoom / 100.0 if camera_enabled else 1.0
        camera_x, camera_y = self._camera_center_values()
        if frame_shape is None:
            frame = self._zoom_live_overview_frame
            frame_shape = getattr(frame, "shape", None)
        if frame_shape is None:
            return (
                camera_factor * software_zoom,
                0.5,
                0.5,
                None,
            )
        rect = calcular_viewport_efetivo_display_f3(
            frame_shape,
            camera_factor,
            software_zoom,
            camera_x,
            camera_y,
            software_x,
            software_y,
        )
        return rect[6], rect[4], rect[5], rect[:4]

    def _update_zoom_labels(self) -> None:
        camera_zoom, software_zoom, _center_x, _center_y = self._zoom_values()
        effective_zoom, effective_x, effective_y, _rect = (
            self._effective_zoom_view()
        )
        try:
            self.camera_zoom_value_label.configure(
                text=f"{camera_zoom / 100.0:.2f}×"
            )
            self.software_zoom_value_label.configure(
                text=f"{software_zoom:.2f}×"
            )
            self.zoom_center_label.configure(
                text=(
                    f"ÁREA F3 • {effective_zoom:.2f}× • "
                    f"centro X {effective_x * 100.0:.1f}% • "
                    f"Y {effective_y * 100.0:.1f}%"
                )
            )
        except Exception:
            pass

    def _publish_hardware_zoom_preview(self) -> None:
        callback = self.on_camera_zoom_preview
        if not callable(callback) or not self._selected_name():
            return
        center_x, center_y = self._camera_center_values()
        try:
            callback(
                bool(self.camera_zoom_enabled_var.get()),
                float(self.camera_zoom_var.get()),
                center_x,
                center_y,
            )
        except TypeError:
            try:
                callback(
                    bool(self.camera_zoom_enabled_var.get()),
                    float(self.camera_zoom_var.get()),
                )
            except Exception:
                pass
        except Exception:
            pass

    def _on_hardware_zoom_changed(self) -> None:
        camera_zoom = float(self.camera_zoom_var.get())
        factor = (
            camera_zoom / 100.0
            if bool(self.camera_zoom_enabled_var.get())
            else 1.0
        )
        center_x, center_y = normalizar_centro_zoom_software_display_f3(
            factor,
            float(self.camera_zoom_center_x_var.get()),
            float(self.camera_zoom_center_y_var.get()),
        )
        self.camera_zoom_center_x_var.set(center_x)
        self.camera_zoom_center_y_var.set(center_y)
        self._update_zoom_labels()
        self._publish_hardware_zoom_preview()
        self._rerender_zoom_preview()

    def _publish_software_zoom_preview(self) -> None:
        callback = self.on_software_zoom_preview
        if not callable(callback) or not self._selected_name():
            return
        _camera_zoom, software_zoom, center_x, center_y = self._zoom_values()
        try:
            callback(software_zoom, center_x, center_y)
        except Exception:
            pass

    def _on_software_zoom_changed(self) -> None:
        _camera_zoom, software_zoom, center_x, center_y = self._zoom_values()
        self.software_zoom_center_x_var.set(center_x)
        self.software_zoom_center_y_var.set(center_y)
        self._update_zoom_labels()
        self._publish_software_zoom_preview()
        self._rerender_zoom_preview()

    @staticmethod
    def _canvas_size(canvas) -> tuple[int, int]:
        try:
            width = int(canvas.winfo_width())
            height = int(canvas.winfo_height())
        except Exception:
            width = height = 1
        if width <= 1:
            try:
                width = int(canvas.cget("width"))
            except Exception:
                width = 360
        if height <= 1:
            try:
                height = int(canvas.cget("height"))
            except Exception:
                height = 190
        return max(40, width), max(40, height)

    def _render_bgr_zoom_canvas(self, canvas, frame, photo_attr: str):
        if canvas is None:
            return None
        if frame is None or getattr(frame, "size", 0) == 0:
            canvas.delete("all")
            width, height = self._canvas_size(canvas)
            canvas.create_text(
                width / 2,
                height / 2,
                text="Aguardando câmera...",
                fill=self.MUTED,
                font=("Segoe UI", 9, "bold"),
            )
            setattr(self, photo_attr, None)
            return None

        source_h, source_w = frame.shape[:2]
        canvas_w, canvas_h = self._canvas_size(canvas)
        scale = min(
            float(canvas_w) / max(1.0, float(source_w)),
            float(canvas_h) / max(1.0, float(source_h)),
        )
        render_w = max(1, int(round(source_w * scale)))
        render_h = max(1, int(round(source_h * scale)))
        interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        rendered = cv2.resize(
            frame,
            (render_w, render_h),
            interpolation=interpolation,
        )
        success, buffer = cv2.imencode(".png", rendered)
        if not success:
            return None
        photo = tk.PhotoImage(data=base64.b64encode(buffer).decode("ascii"))
        setattr(self, photo_attr, photo)
        offset_x = (canvas_w - render_w) / 2.0
        offset_y = (canvas_h - render_h) / 2.0
        canvas.delete("all")
        canvas.create_image(
            offset_x,
            offset_y,
            image=photo,
            anchor=tk.NW,
            tags=("zoom_image",),
        )
        return {
            "offset_x": float(offset_x),
            "offset_y": float(offset_y),
            "render_width": float(render_w),
            "render_height": float(render_h),
            "source_width": int(source_w),
            "source_height": int(source_h),
        }

    def _update_zoom_viewport_overlay(self, frame=None) -> None:
        canvas = getattr(self, "zoom_source_canvas", None)
        mapping = self._zoom_source_mapping
        if canvas is None or not isinstance(mapping, dict):
            return

        if frame is None:
            frame = self._zoom_live_overview_frame
        if frame is None or getattr(frame, "size", 0) == 0:
            return

        effective_zoom, effective_x, effective_y, rect = (
            self._effective_zoom_view(frame.shape)
        )
        if rect is None:
            return
        x0, y0, x1, y1 = rect

        sx = mapping["render_width"] / max(
            1.0,
            float(mapping["source_width"]),
        )
        sy = mapping["render_height"] / max(
            1.0,
            float(mapping["source_height"]),
        )
        ox = mapping["offset_x"]
        oy = mapping["offset_y"]
        canvas.delete("zoom_viewport")
        canvas.create_rectangle(
            ox + x0 * sx,
            oy + y0 * sy,
            ox + x1 * sx,
            oy + y1 * sy,
            outline="#22D3EE",
            width=3,
            tags=("zoom_viewport",),
        )
        center_canvas_x = ox + effective_x * mapping["source_width"] * sx
        center_canvas_y = oy + effective_y * mapping["source_height"] * sy
        canvas.create_line(
            center_canvas_x - 8,
            center_canvas_y,
            center_canvas_x + 8,
            center_canvas_y,
            fill="#FFFFFF",
            width=1,
            tags=("zoom_viewport",),
        )
        canvas.create_line(
            center_canvas_x,
            center_canvas_y - 8,
            center_canvas_x,
            center_canvas_y + 8,
            fill="#FFFFFF",
            width=1,
            tags=("zoom_viewport",),
        )

    def _draw_zoom_source_viewport(self, frame) -> None:
        canvas = getattr(self, "zoom_source_canvas", None)
        if canvas is None:
            return

        mapping = self._render_bgr_zoom_canvas(
            canvas,
            frame,
            "_zoom_source_photo",
        )
        self._zoom_source_mapping = mapping
        if mapping is None:
            return
        self._update_zoom_viewport_overlay(frame)

    def update_live_zoom_preview(
        self,
        source_frame,
        *,
        overview_frame=None,
        visual_rotation: int = 0,
    ) -> None:
        if not self.visible:
            return
        source_canvas = getattr(self, "zoom_source_canvas", None)
        final_canvas = getattr(self, "zoom_final_canvas", None)
        if source_canvas is None or final_canvas is None:
            return
        self._zoom_live_source_frame = source_frame
        self._zoom_live_visual_rotation = int(visual_rotation or 0)
        if overview_frame is not None and getattr(overview_frame, "size", 0) > 0:
            self._zoom_live_overview_frame = overview_frame
        elif self._zoom_live_overview_frame is None:
            self._zoom_live_overview_frame = source_frame
        overview_frame = (
            self._zoom_live_overview_frame
            if self._zoom_live_overview_frame is not None
            else source_frame
        )
        if self._zoom_drag_active:
            self._update_zoom_viewport_overlay(overview_frame)
        else:
            self._draw_zoom_source_viewport(overview_frame)

        _camera_zoom, software_zoom, center_x, center_y = self._zoom_values()
        final_frame = aplicar_zoom_software_frame_display_f3(
            source_frame,
            software_zoom,
            center_x,
            center_y,
        )
        self._render_bgr_zoom_canvas(
            final_canvas,
            final_frame,
            "_zoom_final_photo",
        )
        self._update_zoom_labels()

    def _rerender_zoom_preview(self) -> None:
        if (
            getattr(self, "zoom_source_canvas", None) is None
            or getattr(self, "zoom_final_canvas", None) is None
        ):
            return

        frame = self._zoom_live_source_frame
        if frame is None or getattr(frame, "size", 0) == 0:
            try:
                frame = self.source_frame_provider()
            except Exception:
                frame = None
        self.update_live_zoom_preview(
            frame,
            visual_rotation=0,
        )

    def _zoom_pointer_normalized(self, event) -> tuple[float, float] | None:
        mapping = self._zoom_source_mapping
        if not isinstance(mapping, dict):
            return None
        width = max(1.0, float(mapping["render_width"]))
        height = max(1.0, float(mapping["render_height"]))
        x = (
            float(getattr(event, "x", 0)) - float(mapping["offset_x"])
        ) / width
        y = (
            float(getattr(event, "y", 0)) - float(mapping["offset_y"])
        ) / height
        return (
            min(1.0, max(0.0, x)),
            min(1.0, max(0.0, y)),
        )

    def _render_zoom_final_only(self) -> None:
        frame = self._zoom_live_source_frame
        final_canvas = getattr(self, "zoom_final_canvas", None)
        if (
            final_canvas is None
            or frame is None
            or getattr(frame, "size", 0) == 0
        ):
            return

        _camera_zoom, software_zoom, center_x, center_y = self._zoom_values()
        final_frame = aplicar_zoom_software_frame_display_f3(
            frame,
            software_zoom,
            center_x,
            center_y,
        )
        try:
            from src.platform.display_visual_rotation import (
                preparar_frame_visual_display,
            )
            final_frame = preparar_frame_visual_display(
                final_frame,
                self._zoom_live_visual_rotation,
            )
        except Exception:
            pass
        self._render_bgr_zoom_canvas(
            final_canvas,
            final_frame,
            "_zoom_final_photo",
        )

    def _on_zoom_viewport_press(self, event) -> str:
        pointer = self._zoom_pointer_normalized(event)
        if pointer is None:
            return "break"

        effective_zoom, center_x, center_y, _rect = (
            self._effective_zoom_view()
        )
        if effective_zoom <= 1.0001:
            self._zoom_drag_active = False
            try:
                self.status.configure(
                    text="Aumente o zoom da câmera ou o Zoom ODIN acima de 1× para mover o quadro azul."
                )
            except Exception:
                pass
            return "break"

        px, py = pointer
        margin = min(0.5, 0.5 / effective_zoom)
        inside = (
            center_x - margin <= px <= center_x + margin
            and center_y - margin <= py <= center_y + margin
        )
        self._zoom_drag_offset_x = center_x - px if inside else 0.0
        self._zoom_drag_offset_y = center_y - py if inside else 0.0
        # O fator de zoom é parte do gesto iniciado no Button-1. Ele não pode
        # mudar até o release, mesmo que outro callback/refresh do Tk atualize
        # a DoubleVar durante o drag no Windows.
        self._zoom_drag_software_zoom = float(software_zoom)
        self._zoom_drag_active = True
        try:
            self.software_zoom_var.set(float(software_zoom))
        except Exception:
            pass
        return self._on_zoom_viewport_drag(event)

    def _on_zoom_viewport_drag(self, event) -> str:
        if not self._zoom_drag_active:
            return "break"
        pointer = self._zoom_pointer_normalized(event)
        if pointer is None:
            return "break"

        px, py = pointer
        camera_zoom, software_zoom, _old_x, _old_y = self._zoom_values()
        try:
            self.software_zoom_var.set(float(software_zoom))
        except Exception:
            pass
        effective_zoom, _effective_x, _effective_y, _rect = (
            self._effective_zoom_view()
        )
        desired_x, desired_y = normalizar_centro_zoom_software_display_f3(
            effective_zoom,
            px + self._zoom_drag_offset_x,
            py + self._zoom_drag_offset_y,
        )

        camera_enabled = bool(self.camera_zoom_enabled_var.get())
        camera_factor = camera_zoom / 100.0 if camera_enabled else 1.0
        if camera_factor > 1.0001:
            camera_x, camera_y = normalizar_centro_zoom_software_display_f3(
                camera_factor,
                desired_x,
                desired_y,
            )
            self.camera_zoom_center_x_var.set(camera_x)
            self.camera_zoom_center_y_var.set(camera_y)
            self.software_zoom_center_x_var.set(0.5)
            self.software_zoom_center_y_var.set(0.5)
            self._publish_hardware_zoom_preview()
        else:
            center_x, center_y = normalizar_centro_zoom_software_display_f3(
                software_zoom,
                desired_x,
                desired_y,
            )
            self.software_zoom_center_x_var.set(center_x)
            self.software_zoom_center_y_var.set(center_y)

        self._update_zoom_labels()
        self._publish_software_zoom_preview()
        self._update_zoom_viewport_overlay()
        self._render_zoom_final_only()
        return "break"

    def _on_zoom_viewport_release(self, _event=None) -> str:
        locked_zoom = getattr(self, "_zoom_drag_software_zoom", None)
        if locked_zoom is not None:
            try:
                self.software_zoom_var.set(float(locked_zoom))
            except Exception:
                pass
        self._publish_software_zoom_preview()
        self._zoom_drag_active = False
        self._zoom_drag_offset_x = 0.0
        self._zoom_drag_offset_y = 0.0
        self._zoom_drag_software_zoom = None
        self._rerender_zoom_preview()
        return "break"

    def save_zoom(self) -> bool:
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "Sem Projeto Display",
                "Selecione ou crie um projeto primeiro.",
                parent=self.window,
            )
            return False
        try:
            camera_zoom, software_zoom, center_x, center_y = self._zoom_values()
            camera_center_x, camera_center_y = self._camera_center_values()
        except (TypeError, ValueError, tk.TclError):
            return False
        saved = self.repository.salvar_zoom_projeto(
            name,
            camera_enabled=bool(self.camera_zoom_enabled_var.get()),
            camera_zoom=camera_zoom,
            software_zoom=software_zoom,
            camera_center_x=camera_center_x,
            camera_center_y=camera_center_y,
            center_x=center_x,
            center_y=center_y,
        )
        if not saved:
            messagebox.showerror(
                "Falha ao salvar",
                "Não foi possível salvar o zoom do Projeto Display.",
                parent=self.window,
            )
            return False
        self.refresh(name)
        self._notify_change()
        self.status.configure(
            text=(
                f"Zoom salvo em {name}: câmera {camera_zoom / 100.0:.2f}× "
                f"({'ativo' if self.camera_zoom_enabled_var.get() else 'desativado'}) "
                f"• ODIN {software_zoom:.2f}× • "
                f"centro {center_x * 100.0:.1f}%/{center_y * 100.0:.1f}%."
            )
        )
        return True

    def _button(self, parent, text, command, primary: bool = False, danger: bool = False):
        bg = "#0E7490" if primary else "#1E293B"
        active = "#0891B2" if primary else "#334155"
        if danger:
            bg = "#7F1D1D"
            active = "#991B1B"
        return tk.Button(
            parent,
            text=text,
            command=command,
            font=("Segoe UI", 8, "bold"),
            bg=bg,
            fg="#FFFFFF",
            activebackground=active,
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            bd=0,
            padx=10,
            pady=7,
            cursor="hand2",
        )

    def _resolution_field(self, parent, label, variable):
        box = tk.Frame(parent, bg="#0F1B2C")
        tk.Label(
            box,
            text=label,
            font=("Segoe UI", 8),
            fg=self.MUTED,
            bg="#0F1B2C",
        ).pack(anchor="w")
        tk.Entry(
            box,
            textvariable=variable,
            width=11,
            font=("Segoe UI", 10, "bold"),
            bg="#020617",
            fg=self.TEXT,
            insertbackground="#FFFFFF",
            relief=tk.FLAT,
            bd=0,
        ).pack(pady=(3, 0), ipady=5)
        return box

    @property
    def visible(self) -> bool:
        try:
            return bool(self.window.winfo_exists())
        except Exception:
            return False

    def _selected_name(self) -> str | None:
        selection = self.project_list.curselection()
        if not selection:
            return None
        return str(self.project_list.get(selection[0]))

    def _notify_change(self) -> None:
        if self.on_change is not None:
            self.on_change()

    def _mask_reference_store(self):
        from src.platform.display_f3_mask_editor_reference import (
            DisplayMaskEditorReferenceStore,
        )
        return DisplayMaskEditorReferenceStore(self.repository)

    def _clear_mask_reference_preview(self, text: str) -> None:
        canvas = getattr(self, "mask_reference_preview", None)
        if canvas is None:
            return
        try:
            canvas.delete("all")
            width = max(40, int(canvas.winfo_width() or 360))
            height = max(40, int(canvas.winfo_height() or 150))
            canvas.create_text(
                width / 2,
                height / 2,
                text=str(text),
                fill=self.MUTED,
                font=("Segoe UI", 9, "bold"),
                justify=tk.CENTER,
            )
        except Exception:
            pass
        self._mask_preview_photo = None

    def _render_mask_reference_preview(self, project=None) -> None:
        self._mask_preview_resize_after_id = None
        canvas = getattr(self, "mask_reference_preview", None)
        status = getattr(self, "mask_reference_status", None)
        if canvas is None:
            return

        name = self._selected_name()
        if not name:
            self._clear_mask_reference_preview("Selecione um Projeto Display.")
            if status is not None:
                status.configure(text="Nenhuma foto de referência.")
            return

        if not isinstance(project, dict):
            cached = self._current_project_snapshot
            if (
                isinstance(cached, dict)
                and str(cached.get("name") or "") == name
            ):
                project = cached
            else:
                project = self.repository.carregar_projeto(name)
        if not isinstance(project, dict):
            self._clear_mask_reference_preview("Selecione um Projeto Display.")
            return

        try:
            from src.platform.display_visual_rotation import (
                obter_rotacao_visual_do_frame_provider,
            )
            visual_rotation = obter_rotacao_visual_do_frame_provider(
                self.frame_provider
            )
        except Exception:
            visual_rotation = 0

        target_width, target_height = self._mask_preview_target_size()
        self._mask_preview_requested_size = (target_width, target_height)
        self._mask_preview_generation += 1
        generation = int(self._mask_preview_generation)
        service = self._get_config_preview_service()
        key = service.submit_mask_reference_preview(
            generation=generation,
            repository=self.repository,
            project_name=name,
            project=project,
            visual_rotation=visual_rotation,
            target_width=target_width,
            target_height=target_height,
        )
        self._register_config_preview_request(key, generation)
        if status is not None:
            status.configure(text="Carregando prévia da referência...")

    def _apply_mask_reference_preview_result(self, result) -> None:
        if int(result.generation) != int(self._mask_preview_generation):
            return
        payload = result.payload if isinstance(result.payload, dict) else {}
        if str(payload.get("project_name") or "") != str(
            self._selected_name() or ""
        ):
            return

        status = getattr(self, "mask_reference_status", None)
        if result.error:
            self._clear_mask_reference_preview(
                "FOTO SALVA\nPreview indisponível."
            )
            if status is not None:
                status.configure(
                    text=f"Foto estática salva • erro da preview: {result.error}"
                )
            return

        if not bool(payload.get("available")):
            reason = str(payload.get("reason") or "")
            if reason == "no_reference":
                self._clear_mask_reference_preview(
                    "SEM FOTO\nUse “Tirar foto com a câmera”."
                )
                if status is not None:
                    status.configure(
                        text="Nenhuma foto de referência salva."
                    )
            else:
                self._clear_mask_reference_preview(
                    "FOTO SALVA\nPreview indisponível."
                )
                if status is not None:
                    status.configure(
                        text="Foto de referência indisponível."
                    )
            return

        photo_data = payload.get("photo_data")
        if not photo_data:
            return
        try:
            photo = tk.PhotoImage(data=photo_data)
        except Exception:
            return

        self._mask_preview_photo = photo
        rendered_width = max(
            1,
            int(payload.get("rendered_width", 1) or 1),
        )
        rendered_height = max(
            1,
            int(payload.get("rendered_height", 1) or 1),
        )
        self._mask_preview_rendered_size = (
            rendered_width,
            rendered_height,
        )
        canvas = self.mask_reference_preview
        width, height = self._mask_preview_target_size()
        canvas.delete("all")
        canvas.create_image(
            width / 2,
            height / 2,
            image=photo,
            anchor=tk.CENTER,
            tags=("mask_preview_image",),
        )
        canvas.create_rectangle(
            (width - rendered_width) / 2,
            (height - rendered_height) / 2,
            (width + rendered_width) / 2,
            (height + rendered_height) / 2,
            outline="#334155",
            width=1,
            tags=("mask_preview_border",),
        )
        if status is not None:
            status.configure(
                text=(
                    f"Foto estática salva • "
                    f"{int(payload.get('source_width', 0))}x"
                    f"{int(payload.get('source_height', 0))} • "
                    f"{int(payload.get('mask_count', 0))} máscara(s) • "
                    f"VISUAL {int(payload.get('visual_rotation', 0))}°"
                )
            )

    def capture_masks_reference_photo(self) -> None:
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "Sem Projeto Display",
                "Selecione um Projeto Display antes de capturar a foto.",
                parent=self.window,
            )
            return
        resolution = self._read_resolution_fields()
        if resolution is None:
            return

        existing = getattr(self, "mask_capture_window", None)
        if existing is not None:
            try:
                if bool(existing.window.winfo_exists()):
                    existing.window.lift()
                    existing.window.focus_force()
                    return
            except Exception:
                pass

        from src.platform.display_f3_mask_editor_reference import (
            F3MaskReferenceCaptureWindow,
        )

        def captured(_metadata=None) -> None:
            self.mask_capture_window = None
            self._render_mask_reference_preview()
            self.status.configure(
                text=f"Foto estática das máscaras capturada para {name}."
            )

        self.mask_capture_window = F3MaskReferenceCaptureWindow(
            parent=self.window,
            frame_provider=self.frame_provider,
            store=self._mask_reference_store(),
            project_name=name,
            master_resolution=resolution,
            on_captured=captured,
        )

    def remove_masks_reference_photo(self) -> None:
        name = self._selected_name()
        if not name:
            return
        if not messagebox.askyesno(
            "Remover foto",
            (
                "Remover somente a foto estática usada para desenhar a placa "
                "e as máscaras?\n\nAs máscaras e o contorno já salvos serão mantidos."
            ),
            parent=self.window,
        ):
            return
        self._mask_reference_store().remove_project(name)
        self._render_mask_reference_preview()
        self.status.configure(
            text="Foto de referência removida. Máscaras e contorno foram mantidos."
        )

    def draw_masks_geometry(self) -> None:
        name = self._selected_name()
        if not name:
            return
        resolution = self._read_resolution_fields()
        if resolution is None:
            return
        project = self.repository.carregar_projeto(name)
        if project is None:
            return

        store = self._mask_reference_store()
        frame = store.load_frame(name)
        if frame is None or getattr(frame, "size", 0) == 0:
            messagebox.showwarning(
                "Foto necessária",
                (
                    "Tire primeiro uma foto com a câmera. O editor usa essa "
                    "imagem estática para a placa não mudar de posição entre edições."
                ),
                parent=self.window,
            )
            return

        from src.platform.display_f3_object_tracking import (
            F3TrackingConfigStore,
            canonical_board_points,
        )
        from src.platform.display_f3_reference_geometry_editor import (
            F3ReferenceGeometryEditor,
        )
        from src.platform.display_visual_rotation import (
            obter_rotacao_visual_do_frame_provider,
            preparar_check_visual_display,
            preparar_pontos_visuais_display,
            restaurar_mascara_original_display,
            restaurar_pontos_originais_display,
        )

        tracking_store = F3TrackingConfigStore(self.repository)
        visual_rotation = obter_rotacao_visual_do_frame_provider(
            self.frame_provider
        )
        frame_visual, visual_resolution, masks_visual = (
            preparar_check_visual_display(
                frame,
                resolution,
                project.get("masks", []),
                visual_rotation,
            )
        )
        board_original = canonical_board_points(project, tracking_store)
        board_visual = preparar_pontos_visuais_display(
            board_original,
            resolution[0],
            resolution[1],
            visual_rotation,
        )

        def save_geometry(board_points, masks) -> bool:
            masks_original = [
                restaurar_mascara_original_display(
                    mask,
                    resolution[0],
                    resolution[1],
                    visual_rotation,
                )
                for mask in (masks or [])
                if isinstance(mask, dict)
            ]
            board_saved = restaurar_pontos_originais_display(
                board_points,
                resolution[0],
                resolution[1],
                visual_rotation,
            )
            masks_ok = self.repository.salvar_configuracao_projeto(
                name,
                resolution,
                masks_original,
            )
            board_ok = (
                tracking_store.save_board_points(name, board_saved)
                if len(board_saved) >= 3
                else False
            )
            if masks_ok and board_ok:
                self.refresh(name)
                self._render_mask_reference_preview()
                self._notify_change()
                self.status.configure(
                    text=(
                        f"Placa + {len(masks_original)} máscara(s) salvas em {name}."
                    )
                )
                return True
            return False

        self.mask_geometry_editor = F3ReferenceGeometryEditor(
            parent=self.window,
            image=frame_visual,
            width=int(visual_resolution[0]),
            height=int(visual_resolution[1]),
            board_points=board_visual,
            masks=masks_visual,
            on_save=save_geometry,
            title="ODIN • F3 • Placa e máscaras",
            header_title="F3 • PLACA + MÁSCARAS • REFERÊNCIA ESTÁTICA",
            on_close=self._render_mask_reference_preview,
            allow_mask_creation=True,
        )

    def edit_masks(self) -> None:
        # Compatibilidade com atalhos/camadas antigas: a edição atual é sempre
        # feita pelo mesmo editor geométrico usado pelas demais referências F3.
        self.draw_masks_geometry()

    def _current_frame_resolution(self) -> tuple[int, int] | None:
        try:
            frame = self.frame_provider()
        except Exception:
            frame = None
        shape = getattr(frame, "shape", None)
        if shape is None or len(shape) < 2:
            return None
        return int(shape[1]), int(shape[0])

    def refresh(self, prefer: str | None = None) -> None:
        projects = self.repository.listar_projetos()
        active = self.repository.obter_projeto_ativo()
        target = normalizar_nome_projeto_display(prefer) or active
        self.project_list.delete(0, tk.END)
        selected_index = None
        for index, name in enumerate(projects):
            self.project_list.insert(tk.END, name)
            if name == target:
                selected_index = index
        if selected_index is None and projects:
            selected_index = 0
        if selected_index is not None:
            self.project_list.selection_set(selected_index)
            self.project_list.see(selected_index)
            self._load_selected()
        else:
            self._show_no_project()
        self.status.configure(
            text=f"Projeto Display ativo: {active or 'NENHUM'} • {len(projects)} projeto(s)"
        )

    def _show_no_project(self) -> None:
        self._current_project_snapshot = None
        self._mask_preview_generation += 1
        self.project_title.configure(text="SEM PROJETO")
        self.project_state.configure(
            text="Crie um Projeto Display para definir resolução, máscaras e CHECKS."
        )
        self.width_var.set("")
        self.height_var.set("")
        self.camera_zoom_enabled_var.set(False)
        self.camera_zoom_var.set(float(CAMERA_ZOOM_MIN))
        self.camera_zoom_center_x_var.set(0.5)
        self.camera_zoom_center_y_var.set(0.5)
        self.software_zoom_var.set(1.0)
        self.software_zoom_center_x_var.set(0.5)
        self.software_zoom_center_y_var.set(0.5)
        self._update_zoom_labels()
        self.update_live_zoom_preview(None)
        self.mask_summary.configure(text="0 máscaras salvas")
        self._clear_mask_reference_preview("Selecione um Projeto Display.")
        if getattr(self, "mask_reference_status", None) is not None:
            self.mask_reference_status.configure(text="Nenhuma foto de referência.")
        self.check_summary.configure(text="0 CHECKS configurados")

    def _load_selected(self) -> None:
        name = self._selected_name()
        project = self.repository.carregar_projeto(name)
        if project is None:
            self._show_no_project()
            return
        self._current_project_snapshot = project
        self.project_title.configure(text=project["name"])
        resolution = normalizar_resolucao_display(project.get("master_resolution"))
        if resolution is None:
            self.width_var.set("")
            self.height_var.set("")
            resolution_text = "resolução mestre não definida"
        else:
            self.width_var.set(str(resolution[0]))
            self.height_var.set(str(resolution[1]))
            resolution_text = f"{resolution[0]}x{resolution[1]}"
        zoom = normalizar_zoom_projeto_display(project)
        camera_zoom = zoom["camera_zoom"]
        self.camera_zoom_enabled_var.set(bool(camera_zoom["enabled"]))
        self.camera_zoom_var.set(float(camera_zoom["value"]))
        camera_center = zoom["camera_zoom_center"]
        self.camera_zoom_center_x_var.set(float(camera_center["x"]))
        self.camera_zoom_center_y_var.set(float(camera_center["y"]))
        self.software_zoom_var.set(float(zoom["software_zoom"]))
        center = zoom["software_zoom_center"]
        self.software_zoom_center_x_var.set(float(center["x"]))
        self.software_zoom_center_y_var.set(float(center["y"]))
        self._update_zoom_labels()
        self._on_hardware_zoom_changed()
        try:
            source_frame = self.source_frame_provider()
        except Exception:
            source_frame = None
        if source_frame is not None and getattr(source_frame, "size", 0) > 0:
            self.update_live_zoom_preview(source_frame)
        masks = project.get("masks", [])
        checks = project.get("checks", [])
        active = self.repository.obter_projeto_ativo()
        self.project_state.configure(
            text=(
                f"{'ATIVO NO F3' if project['name'] == active else 'Projeto disponível'} • "
                f"{resolution_text}"
            )
        )
        self.mask_summary.configure(text=f"{len(masks)} máscara(s) salva(s)")
        check_names = " → ".join(str(check.get("name", "CHECK")) for check in checks)
        if len(check_names) > 54:
            check_names = check_names[:51] + "..."
        self.check_summary.configure(
            text=(
                f"{len(checks)} CHECK(s) configurado(s)"
                + (f"\n{check_names}" if check_names else "")
            )
        )
        self._render_mask_reference_preview(project)

    def add_project(self) -> None:
        name = simpledialog.askstring(
            "Novo Projeto Display",
            "Nome do Projeto Display:",
            parent=self.window,
        )
        name = normalizar_nome_projeto_display(name)
        if not name:
            return
        resolution = self._current_frame_resolution()
        if not self.repository.adicionar_projeto(name, resolution):
            messagebox.showwarning(
                "Projeto não criado",
                "O nome é inválido ou já existe.",
                parent=self.window,
            )
            return
        self.repository.definir_projeto_ativo(name)
        self.refresh(name)
        self._notify_change()

    def rename_selected(self) -> None:
        current = self._selected_name()
        if not current:
            return
        new_name = simpledialog.askstring(
            "Renomear Projeto Display",
            "Novo nome:",
            initialvalue=current,
            parent=self.window,
        )
        if not new_name:
            return
        if not self.repository.renomear_projeto(current, new_name):
            messagebox.showwarning(
                "Não foi possível renomear",
                "Verifique se o novo nome já existe.",
                parent=self.window,
            )
            return
        try:
            self._mask_reference_store().rename_project(current, new_name)
        except Exception:
            pass
        self.refresh(new_name)
        self._notify_change()

    def remove_selected(self) -> None:
        name = self._selected_name()
        if not name:
            return
        if not messagebox.askyesno(
            "Remover Projeto Display",
            f"Remover {name}, suas máscaras e seus CHECKS?",
            parent=self.window,
        ):
            return
        if self.repository.remover_projeto(name):
            try:
                self._mask_reference_store().remove_project(name)
            except Exception:
                pass
            self.refresh()
            self._notify_change()

    def _read_resolution_fields(self) -> tuple[int, int] | None:
        resolution = normalizar_resolucao_display(
            (self.width_var.get(), self.height_var.get())
        )
        if resolution is None:
            messagebox.showwarning(
                "Resolução mestre inválida",
                "Informe largura e altura maiores que zero.",
                parent=self.window,
            )
        return resolution

    def save_resolution(self) -> bool:
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "Sem Projeto Display",
                "Selecione ou crie um projeto primeiro.",
                parent=self.window,
            )
            return False
        resolution = self._read_resolution_fields()
        if resolution is None:
            return False
        if not self.repository.salvar_resolucao_mestra(name, *resolution):
            messagebox.showerror(
                "Falha ao salvar",
                "Não foi possível salvar a resolução mestre do Projeto Display.",
                parent=self.window,
            )
            return False
        self.status.configure(
            text=f"Resolução {resolution[0]}x{resolution[1]} salva em {name}."
        )
        self.refresh(name)
        self._notify_change()
        return True

    def activate_selected(self) -> None:
        name = self._selected_name()
        if not name:
            return
        if self.repository.definir_projeto_ativo(name):
            self.refresh(name)
            self._notify_change()

    def manage_checks(self) -> None:
        name = self._selected_name()
        if not name:
            messagebox.showwarning(
                "Sem Projeto Display",
                "Selecione ou crie um projeto primeiro.",
                parent=self.window,
            )
            return
        existing = self.check_manager
        if existing is not None and existing.visible:
            try:
                existing.window.lift()
                existing.window.focus_force()
            except Exception:
                pass
            return

        def checks_changed() -> None:
            self.refresh(name)
            self._notify_change()

        def checks_closed() -> None:
            self.check_manager = None
            self.refresh(name)
            try:
                self.window.lift()
                self.window.focus_force()
            except Exception:
                pass

        self.check_manager = DisplayCheckManagerWindow(
            root=self.root,
            repository=self.repository,
            project_name=name,
            frame_provider=self.frame_provider,
            on_change=checks_changed,
            on_close=checks_closed,
        )

    def close(self) -> None:
        for attr in (
            "_initial_refresh_after_id",
            "_config_preview_poll_after_id",
            "_mask_preview_resize_after_id",
        ):
            after_id = getattr(self, attr, None)
            if after_id is not None:
                try:
                    self.window.after_cancel(after_id)
                except Exception:
                    pass
                setattr(self, attr, None)
        service = self._config_preview_service
        self._config_preview_service = None
        self._config_preview_outstanding.clear()
        if service is not None:
            try:
                service.stop()
            except Exception:
                pass
        if self._owns_heavy_executor and self._heavy_executor is not None:
            self._heavy_executor.shutdown(
                wait=False,
                cancel_pending=True,
            )
            self._heavy_executor = None
            self._owns_heavy_executor = False

        manager = self.check_manager
        if manager is not None and manager.visible:
            manager.close()
        self.check_manager = None
        editor = self.mask_editor
        if editor is not None and editor.visible:
            editor.close()
        self.mask_editor = None
        geometry_editor = getattr(self, "mask_geometry_editor", None)
        if geometry_editor is not None:
            try:
                geometry_editor.close()
            except Exception:
                pass
        self.mask_geometry_editor = None
        capture_window = getattr(self, "mask_capture_window", None)
        if capture_window is not None:
            try:
                capture_window.close()
            except Exception:
                pass
        self.mask_capture_window = None
        self._zoom_live_source_frame = None
        self._zoom_live_overview_frame = None
        self._zoom_source_photo = None
        self._zoom_final_photo = None
        self._zoom_source_mapping = None
        self._zoom_drag_active = False
        self._zoom_drag_software_zoom = None
        try:
            self.window.destroy()
        except Exception:
            pass
        if self.on_close is not None:
            self.on_close()
