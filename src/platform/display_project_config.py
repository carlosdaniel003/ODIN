from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, simpledialog

from src.platform.display_check_editor import DisplayCheckManagerWindow
from src.platform.display_f3_window_geometry import fit_f3_toplevel
from src.platform.display_mask_editor import DisplayMaskEditorWindow
from src.platform.display_project_repository import (
    DisplayProjectRepository,
    normalizar_nome_projeto_display,
    normalizar_resolucao_display,
)


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
        on_change: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.root = root
        self.repository = repository
        self.frame_provider = frame_provider
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
            service = DisplayF3ConfigPreviewService()
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
        try:
            self.window.destroy()
        except Exception:
            pass
        if self.on_close is not None:
            self.on_close()
