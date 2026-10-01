from __future__ import annotations

"""Preview visual simples e legível para o Display F3.

Esta camada altera somente a apresentação das máscaras sobre a câmera do F3.
A classificação, a decisão OK/NG, o debounce e o fluxo produtivo continuam sob
as autoridades já instaladas.

Regra visual final:
- verde vivo: segmento fisicamente ACESO;
- verde escuro: segmento fisicamente APAGADO;
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
    mascaras_geometria_runtime_fixa_display,
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
F3_PREVIEW_CLASSIC_MASK_BGR = (184, 163, 148)  # neutro/desconhecido #94A3B8
F3_PREVIEW_CLASSIC_LIGHT_BGR = (94, 197, 34)   # verde aceso #22C55E
F3_PREVIEW_CLASSIC_OFF_BGR = (45, 83, 20)      # verde escuro #14532D
F3_PREVIEW_CLASSIC_LIGHT_ALPHA = 0.16
F3_PREVIEW_CLASSIC_OFF_ALPHA = 0.16
F3_PREVIEW_STARTUP_NUMBER_BGR = (203, 213, 225)
F3_PREVIEW_FAILURE_BADGE_BGR = (68, 68, 239)
F3_PREVIEW_FAILURE_BADGE_TEXT_BGR = (255, 255, 255)
F3_PREVIEW_ZOOM_WIDTH_RATIO = 0.38
F3_PREVIEW_ZOOM_MAX_WIDTH = 300
F3_PREVIEW_ZOOM_PADDING_RATIO = 0.18

# Espelho visual latest-frame-wins. Estes parâmetros NÃO classificam o produto;
# apenas dizem quais ROIs do frame já reduzido parecem emitir luz para que câmera
# e visor reajam juntos. O analyzer produtivo continua sendo a única autoridade
# de ON/OFF/POUCA LUZ/OK/NG.
F3_LIVE_VISUAL_CORE_SCALE = 0.66
F3_LIVE_VISUAL_BASE_PERCENTILE = 25.0
F3_LIVE_VISUAL_SCORE_MID_PERCENTILE = 50.0
F3_LIVE_VISUAL_SCORE_HIGH_PERCENTILE = 85.0
F3_LIVE_VISUAL_HIGH_WEIGHT = 0.28
F3_LIVE_VISUAL_MIN_PEAK = 135.0
F3_LIVE_VISUAL_MIN_DYNAMIC_RANGE = 22.0
F3_LIVE_VISUAL_THRESHOLD_RANGE_FRACTION = 0.58
F3_LIVE_VISUAL_MIN_THRESHOLD_MARGIN = 16.0
# A visualização não é autoridade produtiva. Para espelhar o que o operador vê,
# também aceitamos uma separação clara entre dois grupos de brilho e uma emissão
# absoluta forte. Isso cobre CHECKS com maioria (ou todos) os segmentos acesos,
# cenário em que o percentil-base sozinho sobe e pode esconder luz real.
F3_LIVE_VISUAL_MIN_CLUSTER_GAP = 12.0
F3_LIVE_VISUAL_STRONG_SCORE = 150.0
F3_LIVE_VISUAL_STRONG_PEAK = 175.0

F3_PREVIEW_CLEAR_COLORS = {
    DISPLAY_CHECK_STATE_ON: F3_PREVIEW_CLASSIC_LIGHT_BGR,
    DISPLAY_CHECK_STATE_OFF: F3_PREVIEW_CLASSIC_OFF_BGR,
    "warning": (21, 204, 250),                   # amarelo #FACC15
    "alert": (68, 68, 239),                      # vermelho #EF4444
}

F3_PREVIEW_CLEAR_LEGEND = (
    "VERDE: ACESO  •  VERDE ESCURO: APAGADO  •  "
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
    tracking_runtime = None
    canonical_board_points_fn = None
    try:
        from src.platform.display_f3_object_tracking import (
            canonical_board_points as canonical_board_points_fn,
            get_tracking_runtime,
            tracking_enabled as tracking_runtime_enabled,
        )
        tracking_runtime = get_tracking_runtime(app)
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

            luminous_mask_ids = _luminous_mask_ids_for_current_check(
                app,
                project_name=project_name,
                check_id=check_id,
            )
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
                "live_luminous_only": True,
                "luminous_mask_ids": luminous_mask_ids,
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
            "live_luminous_only": True,
            "luminous_mask_ids": (),
        }

    # Modo legado/desligado: geometria fixa do Projeto Display.
    resolution = normalizar_resolucao_display(project.get("master_resolution"))
    if resolution is None:
        return None

    fixed_board_points = []
    if tracking_runtime is not None and callable(canonical_board_points_fn):
        try:
            fixed_board_points = canonical_board_points_fn(
                project,
                tracking_runtime.store,
            )
        except Exception:
            fixed_board_points = []

    board_signature = tuple(
        (
            round(float(point[0]), 3),
            round(float(point[1]), 3),
        )
        for point in fixed_board_points
        if isinstance(point, (list, tuple)) and len(point) >= 2
    )
    cache_key = (
        project_name,
        check_id,
        int(visual_rotation or 0) % 360,
        overlay_module._config_signature(repository),
        board_signature,
    )
    if cache_key == getattr(window, "_display_f3_clear_preview_project_key", None):
        cached = getattr(window, "_display_f3_clear_preview_project_context", None)
        return deepcopy(cached) if isinstance(cached, dict) else None

    effective_masks = mascaras_geometria_runtime_fixa_display(project)

    try:
        _, visual_resolution, visual_masks = preparar_check_visual_display(
            None,
            resolution,
            effective_masks,
            int(visual_rotation or 0) % 360,
        )
        visual_board = preparar_pontos_visuais_display(
            fixed_board_points,
            int(resolution[0]),
            int(resolution[1]),
            int(visual_rotation or 0) % 360,
        )
    except Exception:
        return None

    result = {
        "project_name": project_name,
        "check_id": check_id,
        "resolution": tuple(visual_resolution),
        "masks": tuple(visual_masks),
        "board_points": tuple(visual_board),
        "expected_states": expected,
        "intermittent": bool(check.get("intermittent", False)),
        "readout_mask_ids": readout_mask_ids,
        "readout_slot_mask_ids": readout_slot_mask_ids,
        "tracking_active": False,
        "tracking_locked": False,
        # D-033: tracking OFF muda somente a geometria (fixa em vez de móvel).
        # O espelho visual continua latest-frame e independente dos gates.
        "live_luminous_only": True,
        "luminous_mask_ids": (),
    }
    window._display_f3_clear_preview_project_key = cache_key
    window._display_f3_clear_preview_project_context = deepcopy(result)
    return result


def _luminous_mask_ids_for_current_check(
    app,
    *,
    project_name: str,
    check_id: str,
) -> tuple[str, ...]:
    telemetry = getattr(app, "_display_f3_luminous_tracking_debug", None)
    if not isinstance(telemetry, dict):
        return ()
    if str(telemetry.get("project_name") or "") != str(project_name or ""):
        return ()
    if str(telemetry.get("check_id") or "") != str(check_id or ""):
        return ()
    if not bool(telemetry.get("alignment_ready")):
        return ()
    return tuple(
        sorted(
            {
                str(mask_id)
                for mask_id in (telemetry.get("matched_mask_ids") or ())
                if str(mask_id)
            }
        )
    )


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


def _latest_physical_visual_classifications(
    window,
    *,
    project_name: str,
) -> dict[str, str]:
    """Retorna estados físicos recentes sem atrelar a cor ao CHECK lógico.

    O campo classified de cada máscara descreve o que a câmera observou
    fisicamente (ON/OFF/POUCA LUZ). O check_id só é necessário para avaliar
    conformidade/expected; ele não pode impedir o espelho visual de mostrar uma
    luz que o próprio analyzer já reconheceu.

    A fonte continua limitada ao projeto ativo para nunca reaproveitar uma
    análise antiga de outro produto.
    """
    app = overlay_module._app_from_window(window)
    if app is None:
        return {}

    valid_states = {
        DISPLAY_CHECK_STATE_ON,
        DISPLAY_CHECK_STATE_OFF,
        DISPLAY_AUTO_CLASS_LOW_LIGHT,
    }
    physical: dict[str, str] = {}
    for attr in (
        "_display_auto_last_analysis",
        "_display_f3_overlay_analysis_cache",
        "_display_f3_live_probe_last_analysis",
    ):
        analysis = getattr(app, attr, None)
        if not isinstance(analysis, dict):
            continue

        analysis_project = str(analysis.get("project_name") or "")
        if (
            analysis_project
            and project_name
            and analysis_project != str(project_name)
        ):
            continue

        analysis_physical = {}
        for item in analysis.get("mask_results", []) or []:
            if not isinstance(item, dict):
                continue
            mask_id = str(item.get("mask_id") or "")
            state = str(item.get("classified") or "").strip().lower()
            if mask_id and state in valid_states:
                analysis_physical[mask_id] = state

        if not analysis_physical:
            for key in ("classifications", "effective_classifications"):
                source = analysis.get(key)
                if not isinstance(source, dict):
                    continue
                analysis_physical = {
                    str(mask_id): str(state or "").strip().lower()
                    for mask_id, state in source.items()
                    if str(mask_id)
                    and str(state or "").strip().lower() in valid_states
                }
                if analysis_physical:
                    break

        if analysis_physical:
            physical.update(analysis_physical)
            break

    # A autoridade de energia já mantém uma leitura física check-independente
    # das máscaras discriminantes no frame do pipeline. Ela complementa a
    # análise semântica para apresentação, mas nunca fornece expected/matched.
    power_status = getattr(app, "_display_f3_power_authority_status", None)
    energy = power_status.get("energy") if isinstance(power_status, dict) else None
    if isinstance(energy, dict):
        energy_project = str(energy.get("project_name") or "")
        same_project = bool(
            not energy_project
            or not project_name
            or energy_project == str(project_name)
        )
        raw_power_states = energy.get("mask_classifications")
        if same_project and isinstance(raw_power_states, dict):
            for mask_id, state in raw_power_states.items():
                normalized = str(state or "").strip().lower()
                if str(mask_id) and normalized in valid_states:
                    # A autoridade física live é mais atual para as máscaras
                    # que ela consegue discriminar.
                    physical[str(mask_id)] = normalized

    return physical


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


def _effective_phase_mask_ids_for_current_check(
    window,
    *,
    project_name: str,
    check_id: str,
) -> tuple[set[str], set[str]]:
    app = overlay_module._app_from_window(window)
    if app is None:
        return set(), set()

    for attr in (
        "_display_auto_last_analysis",
        "_display_f3_overlay_analysis_cache",
        "_display_f3_live_probe_last_analysis",
    ):
        analysis = getattr(app, attr, None)
        if not _analysis_matches_current(
            analysis,
            project_name=project_name,
            check_id=check_id,
        ):
            continue
        confirmed = {
            str(mask_id)
            for mask_id in (
                (analysis or {}).get("effective_confirmed_failed_mask_ids") or ()
            )
            if str(mask_id)
        }
        validating = {
            str(mask_id)
            for mask_id in (
                (analysis or {}).get("effective_validating_mask_ids") or ()
            )
            if str(mask_id)
        }
        return confirmed, validating

    return set(), set()


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
        result["live_luminous_only"] = bool(
            project_context.get("live_luminous_only")
        )
        result["luminous_mask_ids"] = tuple(
            project_context.get("luminous_mask_ids") or ()
        )
        result["terminal_segregated"] = bool(
            getattr(window, "_display_terminal_waiting_removal", False)
            and str(
                getattr(window, "_display_terminal_result_kind", "") or ""
            ) == "segregated"
        )

        classifications, failed_mask_ids = _mask_snapshot_for_current_check(
            window,
            project_name=str(project_context.get("project_name") or ""),
            check_id=str(project_context.get("check_id") or ""),
            base=result,
        )
        confirmed_failed_mask_ids, validating_mask_ids = (
            _effective_phase_mask_ids_for_current_check(
                window,
                project_name=str(project_context.get("project_name") or ""),
                check_id=str(project_context.get("check_id") or ""),
            )
        )
        if not confirmed_failed_mask_ids and not validating_mask_ids:
            if bool(project_context.get("intermittent", False)):
                validating_mask_ids = set(failed_mask_ids)
            else:
                confirmed_failed_mask_ids = set(failed_mask_ids)

        result["classifications"] = classifications
        result["effective_classifications"] = dict(classifications)
        result["visual_physical_classifications"] = (
            _latest_physical_visual_classifications(
                window,
                project_name=str(project_context.get("project_name") or ""),
            )
        )
        result["failed_mask_ids"] = tuple(sorted(failed_mask_ids))
        result["effective_failed_mask_ids"] = tuple(sorted(failed_mask_ids))
        result["effective_confirmed_failed_mask_ids"] = tuple(
            sorted(confirmed_failed_mask_ids)
        )
        result["effective_validating_mask_ids"] = tuple(
            sorted(validating_mask_ids)
        )
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
        # O contexto é apenas preparado aqui. O VISOR é atualizado pelo
        # consumidor do frame, DEPOIS da amostra visual latest-frame. Isso evita
        # um repaint intermediário cinza e garante câmera + visor no mesmo estado.
        return result

    return build


def _mask_geometry(mask: dict, sx: float, sy: float):
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
        return ("circle", center, axes)

    polygon = overlay_module._scaled_polygon(mask, sx, sy)
    if polygon is None or len(polygon) < 3:
        return None
    return ("polygon", polygon)


def _live_visual_core_values(
    value_channel,
    mask: dict,
    sx: float,
    sy: float,
):
    """Amostra somente o núcleo da ROI no preview reduzido.

    A operação é deliberadamente pequena: nenhum ORB, template, feature extractor
    ou leitura de disco. Cada máscara cria apenas uma máscara local no seu bbox.
    """
    geometry = _mask_geometry(mask, sx, sy)
    if geometry is None:
        return None

    frame_h, frame_w = value_channel.shape[:2]
    local_mask = None
    crop = None

    if geometry[0] == "circle":
        _kind, center, axes = geometry
        cx, cy = int(center[0]), int(center[1])
        rx = max(1, int(round(float(axes[0]) * F3_LIVE_VISUAL_CORE_SCALE)))
        ry = max(1, int(round(float(axes[1]) * F3_LIVE_VISUAL_CORE_SCALE)))
        x1 = max(0, cx - rx - 1)
        y1 = max(0, cy - ry - 1)
        x2 = min(frame_w, cx + rx + 2)
        y2 = min(frame_h, cy + ry + 2)
        if x2 <= x1 or y2 <= y1:
            return None
        crop = value_channel[y1:y2, x1:x2]
        local_mask = np.zeros(crop.shape[:2], dtype=np.uint8)
        cv2.ellipse(
            local_mask,
            (cx - x1, cy - y1),
            (rx, ry),
            0,
            0,
            360,
            255,
            -1,
            cv2.LINE_8,
        )
    else:
        _kind, polygon = geometry
        points = np.asarray(polygon, dtype=np.float32).reshape(-1, 2)
        if len(points) < 3:
            return None
        center = np.mean(points, axis=0)
        core = center + (points - center) * float(F3_LIVE_VISUAL_CORE_SCALE)
        core = np.rint(core).astype(np.int32)
        x1 = max(0, int(np.min(core[:, 0])) - 1)
        y1 = max(0, int(np.min(core[:, 1])) - 1)
        x2 = min(frame_w, int(np.max(core[:, 0])) + 2)
        y2 = min(frame_h, int(np.max(core[:, 1])) + 2)
        if x2 <= x1 or y2 <= y1:
            return None
        crop = value_channel[y1:y2, x1:x2]
        local_mask = np.zeros(crop.shape[:2], dtype=np.uint8)
        shifted = core.copy()
        shifted[:, 0] -= x1
        shifted[:, 1] -= y1
        cv2.fillPoly(local_mask, [shifted], 255, lineType=cv2.LINE_8)

    values = crop[local_mask > 0]
    if values.size < 6:
        return None

    p_mid = float(
        np.percentile(values, F3_LIVE_VISUAL_SCORE_MID_PERCENTILE)
    )
    p_high = float(
        np.percentile(values, F3_LIVE_VISUAL_SCORE_HIGH_PERCENTILE)
    )
    score = (
        p_mid * (1.0 - F3_LIVE_VISUAL_HIGH_WEIGHT)
        + p_high * F3_LIVE_VISUAL_HIGH_WEIGHT
    )
    return score, p_high, int(values.size)


def detectar_emissao_visual_ao_vivo_f3(frame, context: dict | None) -> dict:
    """Detecta emissão apenas para apresentação no MESMO frame do preview.

    O resultado nunca entra em energia, analyzer, OK/NG ou sequência. A decisão
    produtiva continua desacoplada e pesada no executor canônico.
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return {"ready": False, "mask_ids": (), "reason": "frame_invalido"}
    if not isinstance(context, dict):
        return {"ready": False, "mask_ids": (), "reason": "contexto_ausente"}

    resolution = context.get("resolution")
    masks = tuple(context.get("masks") or ())
    if (
        not isinstance(resolution, (list, tuple))
        or len(resolution) < 2
        or not masks
    ):
        return {"ready": False, "mask_ids": (), "reason": "geometria_ausente"}

    try:
        value_channel = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[:, :, 2]
    except Exception:
        return {"ready": False, "mask_ids": (), "reason": "canal_v_indisponivel"}

    source_width = max(1, int(resolution[0]))
    source_height = max(1, int(resolution[1]))
    frame_height, frame_width = frame.shape[:2]
    sx = frame_width / float(source_width)
    sy = frame_height / float(source_height)

    rows = []
    for mask in masks:
        if not isinstance(mask, dict):
            continue
        mask_id = str(mask.get("id") or "")
        if not mask_id:
            continue
        stats = _live_visual_core_values(
            value_channel,
            mask,
            sx,
            sy,
        )
        if stats is None:
            continue
        score, p_high, pixel_count = stats
        rows.append(
            {
                "mask_id": mask_id,
                "score": float(score),
                "p_high": float(p_high),
                "pixel_count": int(pixel_count),
            }
        )

    if len(rows) < 3:
        return {
            "ready": False,
            "mask_ids": (),
            "sampled_mask_ids": tuple(
                str(row["mask_id"]) for row in rows
            ),
            "reason": "amostras_insuficientes",
            "sampled_mask_count": len(rows),
        }

    scores = np.asarray([row["score"] for row in rows], dtype=np.float32)
    baseline = float(
        np.percentile(scores, F3_LIVE_VISUAL_BASE_PERCENTILE)
    )
    peak = float(np.max(scores))
    dynamic_range = max(0.0, peak - baseline)

    adaptive_threshold = baseline + max(
        F3_LIVE_VISUAL_MIN_THRESHOLD_MARGIN,
        dynamic_range * F3_LIVE_VISUAL_THRESHOLD_RANGE_FRACTION,
    )

    # Quando a maioria das máscaras está acesa, o percentil 25 pode cair dentro
    # do próprio grupo ON. O maior gap dos ~28 scores é uma separação barata e
    # determinística entre o grupo escuro e o grupo luminoso no MESMO frame.
    sorted_scores = np.sort(scores)
    cluster_gap = 0.0
    cluster_threshold = None
    if sorted_scores.size >= 2:
        gaps = np.diff(sorted_scores)
        gap_index = int(np.argmax(gaps))
        cluster_gap = float(gaps[gap_index])
        if cluster_gap >= F3_LIVE_VISUAL_MIN_CLUSTER_GAP:
            cluster_threshold = float(
                (sorted_scores[gap_index] + sorted_scores[gap_index + 1]) / 2.0
            )

    threshold = float(adaptive_threshold)
    if cluster_threshold is not None:
        threshold = min(threshold, cluster_threshold)

    luminous = set()
    relative_evidence_ready = bool(
        peak >= F3_LIVE_VISUAL_MIN_PEAK
        and (
            dynamic_range >= F3_LIVE_VISUAL_MIN_DYNAMIC_RANGE
            or cluster_threshold is not None
        )
    )
    if relative_evidence_ready:
        minimum_high = max(
            F3_LIVE_VISUAL_MIN_PEAK,
            threshold + 4.0,
        )
        luminous.update(
            row["mask_id"]
            for row in rows
            if row["score"] >= threshold
            and row["p_high"] >= minimum_high
        )

    # Caso todos (ou quase todos) os segmentos estejam realmente acesos, pode
    # não existir grupo escuro suficiente para formar contraste global. Emissão
    # forte cobrindo o núcleo da própria ROI continua sendo evidência VISUAL.
    # Esta regra nunca entra em energia, OK/NG ou avanço de CHECK.
    luminous.update(
        row["mask_id"]
        for row in rows
        if row["score"] >= F3_LIVE_VISUAL_STRONG_SCORE
        and row["p_high"] >= F3_LIVE_VISUAL_STRONG_PEAK
    )
    luminous_ids = tuple(sorted(str(mask_id) for mask_id in luminous))

    return {
        "ready": True,
        "mask_ids": luminous_ids,
        "sampled_mask_ids": tuple(
            str(row["mask_id"]) for row in rows
        ),
        "reason": "ok",
        "sampled_mask_count": len(rows),
        "baseline": round(baseline, 2),
        "peak": round(peak, 2),
        "dynamic_range": round(dynamic_range, 2),
        "threshold": round(float(threshold), 2),
        "cluster_gap": round(cluster_gap, 2),
    }


def preparar_contexto_espelho_visual_f3(
    window,
    visual_frame,
    visual_rotation: int,
    *,
    frame_token=None,
    geometry_token=None,
) -> dict | None:
    """Monta o contexto único de câmera + máscaras + visor.

    Funciona com tracking ON e OFF. Tracking altera somente a geometria retornada
    por _project_preview_context; a semântica visual é sempre latest-frame.
    """
    context = _project_preview_context(
        window,
        int(visual_rotation or 0) % 360,
    )
    if not isinstance(context, dict):
        return None

    context = dict(context)
    context["visual_physical_classifications"] = (
        _latest_physical_visual_classifications(
            window,
            project_name=str(context.get("project_name") or ""),
        )
    )
    return aplicar_emissao_visual_ao_vivo_f3(
        window,
        visual_frame,
        context,
        frame_token=frame_token,
        geometry_token=geometry_token,
    )


def aplicar_emissao_visual_ao_vivo_f3(
    window,
    frame,
    context: dict | None,
    *,
    frame_token=None,
    geometry_token=None,
) -> dict | None:
    """Publica uma única amostra visual por frame para câmera + visor.

    Repaints do mesmo frame reutilizam cache. Assim o sincronismo visual não cria
    um segundo scheduler nem repete processamento quando a câmera não avançou.
    """
    if not isinstance(context, dict):
        return context

    result = dict(context)
    cache_key = (
        repr(frame_token),
        str(result.get("project_name") or ""),
        str(result.get("check_id") or ""),
        repr(geometry_token),
        tuple(getattr(frame, "shape", ()) or ()),
    )
    cached = getattr(window, "_display_f3_live_visual_sample_cache", None)
    if (
        isinstance(cached, dict)
        and cached.get("key") == cache_key
        and isinstance(cached.get("value"), dict)
    ):
        sample = dict(cached["value"])
    else:
        sample = detectar_emissao_visual_ao_vivo_f3(frame, result)
        window._display_f3_live_visual_sample_cache = {
            "key": cache_key,
            "value": dict(sample),
        }

    ready = bool(sample.get("ready"))
    sampled_on_ids = {
        str(mask_id)
        for mask_id in (sample.get("mask_ids") or ())
        if str(mask_id)
    }
    sampled_mask_ids = {
        str(mask_id)
        for mask_id in (sample.get("sampled_mask_ids") or ())
        if str(mask_id)
    }

    # Fallback físico: usado somente para máscaras que o sampler latest-frame
    # não conseguiu medir. Nunca carrega expected/matched/OK/NG.
    visual_states = {
        str(mask_id): str(state or "").strip().lower()
        for mask_id, state in dict(
            result.get("visual_physical_classifications") or {}
        ).items()
        if str(mask_id)
        and str(state or "").strip().lower()
        in {
            DISPLAY_CHECK_STATE_ON,
            DISPLAY_CHECK_STATE_OFF,
            DISPLAY_AUTO_CLASS_LOW_LIGHT,
        }
    }

    # D-035: quando a amostra do MESMO frame está pronta, ela manda no espelho
    # visual. Cada ROI amostrada vira ON ou OFF naquele repaint. Isso permite
    # tanto acender quanto apagar imediatamente, sem herdar ON stale de análise
    # assíncrona anterior.
    if ready:
        for mask_id in sampled_mask_ids:
            visual_states[mask_id] = (
                DISPLAY_CHECK_STATE_ON
                if mask_id in sampled_on_ids
                else DISPLAY_CHECK_STATE_OFF
            )

    visual_on_ids = {
        mask_id
        for mask_id, state in visual_states.items()
        if state == DISPLAY_CHECK_STATE_ON
    }
    mask_ids = tuple(sorted(visual_on_ids))

    result["live_visual_sample_ready"] = ready
    result["live_visual_mask_ids"] = mask_ids
    result["live_visual_classifications"] = dict(visual_states)
    result["live_visual_frame_token"] = frame_token
    result["live_visual_sample_source"] = "latest_preview_frame_core_v"
    result["live_visual_sample_reason"] = str(sample.get("reason") or "")
    result["live_visual_sample_threshold"] = sample.get("threshold")
    result["live_visual_sample_baseline"] = sample.get("baseline")
    result["live_visual_sample_peak"] = sample.get("peak")
    result["live_visual_sampled_mask_count"] = int(
        sample.get("sampled_mask_count", 0) or 0
    )
    result["live_visual_physical_classification_count"] = len(visual_states)

    # A emissão visual é compartilhada por câmera e visor. Nada aqui altera
    # classificação produtiva, conformidade, gate ou sequência.
    if ready or visual_states:
        result["luminous_mask_ids"] = mask_ids
        result["has_any_on"] = bool(mask_ids)

    try:
        window._display_f3_live_visual_sample = dict(sample)
    except Exception:
        pass
    return result


def _draw_mask(tint, mask: dict, sx: float, sy: float, color):
    geometry = _mask_geometry(mask, sx, sy)
    if geometry is None:
        return None
    if geometry[0] == "circle":
        _kind, center, axes = geometry
        cv2.ellipse(tint, center, axes, 0, 0, 360, color, -1, cv2.LINE_AA)
    else:
        _kind, polygon = geometry
        cv2.fillPoly(tint, [polygon], color, lineType=cv2.LINE_AA)
    return geometry


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
    confirmed_failed_mask_ids: set[str],
    validating_mask_ids: set[str],
    *,
    has_any_on: bool,
    intermittent: bool,
    effective_authority: bool,
) -> str | None:
    current = str(classifications.get(mask_id) or "").strip().lower()
    if effective_authority:
        if mask_id in confirmed_failed_mask_ids:
            return "alert"
        if mask_id in validating_mask_ids or mask_id in failed_mask_ids:
            return "warning"
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


def _render_classic_luminous_preview(
    frame,
    context: dict,
    sx: float,
    sy: float,
):
    """Preview operacional: espelho físico visual independente dos gates.

    Tracking ON ou OFF altera somente a geometria das ROIs. A apresentação do
    mesmo frame usa verde vivo para ON e verde escuro para OFF. Uma falha
    efetivamente confirmada pelo analyzer recebe vermelho com prioridade sobre o
    espelho luminoso, para que o frame que fechou o NG preserve visualmente o
    segmento defeituoso. Presença, energia, alinhamento produtivo e sequência não
    recriam a classificação.
    """

    result = frame.copy()
    masks = tuple(context.get("masks") or ())

    live_visual_ready = bool(context.get("live_visual_sample_ready"))
    live_visual_ids = {
        str(mask_id)
        for mask_id in (context.get("live_visual_mask_ids") or ())
        if str(mask_id)
    }
    fallback_luminous_ids = {
        str(mask_id)
        for mask_id in (context.get("luminous_mask_ids") or ())
        if str(mask_id)
    }
    visual_states = {
        str(mask_id): str(state or "").strip().lower()
        for mask_id, state in dict(
            context.get("live_visual_classifications") or {}
        ).items()
        if str(mask_id)
    }
    confirmed_failed_mask_ids = {
        str(mask_id)
        for mask_id in (
            context.get("effective_confirmed_failed_mask_ids") or ()
        )
        if str(mask_id)
    }

    # Câmera e visor recebem a mesma fonte visual composta. O mapa físico
    # permite mostrar os estados que o analyzer já reconheceu mesmo quando o
    # current_check avançou antes da publicação dessa análise.
    luminous_ids = set(live_visual_ids)
    if not live_visual_ready:
        luminous_ids.update(fallback_luminous_ids)
    luminous_ids.update(
        mask_id
        for mask_id, state in visual_states.items()
        if state == DISPLAY_CHECK_STATE_ON
    )

    board_points = context.get("board_points") or ()
    if len(board_points) >= 3:
        try:
            board = np.asarray(
                [
                    [
                        round(float(point[0]) * sx),
                        round(float(point[1]) * sy),
                    ]
                    for point in board_points
                ],
                dtype=np.int32,
            )
            cv2.polylines(
                result,
                [board],
                True,
                F3_PREVIEW_TRACKING_GUIDE_BGR,
                1,
                cv2.LINE_AA,
            )
        except Exception:
            pass

    green_tint = result.copy()
    off_tint = result.copy()
    alert_tint = result.copy()
    green_geometries = []
    off_geometries = []
    alert_geometries = []
    for mask in masks:
        if not isinstance(mask, dict):
            continue
        mask_id = str(mask.get("id") or "")
        geometry = _mask_geometry(mask, sx, sy)
        if geometry is None:
            continue
        visual_state = str(visual_states.get(mask_id) or "").strip().lower()
        if mask_id in confirmed_failed_mask_ids:
            geometry = _draw_mask(
                alert_tint,
                mask,
                sx,
                sy,
                F3_PREVIEW_CLEAR_COLORS["alert"],
            )
            if geometry is not None:
                alert_geometries.append(geometry)
            continue
        if mask_id in luminous_ids or visual_state == DISPLAY_CHECK_STATE_ON:
            geometry = _draw_mask(
                green_tint,
                mask,
                sx,
                sy,
                F3_PREVIEW_CLASSIC_LIGHT_BGR,
            )
            if geometry is not None:
                green_geometries.append(geometry)
        elif visual_state == DISPLAY_AUTO_CLASS_LOW_LIGHT:
            _draw_contour(
                result,
                geometry,
                F3_PREVIEW_CLEAR_COLORS["warning"],
                2,
            )
        elif visual_state == DISPLAY_CHECK_STATE_OFF:
            geometry = _draw_mask(
                off_tint,
                mask,
                sx,
                sy,
                F3_PREVIEW_CLASSIC_OFF_BGR,
            )
            if geometry is not None:
                off_geometries.append(geometry)
        else:
            _draw_contour(
                result,
                geometry,
                F3_PREVIEW_CLASSIC_MASK_BGR,
                1,
            )

    if off_geometries:
        cv2.addWeighted(
            off_tint,
            F3_PREVIEW_CLASSIC_OFF_ALPHA,
            result,
            1.0 - F3_PREVIEW_CLASSIC_OFF_ALPHA,
            0.0,
            dst=result,
        )
        for geometry in off_geometries:
            _draw_contour(
                result,
                geometry,
                F3_PREVIEW_CLASSIC_OFF_BGR,
                1,
            )

    if green_geometries:
        cv2.addWeighted(
            green_tint,
            F3_PREVIEW_CLASSIC_LIGHT_ALPHA,
            result,
            1.0 - F3_PREVIEW_CLASSIC_LIGHT_ALPHA,
            0.0,
            dst=result,
        )
        for geometry in green_geometries:
            _draw_contour(
                result,
                geometry,
                F3_PREVIEW_CLASSIC_LIGHT_BGR,
                2,
            )

    if alert_geometries:
        # D-045: o NG congelado deve apontar o componente que realmente falhou.
        # A fonte é effective_confirmed_failed_mask_ids da mesma análise
        # produtiva; não usamos failed_mask_ids bruto para evitar destacar
        # divergências transitórias de CHECK intermitente.
        cv2.addWeighted(
            alert_tint,
            F3_PREVIEW_ALERT_ALPHA,
            result,
            1.0 - F3_PREVIEW_ALERT_ALPHA,
            0.0,
            dst=result,
        )
        for geometry in alert_geometries:
            _draw_contour(
                result,
                geometry,
                F3_PREVIEW_CLEAR_COLORS["alert"],
                F3_PREVIEW_ALERT_CONTOUR_THICKNESS,
            )

    return result


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
    confirmed_failed_mask_ids: set[str],
    validating_mask_ids: set[str],
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
            confirmed_failed_mask_ids,
            validating_mask_ids,
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


def _render_terminal_segregated_preview(
    frame,
    context: dict,
    sx: float,
    sy: float,
):
    """Pinta toda a geometria live de vermelho sem alterar a semântica óptica."""
    result = frame.copy()
    tint = result.copy()
    alert = F3_PREVIEW_CLEAR_COLORS["alert"]
    geometries = []

    for mask in tuple(context.get("masks") or ()):
        if not isinstance(mask, dict):
            continue
        geometry = _draw_mask(tint, mask, sx, sy, alert)
        if geometry is not None:
            geometries.append(geometry)

    if geometries:
        cv2.addWeighted(
            tint,
            F3_PREVIEW_ALERT_ALPHA,
            result,
            1.0 - F3_PREVIEW_ALERT_ALPHA,
            0.0,
            dst=result,
        )
        for geometry in geometries:
            _draw_contour(
                result,
                geometry,
                alert,
                F3_PREVIEW_ALERT_CONTOUR_THICKNESS,
            )

    board_points = tuple(context.get("board_points") or ())
    if len(board_points) >= 3:
        try:
            board = np.asarray(
                [
                    [
                        int(round(float(point[0]) * sx)),
                        int(round(float(point[1]) * sy)),
                    ]
                    for point in board_points
                ],
                dtype=np.int32,
            )
            cv2.polylines(
                result,
                [board],
                True,
                alert,
                max(2, F3_PREVIEW_ALERT_CONTOUR_THICKNESS),
                cv2.LINE_AA,
            )
        except Exception:
            pass

    return result


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

    # SEGREGAR é um override exclusivamente visual e terminal. A classificação
    # física continua intacta no contexto/telemetria; somente a apresentação
    # produtiva fica integralmente vermelha até EMPTY.
    if bool(context.get("terminal_segregated")):
        return _render_terminal_segregated_preview(
            frame,
            context,
            sx,
            sy,
        )

    if bool(context.get("live_luminous_only")):
        return _render_classic_luminous_preview(
            frame,
            context,
            sx,
            sy,
        )

    classifications = {
        str(key): str(value).strip().lower()
        for key, value in dict(
            context.get("effective_classifications")
            or context.get("classifications")
            or {}
        ).items()
    }
    expected_states = {
        str(key): str(value).strip().lower()
        for key, value in dict(context.get("expected_states") or {}).items()
    }
    effective_failed_declared = "effective_failed_mask_ids" in context
    failed_mask_ids = {
        str(mask_id)
        for mask_id in (
            (
                context.get("effective_failed_mask_ids")
                if effective_failed_declared
                else context.get("failed_mask_ids")
            )
            or ()
        )
        if str(mask_id)
    }
    if not effective_failed_declared:
        failed_mask_ids.update(
            str(mask_id)
            for mask_id in dict(context.get("failed_masks") or {}).keys()
            if str(mask_id)
        )

    confirmed_failed_mask_ids = {
        str(mask_id)
        for mask_id in (
            context.get("effective_confirmed_failed_mask_ids") or ()
        )
        if str(mask_id)
    }
    validating_mask_ids = {
        str(mask_id)
        for mask_id in (
            context.get("effective_validating_mask_ids") or ()
        )
        if str(mask_id)
    }
    if not confirmed_failed_mask_ids and not validating_mask_ids:
        if bool(context.get("intermittent", False)) and effective_failed_declared:
            validating_mask_ids = set(failed_mask_ids)
        else:
            confirmed_failed_mask_ids = set(failed_mask_ids)

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
        confirmed_failed_mask_ids = set()
        validating_mask_ids = set()

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
            confirmed_failed_mask_ids,
            validating_mask_ids,
            has_any_on=has_any_on,
            intermittent=bool(context.get("intermittent", False)),
            effective_authority=effective_authority,
        )

        if presentation is None:
            continue

        color = F3_PREVIEW_CLEAR_COLORS[presentation]
        if presentation in {"alert", "warning"}:
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
                confirmed_failed_mask_ids,
                validating_mask_ids,
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
                F3_PREVIEW_CLEAR_COLORS[presentation],
            )
        alert_alpha = (
            F3_PREVIEW_ALERT_ALPHA
            if confirmed_failed_mask_ids
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
                confirmed_failed_mask_ids,
                validating_mask_ids,
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
            if mask_id not in confirmed_failed_mask_ids:
                continue
            _draw_failure_badge(
                result,
                mask,
                sx,
                sy,
                display_bbox,
            )

        if has_any_on and (semantic_power_ready or not energy_gate_declared):
            _draw_display_zoom_inset(
                source_for_inset,
                result,
                masks,
                sx,
                sy,
                classifications,
                expected_states,
                failed_mask_ids,
                confirmed_failed_mask_ids,
                validating_mask_ids,
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
