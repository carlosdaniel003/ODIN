from __future__ import annotations

"""Overlay visual do rastreamento automático na câmera ao vivo da Produção F2.

Contrato visual desta camada:
- tracking DESLIGADO: não altera a Produção F2 existente;
- tracking LIGADO, sem lock: frame bruto, sem máscaras fixas e sem retângulo legado;
- tracking LIGADO, com lock: mostra somente o contorno salvo da placa e as ROIs
  transformadas para a posição física encontrada no frame bruto;
- análise automática + tracking: a análise continua no frame alinhado/canônico e
  as cores ACESO/APAGADO/POUCA LUZ são aplicadas somente às ROIs rastreadas.

Nenhuma transformação visual é gravada nas referências nem nas ROIs do projeto.
"""

import cv2
import numpy as np

from src.core.roi_geometry import TIPO_ROI_SEGMENTO, normalizar_tipo_roi, pontos_segmento
from src.models.led_selection import LedSelection
from src.platform.f2_board_presence_references import (
    F2_BOARD_PRESENCE_EMPTY,
    F2_BOARD_PRESENCE_UNAVAILABLE,
    F2_BOARD_REF_BOARD_OFF,
    F2_BOARD_REF_BOARD_ON,
)
from src.platform.f2_board_shape_editor import carregar_contorno_placa_leds
from src.platform.f2_object_tracking import F2ObjectTrackingMixin
from src.platform.segment_display_operation_window import renderizar_overlay_rois_f2


F2_TRACKING_BOARD_OUTLINE_BGR = (238, 211, 34)  # ciano no BGR
F2_TRACKING_BOARD_SHADOW_BGR = (15, 23, 42)
F2_TRACKING_BOARD_OUTLINE_THICKNESS = 3
F2_TRACKING_BOARD_SHADOW_THICKNESS = 7
F2_TRACKING_LED_OUTLINE_BGR = (248, 189, 56)
F2_TRACKING_LED_SHADOW_BGR = (15, 23, 42)
F2_TRACKING_LED_OUTLINE_THICKNESS = 2
F2_TRACKING_LED_SHADOW_THICKNESS = 4
F2_TRACKING_ONLY_LEGEND = "CIANO: CONTORNO DA PLACA  •  AZUL: MÁSCARAS RASTREADAS"

_PATCH_INSTALADO = False


def inverter_matriz_rastreamento_f2(matrix) -> np.ndarray | None:
    """Converte a matriz CURRENT->REFERÊNCIA em REFERÊNCIA->CURRENT."""
    if matrix is None:
        return None
    try:
        affine = np.asarray(matrix, dtype=np.float32).reshape(2, 3)
        return cv2.invertAffineTransform(affine).astype(np.float32)
    except Exception:
        return None


def transformar_pontos_rastreamento_f2(points, matrix) -> np.ndarray:
    """Aplica uma transformação afim 2x3 a uma coleção Nx2."""
    values = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    if values.size == 0:
        return values.reshape(0, 2)
    affine = np.asarray(matrix, dtype=np.float32).reshape(2, 3)
    homogeneous = np.concatenate(
        [values, np.ones((len(values), 1), dtype=np.float32)],
        axis=1,
    )
    return homogeneous @ affine.T


def _adaptar_roi_base(roi, width: int, height: int):
    try:
        base_w = int(getattr(roi, "largura_base", 0) or 0)
        base_h = int(getattr(roi, "altura_base", 0) or 0)
        if base_w > 0 and base_h > 0 and (base_w != width or base_h != height):
            adaptar = getattr(roi, "adaptar_para_resolucao", None)
            if callable(adaptar):
                return adaptar(
                    int(width),
                    int(height),
                    raio_minimo=1,
                    raio_maximo=max(int(width), int(height)),
                )
    except Exception:
        pass
    return roi


def transformar_roi_para_frame_atual_f2(
    roi,
    reference_to_current,
    width: int,
    height: int,
):
    """Transforma uma ROI canônica para a posição rastreada no frame bruto."""
    roi = _adaptar_roi_base(roi, int(width), int(height))
    affine = np.asarray(reference_to_current, dtype=np.float32).reshape(2, 3)
    tipo = normalizar_tipo_roi(getattr(roi, "tipo_roi", None))

    if tipo == TIPO_ROI_SEGMENTO:
        try:
            polygon = np.asarray(pontos_segmento(roi), dtype=np.float32).reshape(-1, 2)
        except Exception:
            return None
        if len(polygon) < 3:
            return None
        transformed = transformar_pontos_rastreamento_f2(polygon, affine)
        center = np.mean(transformed, axis=0)
        relative = [
            (float(point[0] - center[0]), float(point[1] - center[1]))
            for point in transformed
        ]
        try:
            return LedSelection(
                id=str(getattr(roi, "id", "ROI")),
                centro_x=int(round(float(center[0]))),
                centro_y=int(round(float(center[1]))),
                raio=2,
                tipo_roi=TIPO_ROI_SEGMENTO,
                pontos_segmento_livre=relative,
            )
        except Exception:
            return None

    try:
        center = np.asarray(
            [[float(getattr(roi, "centro_x")), float(getattr(roi, "centro_y"))]],
            dtype=np.float32,
        )
        transformed_center = transformar_pontos_rastreamento_f2(center, affine)[0]
        a = float(affine[0, 0])
        c = float(affine[1, 0])
        scale = max(0.05, float((a * a + c * c) ** 0.5))
        radius = max(1, int(round(float(getattr(roi, "raio", 1) or 1) * scale)))
        return LedSelection(
            id=str(getattr(roi, "id", "ROI")),
            centro_x=int(round(float(transformed_center[0]))),
            centro_y=int(round(float(transformed_center[1]))),
            raio=radius,
        )
    except Exception:
        return None


def transformar_rois_para_frame_atual_f2(
    rois,
    reference_to_current,
    width: int,
    height: int,
) -> list[LedSelection]:
    transformed: list[LedSelection] = []
    for roi in tuple(rois or ()):
        item = transformar_roi_para_frame_atual_f2(
            roi,
            reference_to_current,
            width,
            height,
        )
        if item is not None:
            transformed.append(item)
    return transformed


def desenhar_contorno_rastreado_f2(frame, board_shape) -> object:
    """Desenha somente o contorno físico salvo da placa em uma cópia da preview."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return frame
    result = frame.copy()
    for roi in tuple(board_shape or ()):
        tipo = normalizar_tipo_roi(getattr(roi, "tipo_roi", None))
        try:
            if tipo == TIPO_ROI_SEGMENTO:
                points = np.rint(np.asarray(pontos_segmento(roi))).astype(np.int32)
                if len(points) < 3:
                    continue
                polygon = points.reshape((-1, 1, 2))
                cv2.polylines(
                    result,
                    [polygon],
                    True,
                    F2_TRACKING_BOARD_SHADOW_BGR,
                    F2_TRACKING_BOARD_SHADOW_THICKNESS,
                    cv2.LINE_AA,
                )
                cv2.polylines(
                    result,
                    [polygon],
                    True,
                    F2_TRACKING_BOARD_OUTLINE_BGR,
                    F2_TRACKING_BOARD_OUTLINE_THICKNESS,
                    cv2.LINE_AA,
                )
                continue

            center = (
                int(getattr(roi, "centro_x", 0)),
                int(getattr(roi, "centro_y", 0)),
            )
            radius = max(2, int(getattr(roi, "raio", 2) or 2))
            cv2.circle(
                result,
                center,
                radius,
                F2_TRACKING_BOARD_SHADOW_BGR,
                F2_TRACKING_BOARD_SHADOW_THICKNESS,
                cv2.LINE_AA,
            )
            cv2.circle(
                result,
                center,
                radius,
                F2_TRACKING_BOARD_OUTLINE_BGR,
                F2_TRACKING_BOARD_OUTLINE_THICKNESS,
                cv2.LINE_AA,
            )
        except Exception:
            continue
    return result


def desenhar_mascaras_rastreadas_neutras_f2(frame, leds) -> object:
    """Desenha somente as ROIs móveis quando tracking está ativo sem auto análise."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return frame
    result = frame.copy()
    for led in tuple(leds or ()):
        tipo = normalizar_tipo_roi(getattr(led, "tipo_roi", None))
        try:
            if tipo == TIPO_ROI_SEGMENTO:
                points = np.rint(np.asarray(pontos_segmento(led))).astype(np.int32)
                if len(points) < 3:
                    continue
                polygon = points.reshape((-1, 1, 2))
                cv2.polylines(
                    result,
                    [polygon],
                    True,
                    F2_TRACKING_LED_SHADOW_BGR,
                    F2_TRACKING_LED_SHADOW_THICKNESS,
                    cv2.LINE_AA,
                )
                cv2.polylines(
                    result,
                    [polygon],
                    True,
                    F2_TRACKING_LED_OUTLINE_BGR,
                    F2_TRACKING_LED_OUTLINE_THICKNESS,
                    cv2.LINE_AA,
                )
                continue

            center = (
                int(getattr(led, "centro_x", 0)),
                int(getattr(led, "centro_y", 0)),
            )
            radius = max(2, int(getattr(led, "raio", 2) or 2))
            cv2.circle(
                result,
                center,
                radius,
                F2_TRACKING_LED_SHADOW_BGR,
                F2_TRACKING_LED_SHADOW_THICKNESS,
                cv2.LINE_AA,
            )
            cv2.circle(
                result,
                center,
                radius,
                F2_TRACKING_LED_OUTLINE_BGR,
                F2_TRACKING_LED_OUTLINE_THICKNESS,
                cv2.LINE_AA,
            )
        except Exception:
            continue
    return result


def _carregar_geometria_visual(app):
    tracker = getattr(app, "_f2_object_tracker", None)
    controller = getattr(app, "_f2_board_presence_refs", None)
    if tracker is None or controller is None or not getattr(tracker, "ready", False):
        return (), ()

    signature = getattr(tracker, "signature", None)
    cache = getattr(app, "_f2_tracking_visual_geometry_cache", None)
    if isinstance(cache, dict) and cache.get("signature") == signature:
        return tuple(cache.get("shape", ())), tuple(cache.get("leds", ()))

    project = str(getattr(tracker, "project", "") or controller.project_name() or "").strip()
    width = int(getattr(tracker, "width", 0) or 0)
    height = int(getattr(tracker, "height", 0) or 0)
    if not project or width <= 0 or height <= 0:
        return (), ()

    shape = tuple(carregar_contorno_placa_leds(controller, project, width, height) or ())
    repository = getattr(app, "config_repository", None)
    getter = getattr(repository, "carregar_leds_fixos", None)
    leds = []
    if callable(getter):
        try:
            leds = list(getter(projeto=project) or ())
        except TypeError:
            try:
                leds = list(getter(project) or ())
            except Exception:
                leds = []
        except Exception:
            leds = []
    leds = tuple(_adaptar_roi_base(item, width, height) for item in leds)

    app._f2_tracking_visual_geometry_cache = {
        "signature": signature,
        "shape": shape,
        "leds": leds,
    }
    return shape, leds


def preparar_preview_rastreamento_f2(app, raw_frame):
    """Retorna (frame_com_contorno, leds_transformados) ou None sem lock válido."""
    if raw_frame is None or getattr(raw_frame, "size", 0) == 0:
        return None
    if not bool(getattr(app, "_f2_tracking_enabled", lambda: False)()):
        return None

    status = getattr(app, "_f2_object_tracking_last_status", {})
    tracker = getattr(app, "_f2_object_tracker", None)
    if (
        not isinstance(status, dict)
        or not bool(status.get("locked"))
        or tracker is None
        or getattr(tracker, "last_matrix", None) is None
    ):
        return None

    reference_to_current = inverter_matriz_rastreamento_f2(tracker.last_matrix)
    if reference_to_current is None:
        return None

    shape, leds = _carregar_geometria_visual(app)
    if not shape:
        return None

    height, width = raw_frame.shape[:2]
    tracked_shape = transformar_rois_para_frame_atual_f2(
        shape,
        reference_to_current,
        width,
        height,
    )
    tracked_leds = transformar_rois_para_frame_atual_f2(
        leds,
        reference_to_current,
        width,
        height,
    )
    if not tracked_shape:
        return None

    decorated = desenhar_contorno_rastreado_f2(raw_frame, tracked_shape)
    app._f2_object_tracking_visual_last = {
        "locked": True,
        "board_shapes": len(tracked_shape),
        "led_masks": len(tracked_leds),
        "reference": status.get("reference", ""),
        "dx": status.get("dx", 0.0),
        "dy": status.get("dy", 0.0),
        "rotation_deg": status.get("rotation_deg", 0.0),
        "scale": status.get("scale", 1.0),
    }
    return decorated, tracked_leds


def _classificar_presenca_tracking_f2(app, raw_frame) -> str:
    controller = getattr(app, "_f2_board_presence_refs", None)
    if controller is None:
        return F2_BOARD_PRESENCE_UNAVAILABLE
    try:
        presence, _scores = controller.classify(raw_frame)
        return str(presence or "unknown")
    except Exception:
        return "unknown"


def _publicar_status_placa_tracking_f2(app, raw_frame, presence: str | None = None) -> str:
    """Reutiliza o mesmo STATUS DA PLACA do auto, sem ligar análise automática."""
    window = getattr(app, "operacao_window", None)
    setter = getattr(window, "set_board_presence_status", None)
    if not callable(setter):
        return "unknown"

    # Quando a análise automática está ativa ela continua sendo a autoridade do
    # status produtivo, inclusive JÁ ANALISADA/OK/NG. O tracking não sobrescreve.
    auto_enabled = bool(getattr(app, "_f2_auto_enabled", lambda: False)())
    if auto_enabled:
        return str(presence or "auto")

    physical_presence = str(
        presence if presence is not None else _classificar_presenca_tracking_f2(app, raw_frame)
    )
    tracking_status = getattr(app, "_f2_object_tracking_last_status", {})
    locked = isinstance(tracking_status, dict) and bool(tracking_status.get("locked"))

    if physical_presence == F2_BOARD_PRESENCE_EMPTY:
        visual_status = "empty_support"
    elif physical_presence == F2_BOARD_PRESENCE_UNAVAILABLE:
        visual_status = "unavailable"
    elif locked:
        reference = str(tracking_status.get("reference") or "")
        if reference == F2_BOARD_REF_BOARD_ON:
            visual_status = "board_on"
        elif reference == F2_BOARD_REF_BOARD_OFF:
            visual_status = "board_off"
        else:
            visual_status = "unknown"
    else:
        visual_status = "unknown"

    try:
        setter(visual_status, enabled=True)
    except Exception:
        pass
    return visual_status


def _configurar_legenda_tracking_f2(app) -> None:
    if bool(getattr(app, "_f2_auto_enabled", lambda: False)()):
        return
    label = getattr(getattr(app, "operacao_window", None), "preview_legend", None)
    if label is None:
        return
    try:
        label.configure(text=F2_TRACKING_ONLY_LEGEND)
    except Exception:
        pass


def _limpar_status_tracking_se_desligado(app) -> None:
    if bool(getattr(app, "_f2_auto_enabled", lambda: False)()):
        return
    setter = getattr(getattr(app, "operacao_window", None), "set_board_presence_status", None)
    if callable(setter):
        try:
            setter(None, enabled=False)
        except Exception:
            pass


def instalar_overlay_visual_rastreamento_f2() -> None:
    """Publica somente geometria móvel no tracking; desligado preserva o F2 atual."""
    global _PATCH_INSTALADO
    if _PATCH_INSTALADO:
        return

    current = F2ObjectTrackingMixin._atualizar_preview_operacao
    if bool(getattr(current, "_odin_f2_tracking_visual_overlay", False)):
        _PATCH_INSTALADO = True
        return
    previous = current

    def atualizar_preview_com_geometria_rastreada(self):
        tracking_enabled = bool(getattr(self, "_f2_tracking_enabled", lambda: False)())
        if not tracking_enabled or getattr(self, "camera_frame_atual", None) is None:
            if not tracking_enabled:
                _limpar_status_tracking_se_desligado(self)
            return previous(self)

        window = getattr(self, "operacao_window", None)
        original_update = getattr(window, "update_preview", None)
        if window is None or not callable(original_update):
            return previous(self)

        raw_frame = self.camera_frame_atual
        _configurar_legenda_tracking_f2(self)

        def update_preview_tracking_visual(_frame, _leds=()):
            # A classificação de presença serve apenas à apresentação. EMPTY tem
            # prioridade para nunca deixar uma geometria antiga/falsa sobre suporte vazio.
            presence = _classificar_presenca_tracking_f2(self, raw_frame)
            _publicar_status_placa_tracking_f2(self, raw_frame, presence)

            tracking_status = getattr(self, "_f2_object_tracking_last_status", {})
            locked = isinstance(tracking_status, dict) and bool(tracking_status.get("locked"))
            if not locked or presence == F2_BOARD_PRESENCE_EMPTY:
                self._f2_object_tracking_visual_last = {
                    "locked": False,
                    "board_shapes": 0,
                    "led_masks": 0,
                    "presence": presence,
                }
                # Contrato principal: tracking ativo SEM lock nunca mostra as
                # máscaras canônicas fixas nem o retângulo pontilhado legado.
                return original_update(raw_frame, leds=())

            try:
                visual = preparar_preview_rastreamento_f2(self, raw_frame)
            except Exception:
                visual = None
            if visual is None:
                return original_update(raw_frame, leds=())

            decorated, tracked_leds = visual
            auto_enabled = bool(getattr(self, "_f2_auto_enabled", lambda: False)())
            states = dict(getattr(self, "_f2_auto_last_states", {}) or {})
            if auto_enabled and states:
                # Reaproveita exatamente a semântica de cores do F2 automático,
                # mas sobre ROIs já transformadas para acompanhar a placa real.
                decorated = renderizar_overlay_rois_f2(
                    decorated,
                    tracked_leds,
                    states,
                )
            else:
                decorated = desenhar_mascaras_rastreadas_neutras_f2(
                    decorated,
                    tracked_leds,
                )

            # leds=() é intencional. A janela base não deve redesenhar ROIs fixas
            # nem gerar o retângulo pontilhado calculado pelos limites das máscaras.
            return original_update(decorated, leds=())

        # Intercepta apenas a publicação visual desta iteração. O frame alinhado
        # continua dentro de camera_frame_atual enquanto presença/LEDs são julgados.
        try:
            window.update_preview = update_preview_tracking_visual
            return previous(self)
        finally:
            window.update_preview = original_update

    atualizar_preview_com_geometria_rastreada._odin_f2_tracking_visual_overlay = True
    atualizar_preview_com_geometria_rastreada._odin_f2_tracking_visual_overlay_base = previous
    F2ObjectTrackingMixin._atualizar_preview_operacao = atualizar_preview_com_geometria_rastreada
    _PATCH_INSTALADO = True
