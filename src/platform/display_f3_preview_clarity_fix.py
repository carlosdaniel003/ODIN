from __future__ import annotations

"""Preview visual simples e legível para o Display F3.

Esta camada altera somente a apresentação das máscaras sobre a câmera do F3.
A classificação, a decisão OK/NG, o debounce e o fluxo produtivo continuam sob
as autoridades já instaladas.

Regra visual final:
- verde fino: segmento ACESO conforme;
- azul/cinza fino: segmento APAGADO conforme;
- amarelo: leitura em validação/POUCA LUZ;
- vermelho: somente falha efetiva confirmada;
- no ao vivo, somente falhas recebem numero grande e linha-guia;
- o visor fisico recebe um inset ampliado para preservar a leitura dos segmentos;
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
from src.platform.display_mask_geometry import (
    bbox_mascara_display,
    mapear_slots_sete_segmentos_display,
)
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


# O frame fisico deve continuar legivel. Estados conformes quase nao recebem
# preenchimento; a falha efetiva e a unica regiao com destaque forte.
F3_PREVIEW_CLEAR_ALPHA = 0.035
F3_PREVIEW_CLEAR_CONTOUR_THICKNESS = 1
F3_PREVIEW_WARNING_ALPHA = 0.08
F3_PREVIEW_ALERT_ALPHA = 0.18
F3_PREVIEW_ALERT_CONTOUR_THICKNESS = 3
F3_PREVIEW_TRACKING_GUIDE_BGR = (139, 116, 100)
F3_PREVIEW_TRACKING_GUIDE_THICKNESS = 1
F3_PREVIEW_STARTUP_NUMBER_BGR = (203, 213, 225)
F3_PREVIEW_FAILURE_BADGE_BGR = (68, 68, 239)
F3_PREVIEW_FAILURE_BADGE_TEXT_BGR = (255, 255, 255)
F3_PREVIEW_ZOOM_WIDTH_RATIO = 0.38
F3_PREVIEW_ZOOM_MAX_WIDTH = 300
F3_PREVIEW_ZOOM_PADDING_RATIO = 0.18

F3_PREVIEW_CLEAR_COLORS = {
    DISPLAY_CHECK_STATE_ON: (94, 197, 34),       # verde #22C55E
    DISPLAY_CHECK_STATE_OFF: (139, 116, 100),    # azul/cinza #64748B
    "warning": (21, 204, 250),                   # amarelo #FACC15
    "alert": (68, 68, 239),                      # vermelho #EF4444
}

F3_PREVIEW_CLEAR_LEGEND = (
    "VERDE: ACESO  •  AZUL/CINZA: APAGADO  •  "
    "AMARELO: VALIDANDO  •  VERMELHO: FALHA CONFIRMADA"
)


def estado_visual_mascara_f3(
    classified: str | None,
    expected: str | None,
    *,
    has_any_on: bool,
    intermittent: bool = False,
) -> str | None:
    """Converte classificação+gabarito em somente verde/vermelho/amarelo."""
    current = str(classified or "").strip().lower()
    target = str(expected or "").strip().lower()

    if current == DISPLAY_AUTO_CLASS_LOW_LIGHT:
        return "warning"

    if current == DISPLAY_CHECK_STATE_ON:
        if target == DISPLAY_CHECK_STATE_OFF and has_any_on:
            return "alert"
        return DISPLAY_CHECK_STATE_ON

    if current == DISPLAY_CHECK_STATE_OFF:
        if (
            target == DISPLAY_CHECK_STATE_ON
            and intermittent
            and not has_any_on
        ):
            # BLUE/BT totalmente escuro ainda pode ser apenas a fase OFF do pisca.
            return DISPLAY_CHECK_STATE_OFF
        if not has_any_on:
            return None
        if target == DISPLAY_CHECK_STATE_ON:
            # Existe outro segmento ON no mesmo frame: a fase acesa foi provada.
            # O segmento que continuou OFF é divergência/NG.
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
    readout_mask_ids = tuple(
        str(mask.get("id") or "")
        for mask in (project.get("masks") or [])
        if isinstance(mask, dict) and str(mask.get("id") or "")
    )
    readout_slot_mask_ids = ()
    base_resolution = normalizar_resolucao_display(project.get("master_resolution"))
    if base_resolution is not None:
        try:
            _, _, canonical_visual_masks = preparar_check_visual_display(
                None,
                base_resolution,
                project.get("masks", []),
                int(visual_rotation or 0) % 360,
            )
            readout_slot_mask_ids = tuple(
                mapear_slots_sete_segmentos_display(
                    canonical_visual_masks,
                    digit_count=4,
                )
            )
        except Exception:
            readout_slot_mask_ids = ()

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
                "intermittent": bool(check.get("intermittent", False)),
                "readout_mask_ids": readout_mask_ids,
                "readout_slot_mask_ids": readout_slot_mask_ids,
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
            "intermittent": bool(check.get("intermittent", False)),
            "readout_mask_ids": readout_mask_ids,
            "readout_slot_mask_ids": readout_slot_mask_ids,
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
        "intermittent": bool(check.get("intermittent", False)),
        "readout_mask_ids": readout_mask_ids,
        "readout_slot_mask_ids": readout_slot_mask_ids,
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

    effective = analysis.get("effective_classifications")
    if isinstance(effective, dict):
        return {
            str(mask_id): str(state).strip().lower()
            for mask_id, state in effective.items()
            if str(mask_id) and str(state).strip()
        }

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

    if "effective_failed_mask_ids" in analysis:
        return {
            str(mask_id)
            for mask_id in (analysis.get("effective_failed_mask_ids") or ())
            if str(mask_id)
        }

    results = [
        item
        for item in (analysis.get("mask_results") or [])
        if isinstance(item, dict) and str(item.get("mask_id") or "")
    ]
    has_any_on = any(
        str(item.get("classified") or "").strip().lower()
        == DISPLAY_CHECK_STATE_ON
        for item in results
    )

    failed = set()
    for item in results:
        mask_id = str(item.get("mask_id") or "")
        expected = str(item.get("expected") or "").strip().lower()
        classified = str(item.get("classified") or "").strip().lower()

        if item.get("matched") is False:
            failed.add(mask_id)
            continue
        if classified == DISPLAY_AUTO_CLASS_LOW_LIGHT:
            failed.add(mask_id)
            continue
        if expected == DISPLAY_CHECK_STATE_OFF and classified == DISPLAY_CHECK_STATE_ON:
            failed.add(mask_id)
            continue
        if (
            has_any_on
            and expected == DISPLAY_CHECK_STATE_ON
            and classified == DISPLAY_CHECK_STATE_OFF
        ):
            # Mesmo que uma camada intermitente tenha marcado matched=True,
            # OFF parcial durante a fase ON é falha visual real.
            failed.add(mask_id)

    return failed


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
        result["intermittent"] = bool(project_context.get("intermittent", False))
        result["readout_mask_ids"] = tuple(
            project_context.get("readout_mask_ids") or ()
        )
        result["readout_slot_mask_ids"] = tuple(
            project_context.get("readout_slot_mask_ids") or ()
        )
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
        result["effective_classifications"] = dict(classifications)
        result["failed_mask_ids"] = tuple(sorted(failed_mask_ids))
        result["effective_failed_mask_ids"] = tuple(sorted(failed_mask_ids))
        result["ui_mask_authority"] = "effective_mask_results_v1"
        result["has_any_on"] = any(
            str(state).strip().lower() == DISPLAY_CHECK_STATE_ON
            for state in classifications.values()
        )
        app = overlay_module._app_from_window(window)
        power = getattr(app, "_display_f3_power_authority_status", None)
        energy = power.get("energy") if isinstance(power, dict) else None
        result["power_confirmed"] = bool(
            isinstance(energy, dict)
            and energy.get("powered_confirmed") is True
        )
        result["power_off_confirmed"] = bool(
            isinstance(energy, dict)
            and energy.get("off_confirmed") is True
        )
        result["energy_state"] = (
            str(energy.get("energy_state") or "").strip().lower()
            if isinstance(energy, dict)
            else ""
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


def _presentation_for_effective_mask(
    mask_id: str,
    classifications: dict[str, str],
    expected_states: dict[str, str],
    failed_mask_ids: set[str],
    *,
    has_any_on: bool,
    intermittent: bool,
    effective_authority: bool,
) -> str | None:
    current = str(classifications.get(mask_id) or "").strip().lower()
    if effective_authority:
        if mask_id in failed_mask_ids:
            return "alert"
        if current == DISPLAY_AUTO_CLASS_LOW_LIGHT:
            return "warning"
        if current == DISPLAY_CHECK_STATE_ON:
            return DISPLAY_CHECK_STATE_ON
        if current == DISPLAY_CHECK_STATE_OFF:
            return DISPLAY_CHECK_STATE_OFF if has_any_on else None
        return None

    return estado_visual_mascara_f3(
        current,
        expected_states.get(mask_id),
        has_any_on=has_any_on,
        intermittent=intermittent,
    )


def _mask_bbox_pixels(mask: dict, sx: float, sy: float):
    try:
        x1, y1, x2, y2 = bbox_mascara_display(mask)
        left = int(round(min(float(x1), float(x2)) * sx))
        right = int(round(max(float(x1), float(x2)) * sx))
        top = int(round(min(float(y1), float(y2)) * sy))
        bottom = int(round(max(float(y1), float(y2)) * sy))
        return left, top, right, bottom
    except Exception:
        return None


def _display_bbox_pixels(masks, sx: float, sy: float, frame_shape):
    boxes = [
        box
        for box in (
            _mask_bbox_pixels(mask, sx, sy)
            for mask in masks
            if isinstance(mask, dict)
        )
        if box is not None
    ]
    if not boxes:
        return None
    frame_h, frame_w = frame_shape[:2]
    left = max(0, min(box[0] for box in boxes))
    top = max(0, min(box[1] for box in boxes))
    right = min(frame_w - 1, max(box[2] for box in boxes))
    bottom = min(frame_h - 1, max(box[3] for box in boxes))
    return left, top, right, bottom


def _draw_failure_badge(
    result,
    mask: dict,
    sx: float,
    sy: float,
    display_bbox,
) -> None:
    label = _numero_mascara_f3(mask)
    box = _mask_bbox_pixels(mask, sx, sy)
    if not label or box is None or display_bbox is None:
        return

    x1, y1, x2, y2 = box
    dx1, dy1, dx2, dy2 = display_bbox
    cx = int(round((x1 + x2) / 2.0))
    cy = int(round((y1 + y2) / 2.0))
    dcx = (dx1 + dx2) / 2.0
    dcy = (dy1 + dy2) / 2.0
    frame_h, frame_w = result.shape[:2]

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.48
    thickness = 1
    (tw, th), baseline = cv2.getTextSize(
        label,
        font,
        font_scale,
        thickness,
    )
    badge_w = tw + 12
    badge_h = th + baseline + 8
    gap = 10

    if abs(cx - dcx) >= abs(cy - dcy):
        if cx < dcx:
            bx = dx1 - badge_w - gap
            by = cy - badge_h // 2
        else:
            bx = dx2 + gap
            by = cy - badge_h // 2
    else:
        if cy < dcy:
            bx = cx - badge_w // 2
            by = dy1 - badge_h - gap
        else:
            bx = cx - badge_w // 2
            by = dy2 + gap

    bx = max(3, min(frame_w - badge_w - 3, int(bx)))
    by = max(3, min(frame_h - badge_h - 3, int(by)))
    badge_center = (bx + badge_w // 2, by + badge_h // 2)

    cv2.line(
        result,
        (cx, cy),
        badge_center,
        F3_PREVIEW_FAILURE_BADGE_BGR,
        1,
        cv2.LINE_AA,
    )
    cv2.rectangle(
        result,
        (bx, by),
        (bx + badge_w, by + badge_h),
        F3_PREVIEW_FAILURE_BADGE_BGR,
        -1,
        cv2.LINE_AA,
    )
    cv2.putText(
        result,
        label,
        (bx + 6, by + badge_h - 5),
        font,
        font_scale,
        F3_PREVIEW_FAILURE_BADGE_TEXT_BGR,
        thickness,
        cv2.LINE_AA,
    )


def _draw_inset_mask(
    inset,
    mask: dict,
    sx: float,
    sy: float,
    crop_left: int,
    crop_top: int,
    scale: float,
    color,
    thickness: int,
) -> None:
    kind = str(mask.get("type") or "").lower()
    if kind == "circle":
        center = (
            int(round((float(mask.get("cx", 0)) * sx - crop_left) * scale)),
            int(round((float(mask.get("cy", 0)) * sy - crop_top) * scale)),
        )
        axes = (
            max(1, int(round(float(mask.get("radius", 1)) * sx * scale))),
            max(1, int(round(float(mask.get("radius", 1)) * sy * scale))),
        )
        cv2.ellipse(
            inset, center, axes, 0, 0, 360, color, thickness, cv2.LINE_AA
        )
        return

    polygon = overlay_module._scaled_polygon(mask, sx, sy)
    if polygon is None or len(polygon) < 3:
        return
    transformed = polygon.astype(np.float32)
    transformed[:, 0] = (transformed[:, 0] - float(crop_left)) * scale
    transformed[:, 1] = (transformed[:, 1] - float(crop_top)) * scale
    cv2.polylines(
        inset,
        [np.rint(transformed).astype(np.int32)],
        True,
        color,
        thickness,
        cv2.LINE_AA,
    )


def _draw_display_zoom_inset(
    source,
    result,
    masks,
    sx: float,
    sy: float,
    classifications: dict[str, str],
    expected_states: dict[str, str],
    failed_mask_ids: set[str],
    *,
    has_any_on: bool,
    intermittent: bool,
    effective_authority: bool,
) -> None:
    display_bbox = _display_bbox_pixels(masks, sx, sy, source.shape)
    if display_bbox is None:
        return

    left, top, right, bottom = display_bbox
    width = max(1, right - left + 1)
    height = max(1, bottom - top + 1)
    pad_x = max(8, int(round(width * F3_PREVIEW_ZOOM_PADDING_RATIO)))
    pad_y = max(8, int(round(height * F3_PREVIEW_ZOOM_PADDING_RATIO)))
    frame_h, frame_w = source.shape[:2]
    crop_left = max(0, left - pad_x)
    crop_top = max(0, top - pad_y)
    crop_right = min(frame_w, right + pad_x + 1)
    crop_bottom = min(frame_h, bottom + pad_y + 1)

    crop = source[crop_top:crop_bottom, crop_left:crop_right]
    if crop.size == 0 or crop.shape[1] < 16 or crop.shape[0] < 12:
        return

    target_w = min(
        F3_PREVIEW_ZOOM_MAX_WIDTH,
        max(170, int(round(frame_w * F3_PREVIEW_ZOOM_WIDTH_RATIO))),
    )
    scale = target_w / float(crop.shape[1])
    target_h = max(1, int(round(crop.shape[0] * scale)))
    max_h = max(80, int(round(frame_h * 0.46)))
    if target_h > max_h:
        scale = max_h / float(crop.shape[0])
        target_h = max_h
        target_w = max(1, int(round(crop.shape[1] * scale)))

    inset = cv2.resize(
        crop,
        (target_w, target_h),
        interpolation=cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA,
    )

    for mask in masks:
        if not isinstance(mask, dict):
            continue
        mask_id = str(mask.get("id") or "")
        presentation = _presentation_for_effective_mask(
            mask_id,
            classifications,
            expected_states,
            failed_mask_ids,
            has_any_on=has_any_on,
            intermittent=intermittent,
            effective_authority=effective_authority,
        )
        if presentation is None:
            continue
        color = F3_PREVIEW_CLEAR_COLORS[presentation]
        _draw_inset_mask(
            inset,
            mask,
            sx,
            sy,
            crop_left,
            crop_top,
            scale,
            color,
            3 if presentation == "alert" else 1,
        )

    margin = 10
    display_cx = (left + right) / 2.0
    display_cy = (top + bottom) / 2.0
    candidates = [
        (margin, margin),
        (frame_w - target_w - margin, margin),
        (margin, frame_h - target_h - margin),
        (frame_w - target_w - margin, frame_h - target_h - margin),
    ]
    candidates = [
        (max(0, x), max(0, y))
        for x, y in candidates
        if x >= 0 and y >= 0
    ]
    if not candidates:
        return
    inset_x, inset_y = max(
        candidates,
        key=lambda point: (
            (point[0] + target_w / 2.0 - display_cx) ** 2
            + (point[1] + target_h / 2.0 - display_cy) ** 2
        ),
    )

    result[
        inset_y:inset_y + target_h,
        inset_x:inset_x + target_w,
    ] = inset
    cv2.rectangle(
        result,
        (inset_x - 1, inset_y - 1),
        (inset_x + target_w, inset_y + target_h),
        (15, 23, 42),
        2,
        cv2.LINE_AA,
    )
    zoom = max(1.0, scale)
    label = f"VISOR x{zoom:.1f}"
    cv2.rectangle(
        result,
        (inset_x, inset_y),
        (min(frame_w - 1, inset_x + 92), min(frame_h - 1, inset_y + 20)),
        (15, 23, 42),
        -1,
    )
    cv2.putText(
        result,
        label,
        (inset_x + 5, inset_y + 14),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.38,
        (226, 232, 240),
        1,
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

    # Defesa final no renderer. O contexto produtivo sempre publica a autoridade
    # de energia; nesse caso, classificações brutas não podem gerar cor antes de
    # a energia estar realmente confirmada. Contextos legados/testes que não
    # possuem essas chaves mantêm o comportamento histórico.
    energy_gate_declared = any(
        key in context
        for key in (
            "power_confirmed",
            "power_off_confirmed",
            "energy_state",
        )
    )
    energy_state = str(context.get("energy_state") or "").strip().lower()
    semantic_power_ready = bool(
        context.get("power_confirmed")
        and not bool(context.get("power_off_confirmed"))
        and energy_state != "off"
    )
    if energy_gate_declared and not semantic_power_ready:
        classifications = {}
        failed_mask_ids = set()

    has_any_on = bool(
        (not energy_gate_declared or semantic_power_ready)
        and (
            context.get("has_any_on")
            or any(
                state == DISPLAY_CHECK_STATE_ON
                for state in classifications.values()
            )
        )
    )

    source_for_inset = frame.copy()
    result = frame.copy()
    effective_authority = bool(
        context.get("ui_mask_authority")
        or "effective_failed_mask_ids" in context
        or "effective_classifications" in context
    )

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
        presentation = _presentation_for_effective_mask(
            mask_id,
            classifications,
            expected_states,
            failed_mask_ids,
            has_any_on=has_any_on,
            intermittent=bool(context.get("intermittent", False)),
            effective_authority=effective_authority,
        )

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
            presentation = _presentation_for_effective_mask(
                mask_id,
                classifications,
                expected_states,
                failed_mask_ids,
                has_any_on=has_any_on,
                intermittent=bool(context.get("intermittent", False)),
                effective_authority=effective_authority,
            )
            if presentation not in {"alert", "warning"}:
                continue
            _draw_mask(
                alert_tint,
                mask,
                sx,
                sy,
                F3_PREVIEW_CLEAR_COLORS["alert"],
            )
        alert_alpha = (
            F3_PREVIEW_ALERT_ALPHA
            if failed_mask_ids
            else F3_PREVIEW_WARNING_ALPHA
        )
        cv2.addWeighted(
            alert_tint,
            alert_alpha,
            result,
            1.0 - alert_alpha,
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

    display_bbox = _display_bbox_pixels(masks, sx, sy, result.shape)
    debug_detailed = bool(context.get("debug_frame_specific"))

    if debug_detailed:
        # DEBUG pode manter todos os IDs pequenos; a produção ao vivo não.
        for mask in masks:
            if not isinstance(mask, dict):
                continue
            mask_id = str(mask.get("id") or "")
            presentation = _presentation_for_effective_mask(
                mask_id,
                classifications,
                expected_states,
                failed_mask_ids,
                has_any_on=has_any_on,
                intermittent=bool(context.get("intermittent", False)),
                effective_authority=effective_authority,
            )
            number_color = (
                F3_PREVIEW_CLEAR_COLORS[presentation]
                if presentation in F3_PREVIEW_CLEAR_COLORS
                else F3_PREVIEW_STARTUP_NUMBER_BGR
            )
            _draw_live_mask_number(result, mask, sx, sy, number_color)
    else:
        # Operador: somente falhas reais ganham número grande fora do display.
        for mask in masks:
            if not isinstance(mask, dict):
                continue
            mask_id = str(mask.get("id") or "")
            if mask_id not in failed_mask_ids:
                continue
            _draw_failure_badge(
                result,
                mask,
                sx,
                sy,
                display_bbox,
            )

        if semantic_power_ready or not energy_gate_declared:
            _draw_display_zoom_inset(
                source_for_inset,
                result,
                masks,
                sx,
                sy,
                classifications,
                expected_states,
                failed_mask_ids,
                has_any_on=has_any_on,
                intermittent=bool(context.get("intermittent", False)),
                effective_authority=effective_authority,
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
            "low_light": F3_PREVIEW_CLEAR_COLORS["warning"],
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
