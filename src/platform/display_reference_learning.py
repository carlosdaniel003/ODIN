from __future__ import annotations

import base64
import re
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import messagebox
from uuid import uuid4

import cv2

from src.core.feature_extractor import extrair_features_selecao
from src.core.roi_geometry import (
    TIPO_ROI_CIRCULO,
    TIPO_ROI_SEGMENTO,
    bbox_roi,
    raio_compatibilidade_segmento,
)
from src.models.led_selection import LedSelection
from src.platform.display_f3_window_geometry import fit_f3_toplevel
from src.platform.display_mask_editor import DisplayMaskEditorWindow
from src.platform.display_mask_geometry import (
    bbox_mascara_display,
    converter_mascara_legada_para_editor,
)
from src.platform.display_project_repository import (
    DisplayProjectRepository,
    normalizar_mascaras_display,
    normalizar_nome_projeto_display,
    normalizar_resolucao_display,
)
from src.platform.display_reference_store import (
    DISPLAY_REFERENCE_LABELS,
    DISPLAY_REFERENCE_TYPES,
    MAX_DISPLAY_REFERENCES_PER_STATE,
    DisplayReferenceLearningStore,
    DisplayReferenceLimitError,
    display_learning_path_for_repository,
)
from src.platform.display_visual_rotation import (
    obter_rotacao_visual_do_frame_provider,
    preparar_frame_visual_display,
)
from src.ui.main_window_parts.image.rotacao_visual_principal import dimensoes_visuais


DISPLAY_REFERENCE_IMAGE_DIR = Path("data/config/display_references")
REFERENCE_COLORS = {
    "on": "#22C55E",
    "off": "#EF4444",
    "low_light": "#F59E0B",
}


def _slug(value: str | None) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip()).strip("_")
    return text.lower() or "sem_projeto"


def display_mask_to_led_selection(mask: dict) -> LedSelection:
    """Converte somente a geometria Display para o extrator matemático comum."""
    item = converter_mascara_legada_para_editor(deepcopy(mask))
    kind = str(item.get("type", "")).lower()
    mask_id = str(item.get("id") or "DISPLAY_REFERENCE")

    if kind == "circle":
        return LedSelection(
            id=mask_id,
            centro_x=int(item["cx"]),
            centro_y=int(item["cy"]),
            raio=max(2, int(item["radius"])),
            tipo_roi=TIPO_ROI_CIRCULO,
        )

    if kind == "segment":
        width = max(1, int(item.get("width", 48)))
        height = max(1, int(item.get("height", 14)))
        return LedSelection(
            id=mask_id,
            centro_x=int(item.get("cx", 0)),
            centro_y=int(item.get("cy", 0)),
            raio=raio_compatibilidade_segmento(width, height),
            tipo_roi=TIPO_ROI_SEGMENTO,
            largura=width,
            altura=height,
            angulo=float(item.get("angle", 0.0) or 0.0),
        )

    if kind == "polygon":
        points = [
            (float(point[0]), float(point[1]))
            for point in item.get("points", [])
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]
        if len(points) < 3:
            raise ValueError("Polígono de referência inválido.")
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        cx = (min(xs) + max(xs)) / 2.0
        cy = (min(ys) + max(ys)) / 2.0
        local_points = [(x - cx, y - cy) for x, y in points]
        width = max(1, int(round(max(xs) - min(xs))))
        height = max(1, int(round(max(ys) - min(ys))))
        return LedSelection(
            id=mask_id,
            centro_x=int(round(cx)),
            centro_y=int(round(cy)),
            raio=raio_compatibilidade_segmento(width, height),
            tipo_roi=TIPO_ROI_SEGMENTO,
            largura=width,
            altura=height,
            angulo=0.0,
            pontos_segmento_livre=local_points,
        )

    raise ValueError("Tipo de máscara não suportado para referência Display.")


def crop_display_reference(frame, mask: dict):
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    selection = display_mask_to_led_selection(mask)
    x1, y1, x2, y2 = bbox_roi(selection)
    height, width = frame.shape[:2]
    x1 = max(0, int(x1))
    y1 = max(0, int(y1))
    x2 = min(width - 1, int(x2))
    y2 = min(height - 1, int(y2))
    if x2 < x1 or y2 < y1:
        return None
    return frame[y1 : y2 + 1, x1 : x2 + 1].copy()


def learn_display_reference(frame, mask: dict) -> dict:
    if frame is None or getattr(frame, "size", 0) == 0:
        raise ValueError("Não existe frame válido para aprender a referência.")
    selection = display_mask_to_led_selection(mask)
    features = extrair_features_selecao(frame, selection)
    return {
        "features": features.to_dict(),
        "mask": deepcopy(mask),
        "selection": selection.to_dict(),
    }


def _photo_from_bgr(image, max_width: int = 175, max_height: int = 72):
    if image is None or getattr(image, "size", 0) == 0:
        return None
    height, width = image.shape[:2]
    scale = min(max_width / max(1, width), max_height / max(1, height), 1.0)
    target = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    preview = cv2.resize(image, target, interpolation=cv2.INTER_AREA) if target != (width, height) else image
    ok, buffer = cv2.imencode(".png", preview, [cv2.IMWRITE_PNG_COMPRESSION, 1])
    if not ok:
        return None
    return tk.PhotoImage(data=base64.b64encode(buffer).decode("ascii"))


class DisplayReferenceMaskEditorWindow(DisplayMaskEditorWindow):
    """Mesmo editor de máscaras do F3, limitado a uma ROI de referência."""

    def __init__(self, *args, reference_label: str = "REFERÊNCIA", **kwargs) -> None:
        self.reference_label = str(reference_label)
        super().__init__(*args, **kwargs)
        try:
            self.window.title(f"ODIN • {self.reference_label} • Seleção de ROI")
        except Exception:
            pass

    def save(self):
        if self.freeform:
            self._finish_freeform()
        masks = normalizar_mascaras_display(deepcopy(self.masks))
        if len(masks) != 1:
            messagebox.showwarning(
                "Uma máscara necessária",
                "Desenhe exatamente uma máscara de referência antes de clicar em OK.",
                parent=self.window,
            )
            return
        if self.on_save:
            self.on_save(masks)
        self.close()


class DisplayReferenceConfigWindow:
    """Até três referências ACESO/APAGADO/POUCA LUZ por contexto Display."""

    BG = "#07111F"
    PANEL = "#0B1728"
    CARD = "#0F1B2C"
    BORDER = "#253247"
    TEXT = "#F8FAFC"
    MUTED = "#94A3B8"

    def __init__(
        self,
        root,
        repository: DisplayProjectRepository,
        project_name: str,
        frame_provider,
        on_change=None,
        on_close=None,
    ) -> None:
        self.root = root
        self.repository = repository
        self.project_name = normalizar_nome_projeto_display(project_name)
        self.frame_provider = frame_provider
        self.on_change = on_change
        self.on_close = on_close
        self.store = DisplayReferenceLearningStore(
            display_learning_path_for_repository(repository)
        )
        self.capture_editor: DisplayReferenceMaskEditorWindow | None = None
        self._photos = []

        self.window = tk.Toplevel(root)
        self.window.title(f"ODIN • Referências Display • {self.project_name}")
        self.window.configure(bg=self.BG)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        fit_f3_toplevel(
            self.window,
            root,
            preferred_width=1080,
            preferred_height=700,
            min_width=820,
            min_height=560,
        )

        tk.Label(
            self.window,
            text="REFERÊNCIAS E APRENDIZADO • DISPLAY F3",
            font=("Segoe UI", 16, "bold"),
            bg=self.BG,
            fg=self.TEXT,
        ).pack(anchor="w", padx=20, pady=(18, 3))
        tk.Label(
            self.window,
            text=(
                f"Projeto: {self.project_name} • até 3 amostras ativas por estado. "
                "GLOBAL serve para todos os Projetos Display; PROJETO serve somente para este projeto."
            ),
            font=("Segoe UI", 9),
            bg=self.BG,
            fg=self.MUTED,
            wraplength=1020,
            justify=tk.LEFT,
        ).pack(anchor="w", padx=20, pady=(0, 12))

        self.grid = tk.Frame(self.window, bg=self.BG)
        self.grid.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 12))
        for column in range(3):
            self.grid.grid_columnconfigure(column, weight=1, uniform="display_refs")
        self.grid.grid_rowconfigure(0, weight=1)

        footer = tk.Frame(self.window, bg=self.BG)
        footer.pack(fill=tk.X, padx=20, pady=(0, 14))
        self.learning_status = tk.Label(
            footer,
            text="",
            font=("Segoe UI", 9, "bold"),
            bg=self.BG,
            fg=self.MUTED,
            anchor="w",
        )
        self.learning_status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(
            footer,
            text="Fechar",
            command=self.close,
            font=("Segoe UI", 9, "bold"),
            bg="#334155",
            fg="#FFFFFF",
            activebackground="#475569",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            padx=18,
            pady=7,
        ).pack(side=tk.RIGHT)

        self.refresh()
        self.window.lift()
        self.window.focus_force()

    @property
    def visible(self) -> bool:
        try:
            return bool(self.window.winfo_exists())
        except Exception:
            return False

    def _notify_change(self) -> None:
        if self.on_change is not None:
            self.on_change()

    def refresh(self) -> None:
        for child in self.grid.winfo_children():
            child.destroy()
        self._photos = []
        snapshot = self.store.learning_snapshot(self.project_name)
        learned_states = 0
        for column, tipo in enumerate(DISPLAY_REFERENCE_TYPES):
            data = snapshot[tipo]
            entries = list(data["references"])
            learned = data.get("features") is not None
            learned_states += int(learned)
            self._build_state_card(column, tipo, entries, learned)
        self.learning_status.configure(
            text=(
                f"Aprendizado ativo em {learned_states}/3 estados • "
                "o centróide das amostras ativas é recalculado automaticamente ao salvar, editar, remover ou mudar escopo."
            )
        )

    def _build_state_card(self, column: int, tipo: str, entries: list[dict], learned: bool) -> None:
        color = REFERENCE_COLORS[tipo]
        card = tk.Frame(
            self.grid,
            bg=self.PANEL,
            highlightbackground=self.BORDER,
            highlightthickness=1,
        )
        card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 5, 0 if column == 2 else 5))
        tk.Label(
            card,
            text=f"{DISPLAY_REFERENCE_LABELS[tipo]}   {len(entries)}/{MAX_DISPLAY_REFERENCES_PER_STATE}",
            font=("Segoe UI", 11, "bold"),
            fg=color,
            bg=self.PANEL,
            anchor="w",
        ).pack(fill=tk.X, padx=10, pady=(10, 2))
        tk.Label(
            card,
            text="APRENDIDO" if learned else "SEM APRENDIZADO",
            font=("Segoe UI", 8, "bold"),
            fg="#86EFAC" if learned else self.MUTED,
            bg=self.PANEL,
            anchor="w",
        ).pack(fill=tk.X, padx=10, pady=(0, 7))

        slots = tk.Frame(card, bg=self.PANEL)
        slots.pack(fill=tk.BOTH, expand=True, padx=9)
        for position, entry in enumerate(entries, start=1):
            self._build_slot(slots, tipo, position, entry)

        if len(entries) < MAX_DISPLAY_REFERENCES_PER_STATE:
            actions = tk.Frame(card, bg=self.PANEL)
            actions.pack(fill=tk.X, padx=9, pady=(7, 10))
            tk.Button(
                actions,
                text="+ Projeto",
                command=lambda t=tipo: self.capture_reference(t, "project", None),
                font=("Segoe UI", 8, "bold"),
                bg=self.CARD,
                fg=self.TEXT,
                relief=tk.FLAT,
                padx=8,
                pady=5,
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)
            tk.Button(
                actions,
                text="+ Global",
                command=lambda t=tipo: self.capture_reference(t, "global", None),
                font=("Segoe UI", 8, "bold"),
                bg=self.CARD,
                fg=color,
                relief=tk.FLAT,
                padx=8,
                pady=5,
            ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))

    def _build_slot(self, parent, tipo: str, position: int, entry: dict) -> None:
        color = REFERENCE_COLORS[tipo]
        sample = entry.get("sample", {})
        scope = str(entry.get("scope", "project"))
        index = int(entry.get("index", position - 1))
        slot = tk.Frame(parent, bg=self.CARD, highlightbackground=self.BORDER, highlightthickness=1)
        slot.pack(fill=tk.X, pady=(0, 7))
        header = tk.Frame(slot, bg=self.CARD)
        header.pack(fill=tk.X, padx=6, pady=(5, 2))
        tk.Label(header, text=f"#{position}", font=("Segoe UI", 8, "bold"), bg=self.CARD, fg=self.MUTED).pack(side=tk.LEFT)
        tk.Label(
            header,
            text="GLOBAL" if scope == "global" else "PROJETO",
            font=("Segoe UI", 7, "bold"),
            bg=self.CARD,
            fg=color if scope == "global" else self.MUTED,
        ).pack(side=tk.RIGHT)

        image = cv2.imread(str(sample.get("image_path") or "")) if sample.get("image_path") else None
        photo = _photo_from_bgr(image)
        preview = tk.Frame(slot, bg="#020617", height=78)
        preview.pack(fill=tk.X, padx=6)
        preview.pack_propagate(False)
        if photo is not None:
            self._photos.append(photo)
            tk.Label(preview, image=photo, bg="#020617").pack(fill=tk.BOTH, expand=True)
        else:
            tk.Label(preview, text="Preview indisponível", font=("Segoe UI", 8), bg="#020617", fg=self.MUTED).pack(fill=tk.BOTH, expand=True)

        actions = tk.Frame(slot, bg=self.CARD)
        actions.pack(fill=tk.X, padx=6, pady=5)
        tk.Button(
            actions,
            text="Editar",
            command=lambda: self.capture_reference(tipo, scope, index),
            font=("Segoe UI", 7, "bold"),
            bg=self.PANEL,
            fg=self.TEXT,
            relief=tk.FLAT,
            padx=6,
            pady=3,
        ).pack(side=tk.LEFT)
        tk.Button(
            actions,
            text="Tudo: SIM" if scope == "global" else "Tudo: NÃO",
            command=lambda: self.toggle_scope(tipo, scope, index),
            font=("Segoe UI", 7, "bold"),
            bg=self.PANEL,
            fg=color if scope == "global" else self.MUTED,
            relief=tk.FLAT,
            padx=6,
            pady=3,
        ).pack(side=tk.LEFT, padx=4)
        tk.Button(
            actions,
            text="×",
            command=lambda: self.remove_reference(tipo, scope, index),
            font=("Segoe UI", 8, "bold"),
            bg=self.PANEL,
            fg="#FCA5A5",
            relief=tk.FLAT,
            padx=7,
            pady=3,
        ).pack(side=tk.RIGHT)

    def _entry_sample(self, tipo: str, scope: str, index: int | None):
        if index is None:
            return None
        for entry in self.store.active_references(self.project_name, tipo):
            if entry.get("scope") == scope and int(entry.get("index", -1)) == int(index):
                return entry.get("sample")
        return None

    def capture_reference(self, tipo: str, scope: str, index: int | None) -> None:
        project = self.repository.carregar_projeto(self.project_name)
        if project is None:
            return
        resolution = normalizar_resolucao_display(project.get("master_resolution"))
        if resolution is None:
            messagebox.showwarning("Resolução necessária", "Defina a resolução mestre do Projeto Display primeiro.", parent=self.window)
            return
        try:
            frame = self.frame_provider()
        except Exception:
            frame = None
        if frame is None or getattr(frame, "size", 0) == 0:
            messagebox.showwarning("Câmera necessária", "Não existe um frame válido da câmera para capturar a referência.", parent=self.window)
            return

        rotation = obter_rotacao_visual_do_frame_provider(self.frame_provider)
        frame_visual = preparar_frame_visual_display(frame, rotation)
        visual_resolution = dimensoes_visuais(resolution[0], resolution[1], rotation)
        existing = self._entry_sample(tipo, scope, index)
        initial_masks = [deepcopy(existing["mask"])] if isinstance(existing, dict) and isinstance(existing.get("mask"), dict) else []

        def save_mask(masks: list[dict]) -> None:
            self._save_reference(tipo, scope, index, frame_visual, masks[0], existing)

        self.capture_editor = DisplayReferenceMaskEditorWindow(
            root=self.root,
            master_resolution=visual_resolution,
            masks=initial_masks,
            frame=frame_visual,
            on_save=save_mask,
            reference_label=f"REFERÊNCIA {DISPLAY_REFERENCE_LABELS[tipo]} • {'GLOBAL' if scope == 'global' else self.project_name}",
        )

    def _save_reference(self, tipo, scope, index, frame, mask, existing) -> None:
        try:
            learned = learn_display_reference(frame, mask)
            crop = crop_display_reference(frame, mask)
            if crop is None or getattr(crop, "size", 0) == 0:
                raise ValueError("Não foi possível gerar o recorte da referência.")

            sample_id = str((existing or {}).get("id") or uuid4().hex)
            old_path = str((existing or {}).get("image_path") or "")
            if old_path:
                path = Path(old_path)
            else:
                destination = "global" if scope == "global" else _slug(self.project_name)
                path = DISPLAY_REFERENCE_IMAGE_DIR / f"reference_{destination}_{tipo}_{sample_id[:10]}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(path), crop):
                raise RuntimeError("Não foi possível gravar a imagem da referência Display.")

            sample = {
                "id": sample_id,
                "image_path": str(path),
                "features": learned["features"],
                "mask": learned["mask"],
                "selection": learned["selection"],
            }
            self.store.save_sample(
                self.project_name,
                tipo,
                sample,
                scope=scope,
                index=index,
            )
        except (DisplayReferenceLimitError, ValueError, IndexError, RuntimeError) as error:
            messagebox.showwarning("Referência não salva", str(error), parent=self.window)
            return

        self.refresh()
        self._notify_change()
        try:
            self.window.lift()
            self.window.focus_force()
        except Exception:
            pass

    def toggle_scope(self, tipo: str, scope: str, index: int) -> None:
        try:
            self.store.move_scope(self.project_name, tipo, scope, index)
        except (DisplayReferenceLimitError, ValueError, IndexError) as error:
            messagebox.showwarning("Limite de referências", str(error), parent=self.window)
            return
        self.refresh()
        self._notify_change()

    def remove_reference(self, tipo: str, scope: str, index: int) -> None:
        if not messagebox.askyesno(
            "Remover referência",
            f"Remover esta amostra de {DISPLAY_REFERENCE_LABELS[tipo]}?",
            parent=self.window,
        ):
            return
        removed = self.store.remove_sample(self.project_name, tipo, scope, index)
        if removed is not None:
            self.refresh()
            self._notify_change()

    def close(self) -> None:
        editor = self.capture_editor
        if editor is not None and editor.visible:
            editor.close()
        self.capture_editor = None
        try:
            self.window.destroy()
        except Exception:
            pass
        if self.on_close is not None:
            self.on_close()


def _install_repository_lifecycle_hooks() -> None:
    cls = DisplayProjectRepository
    if getattr(cls, "_odin_display_reference_lifecycle", False):
        return
    original_rename = cls.renomear_projeto
    original_remove = cls.remover_projeto

    def rename(self, old_name, new_name):
        result = original_rename(self, old_name, new_name)
        if result:
            DisplayReferenceLearningStore(
                display_learning_path_for_repository(self)
            ).rename_project(old_name, new_name)
        return result

    def remove(self, name):
        result = original_remove(self, name)
        if result:
            DisplayReferenceLearningStore(
                display_learning_path_for_repository(self)
            ).remove_project(name)
        return result

    cls.renomear_projeto = rename
    cls.remover_projeto = remove
    cls._odin_display_reference_lifecycle = True


def install_display_reference_learning() -> None:
    """Acopla a UI somente ao Configurar do F3, sem modificar classes do F2."""
    from src.platform.display_project_config import DisplayProjectConfigWindow

    _install_repository_lifecycle_hooks()
    cls = DisplayProjectConfigWindow
    if getattr(cls, "_odin_display_reference_learning", False):
        return

    original_init = cls.__init__
    original_load = cls._load_selected
    original_no_project = cls._show_no_project
    original_close = cls.close

    def update_reference_summary(self) -> None:
        label = getattr(self, "reference_summary", None)
        if label is None:
            return
        name = self._selected_name()
        if not name:
            label.configure(text="ACESO 0/3 • APAGADO 0/3 • POUCA LUZ 0/3")
            return
        store = DisplayReferenceLearningStore(
            display_learning_path_for_repository(self.repository)
        )
        snapshot = store.learning_snapshot(name)
        label.configure(
            text=(
                f"ACESO {snapshot['on']['count']}/3 • "
                f"APAGADO {snapshot['off']['count']}/3 • "
                f"POUCA LUZ {snapshot['low_light']['count']}/3"
            )
        )

    def open_references(self) -> None:
        name = self._selected_name()
        if not name:
            messagebox.showwarning("Sem Projeto Display", "Selecione ou crie um Projeto Display primeiro.", parent=self.window)
            return
        existing = getattr(self, "reference_window", None)
        if existing is not None and existing.visible:
            existing.window.lift()
            existing.window.focus_force()
            return

        def changed():
            update_reference_summary(self)
            self._notify_change()

        def closed():
            self.reference_window = None
            update_reference_summary(self)
            try:
                self.window.lift()
                self.window.focus_force()
            except Exception:
                pass

        self.reference_window = DisplayReferenceConfigWindow(
            root=self.root,
            repository=self.repository,
            project_name=name,
            frame_provider=self.frame_provider,
            on_change=changed,
            on_close=closed,
        )

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.reference_window = None
        parent = self.activate_button.master
        box = tk.Frame(parent, bg="#0F1B2C")
        try:
            box.pack(fill=tk.X, padx=16, pady=(0, 9), before=self.activate_button)
        except Exception:
            box.pack(fill=tk.X, padx=16, pady=(0, 9))
        tk.Label(
            box,
            text="REFERÊNCIAS / APRENDIZADO",
            font=("Segoe UI", 9, "bold"),
            fg=self.MUTED,
            bg="#0F1B2C",
            anchor="w",
        ).pack(fill=tk.X, padx=12, pady=(9, 3))
        self.reference_summary = tk.Label(
            box,
            text="ACESO 0/3 • APAGADO 0/3 • POUCA LUZ 0/3",
            font=("Segoe UI", 9, "bold"),
            fg=self.TEXT,
            bg="#0F1B2C",
            anchor="w",
        )
        self.reference_summary.pack(fill=tk.X, padx=12, pady=(0, 6))
        self.reference_button = self._button(
            box,
            "Configurar referências e aprendizado",
            lambda: open_references(self),
            primary=True,
        )
        self.reference_button.pack(anchor="w", padx=12, pady=(0, 9))
        fit_f3_toplevel(
            self.window,
            getattr(self, "root", None),
            preferred_width=900,
            preferred_height=760,
            min_width=760,
            min_height=560,
        )
        update_reference_summary(self)

    def load(self):
        result = original_load(self)
        update_reference_summary(self)
        return result

    def no_project(self):
        result = original_no_project(self)
        update_reference_summary(self)
        return result

    def close(self):
        reference_window = getattr(self, "reference_window", None)
        if reference_window is not None and reference_window.visible:
            reference_window.close()
        self.reference_window = None
        return original_close(self)

    cls.__init__ = init
    cls._load_selected = load
    cls._show_no_project = no_project
    cls.open_display_references = open_references
    cls._update_display_reference_summary = update_reference_summary
    cls.close = close
    cls._odin_display_reference_learning = True


install_display_reference_learning()
