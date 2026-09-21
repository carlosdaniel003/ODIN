from __future__ import annotations

"""Preview visual simples e legível para o Display F3.

Esta camada altera somente a apresentação das máscaras sobre a câmera do F3.
A classificação, a decisão OK/NG, o debounce e o fluxo produtivo continuam sob
as autoridades já instaladas.

Regra visual final:
- verde: segmento classificado como ACESO e coerente com o CHECK;
- vermelho: segmento classificado como APAGADO e coerente com o CHECK;
- amarelo: POUCA LUZ ou divergência ACESO/APAGADO contra o CHECK;
- divergência confirmada recebe amarelo muito mais forte que as máscaras normais;
- nenhuma cor cinza/azul e nenhum texto "NG MASK_xxx" sobre a imagem;
- enquanto nenhum segmento ACESO foi reconhecido, segmentos APAGADOS/divergentes
  não são pintados. Isso evita abrir o F3 com o H1 inteiro vermelho/amarelo antes
  de a placa realmente acender.

A geometria das máscaras não depende de existir uma análise produtiva naquele
exato instante. Ela vem diretamente do Projeto Display ativo. A classificação
usa somente análises do CHECK lógico atual e possui fallbacks para o cache de
overlay e para a última sonda ao vivo, evitando a máscara desaparecer quando
algum gate limpa temporariamente ``_display_auto_last_analysis``.

Para destacar defeito não inferimos novamente ACESO/APAGADO. Usamos diretamente
``matched=False`` da mesma análise que alimentou as classificações. Isso é
importante quando foto capturada e ``mask_states`` possuem alguma inconsistência:
a divergência visual continua aparecendo em amarelo forte sem inverter ou ocultar
o defeito na preview.
"""

from copy import deepcopy
import re

import cv2
import numpy as np

import src.platform.display_f3_strict_mask_conformity as strict_module
import src.platform.display_live_roi_overlay as overlay_module
from src.platform.display_mask_geometry import bbox_mascara_display
from src.platform.display_auto_check_analyzer import DISPLAY_AUTO_CLASS_LOW_LIGHT
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
    mascaras_geometria_check_display,
    normalizar_resolucao_display,
)
from src.platform.display_visual_rotation import (
    preparar_check_visual_display,
    preparar_pontos_visuais_display,
)


# O contorno é a informação principal. O preenchimento é deliberadamente muito
# leve para não esconder os segmentos reais do display na câmera ao vivo.
F3_PREVIEW_CLEAR_ALPHA = 0.06
F3_PREVIEW_CLEAR_CONTOUR_THICKNESS = 2
# POUCA LUZ/divergência continua evidente pelo amarelo e contorno mais espesso,
# sem cobrir visualmente o segmento defeituoso.
F3_PREVIEW_ALERT_ALPHA = 0.10
F3_PREVIEW_ALERT_CONTOUR_THICKNESS = 3
F3_PREVIEW_TRACKING_GUIDE_BGR = (248, 189, 56)  # ciano #38BDF8 em BGR
F3_PREVIEW_TRACKING_GUIDE_THICKNESS = 1
F3_PREVIEW_STARTUP_NUMBER_BGR = (240, 232, 226)  # branco frio #E2E8F0

F3_PREVIEW_CLEAR_COLORS = {
    DISPLAY_CHECK_STATE_ON: (94, 197, 34),       # verde #22C55E
    DISPLAY_CHECK_STATE_OFF: (68, 68, 239),      # vermelho #EF4444
    "alert": (21, 204, 250),                     # amarelo #FACC15
}

F3_PREVIEW_CLEAR_LEGEND = (
    "VERDE: ACESO  •  VERMELHO: APAGADO  •  "
    "AMARELO FORTE: POUCA LUZ / DIVERGÊNCIA"
)


def estado_visual_mascara_f3(
    classified: str | None,
    expected: str | None,
    *,
    has_any_on: bool,
) -> str | None:
    """Converte classificação+gabarito em somente verde/vermelho/amarelo."""
    current = str(classified or "").strip().lower()
    target = str(expected or "").strip().lower()

    if current == DISPLAY_AUTO_CLASS_LOW_LIGHT:
        return "alert"

    if current == DISPLAY_CHECK_STATE_ON:
        if target == DISPLAY_CHECK_STATE_OFF and has_any_on:
            return "alert"
        return DISPLAY_CHECK_STATE_ON

    if current == DISPLAY_CHECK_STATE_OFF:
        if not has_any_on:
            return None
        if target == DISPLAY_CHECK_STATE_ON:
            return "alert"
        return DISPLAY_CHECK_STATE_OFF

    return None


def _project_preview_context(window, visual_rotation: int) -> dict | None:
    """Geometria visível do CHECK, usando pose rastreada quando o modo está ativo."""
    app = overlay_module._app_from_window(window)
    if app is None:
        return None

    repository = getattr(app, "display_project_repository", None)
    if repository is None:
        return None

    try:
        project_name = str(repository.obter_projeto_ativo() or "")
    except Exception:
        project_name = ""
    check_id = overlay_module._current_check_id(app)
    if not project_name or not check_id:
        return None

    try:
        project = repository.carregar_projeto(project_name)
    except Exception:
        project = None
    if not isinstance(project, dict):
        return None

    checks = list(project.get("checks", []) or [])
    check = next(
        (
            item
            for item in checks
            if isinstance(item, dict)
            and str(item.get("id") or "") == check_id
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
    expected = {
        str(mask_id): str(state).strip().lower()
        for mask_id, state in states.items()
        if str(state).strip().lower()
        in (DISPLAY_CHECK_STATE_ON, DISPLAY_CHECK_STATE_OFF)
    }

    # Rastreamento ativo: contorno e ROIs já estão projetados para o frame RAW
    # atual. Rotacionamos essa geometria apenas para a orientação visual escolhida
    # pelo operador e NÃO usamos cache, pois ela muda junto com a placa.
    try:
        from src.platform.display_f3_object_tracking import (
            tracking_enabled as tracking_runtime_enabled,
        )
        tracking_enabled = bool(tracking_runtime_enabled(app))
    except Exception:
        tracking_enabled = bool(
            getattr(app, "_display_f3_object_tracking_enabled", False)
        )
    live_geometry = getattr(app, "_display_f3_tracking_live_geometry", None)
    if (
        tracking_enabled
        and isinstance(live_geometry, dict)
        and bool(live_geometry.get("locked"))
    ):
        raw_resolution = live_geometry.get("resolution")
        if (
            isinstance(raw_resolution, (list, tuple))
            and len(raw_resolution) >= 2
        ):
            raw_width = max(1, int(raw_resolution[0]))
            raw_height = max(1, int(raw_resolution[1]))
            # Exiba TODA a geometria rastreada, não somente as máscaras
            # ativas do CHECK. As máscaras sem estado neste CHECK ficam como
            # guias neutras; as ativas recebem verde/vermelho/amarelo depois.
            tracked_masks = [
                deepcopy(mask)
                for mask in (live_geometry.get("masks") or [])
                if isinstance(mask, dict)
            ]
            try:
                _, visual_resolution, visual_masks = preparar_check_visual_display(
                    None,
                    (raw_width, raw_height),
                    tracked_masks,
                    int(visual_rotation or 0) % 360,
                )
                visual_board = preparar_pontos_visuais_display(
                    live_geometry.get("board_points") or [],
                    raw_width,
                    raw_height,
                    int(visual_rotation or 0) % 360,
                )
            except Exception:
                visual_masks = []
                visual_board = []
                visual_resolution = (raw_width, raw_height)

            return {
                "project_name": project_name,
                "check_id": check_id,
                "resolution": tuple(visual_resolution),
                "masks": tuple(visual_masks),
                "board_points": tuple(visual_board),
                "expected_states": expected,
                "tracking_active": True,
                "tracking_locked": True,
                "tracking_reference": str(
                    live_geometry.get("reference") or ""
                ),
                "tracking_space": str(
                    live_geometry.get("geometry_space") or ""
                ),
            }

    if tracking_enabled:
        # Rastreamento ligado mas ainda sem LOCK: nunca volte às ROIs fixas.
        # Isso evita exatamente o efeito visual enganoso de "máscaras paradas"
        # enquanto o tracker ainda procura a placa.
        resolution = normalizar_resolucao_display(project.get("master_resolution"))
        if resolution is None:
            return None
        try:
            _, visual_resolution, _ = preparar_check_visual_display(
                None,
                resolution,
                [],
                int(visual_rotation or 0) % 360,
            )
        except Exception:
            visual_resolution = resolution
        return {
            "project_name": project_name,
            "check_id": check_id,
            "resolution": tuple(visual_resolution),
            "masks": (),
            "board_points": (),
            "expected_states": expected,
            "tracking_active": True,
            "tracking_locked": False,
            "tracking_reference": "",
            "tracking_space": "",
        }

    # Modo legado/desligado: geometria fixa do Projeto Display.
    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    if resolution is None:
        return None

    cache_key = (
        project_name,
        check_id,
        int(visual_rotation or 0) % 360,
        overlay_module._config_signature(repository),
    )
    if cache_key == getattr(window, "_display_f3_clear_preview_project_key", None):
        cached = getattr(window, "_display_f3_clear_preview_project_context", None)
        return deepcopy(cached) if isinstance(cached, dict) else None

    effective_masks = mascaras_geometria_check_display(project, check)
    active_masks = [
        deepcopy(mask)
        for mask in effective_masks
        if isinstance(mask, dict)
        and expected.get(str(mask.get("id") or ""))
        in (DISPLAY_CHECK_STATE_ON, DISPLAY_CHECK_STATE_OFF)
    ]

    try:
        _, visual_resolution, visual_masks = preparar_check_visual_display(
            None,
            resolution,
            active_masks,
            int(visual_rotation or 0) % 360,
        )
    except Exception:
        return None

    result = {
        "project_name": project_name,
        "check_id": check_id,
        "resolution": tuple(visual_resolution),
        "masks": tuple(visual_masks),
        "board_points": (),
        "expected_states": expected,
        "tracking_active": False,
        "tracking_locked": False,
    }
    window._display_f3_clear_preview_project_key = cache_key
    window._display_f3_clear_preview_project_context = deepcopy(result)
    return result


def _analysis_matches_current(
    analysis: dict | None,
    *,
    project_name: str,
    check_id: str,
) -> bool:
    return bool(
        isinstance(analysis, dict)
        and str(analysis.get("project_name") or "") == str(project_name or "")
        and str(analysis.get("check_id") or "") == str(check_id or "")
    )


def _classifications_from_analysis(
    analysis: dict | None,
    *,
    project_name: str,
    check_id: str,
) -> dict[str, str]:
    if not _analysis_matches_current(
        analysis,
        project_name=project_name,
        check_id=check_id,
    ):
        return {}

    result = {}
    for item in analysis.get("mask_results", []) or []:
        if not isinstance(item, dict):
            continue
        mask_id = str(item.get("mask_id") or "")
        state = str(item.get("classified") or "").strip().lower()
        if mask_id and state:
            result[mask_id] = state
    return result


def _failed_mask_ids_from_analysis(
    analysis: dict | None,
    *,
    project_name: str,
    check_id: str,
) -> set[str]:
    """Retorna divergências explícitas da mesma análise usada para a preview."""
    if not _analysis_matches_current(
        analysis,
        project_name=project_name,
        check_id=check_id,
    ):
        return set()

    return {
        str(item.get("mask_id") or "")
        for item in (analysis.get("mask_results") or [])
        if isinstance(item, dict)
        and str(item.get("mask_id") or "")
        and item.get("matched") is False
    }


def _mask_snapshot_for_current_check(
    window,
    *,
    project_name: str,
    check_id: str,
    base: dict | None = None,
) -> tuple[dict[str, str], set[str]]:
    """Lê classificação e falhas sempre da mesma análise do CHECK atual."""
    app = overlay_module._app_from_window(window)
    if app is not None:
        for attr in (
            "_display_auto_last_analysis",
            "_display_f3_overlay_analysis_cache",
            "_display_f3_live_probe_last_analysis",
        ):
            analysis = getattr(app, attr, None)
            classifications = _classifications_from_analysis(
                analysis,
                project_name=project_name,
                check_id=check_id,
            )
            if classifications:
                return (
                    classifications,
                    _failed_mask_ids_from_analysis(
                        analysis,
                        project_name=project_name,
                        check_id=check_id,
                    ),
                )

    classifications = {
        str(key): str(value).strip().lower()
        for key, value in dict((base or {}).get("classifications") or {}).items()
    }
    failed = {
        str(mask_id)
        for mask_id in ((base or {}).get("failed_mask_ids") or ())
        if str(mask_id)
    }
    failed.update(
        str(mask_id)
        for mask_id in dict((base or {}).get("failed_masks") or {}).keys()
        if str(mask_id)
    )
    return classifications, failed


def _classifications_for_current_check(
    window,
    *,
    project_name: str,
    check_id: str,
    base: dict | None = None,
) -> dict[str, str]:
    """Compatibilidade: retorna apenas a classificação do snapshot atual."""
    classifications, _failed = _mask_snapshot_for_current_check(
        window,
        project_name=project_name,
        check_id=check_id,
        base=base,
    )
    return classifications


def _contexto_preview_claro(original):
    def build(window, visual_rotation: int):
        base = original(window, visual_rotation)
        project_context = _project_preview_context(window, visual_rotation)

        if not isinstance(project_context, dict):
            try:
                window.set_display_readout_context(None)
            except (AttributeError, TypeError):
                pass
            return base

        result = dict(base) if isinstance(base, dict) else {}
        result["resolution"] = project_context["resolution"]
        result["masks"] = project_context["masks"]
        result["board_points"] = tuple(project_context.get("board_points") or ())
        result["expected_states"] = dict(project_context["expected_states"])
        result["tracking_active"] = bool(
            project_context.get("tracking_active")
        )
        result["tracking_locked"] = bool(
            project_context.get("tracking_locked")
        )
        result["tracking_reference"] = str(
            project_context.get("tracking_reference") or ""
        )
        result["tracking_space"] = str(
            project_context.get("tracking_space") or ""
        )

        classifications, failed_mask_ids = _mask_snapshot_for_current_check(
            window,
            project_name=str(project_context.get("project_name") or ""),
            check_id=str(project_context.get("check_id") or ""),
            base=result,
        )
        result["classifications"] = classifications
        result["failed_mask_ids"] = tuple(sorted(failed_mask_ids))
        result["has_any_on"] = any(
            str(state).strip().lower() == DISPLAY_CHECK_STATE_ON
            for state in classifications.values()
        )
        try:
            window.set_display_readout_context(result)
        except (AttributeError, TypeError):
            pass
        return result

    return build


def _draw_mask(tint, mask: dict, sx: float, sy: float, color):
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
        return ("circle", center, axes)

    polygon = overlay_module._scaled_polygon(mask, sx, sy)
    if polygon is None or len(polygon) < 3:
        return None
    cv2.fillPoly(tint, [polygon], color, lineType=cv2.LINE_AA)
    return ("polygon", polygon)


def _draw_contour(result, geometry, color, thickness: int) -> None:
    if geometry[0] == "circle":
        _kind, center, axes = geometry
        cv2.ellipse(
            result,
            center,
            axes,
            0,
            0,
            360,
            color,
            int(thickness),
            cv2.LINE_AA,
        )
        return

    _kind, polygon = geometry
    cv2.polylines(
        result,
        [polygon],
        True,
        color,
        int(thickness),
        cv2.LINE_AA,
    )


_F3_MASK_NUMBER_RE = re.compile(r"(\d+)$")


def _numero_mascara_f3(mask: dict) -> str:
    mask_id = str((mask or {}).get("id") or "").strip()
    if not mask_id:
        return ""
    match = _F3_MASK_NUMBER_RE.search(mask_id)
    if match is None:
        return mask_id
    try:
        return str(int(match.group(1)))
    except (TypeError, ValueError):
        return match.group(1)


def _draw_live_mask_number(
    result,
    mask: dict,
    sx: float,
    sy: float,
    color,
) -> None:
    """Número pequeno junto à borda da ROI, sem badge/pill opaco."""
    label = _numero_mascara_f3(mask)
    if not label:
        return
    try:
        x1, y1, x2, _y2 = bbox_mascara_display(mask)
        center_x = ((float(x1) + float(x2)) / 2.0) * float(sx)
        top_y = float(y1) * float(sy)
    except Exception:
        return

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.38
    thickness = 1
    (text_w, text_h), _baseline = cv2.getTextSize(
        label,
        font,
        font_scale,
        thickness,
    )
    frame_h, frame_w = result.shape[:2]
    x = int(round(center_x - text_w / 2.0))
    x = max(2, min(max(2, frame_w - text_w - 2), x))
    # Preferimos acima da ROI; se não houver espaço, fica imediatamente dentro
    # da borda superior. Não há fundo sólido, apenas sombra fina para contraste.
    y = int(round(top_y - 4.0))
    if y < text_h + 2:
        y = int(round(top_y + text_h + 3.0))
    y = max(text_h + 2, min(max(text_h + 2, frame_h - 3), y))

    cv2.putText(
        result,
        label,
        (x + 1, y + 1),
        font,
        font_scale,
        (2, 6, 23),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        result,
        label,
        (x, y),
        font,
        font_scale,
        color,
        thickness,
        cv2.LINE_AA,
    )


def renderizar_preview_claro_display_f3(frame, context):
    """Render final: máscara normal suave e divergência amarela muito evidente."""
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

    classifications = {
        str(key): str(value).strip().lower()
        for key, value in dict(context.get("classifications") or {}).items()
    }
    expected_states = {
        str(key): str(value).strip().lower()
        for key, value in dict(context.get("expected_states") or {}).items()
    }
    failed_mask_ids = {
        str(mask_id)
        for mask_id in (context.get("failed_mask_ids") or ())
        if str(mask_id)
    }
    failed_mask_ids.update(
        str(mask_id)
        for mask_id in dict(context.get("failed_masks") or {}).keys()
        if str(mask_id)
    )

    has_any_on = bool(
        context.get("has_any_on")
        or any(
            state == DISPLAY_CHECK_STATE_ON
            for state in classifications.values()
        )
    )

    result = frame.copy()

    # Bounding box/contorno da placa rastreada: permanece sobre a câmera REAL e
    # acompanha translação/rotação/escala da placa sem deformar a imagem.
    board_points = context.get("board_points") or ()
    if len(board_points) >= 3:
        try:
            board = []
            for point in board_points:
                board.append(
                    [
                        int(round(float(point[0]) * sx)),
                        int(round(float(point[1]) * sy)),
                    ]
                )
            cv2.polylines(
                result,
                [np.asarray(board, dtype=np.int32)],
                True,
                (248, 189, 56),
                max(2, F3_PREVIEW_CLEAR_CONTOUR_THICKNESS),
                cv2.LINE_AA,
            )
        except Exception:
            pass

    # Com tracking ativo/LOCK, todas as máscaras aparecem como guias
    # ciano móveis. Isso torna visível o bounding geometry mesmo antes de existir
    # classificação do CHECK. As máscaras classificadas são recoloridas abaixo.
    if bool(context.get("tracking_active")) and bool(context.get("tracking_locked")):
        for mask in masks:
            if not isinstance(mask, dict):
                continue
            kind = str(mask.get("type") or "").lower()
            try:
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
                        F3_PREVIEW_TRACKING_GUIDE_BGR,
                        F3_PREVIEW_TRACKING_GUIDE_THICKNESS,
                        cv2.LINE_AA,
                    )
                else:
                    polygon = overlay_module._scaled_polygon(mask, sx, sy)
                    if polygon is not None and len(polygon) >= 3:
                        cv2.polylines(
                            result,
                            [polygon],
                            True,
                            F3_PREVIEW_TRACKING_GUIDE_BGR,
                            F3_PREVIEW_TRACKING_GUIDE_THICKNESS,
                            cv2.LINE_AA,
                        )
            except Exception:
                continue

    normal_tint = result.copy()
    alert_tint = result.copy()
    normal_geometries = []
    alert_geometries = []

    for mask in masks:
        if not isinstance(mask, dict):
            continue
        mask_id = str(mask.get("id") or "")
        presentation = estado_visual_mascara_f3(
            classifications.get(mask_id),
            expected_states.get(mask_id),
            has_any_on=has_any_on,
        )

        # matched=False é a evidência direta de divergência. Só ativamos o
        # destaque após a placa mostrar ao menos um segmento realmente aceso.
        # Assim a partida do F3 não vira um painel inteiro amarelo/vermelho.
        confirmed_failure = bool(mask_id in failed_mask_ids and has_any_on)
        if confirmed_failure:
            presentation = "alert"

        if presentation is None:
            continue

        color = F3_PREVIEW_CLEAR_COLORS[presentation]
        if presentation == "alert":
            geometry = _draw_mask(alert_tint, mask, sx, sy, color)
            if geometry is not None:
                alert_geometries.append((geometry, color))
        else:
            geometry = _draw_mask(normal_tint, mask, sx, sy, color)
            if geometry is not None:
                normal_geometries.append((geometry, color))

    if normal_geometries:
        cv2.addWeighted(
            normal_tint,
            F3_PREVIEW_CLEAR_ALPHA,
            result,
            1.0 - F3_PREVIEW_CLEAR_ALPHA,
            0.0,
            dst=result,
        )

    if alert_geometries:
        # O blend é separado para que somente a máscara defeituosa receba a
        # opacidade forte. O restante da câmera continua fácil de inspecionar.
        alert_tint = result.copy()
        for mask in masks:
            if not isinstance(mask, dict):
                continue
            mask_id = str(mask.get("id") or "")
            classified = classifications.get(mask_id)
            expected = expected_states.get(mask_id)
            presentation = estado_visual_mascara_f3(
                classified,
                expected,
                has_any_on=has_any_on,
            )
            if mask_id in failed_mask_ids and has_any_on:
                presentation = "alert"
            if presentation != "alert":
                continue
            _draw_mask(
                alert_tint,
                mask,
                sx,
                sy,
                F3_PREVIEW_CLEAR_COLORS["alert"],
            )
        cv2.addWeighted(
            alert_tint,
            F3_PREVIEW_ALERT_ALPHA,
            result,
            1.0 - F3_PREVIEW_ALERT_ALPHA,
            0.0,
            dst=result,
        )

    for geometry, color in normal_geometries:
        _draw_contour(
            result,
            geometry,
            color,
            F3_PREVIEW_CLEAR_CONTOUR_THICKNESS,
        )

    for geometry, color in alert_geometries:
        _draw_contour(
            result,
            geometry,
            color,
            F3_PREVIEW_ALERT_CONTOUR_THICKNESS,
        )

    # Numeração visível em todas as máscaras, inclusive antes da classificação.
    # O número usa a cor semântica quando existe resultado e uma cor neutra quando
    # ainda estamos apenas rastreando a geometria.
    for mask in masks:
        if not isinstance(mask, dict):
            continue
        mask_id = str(mask.get("id") or "")
        presentation = estado_visual_mascara_f3(
            classifications.get(mask_id),
            expected_states.get(mask_id),
            has_any_on=has_any_on,
        )
        if mask_id in failed_mask_ids and has_any_on:
            presentation = "alert"
        number_color = (
            F3_PREVIEW_CLEAR_COLORS[presentation]
            if presentation in F3_PREVIEW_CLEAR_COLORS
            else F3_PREVIEW_STARTUP_NUMBER_BGR
        )
        _draw_live_mask_number(
            result,
            mask,
            sx,
            sy,
            number_color,
        )

    return result


def _aplicar_render_final() -> None:
    """Reafirma o renderer final; o contexto é embrulhado somente uma vez."""
    if not bool(
        getattr(overlay_module, "_display_f3_clear_preview_context_installed", False)
    ):
        overlay_module._overlay_context = _contexto_preview_claro(
            overlay_module._overlay_context
        )
        overlay_module._display_f3_clear_preview_context_installed = True

    # Estas atribuições são deliberadamente repetíveis. Alguns instaladores F3
    # históricos substituem o renderer durante a construção do app; uma chamada
    # posterior restaura esta camada sem duplicar wrappers nem callbacks.
    overlay_module.renderizar_overlay_rois_display_f3 = (
        renderizar_preview_claro_display_f3
    )
    overlay_module.DISPLAY_ROI_OVERLAY_ALPHA = F3_PREVIEW_CLEAR_ALPHA
    overlay_module.DISPLAY_ROI_OVERLAY_NEUTRAL_ALPHA = 0.0
    overlay_module.DISPLAY_ROI_OVERLAY_COLORS.clear()
    overlay_module.DISPLAY_ROI_OVERLAY_COLORS.update(
        {
            "on": F3_PREVIEW_CLEAR_COLORS[DISPLAY_CHECK_STATE_ON],
            "off": F3_PREVIEW_CLEAR_COLORS[DISPLAY_CHECK_STATE_OFF],
            "low_light": F3_PREVIEW_CLEAR_COLORS["alert"],
            "mismatch": F3_PREVIEW_CLEAR_COLORS["alert"],
        }
    )
    overlay_module.DISPLAY_ROI_OVERLAY_LEGEND = F3_PREVIEW_CLEAR_LEGEND
    overlay_module._display_f3_clear_preview_installed = True


_INSTALLED = False


def instalar_preview_claro_display_f3() -> None:
    """Garante que esta apresentação seja a última camada visual do F3."""
    global _INSTALLED

    if not _INSTALLED:
        previous = strict_module._install_failed_mask_overlay

        def install_failed_mask_overlay_then_clear() -> None:
            previous()
            _aplicar_render_final()

        strict_module._install_failed_mask_overlay = install_failed_mask_overlay_then_clear
        _INSTALLED = True

    # Também é seguro chamar depois da construção completa do app para recuperar
    # o renderer caso qualquer camada posterior o tenha substituído.
    _aplicar_render_final()
