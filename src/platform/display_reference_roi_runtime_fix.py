from __future__ import annotations

"""Correção final das referências visuais por máscaras do Display F3.

A troca do antigo recorte retangular por máscaras é instalada em
``display_reference_roi``. Esta camada corrige somente a ligação entre a
persistência/UI já existentes e essa nova região visual, sem alterar o loop de
preview/análise da Produção F3 e sem tocar no F2.
"""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import cv2

import src.platform.display_check_presence_reference as check_module
import src.platform.display_reference_roi as roi_module
import src.platform.display_visual_reference_status as visual_module
import src.platform.raspberry_pi3_production_app as production_app_module
from src.platform.display_project_repository import (
    normalizar_nome_projeto_display,
    normalizar_resolucao_display,
)


def _valid_frame(frame) -> bool:
    return frame is not None and getattr(frame, "size", 0) > 0


def _copy_frame(frame):
    if not _valid_frame(frame):
        return None
    try:
        return frame.copy()
    except Exception:
        return frame


def _frame_for_configuration(owner):
    """Obtém o último frame válido apenas quando o usuário abre/captura config."""
    provider = getattr(owner, "frame_provider", None)
    if callable(provider):
        try:
            frame = provider()
        except Exception:
            frame = None
        copied = _copy_frame(frame)
        if copied is not None:
            return copied

    app = getattr(provider, "__self__", None)
    if app is None:
        return None

    for name in (
        "camera_frame_atual",
        "imagem_original",
        "_display_f3_last_config_frame",
    ):
        copied = _copy_frame(getattr(app, name, None))
        if copied is not None:
            return copied

    service = getattr(app, "camera_service", None)
    if service is not None:
        try:
            snapshot = service.obter_snapshot(-1)
            copied = _copy_frame(getattr(snapshot, "frame", None))
        except Exception:
            copied = None
        if copied is not None:
            return copied
    return None


def _check_store_get(self, project_name: str, check_id: str):
    """Lê a referência do CHECK sem depender dos wrappers antigos por closure."""
    try:
        data = self._load()
        value = data.get("references", {}).get(
            check_module._reference_key(project_name, check_id)
        )
    except Exception:
        value = None
    if not isinstance(value, dict):
        return None
    metadata = deepcopy(value)
    try:
        check = self.repository.carregar_check(project_name, check_id)
    except Exception:
        check = None
    if isinstance(check, dict):
        overrides = check.get("mask_overrides_reference")
        if isinstance(overrides, dict) and overrides:
            metadata["mask_overrides_reference"] = deepcopy(overrides)
    return roi_module._decorate_metadata(
        self.repository,
        project_name,
        metadata,
    )


def _check_store_capture(
    self,
    project_name: str,
    check_id: str,
    frame,
    master_resolution,
):
    resolution = normalizar_resolucao_display(master_resolution)
    if resolution is None or not _valid_frame(frame):
        return None

    image = check_module._prepare_bgr(frame, resolution)
    project = normalizar_nome_projeto_display(project_name)
    check = check_module._normalizar_check_id(check_id)
    if not _valid_frame(image) or not project or not check:
        return None

    path = self.image_dir / (
        f"{check_module._slug(project)}_{check_module._slug(check)}.jpg"
    )
    if not roi_module._encode_jpeg_to_path(path, image):
        return None

    metadata = {
        "image_path": str(path),
        "threshold": check_module.DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD,
        "width": int(resolution[0]),
        "height": int(resolution[1]),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        data = self._load()
        data.setdefault("references", {})[
            check_module._reference_key(project, check)
        ] = metadata
        self._write(data)
    except Exception:
        return None

    return roi_module._decorate_metadata(
        self.repository,
        project_name,
        deepcopy(metadata),
    )


def _project_store_get(self, project_name: str, kind: str):
    project = normalizar_nome_projeto_display(project_name)
    ref_kind = str(kind or "").strip().lower()
    if ref_kind not in visual_module.DISPLAY_PROJECT_REFERENCE_TYPES:
        return None
    try:
        value = self._load().get("projects", {}).get(project, {}).get(ref_kind)
    except Exception:
        value = None
    if not isinstance(value, dict):
        return None
    return roi_module._decorate_metadata(
        self.repository,
        project_name,
        deepcopy(value),
    )


def _project_store_get_all(self, project_name: str):
    result = {}
    for kind in visual_module.DISPLAY_PROJECT_REFERENCE_TYPES:
        value = _project_store_get(self, project_name, kind)
        if isinstance(value, dict):
            result[kind] = value
    return result


def _project_store_capture(
    self,
    project_name: str,
    kind: str,
    frame,
    master_resolution,
):
    project = normalizar_nome_projeto_display(project_name)
    ref_kind = str(kind or "").strip().lower()
    resolution = normalizar_resolucao_display(master_resolution)
    if (
        not project
        or ref_kind not in visual_module.DISPLAY_PROJECT_REFERENCE_TYPES
        or resolution is None
        or not _valid_frame(frame)
    ):
        return None

    image = visual_module._prepare_bgr(frame, resolution)
    if not _valid_frame(image):
        return None
    path = self.image_dir / f"{visual_module._slug(project)}_{ref_kind}.jpg"
    if not roi_module._encode_jpeg_to_path(path, image):
        return None

    try:
        data = self._load()
    except Exception:
        return None
    previous = (
        data.get("projects", {}).get(project, {}).get(ref_kind, {})
        if isinstance(data, dict)
        else {}
    )
    metadata = {
        "image_path": str(path),
        "threshold": check_module.DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD,
        "width": int(resolution[0]),
        "height": int(resolution[1]),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    if isinstance(previous, dict):
        for key in ("board_points_reference", "mask_overrides_reference"):
            if previous.get(key):
                metadata[key] = deepcopy(previous[key])
    try:
        data.setdefault("projects", {}).setdefault(project, {})[
            ref_kind
        ] = metadata
        self._write(data)
    except Exception:
        return None

    return roi_module._decorate_metadata(
        self.repository,
        project_name,
        deepcopy(metadata),
    )


def _update_check_presence_detail(self) -> None:
    canvas = getattr(self, "reference_canvas", None)
    status = getattr(self, "reference_status", None)
    store = getattr(self, "_presence_store", None)
    if canvas is None or status is None or store is None:
        return

    canvas.delete("all")
    self._presence_photo = None
    check_id = self._selected_id()
    if not check_id:
        status.configure(text="Selecione um CHECK.", fg=self.MUTED)
        return

    metadata = store.get(self.project_name, check_id)
    if not isinstance(metadata, dict):
        status.configure(text="Nenhuma referência visual anexada.", fg=self.MUTED)
        canvas.create_text(
            165,
            46,
            text="SEM REFERÊNCIA",
            fill="#64748B",
            font=("Segoe UI", 9, "bold"),
        )
        return

    path = Path(str(metadata.get("image_path") or ""))
    image = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.is_file() else None
    if not _valid_frame(image):
        status.configure(
            text="Referência configurada, mas o arquivo de imagem não foi encontrado.",
            fg="#FCA5A5",
        )
        canvas.create_text(
            165,
            46,
            text="ARQUIVO AUSENTE",
            fill="#FCA5A5",
            font=("Segoe UI", 9, "bold"),
        )
        return

    decorated = roi_module._decorate_reference_image(image, metadata)
    photo = self._photo_from_image(decorated, 326, 88)
    if photo is not None:
        self._presence_photo = photo
        canvas.create_image(165, 46, image=photo, anchor="center")

    try:
        threshold = float(
            metadata.get(
                "threshold",
                check_module.DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD,
            )
        )
    except (TypeError, ValueError):
        threshold = check_module.DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD
    status.configure(
        text=(
            f"Referência ativa • ROI: {int(metadata.get('mask_region_count', 0) or 0)} máscaras • "
            f"mínimo {threshold * 100:.0f}% • "
            f"{int(metadata.get('width', 0))}x{int(metadata.get('height', 0))}"
        ),
        fg="#86EFAC",
    )


def _capture_check_presence_reference(self) -> None:
    check_id = self._selected_id()
    store = getattr(self, "_presence_store", None)
    if not check_id or store is None:
        return

    project = self.repository.carregar_projeto(self.project_name)
    if project is None:
        return
    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    if resolution is None:
        check_module.messagebox.showwarning(
            "Sem resolução mestre",
            "Defina a resolução mestre do Projeto Display antes da referência.",
            parent=self.window,
        )
        return

    frame = _frame_for_configuration(self)
    if not _valid_frame(frame):
        check_module.messagebox.showwarning(
            "Câmera sem imagem",
            "Não há um frame válido da câmera para anexar ao CHECK.",
            parent=self.window,
        )
        return

    metadata = store.capture(
        self.project_name,
        check_id,
        frame,
        resolution,
    )
    if not isinstance(metadata, dict):
        check_module.messagebox.showerror(
            "Falha na captura",
            "Não foi possível salvar a referência visual deste CHECK.",
            parent=self.window,
        )
        return

    self.refresh(check_id)
    self._notify_change()
    self.status.configure(
        text=(
            "Foto da câmera anexada. A preview usa as máscaras do projeto "
            "como ROI visual."
        )
    )


def _update_project_presence_detail(self) -> None:
    store = getattr(self, "_project_presence_store", None)
    if store is None:
        return
    project_name = self._selected_name()
    self._project_presence_photos.clear()

    for kind in visual_module.DISPLAY_PROJECT_REFERENCE_TYPES:
        canvas = self._project_presence_canvases.get(kind)
        status = self._project_presence_status.get(kind)
        if canvas is None or status is None:
            continue
        canvas.delete("all")
        metadata = store.get(project_name or "", kind) if project_name else None
        if not isinstance(metadata, dict):
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
        image = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.is_file() else None
        if not _valid_frame(image):
            canvas.create_text(
                87,
                41,
                text="ARQUIVO AUSENTE",
                fill="#FCA5A5",
                font=("Segoe UI", 7, "bold"),
            )
            status.configure(text="ARQUIVO AUSENTE", fg="#FCA5A5")
            continue

        decorated = roi_module._decorate_reference_image(image, metadata)
        photo = visual_module._photo_from_image(decorated, 170, 78)
        if photo is not None:
            self._project_presence_photos[kind] = photo
            canvas.create_image(87, 41, image=photo, anchor="center")
        status.configure(
            text=(
                f"ATIVA • ROI {int(metadata.get('mask_region_count', 0) or 0)} máscaras • "
                f"{int(metadata.get('width', 0))}x{int(metadata.get('height', 0))}"
            ),
            fg="#86EFAC",
        )


def _capture_project_presence_reference(self, kind: str) -> None:
    store = getattr(self, "_project_presence_store", None)
    project_name = self._selected_name()
    if store is None or not project_name:
        return

    project = self.repository.carregar_projeto(project_name)
    if project is None:
        return
    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    if resolution is None:
        visual_module.messagebox.showwarning(
            "Sem resolução mestre",
            "Defina a resolução mestre antes de capturar a referência.",
            parent=self.window,
        )
        return

    frame = _frame_for_configuration(self)
    if not _valid_frame(frame):
        visual_module.messagebox.showwarning(
            "Câmera sem imagem",
            "Não há imagem válida da câmera para esta referência.",
            parent=self.window,
        )
        return

    metadata = store.capture(project_name, kind, frame, resolution)
    if not isinstance(metadata, dict):
        visual_module.messagebox.showerror(
            "Falha na captura",
            "Não foi possível salvar a referência do Projeto Display.",
            parent=self.window,
        )
        return

    self._update_project_presence_detail()
    self._notify_change()
    self.status.configure(
        text=(
            f"Referência '{visual_module.DISPLAY_PROJECT_REFERENCE_LABELS[kind]}' "
            "atualizada usando as máscaras do projeto como ROI."
        )
    )


def _repair_store_bindings() -> None:
    check_cls = check_module.DisplayCheckPresenceReferenceStore
    check_cls.get = _check_store_get
    check_cls.capture = _check_store_capture
    check_cls._display_mask_regions_installed = True
    check_cls._display_reference_roi_runtime_fix = True

    project_cls = visual_module.DisplayProjectPresenceReferenceStore
    project_cls.get = _project_store_get
    project_cls.get_all = _project_store_get_all
    project_cls.capture = _project_store_capture
    project_cls._display_mask_regions_installed = True
    project_cls._display_reference_roi_runtime_fix = True


def _repair_ui_bindings() -> None:
    check_cls = check_module.DisplayCheckManagerPresenceWindow
    check_cls._update_presence_detail = _update_check_presence_detail
    check_cls.capture_presence_reference = _capture_check_presence_reference
    check_cls._display_mask_preview_installed = True
    check_cls._display_reference_roi_runtime_fix = True

    project_cls = visual_module.DisplayProjectConfigPresenceWindow
    project_cls._update_project_presence_detail = _update_project_presence_detail
    project_cls.capture_project_presence_reference = _capture_project_presence_reference
    project_cls._display_mask_preview_installed = True
    project_cls._display_reference_roi_runtime_fix = True


def aplicar_correcao_referencias_mascaras_f3() -> None:
    _repair_store_bindings()
    _repair_ui_bindings()


def instalar_correcao_referencias_mascaras_f3() -> None:
    """Executa a correção logo após o instalador original de ROI do F3."""
    if bool(
        getattr(
            production_app_module,
            "_display_reference_roi_runtime_fix_hook",
            False,
        )
    ):
        return

    original_installer = production_app_module.instalar_roi_referencias_display_f3

    def installer():
        result = original_installer()
        aplicar_correcao_referencias_mascaras_f3()
        return result

    production_app_module.instalar_roi_referencias_display_f3 = installer
    production_app_module._display_reference_roi_runtime_fix_hook = True
