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
import numpy as np

import src.platform.display_auto_check_runtime as display_auto_runtime_module
from src.platform.display_f3_window_geometry import fit_f3_toplevel
import src.platform.display_project_config as display_project_config_module
from src.platform.display_auto_check_analyzer import DisplayAutomaticCheckAnalyzer
from src.platform.display_auto_check_policy import (
    DISPLAY_AUTO_DECISION_SEARCHING,
    decidir_analise_display_f3 as decidir_analise_display_f3_base,
)
from src.platform.display_check_editor import DisplayCheckManagerWindow
from src.platform.display_project_repository import (
    DisplayProjectRepository,
    normalizar_nome_projeto_display,
    normalizar_resolucao_display,
)


DISPLAY_CHECK_PRESENCE_SCHEMA_VERSION = 1
DISPLAY_CHECK_PRESENCE_CONFIG_FILENAME = "odin_display_check_presence.json"
DISPLAY_CHECK_PRESENCE_IMAGE_DIRNAME = "display_check_presence"
DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD = 0.72
DISPLAY_CHECK_PRESENCE_COMPARE_WIDTH = 360


def _normalizar_check_id(check_id: str | None) -> str:
    return str(check_id or "").strip().upper()


def _slug(texto: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", str(texto or "").strip()).strip("_")
    return value.lower() or "display"


def _reference_key(project_name: str, check_id: str) -> str:
    return f"{normalizar_nome_projeto_display(project_name)}::{_normalizar_check_id(check_id)}"


def _valid_frame(frame) -> bool:
    return frame is not None and getattr(frame, "size", 0) > 0


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


def _prepare_gray_for_compare(image):
    image = _prepare_bgr(image)
    if image is None:
        return None
    height, width = image.shape[:2]
    if width > DISPLAY_CHECK_PRESENCE_COMPARE_WIDTH:
        target_width = DISPLAY_CHECK_PRESENCE_COMPARE_WIDTH
        target_height = max(1, int(round(height * target_width / float(width))))
        image = cv2.resize(
            image,
            (target_width, target_height),
            interpolation=cv2.INTER_AREA,
        )
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return gray.astype(np.float32)


def calcular_similaridade_presenca_display(reference_image, current_image) -> float:
    """SSIM local leve para cena fixa, sem dependência de scikit-image."""
    reference = _prepare_gray_for_compare(reference_image)
    current = _prepare_gray_for_compare(current_image)
    if reference is None or current is None:
        return 0.0
    if current.shape != reference.shape:
        current = cv2.resize(
            current,
            (reference.shape[1], reference.shape[0]),
            interpolation=cv2.INTER_AREA,
        )

    c1 = (0.01 * 255.0) ** 2
    c2 = (0.03 * 255.0) ** 2
    mu_ref = cv2.GaussianBlur(reference, (11, 11), 1.5)
    mu_cur = cv2.GaussianBlur(current, (11, 11), 1.5)
    mu_ref_sq = mu_ref * mu_ref
    mu_cur_sq = mu_cur * mu_cur
    mu_ref_cur = mu_ref * mu_cur

    sigma_ref_sq = cv2.GaussianBlur(reference * reference, (11, 11), 1.5) - mu_ref_sq
    sigma_cur_sq = cv2.GaussianBlur(current * current, (11, 11), 1.5) - mu_cur_sq
    sigma_ref_cur = cv2.GaussianBlur(reference * current, (11, 11), 1.5) - mu_ref_cur

    numerator = (2.0 * mu_ref_cur + c1) * (2.0 * sigma_ref_cur + c2)
    denominator = (mu_ref_sq + mu_cur_sq + c1) * (
        sigma_ref_sq + sigma_cur_sq + c2
    )
    score_map = numerator / np.maximum(denominator, 1e-9)
    score = float(np.mean(score_map))
    return round(max(0.0, min(1.0, score)), 4)


class DisplayCheckPresenceReferenceStore:
    """Persistência F3 exclusiva para a foto de referência de cada CHECK."""

    def __init__(self, repository: DisplayProjectRepository) -> None:
        self.repository = repository
        config_file = Path(getattr(repository, "config_file", "data/config/odin_display_projects.json"))
        self.config_file = config_file.parent / DISPLAY_CHECK_PRESENCE_CONFIG_FILENAME
        self.image_dir = config_file.parent / DISPLAY_CHECK_PRESENCE_IMAGE_DIRNAME

    @staticmethod
    def _empty() -> dict:
        return {
            "schema_version": DISPLAY_CHECK_PRESENCE_SCHEMA_VERSION,
            "references": {},
        }

    def _load(self) -> dict:
        if not self.config_file.exists():
            return self._empty()
        try:
            data = json.loads(self.config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return self._empty()
        references = data.get("references", {}) if isinstance(data, dict) else {}
        if not isinstance(references, dict):
            references = {}
        normalized = {}
        for key, value in references.items():
            if not isinstance(value, dict):
                continue
            image_path = str(value.get("image_path") or "").strip()
            if not image_path:
                continue
            try:
                threshold = float(
                    value.get("threshold", DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD)
                )
            except (TypeError, ValueError):
                threshold = DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD
            normalized[str(key)] = {
                "image_path": image_path,
                "threshold": max(0.10, min(0.99, threshold)),
                "width": int(value.get("width", 0) or 0),
                "height": int(value.get("height", 0) or 0),
                "captured_at": str(value.get("captured_at") or ""),
            }
        return {
            "schema_version": DISPLAY_CHECK_PRESENCE_SCHEMA_VERSION,
            "references": normalized,
        }

    def _write(self, data: dict) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_file.with_suffix(self.config_file.suffix + ".tmp")
        temporary.write_text(
            json.dumps(data, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.config_file)

    def get(self, project_name: str, check_id: str) -> dict | None:
        value = self._load()["references"].get(_reference_key(project_name, check_id))
        return deepcopy(value) if isinstance(value, dict) else None

    def capture(
        self,
        project_name: str,
        check_id: str,
        frame,
        master_resolution,
    ) -> dict | None:
        resolution = normalizar_resolucao_display(master_resolution)
        if resolution is None or not _valid_frame(frame):
            return None
        image = _prepare_bgr(frame, resolution)
        if image is None:
            return None

        project = normalizar_nome_projeto_display(project_name)
        check = _normalizar_check_id(check_id)
        if not project or not check:
            return None

        self.image_dir.mkdir(parents=True, exist_ok=True)
        path = self.image_dir / f"{_slug(project)}_{_slug(check)}.jpg"
        ok = cv2.imwrite(
            str(path),
            image,
            [cv2.IMWRITE_JPEG_QUALITY, 92],
        )
        if not ok:
            return None

        metadata = {
            "image_path": str(path),
            "threshold": DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD,
            "width": int(resolution[0]),
            "height": int(resolution[1]),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
        data = self._load()
        data["references"][_reference_key(project, check)] = metadata
        self._write(data)
        return deepcopy(metadata)

    def remove(self, project_name: str, check_id: str) -> bool:
        data = self._load()
        key = _reference_key(project_name, check_id)
        metadata = data["references"].pop(key, None)
        if metadata is None:
            return False
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
        prefix = f"{old_project}::"
        moved = {}
        for key in list(data["references"].keys()):
            if not key.startswith(prefix):
                continue
            check_id = key.split("::", 1)[1]
            moved[f"{new_project}::{check_id}"] = data["references"].pop(key)
        if moved:
            data["references"].update(moved)
            self._write(data)

    def remove_project(self, project_name: str) -> None:
        project = normalizar_nome_projeto_display(project_name)
        if not project:
            return
        data = self._load()
        prefix = f"{project}::"
        removed = []
        for key in list(data["references"].keys()):
            if key.startswith(prefix):
                removed.append(data["references"].pop(key))
        if removed:
            self._write(data)
        for metadata in removed:
            path = Path(str(metadata.get("image_path") or ""))
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass


def avaliar_referencia_presenca_display(frame, metadata: dict | None) -> dict:
    if not isinstance(metadata, dict):
        return {
            "configured": False,
            "available": False,
            "matched": True,
            "score": None,
            "threshold": DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD,
        }

    path = Path(str(metadata.get("image_path") or ""))
    try:
        threshold = float(
            metadata.get("threshold", DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD)
        )
    except (TypeError, ValueError):
        threshold = DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD
    threshold = max(0.10, min(0.99, threshold))

    if not path.exists() or not path.is_file():
        return {
            "configured": True,
            "available": False,
            "matched": False,
            "score": None,
            "threshold": round(threshold, 4),
            "image_path": str(path),
        }

    reference = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if reference is None or not _valid_frame(reference) or not _valid_frame(frame):
        return {
            "configured": True,
            "available": False,
            "matched": False,
            "score": None,
            "threshold": round(threshold, 4),
            "image_path": str(path),
        }

    current = _prepare_bgr(frame, (reference.shape[1], reference.shape[0]))
    score = calcular_similaridade_presenca_display(reference, current)
    return {
        "configured": True,
        "available": True,
        "matched": bool(score >= threshold),
        "score": score,
        "threshold": round(threshold, 4),
        "image_path": str(path),
    }


class DisplayPresenceAwareAnalyzer(DisplayAutomaticCheckAnalyzer):
    """Acrescenta presença/cena do CHECK sem alterar o classificador de LEDs."""

    def __init__(self, repository) -> None:
        super().__init__(repository)
        self.presence_store = DisplayCheckPresenceReferenceStore(repository)

    def analyze(
        self,
        frame,
        project_name: str,
        check_id: str,
        visual_rotation: int = 0,
    ) -> dict:
        analysis = super().analyze(
            frame=frame,
            project_name=project_name,
            check_id=check_id,
            visual_rotation=visual_rotation,
        )
        metadata = self.presence_store.get(project_name, check_id)
        presence = avaliar_referencia_presenca_display(frame, metadata)
        analysis["presence_reference"] = presence

        if not presence["configured"]:
            return analysis
        if not presence["available"]:
            analysis["ready"] = False
            analysis["approved"] = None
            analysis["reason"] = "referencia_visual_check_indisponivel"
            return analysis

        if bool(analysis.get("ready")):
            if not presence["matched"]:
                analysis["approved"] = False
                analysis["reason"] = "referencia_visual_check_nao_corresponde"
            elif analysis.get("approved") is True:
                analysis["reason"] = "check_conforme_com_referencia_visual"
        return analysis


def decidir_analise_display_f3_com_presenca(
    analysis: dict | None,
    *,
    reference_gate: bool = False,
) -> dict:
    data = dict(analysis or {})
    presence = data.get("presence_reference")
    if bool(data.get("ready")) and isinstance(presence, dict):
        if bool(presence.get("configured")) and not bool(presence.get("matched")):
            return {
                "decision": DISPLAY_AUTO_DECISION_SEARCHING,
                "reason": "aguardando_referencia_visual_check",
                "confirmed_ng": False,
                "board_powered": False,
                "presence_score": presence.get("score"),
                "presence_threshold": presence.get("threshold"),
            }
    return decidir_analise_display_f3_base(
        analysis,
        reference_gate=reference_gate,
    )


class DisplayCheckManagerPresenceWindow(DisplayCheckManagerWindow):
    """CHECKS do F3 com captura e preview da referência visual da cena."""

    def __init__(self, *args, **kwargs) -> None:
        self._presence_store = None
        self._presence_photo = None
        self.reference_canvas = None
        self.reference_status = None
        super().__init__(*args, **kwargs)
        self._presence_store = DisplayCheckPresenceReferenceStore(self.repository)
        fit_f3_toplevel(
            self.window,
            getattr(self, "root", None),
            preferred_width=860,
            preferred_height=720,
            min_width=760,
            min_height=560,
        )
        self._install_presence_panel()
        self._update_presence_detail()

    def _install_presence_panel(self) -> None:
        parent = self.edit_button.master
        box = tk.Frame(parent, bg="#0F1B2C")
        box.pack(
            fill=tk.X,
            padx=16,
            pady=(0, 12),
            before=self.edit_button,
        )
        tk.Label(
            box,
            text="REFERÊNCIA VISUAL / PRESENÇA",
            font=("Segoe UI", 9, "bold"),
            fg=self.MUTED,
            bg="#0F1B2C",
            anchor="w",
        ).pack(fill=tk.X, padx=12, pady=(9, 3))
        tk.Label(
            box,
            text=(
                "Foto da câmera usada como evidência adicional para identificar este CHECK. "
                "No H1, ajuda a confirmar que a placa/display correto entrou na inspeção."
            ),
            font=("Segoe UI", 8),
            fg=self.MUTED,
            bg="#0F1B2C",
            justify=tk.LEFT,
            wraplength=330,
            anchor="w",
        ).pack(fill=tk.X, padx=12, pady=(0, 6))

        self.reference_canvas = tk.Canvas(
            box,
            width=330,
            height=92,
            bg="#020617",
            bd=0,
            highlightthickness=1,
            highlightbackground="#253247",
        )
        self.reference_canvas.pack(padx=12, pady=(0, 5))
        self.reference_status = tk.Label(
            box,
            text="Nenhuma referência visual anexada.",
            font=("Segoe UI", 8, "bold"),
            fg=self.MUTED,
            bg="#0F1B2C",
            anchor="w",
        )
        self.reference_status.pack(fill=tk.X, padx=12, pady=(0, 6))

        actions = tk.Frame(box, bg="#0F1B2C")
        actions.pack(fill=tk.X, padx=12, pady=(0, 9))
        self._button(
            actions,
            "CAPTURAR FOTO DA CÂMERA",
            self.capture_presence_reference,
            primary=True,
        ).pack(side=tk.LEFT, padx=(0, 6))
        self._button(
            actions,
            "Remover",
            self.remove_presence_reference,
            danger=True,
        ).pack(side=tk.LEFT)

    def _update_detail(self) -> None:
        super()._update_detail()
        if self.reference_canvas is not None:
            self._update_presence_detail()

    @staticmethod
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

    def _update_presence_detail(self) -> None:
        canvas = self.reference_canvas
        status = self.reference_status
        store = self._presence_store
        if canvas is None or status is None or store is None:
            return
        canvas.delete("all")
        self._presence_photo = None
        check_id = self._selected_id()
        if not check_id:
            status.configure(text="Selecione um CHECK.", fg=self.MUTED)
            return

        metadata = store.get(self.project_name, check_id)
        if metadata is None:
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
        image = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.exists() else None
        if image is None:
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

        photo = self._photo_from_image(image, 326, 88)
        if photo is not None:
            self._presence_photo = photo
            canvas.create_image(165, 46, image=photo, anchor=tk.CENTER)
        threshold = float(
            metadata.get("threshold", DISPLAY_CHECK_PRESENCE_DEFAULT_THRESHOLD)
        )
        status.configure(
            text=(
                f"Referência ativa • mínimo {threshold * 100:.0f}% • "
                f"{int(metadata.get('width', 0))}x{int(metadata.get('height', 0))}"
            ),
            fg="#86EFAC",
        )

    def capture_presence_reference(self) -> None:
        check_id = self._selected_id()
        if not check_id or self._presence_store is None:
            return
        project = self.repository.carregar_projeto(self.project_name)
        if project is None:
            return
        resolution = normalizar_resolucao_display(project.get("master_resolution"))
        if resolution is None:
            messagebox.showwarning(
                "Sem resolução mestre",
                "Defina a resolução mestre do Projeto Display antes da referência.",
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
                "Não há um frame válido da câmera para anexar ao CHECK.",
                parent=self.window,
            )
            return

        metadata = self._presence_store.capture(
            self.project_name,
            check_id,
            frame,
            resolution,
        )
        if metadata is None:
            messagebox.showerror(
                "Falha na captura",
                "Não foi possível salvar a referência visual deste CHECK.",
                parent=self.window,
            )
            return
        self.refresh(check_id)
        self._notify_change()
        self.status.configure(
            text="Foto da câmera anexada como referência visual do CHECK."
        )

    def remove_presence_reference(self) -> None:
        check_id = self._selected_id()
        if not check_id or self._presence_store is None:
            return
        if self._presence_store.get(self.project_name, check_id) is None:
            return
        if not messagebox.askyesno(
            "Remover referência visual",
            "Remover a foto de referência deste CHECK?",
            parent=self.window,
        ):
            return
        self._presence_store.remove(self.project_name, check_id)
        self.refresh(check_id)
        self._notify_change()


def _install_repository_lifecycle_hooks() -> None:
    cls = DisplayProjectRepository
    if bool(getattr(cls, "_display_presence_reference_hooks_installed", False)):
        return

    original_rename_project = cls.renomear_projeto
    original_remove_project = cls.remover_projeto
    original_remove_check = cls.remover_check

    def rename_project(self, nome_atual: str, novo_nome: str) -> bool:
        old_name = normalizar_nome_projeto_display(nome_atual)
        new_name = normalizar_nome_projeto_display(novo_nome)
        changed = original_rename_project(self, nome_atual, novo_nome)
        if changed:
            DisplayCheckPresenceReferenceStore(self).rename_project(old_name, new_name)
        return changed

    def remove_project(self, nome: str) -> bool:
        project_name = normalizar_nome_projeto_display(nome)
        removed = original_remove_project(self, nome)
        if removed:
            DisplayCheckPresenceReferenceStore(self).remove_project(project_name)
        return removed

    def remove_check(self, nome_projeto: str, check_id: str) -> bool:
        project_name = normalizar_nome_projeto_display(nome_projeto)
        normalized_check_id = _normalizar_check_id(check_id)
        removed = original_remove_check(self, nome_projeto, check_id)
        if removed:
            DisplayCheckPresenceReferenceStore(self).remove(
                project_name,
                normalized_check_id,
            )
        return removed

    cls.renomear_projeto = rename_project
    cls.remover_projeto = remove_project
    cls.remover_check = remove_check
    cls._display_presence_reference_hooks_installed = True


def _install_runtime_messages() -> None:
    cls = display_auto_runtime_module.DisplayAutomaticCheckF3Mixin
    if bool(getattr(cls, "_display_presence_reference_messages_installed", False)):
        return

    original_reason = cls._display_auto_reason_text
    original_searching = cls._display_auto_searching_text

    def reason_text(reason: str) -> str:
        if str(reason) == "referencia_visual_check_indisponivel":
            return "Imagem de referência visual do CHECK não encontrada"
        return original_reason(reason)

    def searching_text(reason: str) -> str:
        if str(reason) == "aguardando_referencia_visual_check":
            return "buscando presença/estado visual de referência do CHECK"
        return original_searching(reason)

    cls._display_auto_reason_text = staticmethod(reason_text)
    cls._display_auto_searching_text = staticmethod(searching_text)
    cls._display_presence_reference_messages_installed = True


_DISPLAY_CHECK_PRESENCE_INSTALLED = False


def instalar_referencia_presenca_check_display() -> None:
    """Instala a extensão somente no perfil F3 final, sem tocar no runtime F2."""
    global _DISPLAY_CHECK_PRESENCE_INSTALLED
    if _DISPLAY_CHECK_PRESENCE_INSTALLED:
        return

    _install_repository_lifecycle_hooks()
    _install_runtime_messages()
    display_project_config_module.DisplayCheckManagerWindow = (
        DisplayCheckManagerPresenceWindow
    )
    display_auto_runtime_module.DisplayAutomaticCheckAnalyzer = (
        DisplayPresenceAwareAnalyzer
    )
    display_auto_runtime_module.decidir_analise_display_f3 = (
        decidir_analise_display_f3_com_presenca
    )
    _DISPLAY_CHECK_PRESENCE_INSTALLED = True
