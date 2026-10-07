from __future__ import annotations

from copy import deepcopy

import cv2
import numpy as np

from src.platform.display_mask_geometry import (
    mapear_slots_sete_segmentos_display,
)
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
    mascaras_geometria_runtime_fixa_display,
    normalizar_resolucao_display,
)
from src.platform.display_visual_rotation import (
    preparar_check_visual_display,
    preparar_frame_visual_display,
    preparar_pontos_visuais_display,
)


DISPLAY_ROI_OVERLAY_ALPHA = 0.14
DISPLAY_ROI_OVERLAY_NEUTRAL_ALPHA = 0.07
DISPLAY_ROI_OVERLAY_COLORS = {
    "on": (94, 197, 34),        # #22C55E em BGR
    "off": (68, 68, 239),       # #EF4444 em BGR
    "low_light": (21, 204, 250),# #FACC15 em BGR
    "unknown": (184, 163, 148), # #94A3B8 em BGR
}
DISPLAY_ROI_OVERLAY_LEGEND = (
    "VERDE: ACESO  •  VERMELHO: APAGADO  •  AMARELO: POUCA LUZ"
)


def _normalizar_rotacao(rotacao) -> int:
    try:
        angle = int(rotacao) % 360
    except (TypeError, ValueError):
        return 0
    return angle if angle in (0, 90, 180, 270) else 0


def _app_from_window(window):
    callback = getattr(window, "on_configure", None)
    return getattr(callback, "__self__", None)


def _config_signature(repository) -> tuple[int, int]:
    try:
        stat = repository.config_file.stat()
        return int(stat.st_mtime_ns), int(stat.st_size)
    except (AttributeError, OSError):
        return 0, 0


def _current_check_id(app) -> str:
    runtime = getattr(app, "display_check_runtime", None)
    if runtime is None:
        return ""
    try:
        current = runtime.snapshot().get("current_check")
    except Exception:
        return ""
    if not isinstance(current, dict):
        return ""
    return str(current.get("id") or "")


def _prepare_live_visual_mirror_context(
    window,
    visual_frame,
    context: dict | None,
    visual_rotation: int,
) -> dict | None:
    """Aplica o espelho visual latest-frame também com tracking desligado.

    Tracking ON e OFF diferem somente na origem geométrica das ROIs:
    - ON: geometria móvel publicada pelo tracker;
    - OFF: geometria fixa do Projeto Display.

    A leitura visual continua sendo a mesma amostra leve do frame que será
    exibido. Não participa de energia, OK/NG, debounce ou avanço de CHECK.
    """
    if not isinstance(context, dict):
        return context
    if not bool(context.get("live_luminous_only")):
        return context

    app = _app_from_window(window)
    frame_token = ("object", id(visual_frame))
    if app is not None:
        token_fn = getattr(app, "_display_auto_frame_token", None)
        if callable(token_fn):
            try:
                frame_token = token_fn(
                    getattr(app, "camera_frame_atual", visual_frame)
                )
            except Exception:
                frame_token = ("object", id(visual_frame))

    repository = (
        getattr(app, "display_project_repository", None)
        if app is not None
        else None
    )
    geometry_token = (
        "fixed",
        str(context.get("project_name") or ""),
        str(context.get("check_id") or ""),
        int(visual_rotation or 0) % 360,
        _config_signature(repository) if repository is not None else (0, 0),
    )
    if bool(context.get("tracking_active")) and app is not None:
        geometry = getattr(app, "_display_f3_tracking_live_geometry", None)
        geometry_token = ("tracked", id(geometry))

    debug = {
        "hook_active": True,
        "tracking_enabled": bool(context.get("tracking_active")),
        "frame_id": getattr(app, "camera_ultimo_frame_id", None)
        if app is not None
        else None,
        "visual_rotation": int(visual_rotation or 0) % 360,
        "stage": "fixed_visual_sampling"
        if not bool(context.get("tracking_active"))
        else "tracked_visual_sampling",
        "render_path": "",
        "geometry_present": True,
        "geometry_locked": bool(
            context.get("tracking_locked")
            or not bool(context.get("tracking_active"))
        ),
        "geometry_mask_count": len(tuple(context.get("masks") or ())),
        "context_ready": True,
        "context_mask_count": len(tuple(context.get("masks") or ())),
        "readout_mask_id_count": len(
            tuple(context.get("readout_mask_ids") or ())
        ),
        "readout_slot_count": len(
            tuple(context.get("readout_slot_mask_ids") or ())
        ),
        "error_type": "",
        "error": "",
    }

    try:
        from src.platform.display_f3_preview_clarity_fix import (
            aplicar_emissao_visual_ao_vivo_f3,
        )

        result = aplicar_emissao_visual_ao_vivo_f3(
            window,
            visual_frame,
            context,
            frame_token=frame_token,
            geometry_token=geometry_token,
        )
        if isinstance(result, dict):
            debug.update(
                {
                    "stage": "fixed_visual_sample_ready"
                    if not bool(context.get("tracking_active"))
                    else "tracked_visual_sample_ready",
                    "render_path": "fixed_latest_frame_live_visual"
                    if not bool(context.get("tracking_active"))
                    else "tracked_latest_frame_live_visual",
                    "live_visual_sample_ready": bool(
                        result.get("live_visual_sample_ready")
                    ),
                    "live_visual_sample_reason": str(
                        result.get("live_visual_sample_reason") or ""
                    ),
                    "live_visual_sampled_mask_count": int(
                        result.get("live_visual_sampled_mask_count", 0) or 0
                    ),
                    "live_visual_sample_threshold": result.get(
                        "live_visual_sample_threshold"
                    ),
                    "live_visual_sample_baseline": result.get(
                        "live_visual_sample_baseline"
                    ),
                    "live_visual_sample_peak": result.get(
                        "live_visual_sample_peak"
                    ),
                    "live_visual_sample_dynamic_range": result.get(
                        "live_visual_sample_dynamic_range"
                    ),
                    "live_visual_sample_cluster_gap": result.get(
                        "live_visual_sample_cluster_gap"
                    ),
                    "live_visual_relative_evidence_ready": bool(
                        result.get("live_visual_relative_evidence_ready")
                    ),
                    "live_visual_absolute_fallback_used": bool(
                        result.get("live_visual_absolute_fallback_used")
                    ),
                    "live_visual_strong_candidate_mask_ids": tuple(
                        str(mask_id)
                        for mask_id in (
                            result.get(
                                "live_visual_strong_candidate_mask_ids"
                            )
                            or ()
                        )
                        if str(mask_id)
                    ),
                    "live_visual_reflection_rejected_mask_ids": tuple(
                        str(mask_id)
                        for mask_id in (
                            result.get(
                                "live_visual_reflection_rejected_mask_ids"
                            )
                            or ()
                        )
                        if str(mask_id)
                    ),
                    "live_visual_mask_ids": tuple(
                        str(mask_id)
                        for mask_id in (
                            result.get("live_visual_mask_ids") or ()
                        )
                        if str(mask_id)
                    ),
                    "live_visual_frame_token": repr(
                        result.get("live_visual_frame_token")
                    ),
                    "live_visual_physical_frame_token": repr(
                        result.get("live_visual_physical_frame_token")
                    ),
                    "live_visual_same_physical_frame": bool(
                        result.get("live_visual_same_physical_frame")
                    ),
                }
            )
            if app is not None:
                app._display_f3_live_visual_mirror_debug = debug
            return result
    except Exception as exc:
        debug.update(
            {
                "stage": "fixed_visual_sample_exception",
                "render_path": "fixed_visual_context_fallback",
                "error_type": type(exc).__name__,
                "error": str(exc)[:240],
            }
        )

    if app is not None:
        app._display_f3_live_visual_mirror_debug = debug
    return context


def _overlay_context(window, visual_rotation: int):
    app = _app_from_window(window)
    if app is None:
        return None

    analysis = getattr(app, "_display_auto_last_analysis", None)
    if not isinstance(analysis, dict):
        return None

    project_name = str(analysis.get("project_name") or "")
    analysis_check_id = str(analysis.get("check_id") or "")
    current_check_id = _current_check_id(app)
    if not project_name or not current_check_id:
        return None

    # Nunca desenhe o resultado do CHECK anterior durante a troca de etapa.
    classification_valid = analysis_check_id == current_check_id

    repository = getattr(app, "display_project_repository", None)
    if repository is None:
        return None

    cache_key = (
        project_name,
        current_check_id,
        int(visual_rotation),
        _config_signature(repository),
    )
    if cache_key != getattr(window, "_display_roi_overlay_cache_key", None):
        project = repository.carregar_projeto(project_name)
        if not isinstance(project, dict):
            return None

        resolution = normalizar_resolucao_display(project.get("master_resolution"))
        if resolution is None:
            return None

        checks = list(project.get("checks", []) or [])
        check = next(
            (
                item
                for item in checks
                if isinstance(item, dict)
                and str(item.get("id") or "") == current_check_id
            ),
            None,
        )
        if not isinstance(check, dict):
            return None

        states = (
            check.get("mask_states", {})
            if isinstance(check.get("mask_states"), dict)
            else {}
        )
        effective_masks = mascaras_geometria_runtime_fixa_display(project)
        active_masks = [
            deepcopy(mask)
            for mask in effective_masks
            if isinstance(mask, dict)
            and states.get(str(mask.get("id")))
            in (DISPLAY_CHECK_STATE_ON, DISPLAY_CHECK_STATE_OFF)
        ]

        _, visual_resolution, visual_masks = preparar_check_visual_display(
            None,
            resolution,
            active_masks,
            visual_rotation,
        )
        window._display_roi_overlay_cache_key = cache_key
        window._display_roi_overlay_resolution = tuple(visual_resolution)
        window._display_roi_overlay_masks = tuple(visual_masks)

    classifications = {}
    if classification_valid:
        effective = analysis.get("effective_classifications")
        if isinstance(effective, dict):
            classifications = {
                str(mask_id): str(state or "unknown").strip().lower()
                for mask_id, state in effective.items()
                if str(mask_id)
            }
        else:
            for item in analysis.get("mask_results", []) or []:
                if not isinstance(item, dict):
                    continue
                mask_id = str(item.get("mask_id") or "")
                if mask_id:
                    classifications[mask_id] = str(
                        item.get("classified") or "unknown"
                    )

    return {
        "resolution": getattr(window, "_display_roi_overlay_resolution", None),
        "masks": getattr(window, "_display_roi_overlay_masks", ()),
        "classifications": classifications,
        "effective_classifications": dict(classifications),
        "failed_mask_ids": tuple(
            sorted(
                str(mask_id)
                for mask_id in (
                    analysis.get("effective_failed_mask_ids") or ()
                )
                if str(mask_id)
            )
        ) if classification_valid else (),
        "effective_failed_mask_ids": tuple(
            sorted(
                str(mask_id)
                for mask_id in (
                    analysis.get("effective_failed_mask_ids") or ()
                )
                if str(mask_id)
            )
        ) if classification_valid else (),
        "effective_confirmed_failed_mask_ids": tuple(
            sorted(
                str(mask_id)
                for mask_id in (
                    analysis.get("effective_confirmed_failed_mask_ids") or ()
                )
                if str(mask_id)
            )
        ) if classification_valid else (),
        "effective_validating_mask_ids": tuple(
            sorted(
                str(mask_id)
                for mask_id in (
                    analysis.get("effective_validating_mask_ids") or ()
                )
                if str(mask_id)
            )
        ) if classification_valid else (),
        "ui_mask_authority": (
            str(analysis.get("ui_mask_authority") or "")
            if classification_valid
            else ""
        ),
    }


def montar_contexto_overlay_snapshot_display_f3(
    repository,
    project_name: str,
    check_id: str,
    analysis: dict | None,
    visual_rotation: int,
    tracking_geometry: dict | None = None,
) -> dict | None:
    """Monta contexto visual determinístico para um snapshot F3.

    Quando D-072 fornece geometria rastreada, frame, máscaras e classificação
    permanecem no mesmo espaço temporal do resultado. Sem geometria explícita,
    preserva o comportamento fixo/canônico usado pelo tracking OFF e pelo DEBUG.
    """
    if repository is None or not project_name or not check_id:
        return None
    try:
        project = repository.carregar_projeto(str(project_name))
    except Exception:
        project = None
    if not isinstance(project, dict):
        return None

    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    if resolution is None:
        return None

    check = next(
        (
            item
            for item in (project.get("checks", []) or [])
            if isinstance(item, dict)
            and str(item.get("id") or "") == str(check_id)
        ),
        None,
    )
    if not isinstance(check, dict):
        return None

    states = (
        check.get("mask_states", {})
        if isinstance(check.get("mask_states"), dict)
        else {}
    )
    expected_states = {
        str(mask_id): str(state or "").strip().lower()
        for mask_id, state in states.items()
        if str(state or "").strip().lower()
        in (DISPLAY_CHECK_STATE_ON, DISPLAY_CHECK_STATE_OFF)
    }
    rotation = _normalizar_rotacao(visual_rotation)

    effective_masks = mascaras_geometria_runtime_fixa_display(project)
    readout_mask_ids = tuple(
        str(mask.get("id") or "")
        for mask in effective_masks
        if isinstance(mask, dict) and str(mask.get("id") or "")
    )

    geometry = (
        tracking_geometry
        if isinstance(tracking_geometry, dict)
        and bool(tracking_geometry.get("locked"))
        else None
    )
    tracking_snapshot_used = False
    visual_board = []
    if isinstance(geometry, dict):
        raw_resolution = geometry.get("resolution")
        if (
            isinstance(raw_resolution, (list, tuple))
            and len(raw_resolution) >= 2
        ):
            raw_resolution = (
                max(1, int(raw_resolution[0])),
                max(1, int(raw_resolution[1])),
            )
        else:
            raw_resolution = resolution

        tracked_masks = [
            deepcopy(mask)
            for mask in (geometry.get("masks") or ())
            if isinstance(mask, dict)
        ]
        if tracked_masks:
            _, visual_resolution, visual_masks = preparar_check_visual_display(
                None,
                raw_resolution,
                tracked_masks,
                rotation,
            )
            visual_board = preparar_pontos_visuais_display(
                geometry.get("board_points") or (),
                int(raw_resolution[0]),
                int(raw_resolution[1]),
                rotation,
            )
            tracking_snapshot_used = True

    readout_slot_mask_ids = ()
    if not tracking_snapshot_used:
        # D-074 / tracking OFF: o VISOR precisa usar a MESMA topologia física
        # A..G da geometria fixa exibida na câmera. A ordem numérica dos
        # MASK_IDs não representa posição de segmento e pode colocar uma falha
        # horizontal em uma barra vertical do visor.
        all_fixed_masks = [
            deepcopy(mask)
            for mask in effective_masks
            if isinstance(mask, dict)
            and str(mask.get("id") or "")
        ]
        try:
            _, _, readout_visual_masks = preparar_check_visual_display(
                None,
                resolution,
                all_fixed_masks,
                rotation,
            )
            mapped_slots = mapear_slots_sete_segmentos_display(
                readout_visual_masks,
                digit_count=4,
            )
            if len(mapped_slots) == 28 and len(set(mapped_slots)) == 28:
                readout_slot_mask_ids = tuple(
                    str(mask_id)
                    for mask_id in mapped_slots
                    if str(mask_id)
                )
        except Exception:
            readout_slot_mask_ids = ()

        active_masks = [
            deepcopy(mask)
            for mask in effective_masks
            if isinstance(mask, dict)
            and states.get(str(mask.get("id")))
            in (DISPLAY_CHECK_STATE_ON, DISPLAY_CHECK_STATE_OFF)
        ]
        _, visual_resolution, visual_masks = preparar_check_visual_display(
            None,
            resolution,
            active_masks,
            rotation,
        )

    classifications = {}
    if isinstance(analysis, dict):
        effective = analysis.get("effective_classifications")
        if isinstance(effective, dict):
            classifications = {
                str(mask_id): str(state or "unknown").strip().lower()
                for mask_id, state in effective.items()
                if str(mask_id)
            }
        else:
            for item in analysis.get("mask_results", []) or []:
                if not isinstance(item, dict):
                    continue
                mask_id = str(item.get("mask_id") or "")
                if mask_id:
                    classifications[mask_id] = str(
                        item.get("classified") or "unknown"
                    ).strip().lower()

    failed = (
        tuple(
            sorted(
                str(mask_id)
                for mask_id in (
                    (analysis or {}).get("effective_failed_mask_ids") or ()
                )
                if str(mask_id)
            )
        )
        if isinstance(analysis, dict)
        else ()
    )
    confirmed = (
        tuple(
            sorted(
                str(mask_id)
                for mask_id in (
                    (analysis or {}).get(
                        "effective_confirmed_failed_mask_ids"
                    )
                    or ()
                )
                if str(mask_id)
            )
        )
        if isinstance(analysis, dict)
        else ()
    )
    validating = (
        tuple(
            sorted(
                str(mask_id)
                for mask_id in (
                    (analysis or {}).get("effective_validating_mask_ids") or ()
                )
                if str(mask_id)
            )
        )
        if isinstance(analysis, dict)
        else ()
    )
    on_ids = tuple(
        sorted(
            mask_id
            for mask_id, state in classifications.items()
            if state == DISPLAY_CHECK_STATE_ON
        )
    )

    return {
        "resolution": tuple(visual_resolution),
        "masks": tuple(deepcopy(visual_masks)),
        "board_points": tuple(deepcopy(visual_board)),
        "classifications": classifications,
        "effective_classifications": dict(classifications),
        "expected_states": expected_states,
        "failed_mask_ids": failed,
        "effective_failed_mask_ids": failed,
        "effective_confirmed_failed_mask_ids": confirmed,
        "effective_validating_mask_ids": validating,
        "ui_mask_authority": (
            str((analysis or {}).get("ui_mask_authority") or "")
            if isinstance(analysis, dict)
            else ""
        ),
        "project_name": str(project_name),
        "check_id": str(check_id),
        "visual_rotation": rotation,
        "intermittent": bool(check.get("intermittent", False)),
        "readout_mask_ids": readout_mask_ids,
        # Somente tracking OFF recebe o mapa físico fixo nesta etapa.
        # Tracking ON permanece exatamente com o contrato anterior.
        "readout_slot_mask_ids": readout_slot_mask_ids,
        "tracking_active": bool(tracking_snapshot_used),
        "tracking_locked": bool(tracking_snapshot_used),
        "tracking_reference": (
            str(geometry.get("reference") or "")
            if tracking_snapshot_used
            else ""
        ),
        "tracking_space": (
            str(geometry.get("geometry_space") or "")
            if tracking_snapshot_used
            else ""
        ),
        "snapshot_geometry_source": (
            "tracking_geometry_snapshot"
            if tracking_snapshot_used
            else "fixed_project_geometry"
        ),
        # A evidência terminal não volta a amostrar brilho. As cores abaixo vêm
        # diretamente da mesma análise que decidiu o NG.
        "live_luminous_only": bool(classifications),
        "live_visual_sample_ready": bool(classifications),
        "live_visual_classifications": dict(classifications),
        "live_visual_mask_ids": on_ids,
        "luminous_mask_ids": on_ids,
        "has_any_on": bool(on_ids),
    }

def _scaled_polygon(mask: dict, sx: float, sy: float):
    kind = str(mask.get("type") or "").lower()
    if kind == "polygon":
        points = mask.get("points", []) or []
        if len(points) < 3:
            return None
        return np.array(
            [[round(float(p[0]) * sx), round(float(p[1]) * sy)] for p in points],
            dtype=np.int32,
        )

    if kind == "segment":
        try:
            rect = (
                (float(mask.get("cx", 0)), float(mask.get("cy", 0))),
                (
                    max(1.0, float(mask.get("width", 1))),
                    max(1.0, float(mask.get("height", 1))),
                ),
                float(mask.get("angle", 0.0) or 0.0),
            )
            points = cv2.boxPoints(rect)
        except (TypeError, ValueError):
            return None
        points[:, 0] *= float(sx)
        points[:, 1] *= float(sy)
        return np.rint(points).astype(np.int32)

    if kind == "rectangle":
        x = float(mask.get("x", 0)) * sx
        y = float(mask.get("y", 0)) * sy
        width = float(mask.get("width", 0)) * sx
        height = float(mask.get("height", 0)) * sy
        return np.array(
            [
                [round(x), round(y)],
                [round(x + width), round(y)],
                [round(x + width), round(y + height)],
                [round(x), round(y + height)],
            ],
            dtype=np.int32,
        )

    return None


def renderizar_overlay_rois_display_f3(frame, context):
    """Desenha somente uma cópia visual leve; nunca altera o frame da câmera."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return frame
    if not isinstance(context, dict):
        return frame.copy()

    resolution = context.get("resolution")
    masks = tuple(context.get("masks") or ())
    if (
        not isinstance(resolution, (list, tuple))
        or len(resolution) < 2
        or not masks
    ):
        return frame.copy()

    source_width = max(1, int(resolution[0]))
    source_height = max(1, int(resolution[1]))
    frame_height, frame_width = frame.shape[:2]
    sx = frame_width / float(source_width)
    sy = frame_height / float(source_height)
    classifications = dict(context.get("classifications") or {})

    result = frame.copy()
    tint = result.copy()

    for mask in masks:
        if not isinstance(mask, dict):
            continue
        state = classifications.get(str(mask.get("id") or ""), "unknown")
        color = DISPLAY_ROI_OVERLAY_COLORS.get(
            state,
            DISPLAY_ROI_OVERLAY_COLORS["unknown"],
        )
        kind = str(mask.get("type") or "").lower()

        if kind == "circle":
            center = (
                int(round(float(mask.get("cx", 0)) * sx)),
                int(round(float(mask.get("cy", 0)) * sy)),
            )
            axes = (
                max(1, int(round(float(mask.get("radius", 1)) * sx))),
                max(1, int(round(float(mask.get("radius", 1)) * sy))),
            )
            cv2.ellipse(tint, center, axes, 0, 0, 360, color, -1, cv2.LINE_AA)
        else:
            polygon = _scaled_polygon(mask, sx, sy)
            if polygon is not None and len(polygon) >= 3:
                cv2.fillPoly(tint, [polygon], color, lineType=cv2.LINE_AA)

    # Fora das ROIs, tint == result; portanto o blend não modifica a imagem.
    # ROIs neutras recebem ainda menos tinta para não competir com o display.
    colored = any(
        classifications.get(str(mask.get("id") or ""), "unknown") != "unknown"
        for mask in masks
        if isinstance(mask, dict)
    )
    alpha = DISPLAY_ROI_OVERLAY_ALPHA if colored else DISPLAY_ROI_OVERLAY_NEUTRAL_ALPHA
    result = cv2.addWeighted(tint, alpha, result, 1.0 - alpha, 0.0)

    thickness = max(1, int(round(min(frame_width, frame_height) / 480.0)))
    for mask in masks:
        if not isinstance(mask, dict):
            continue
        state = classifications.get(str(mask.get("id") or ""), "unknown")
        color = DISPLAY_ROI_OVERLAY_COLORS.get(
            state,
            DISPLAY_ROI_OVERLAY_COLORS["unknown"],
        )
        kind = str(mask.get("type") or "").lower()
        if kind == "circle":
            center = (
                int(round(float(mask.get("cx", 0)) * sx)),
                int(round(float(mask.get("cy", 0)) * sy)),
            )
            axes = (
                max(1, int(round(float(mask.get("radius", 1)) * sx))),
                max(1, int(round(float(mask.get("radius", 1)) * sy))),
            )
            cv2.ellipse(
                result,
                center,
                axes,
                0,
                0,
                360,
                color,
                thickness,
                cv2.LINE_AA,
            )
        else:
            polygon = _scaled_polygon(mask, sx, sy)
            if polygon is not None and len(polygon) >= 3:
                cv2.polylines(
                    result,
                    [polygon],
                    True,
                    color,
                    thickness,
                    cv2.LINE_AA,
                )

    return result


def instalar_overlay_rois_ao_vivo_display_f3() -> None:
    """Estende somente a janela Display/F3; o preview e a análise F2 ficam intactos."""
    import src.platform.display_production_f3_window as window_module

    cls = window_module.DisplayProductionF3Window
    if getattr(cls, "_odin_display_live_roi_overlay", False):
        return

    original_update = cls.update_camera_preview

    def update_camera_preview(self, frame, visual_rotation: int = 0) -> bool:
        if bool(getattr(self, "_display_ng_evidence_frozen", False)):
            # A aquisição física continua fora da janela, mas o canvas permanece
            # exatamente no frame que confirmou o NG.
            return True
        if frame is None or getattr(frame, "size", 0) == 0:
            return original_update(self, frame, visual_rotation=visual_rotation)

        rotation = _normalizar_rotacao(visual_rotation)
        self.visual_rotation = rotation
        visual_frame = preparar_frame_visual_display(frame, rotation)
        if visual_frame is None or getattr(visual_frame, "size", 0) == 0:
            return original_update(self, frame, visual_rotation=visual_rotation)

        context = _overlay_context(self, rotation)
        context = _prepare_live_visual_mirror_context(
            self,
            visual_frame,
            context,
            rotation,
        )

        # O visor recebe exatamente o contexto já amostrado do mesmo frame que
        # será desenhado na câmera. Assim tracking OFF não volta ao caminho cinza
        # condicionado ao power gate.
        if isinstance(context, dict) and bool(
            context.get("live_luminous_only")
        ):
            app = _app_from_window(self)
            try:
                self.set_display_readout_context(context)
                readout = getattr(self, "_display_readout_context", None)
                if app is not None:
                    debug = getattr(
                        app,
                        "_display_f3_live_visual_mirror_debug",
                        None,
                    )
                    if isinstance(debug, dict):
                        debug.update(
                            {
                                "readout_context_ready": isinstance(
                                    readout,
                                    dict,
                                ),
                                "readout_mask_slot_count": (
                                    len(tuple(readout.get("mask_slots") or ()))
                                    if isinstance(readout, dict)
                                    else 0
                                ),
                                "readout_live_visual_mask_ids": (
                                    tuple(
                                        sorted(
                                            str(mask_id)
                                            for mask_id in (
                                                readout.get(
                                                    "live_visual_mask_ids"
                                                )
                                                or ()
                                            )
                                            if str(mask_id)
                                        )
                                    )
                                    if isinstance(readout, dict)
                                    else ()
                                ),
                            }
                        )
            except Exception as exc:
                if app is not None:
                    debug = getattr(
                        app,
                        "_display_f3_live_visual_mirror_debug",
                        None,
                    )
                    if isinstance(debug, dict):
                        debug.update(
                            {
                                "readout_context_ready": False,
                                "readout_error_type": type(exc).__name__,
                                "readout_error": str(exc)[:240],
                            }
                        )

        try:
            self._display_last_overlay_context = deepcopy(context)
        except Exception:
            self._display_last_overlay_context = context
        decorated = renderizar_overlay_rois_display_f3(visual_frame, context)

        if self.preview_legend.cget("text") != DISPLAY_ROI_OVERLAY_LEGEND:
            self.preview_legend.configure(
                text=DISPLAY_ROI_OVERLAY_LEGEND,
                fg=self.PREVIEW_MUTED,
            )

        height, width = decorated.shape[:2]
        rendered = self.update_preview(decorated, leds=())
        app = _app_from_window(self)
        if app is not None:
            debug = getattr(
                app,
                "_display_f3_live_visual_mirror_debug",
                None,
            )
            if isinstance(debug, dict):
                debug["update_preview_rendered"] = bool(rendered)
                if bool(context and context.get("live_luminous_only")):
                    debug["stage"] = (
                        "fixed_live_mirror_rendered"
                        if not bool(context.get("tracking_active"))
                        else "tracked_live_mirror_rendered"
                    )
        if rendered:
            detail = f"Câmera {int(width)}x{int(height)} • Visual {int(rotation)}°"
            if not self._camera_ready or self._camera_detail != detail:
                self.show_camera_ready(width, height, rotation)
        return rendered

    cls.update_camera_preview = update_camera_preview
    cls._odin_display_live_roi_overlay = True


instalar_overlay_rois_ao_vivo_display_f3()
