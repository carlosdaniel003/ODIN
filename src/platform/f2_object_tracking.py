from __future__ import annotations

"""Rastreamento/registro opt-in da placa para o modo Produção F2.

Quando habilitado nas Configurações, o F2 registra geometricamente o frame atual
contra as referências de placa ligada/desligada do projeto, usando apenas a região
física desenhada em ``f2_board_shape`` e evitando as ROIs dos LEDs como pontos de
referência. O frame é então alinhado para o sistema de coordenadas canônico do
projeto ANTES de passar pelo pipeline F2 já existente.

Quando desabilitado, nenhum frame é transformado e o comportamento legado do F2
permanece literalmente no caminho de ``super()``.
"""

import json
import math
import time
import tkinter as tk
from dataclasses import dataclass

import cv2
import numpy as np

from src.core.roi_geometry import (
    TIPO_ROI_SEGMENTO,
    normalizar_tipo_roi,
    pontos_segmento,
)
from src.platform.f2_board_presence_references import (
    F2_BOARD_REF_BOARD_OFF,
    F2_BOARD_REF_BOARD_ON,
)
from src.platform.f2_board_shape_editor import carregar_contorno_placa_leds


F2_OBJECT_TRACKING_SETTING_KEY = "f2_object_tracking_enabled"
F2_OBJECT_TRACKING_OPTION_TEXT = "Ativar rastreamento automático de objetos"
F2_OBJECT_TRACKING_SECTION_TITLE = "Produção F2"
F2_OBJECT_TRACKING_HELP_TEXT = (
    "Quando ativado, o ODIN usa o contorno desenhado da placa e as referências "
    "ligada/desligada para localizar a PCI no frame e estabilizá-la antes da "
    "análise dos LEDs. Desativado, a Produção F2 permanece exatamente no fluxo "
    "normal, sem transformação de imagem."
)

# O Raspberry Pi 3 não precisa recalcular ORB em todo frame de 20 FPS.
F2_TRACKING_REFRESH_S = 0.15
F2_TRACKING_ORB_FEATURES = 1200
F2_TRACKING_RATIO_TEST = 0.74
F2_TRACKING_MIN_MATCHES = 14
F2_TRACKING_MIN_INLIERS = 10
F2_TRACKING_MIN_INLIER_RATIO = 0.36
F2_TRACKING_RANSAC_THRESHOLD_PX = 3.5
F2_TRACKING_MIN_SCALE = 0.82
F2_TRACKING_MAX_SCALE = 1.20
F2_TRACKING_MAX_ROTATION_DEG = 14.0
F2_TRACKING_MAX_TRANSLATION_FRACTION = 0.40
F2_TRACKING_SMOOTH_ALPHA = 0.42
F2_TRACKING_BOARD_MASK_DILATE_PX = 7
F2_TRACKING_LED_EXCLUSION_PADDING_PX = 7


@dataclass(frozen=True)
class F2TrackingResult:
    locked: bool
    frame: object
    reference: str = ""
    matches: int = 0
    inliers: int = 0
    inlier_ratio: float = 0.0
    dx: float = 0.0
    dy: float = 0.0
    rotation_deg: float = 0.0
    scale: float = 1.0
    reason: str = ""


def carregar_rastreamento_automatico_f2(repository) -> bool:
    if repository is None:
        return False
    try:
        config = repository.carregar_configuracao_existente_sem_alerta()
    except Exception:
        return False
    settings = config.get("settings", {}) if isinstance(config, dict) else {}
    if not isinstance(settings, dict):
        return False
    return bool(settings.get(F2_OBJECT_TRACKING_SETTING_KEY, False))


def salvar_rastreamento_automatico_f2(repository, enabled: bool) -> bool:
    if repository is None:
        return False
    try:
        config = repository.carregar_configuracao_existente_sem_alerta()
        if not isinstance(config, dict):
            config = {}
        settings = config.get("settings", {})
        if not isinstance(settings, dict):
            settings = {}
        settings[F2_OBJECT_TRACKING_SETTING_KEY] = bool(enabled)
        config["settings"] = settings
        path = repository.config_file
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            json.dump(config, file, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False


def _walk_widgets(widget):
    try:
        children = tuple(widget.winfo_children())
    except Exception:
        children = ()
    for child in children:
        yield child
        yield from _walk_widgets(child)


def _find_settings_window(root):
    candidates = []
    try:
        children = tuple(root.winfo_children())
    except Exception:
        children = ()
    for widget in children:
        if not isinstance(widget, tk.Toplevel):
            continue
        try:
            if widget.winfo_exists() and "Configurações" in str(widget.title()):
                candidates.append(widget)
        except Exception:
            continue
    return candidates[-1] if candidates else None


def _find_f2_card(settings_window):
    if settings_window is None:
        return None
    for widget in _walk_widgets(settings_window):
        if not isinstance(widget, tk.Label):
            continue
        try:
            if str(widget.cget("text")) == F2_OBJECT_TRACKING_SECTION_TITLE:
                return widget.master
        except Exception:
            continue
    return None


def _add_tracking_setting(app, settings_window) -> bool:
    if settings_window is None:
        return False
    if bool(getattr(settings_window, "_odin_f2_object_tracking_setting_added", False)):
        return False
    card = _find_f2_card(settings_window)
    if card is None:
        return False

    view = app.view
    tk.Frame(card, bg="#172033", height=1).pack(
        fill=tk.X,
        padx=14,
        pady=(2, 9),
    )
    tk.Checkbutton(
        card,
        text=F2_OBJECT_TRACKING_OPTION_TEXT,
        variable=app._f2_object_tracking_settings_var,
        font=("Segoe UI", 10, "bold"),
        fg=view.COR_TEXTO,
        bg=view.COR_CARD_2,
        activebackground=view.COR_CARD_2,
        activeforeground=view.COR_TEXTO,
        selectcolor=view.COR_CARD,
        anchor="w",
    ).pack(fill=tk.X, padx=14, pady=(0, 5))
    tk.Label(
        card,
        text=F2_OBJECT_TRACKING_HELP_TEXT,
        font=("Segoe UI", 8),
        fg=view.COR_TEXTO_3,
        bg=view.COR_CARD_2,
        anchor="w",
        justify=tk.LEFT,
        wraplength=650,
    ).pack(fill=tk.X, padx=14, pady=(0, 12))

    settings_window._odin_f2_object_tracking_setting_added = True
    try:
        settings_window.update_idletasks()
    except Exception:
        pass
    return True


def _adapt_led(led, width: int, height: int):
    try:
        base_w = int(getattr(led, "largura_base", 0) or 0)
        base_h = int(getattr(led, "altura_base", 0) or 0)
        if base_w > 0 and base_h > 0 and (base_w != width or base_h != height):
            adapt = getattr(led, "adaptar_para_resolucao", None)
            if callable(adapt):
                return adapt(
                    int(width),
                    int(height),
                    raio_minimo=1,
                    raio_maximo=max(int(width), int(height)),
                )
    except Exception:
        pass
    return led


def _draw_roi_mask(mask: np.ndarray, led, value: int, padding: int = 0) -> None:
    height, width = mask.shape[:2]
    led = _adapt_led(led, width, height)
    try:
        tipo = normalizar_tipo_roi(getattr(led, "tipo_roi", None))
        if tipo == TIPO_ROI_SEGMENTO:
            points = np.rint(pontos_segmento(led)).astype(np.int32)
            if len(points) >= 3:
                cv2.fillPoly(mask, [points], int(value))
                if padding > 0:
                    x, y, w, h = cv2.boundingRect(points)
                    cv2.rectangle(
                        mask,
                        (max(0, x - padding), max(0, y - padding)),
                        (
                            min(width - 1, x + w + padding),
                            min(height - 1, y + h + padding),
                        ),
                        int(value),
                        thickness=-1,
                    )
                return

        cx = int(getattr(led, "centro_x", 0) or 0)
        cy = int(getattr(led, "centro_y", 0) or 0)
        radius = max(2, int(getattr(led, "raio", 2) or 2)) + max(0, int(padding))
        cv2.circle(mask, (cx, cy), radius, int(value), thickness=-1)
    except Exception:
        return


def construir_mascara_rastreamento_f2(
    shape,
    leds,
    width: int,
    height: int,
) -> np.ndarray | None:
    if width <= 0 or height <= 0 or not shape:
        return None
    mask = np.zeros((int(height), int(width)), dtype=np.uint8)
    for roi in tuple(shape or ()):
        _draw_roi_mask(mask, roi, 255, padding=0)
    if int(cv2.countNonZero(mask)) < 1200:
        return None

    if F2_TRACKING_BOARD_MASK_DILATE_PX > 0:
        size = 1 + 2 * int(F2_TRACKING_BOARD_MASK_DILATE_PX)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        mask = cv2.dilate(mask, kernel, iterations=1)

    # LEDs são deliberadamente removidos da área usada pelo registro. Assim o
    # mesmo rastreador funciona com a placa ligada, desligada e com padrões de LED
    # diferentes sem confundir emissão luminosa com geometria da PCI.
    for led in tuple(leds or ()):
        _draw_roi_mask(
            mask,
            led,
            0,
            padding=F2_TRACKING_LED_EXCLUSION_PADDING_PX,
        )
    if int(cv2.countNonZero(mask)) < 900:
        return None
    return mask


class F2BoardObjectTracker:
    """Registra o frame atual no sistema canônico das referências do projeto."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.project = ""
        self.signature = None
        self.width = 0
        self.height = 0
        self.references: dict[str, tuple[list, np.ndarray]] = {}
        self.ready = False
        self.reason = "not_configured"
        self.last_matrix: np.ndarray | None = None
        self.last_compute_s = 0.0
        self.last_result: F2TrackingResult | None = None
        self.last_frame_id = None

    @staticmethod
    def _prepare_gray(image):
        if image is None or getattr(image, "size", 0) == 0:
            return None
        try:
            gray = (
                image
                if len(image.shape) == 2
                else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            )
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            return clahe.apply(gray)
        except Exception:
            return None

    @staticmethod
    def _load_leds(controller, project: str):
        repository = getattr(controller.app, "config_repository", None)
        getter = getattr(repository, "carregar_leds_fixos", None)
        if not callable(getter):
            return []
        try:
            return list(getter(projeto=project) or [])
        except TypeError:
            try:
                return list(getter(project) or [])
            except Exception:
                return []
        except Exception:
            return []

    def configure(self, controller) -> bool:
        if controller is None:
            self.reset()
            self.reason = "presence_controller_missing"
            return False
        project = str(controller.project_name() or "").strip()
        resolution = controller.master_resolution(project) if project else None
        entries = controller._entries(project) if project else {}
        if not project or not resolution:
            self.reset()
            self.reason = "project_or_resolution_missing"
            return False

        width, height = int(resolution[0]), int(resolution[1])
        paths = {
            slot: str(entries.get(slot, {}).get("image_path") or "").strip()
            for slot in (F2_BOARD_REF_BOARD_ON, F2_BOARD_REF_BOARD_OFF)
        }
        repository = getattr(controller.app, "config_repository", None)
        config = (
            repository.carregar_configuracao_existente_sem_alerta()
            if repository is not None
            else {}
        )
        project_data = (
            config.get("led_projects", {}).get(project, {})
            if isinstance(config, dict)
            else {}
        )
        shape_stamp = (
            project_data.get("f2_board_shape", {}).get("updated_at")
            if isinstance(project_data, dict)
            and isinstance(project_data.get("f2_board_shape", {}), dict)
            else None
        )
        signature = (
            project,
            width,
            height,
            paths[F2_BOARD_REF_BOARD_ON],
            paths[F2_BOARD_REF_BOARD_OFF],
            entries.get(F2_BOARD_REF_BOARD_ON, {}).get("updated_at"),
            entries.get(F2_BOARD_REF_BOARD_OFF, {}).get("updated_at"),
            shape_stamp,
        )
        if signature == self.signature:
            return self.ready

        self.reset()
        self.project = project
        self.signature = signature
        self.width = width
        self.height = height

        shape = carregar_contorno_placa_leds(controller, project, width, height)
        if not shape:
            self.reason = "board_shape_missing"
            return False
        leds = self._load_leds(controller, project)
        tracking_mask = construir_mascara_rastreamento_f2(
            shape,
            leds,
            width,
            height,
        )
        if tracking_mask is None:
            self.reason = "board_shape_mask_invalid"
            return False

        orb = cv2.ORB_create(
            nfeatures=F2_TRACKING_ORB_FEATURES,
            scaleFactor=1.2,
            nlevels=8,
            edgeThreshold=15,
            fastThreshold=9,
        )
        refs = {}
        for slot in (F2_BOARD_REF_BOARD_ON, F2_BOARD_REF_BOARD_OFF):
            image = cv2.imread(paths[slot]) if paths[slot] else None
            if image is None or getattr(image, "size", 0) == 0:
                continue
            if image.shape[1] != width or image.shape[0] != height:
                continue
            gray = self._prepare_gray(image)
            if gray is None:
                continue
            keypoints, descriptors = orb.detectAndCompute(gray, tracking_mask)
            if descriptors is None or len(keypoints) < F2_TRACKING_MIN_MATCHES:
                continue
            refs[slot] = (keypoints, descriptors)

        if not refs:
            self.reason = "reference_features_insufficient"
            return False
        self.references = refs
        self.ready = True
        self.reason = "ready"
        return True

    def _candidate(self, current_gray, current_kp, current_desc, slot: str):
        ref_kp, ref_desc = self.references[slot]
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        try:
            pairs = matcher.knnMatch(ref_desc, current_desc, k=2)
        except Exception:
            return None
        good = []
        for pair in pairs:
            if len(pair) < 2:
                continue
            first, second = pair[0], pair[1]
            if first.distance < F2_TRACKING_RATIO_TEST * second.distance:
                good.append(first)
        if len(good) < F2_TRACKING_MIN_MATCHES:
            return None

        # queryIdx pertence à referência; trainIdx pertence ao frame atual.
        current_points = np.float32(
            [current_kp[m.trainIdx].pt for m in good]
        ).reshape(-1, 1, 2)
        reference_points = np.float32(
            [ref_kp[m.queryIdx].pt for m in good]
        ).reshape(-1, 1, 2)
        matrix, inlier_mask = cv2.estimateAffinePartial2D(
            current_points,
            reference_points,
            method=cv2.RANSAC,
            ransacReprojThreshold=F2_TRACKING_RANSAC_THRESHOLD_PX,
            maxIters=2000,
            confidence=0.995,
            refineIters=10,
        )
        if matrix is None or inlier_mask is None:
            return None
        inliers = int(np.count_nonzero(inlier_mask))
        ratio = float(inliers / max(1, len(good)))
        if inliers < F2_TRACKING_MIN_INLIERS or ratio < F2_TRACKING_MIN_INLIER_RATIO:
            return None

        a = float(matrix[0, 0])
        b = float(matrix[0, 1])
        scale = math.sqrt(max(1e-12, a * a + b * b))
        rotation_deg = math.degrees(math.atan2(float(matrix[1, 0]), a))
        dx = float(matrix[0, 2])
        dy = float(matrix[1, 2])
        if not (F2_TRACKING_MIN_SCALE <= scale <= F2_TRACKING_MAX_SCALE):
            return None
        if abs(rotation_deg) > F2_TRACKING_MAX_ROTATION_DEG:
            return None
        if abs(dx) > self.width * F2_TRACKING_MAX_TRANSLATION_FRACTION:
            return None
        if abs(dy) > self.height * F2_TRACKING_MAX_TRANSLATION_FRACTION:
            return None

        score = float(inliers) + ratio * 10.0
        return {
            "slot": slot,
            "matrix": matrix.astype(np.float32),
            "matches": len(good),
            "inliers": inliers,
            "ratio": ratio,
            "dx": dx,
            "dy": dy,
            "rotation_deg": rotation_deg,
            "scale": scale,
            "score": score,
        }

    def align(self, frame, frame_id=None) -> F2TrackingResult:
        if frame is None or getattr(frame, "size", 0) == 0:
            return F2TrackingResult(False, frame, reason="invalid_frame")
        if not self.ready:
            return F2TrackingResult(False, frame, reason=self.reason)
        if frame.shape[1] != self.width or frame.shape[0] != self.height:
            return F2TrackingResult(False, frame, reason="resolution_mismatch")
        if frame_id is not None and frame_id == self.last_frame_id and self.last_result is not None:
            return self.last_result

        now = time.monotonic()
        # Reutiliza a última matriz por poucos milissegundos para economizar CPU,
        # mas somente se o frame anterior já estava travado no objeto.
        if (
            self.last_matrix is not None
            and self.last_result is not None
            and self.last_result.locked
            and now - self.last_compute_s < F2_TRACKING_REFRESH_S
        ):
            aligned = cv2.warpAffine(
                frame,
                self.last_matrix,
                (self.width, self.height),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT101,
            )
            result = F2TrackingResult(
                True,
                aligned,
                reference=self.last_result.reference,
                matches=self.last_result.matches,
                inliers=self.last_result.inliers,
                inlier_ratio=self.last_result.inlier_ratio,
                dx=self.last_result.dx,
                dy=self.last_result.dy,
                rotation_deg=self.last_result.rotation_deg,
                scale=self.last_result.scale,
                reason="cached_transform",
            )
            self.last_result = result
            self.last_frame_id = frame_id
            return result

        gray = self._prepare_gray(frame)
        if gray is None:
            result = F2TrackingResult(False, frame, reason="gray_prepare_failed")
            self.last_result = result
            self.last_frame_id = frame_id
            return result

        orb = cv2.ORB_create(
            nfeatures=F2_TRACKING_ORB_FEATURES,
            scaleFactor=1.2,
            nlevels=8,
            edgeThreshold=15,
            fastThreshold=9,
        )
        current_kp, current_desc = orb.detectAndCompute(gray, None)
        if current_desc is None or len(current_kp) < F2_TRACKING_MIN_MATCHES:
            self.last_matrix = None
            result = F2TrackingResult(False, frame, reason="current_features_insufficient")
            self.last_result = result
            self.last_frame_id = frame_id
            self.last_compute_s = now
            return result

        candidates = []
        for slot in tuple(self.references):
            candidate = self._candidate(gray, current_kp, current_desc, slot)
            if candidate is not None:
                candidates.append(candidate)
        if not candidates:
            self.last_matrix = None
            result = F2TrackingResult(False, frame, reason="object_not_locked")
            self.last_result = result
            self.last_frame_id = frame_id
            self.last_compute_s = now
            return result

        best = max(candidates, key=lambda item: item["score"])
        matrix = best["matrix"]
        if self.last_matrix is not None:
            alpha = float(F2_TRACKING_SMOOTH_ALPHA)
            matrix = (
                (1.0 - alpha) * self.last_matrix.astype(np.float32)
                + alpha * matrix.astype(np.float32)
            ).astype(np.float32)
        self.last_matrix = matrix
        self.last_compute_s = now

        aligned = cv2.warpAffine(
            frame,
            matrix,
            (self.width, self.height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT101,
        )
        a = float(matrix[0, 0])
        b = float(matrix[0, 1])
        scale = math.sqrt(max(1e-12, a * a + b * b))
        rotation_deg = math.degrees(math.atan2(float(matrix[1, 0]), a))
        result = F2TrackingResult(
            True,
            aligned,
            reference=str(best["slot"]),
            matches=int(best["matches"]),
            inliers=int(best["inliers"]),
            inlier_ratio=float(best["ratio"]),
            dx=float(matrix[0, 2]),
            dy=float(matrix[1, 2]),
            rotation_deg=rotation_deg,
            scale=scale,
            reason="locked",
        )
        self.last_result = result
        self.last_frame_id = frame_id
        return result


class F2ObjectTrackingMixin:
    """Camada opt-in; desligada, não altera nenhum caminho produtivo do F2."""

    def __init__(self, *args, **kwargs) -> None:
        self.rastreamento_automatico_f2 = False
        self._f2_object_tracking_settings_var = None
        self._f2_object_tracker = F2BoardObjectTracker()
        self._f2_object_tracking_override_depth = 0
        self._f2_object_tracking_last_status = {
            "enabled": False,
            "locked": False,
            "reason": "disabled",
        }
        super().__init__(*args, **kwargs)
        self.rastreamento_automatico_f2 = carregar_rastreamento_automatico_f2(
            getattr(self, "config_repository", None)
        )

    def _f2_tracking_enabled(self) -> bool:
        return bool(getattr(self, "rastreamento_automatico_f2", False))

    def _f2_tracking_reset_runtime(self) -> None:
        tracker = getattr(self, "_f2_object_tracker", None)
        if tracker is not None:
            tracker.reset()
        self._f2_object_tracking_last_status = {
            "enabled": self._f2_tracking_enabled(),
            "locked": False,
            "reason": "reset",
        }

    def _f2_tracking_prepare(self) -> bool:
        if not self._f2_tracking_enabled():
            return False
        tracker = getattr(self, "_f2_object_tracker", None)
        controller = getattr(self, "_f2_board_presence_refs", None)
        if tracker is None or controller is None:
            return False
        try:
            return bool(tracker.configure(controller))
        except Exception:
            return False

    def _f2_tracking_frame(self, frame):
        if not self._f2_tracking_enabled():
            return frame
        if not self._f2_tracking_prepare():
            tracker = getattr(self, "_f2_object_tracker", None)
            self._f2_object_tracking_last_status = {
                "enabled": True,
                "locked": False,
                "reason": getattr(tracker, "reason", "not_ready"),
            }
            return frame

        tracker = self._f2_object_tracker
        result = tracker.align(
            frame,
            frame_id=getattr(self, "camera_ultimo_frame_id", None),
        )
        self._f2_object_tracking_last_status = {
            "enabled": True,
            "locked": bool(result.locked),
            "reference": result.reference,
            "matches": int(result.matches),
            "inliers": int(result.inliers),
            "inlier_ratio": round(float(result.inlier_ratio), 4),
            "dx": round(float(result.dx), 3),
            "dy": round(float(result.dy), 3),
            "rotation_deg": round(float(result.rotation_deg), 3),
            "scale": round(float(result.scale), 5),
            "reason": result.reason,
        }
        return result.frame if result.locked else frame

    def abrir_configuracoes(self) -> None:
        self._f2_object_tracking_settings_var = tk.BooleanVar(
            master=self.root,
            value=self._f2_tracking_enabled(),
        )
        result = super().abrir_configuracoes()
        window = _find_settings_window(self.root)
        if window is not None:
            _add_tracking_setting(self, window)
        return result

    def salvar_configuracoes_sistema(
        self,
        salvar_resultados_analise: bool,
        raio_configurado_px: int | None = None,
        configuracoes_camera: dict | None = None,
    ) -> None:
        enabled = self._f2_tracking_enabled()
        variable = getattr(self, "_f2_object_tracking_settings_var", None)
        if variable is not None:
            try:
                enabled = bool(variable.get())
            except Exception:
                pass

        result = super().salvar_configuracoes_sistema(
            salvar_resultados_analise,
            raio_configurado_px,
            configuracoes_camera,
        )
        self.rastreamento_automatico_f2 = bool(enabled)
        salvar_rastreamento_automatico_f2(
            getattr(self, "config_repository", None),
            self.rastreamento_automatico_f2,
        )
        self._f2_tracking_reset_runtime()
        return result

    def abrir_tela_operacao(self) -> None:
        self._f2_tracking_reset_runtime()
        return super().abrir_tela_operacao()

    def fechar_tela_operacao(self) -> None:
        self._f2_tracking_reset_runtime()
        return super().fechar_tela_operacao()

    def _atualizar_preview_operacao(self) -> None:
        # Este é o ponto único do loop F2. Com tracking desligado, nenhum frame é
        # copiado/substituído. Ligado, o mesmo frame alinhado alimenta preview,
        # presença e análise automática daquele ciclo.
        if (
            not self._f2_tracking_enabled()
            or self._f2_object_tracking_override_depth > 0
            or getattr(self, "camera_frame_atual", None) is None
        ):
            return super()._atualizar_preview_operacao()

        original = self.camera_frame_atual
        aligned = self._f2_tracking_frame(original)
        if aligned is original:
            return super()._atualizar_preview_operacao()

        self._f2_object_tracking_override_depth += 1
        self.camera_frame_atual = aligned
        try:
            return super()._atualizar_preview_operacao()
        finally:
            self.camera_frame_atual = original
            self._f2_object_tracking_override_depth -= 1

    def disparar_inspecao_operacao(self) -> None:
        # Enter/GPIO/manual também recebem o registro quando o recurso está ativo.
        if (
            not self._f2_tracking_enabled()
            or self._f2_object_tracking_override_depth > 0
            or getattr(self, "camera_frame_atual", None) is None
        ):
            return super().disparar_inspecao_operacao()

        original = self.camera_frame_atual
        aligned = self._f2_tracking_frame(original)
        if aligned is original:
            return super().disparar_inspecao_operacao()

        self._f2_object_tracking_override_depth += 1
        self.camera_frame_atual = aligned
        try:
            return super().disparar_inspecao_operacao()
        finally:
            self.camera_frame_atual = original
            self._f2_object_tracking_override_depth -= 1
