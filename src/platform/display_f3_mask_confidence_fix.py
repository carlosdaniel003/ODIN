from __future__ import annotations

"""Correcoes finais de discriminacao e apresentacao exclusivas do Display F3.

O Debug Tecnico mostrou dois problemas relacionados:

* mascaras que permanecem ACESAS em todos os CHECKS (como MASK_008/MASK_009)
  ficavam sem uma amostra APAGADA da mesma mascara depois que a foto do CHECK
  atual era excluida. O analisador caia para um pool de OUTRAS mascaras e podia
  inverter um segmento claramente aceso;
* quando a comparacao global de fotos ficava ambigua, o status visual continuava
  em ``IDENTIFICANDO...`` mesmo depois de a autoridade por mascaras confirmar
  integralmente o CHECK atual.

A referencia ``PLACA DESLIGADA NO SUPORTE`` e uma amostra APAGADA fisicamente
valida para TODAS as mascaras. Esta camada a injeta como referencia OFF da mesma
mascara, preservando a regra de nao usar a foto do proprio CHECK para aprova-lo.
Tambem padroniza a paleta do preview ao vivo:

- verde: aceso;
- amarelo: pouca luz;
- vermelho: falha/NG;
- azul: apagado.

Nada deste modulo altera Produção F2.
"""

from copy import deepcopy
from pathlib import Path

import cv2

import src.platform.display_f3_operational_status as operational_module
import src.platform.display_f3_strict_mask_conformity as strict_module
import src.platform.display_f3_visual_analysis_relative_fallback as visual_module
import src.platform.display_live_roi_overlay as overlay_module
from src.core.feature_extractor import extrair_features_selecao
from src.platform.display_auto_check_analyzer import display_mask_to_analysis_selection
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
    normalizar_resolucao_display,
)
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DisplayProjectPresenceReferenceStore,
)
from src.platform.display_visual_rotation import preparar_check_visual_display


F3_PREVIEW_ON_BGR = (94, 197, 34)       # #22C55E
F3_PREVIEW_LOW_LIGHT_BGR = (21, 204, 250)  # #FACC15
F3_PREVIEW_FAILURE_BGR = (68, 68, 239)   # #EF4444
F3_PREVIEW_OFF_BGR = (246, 130, 59)      # #3B82F6
F3_PREVIEW_UNKNOWN_BGR = (184, 163, 148) # #94A3B8

F3_PREVIEW_LEGEND = (
    "VERDE: ACESO  •  AMARELO: POUCA LUZ  •  "
    "VERMELHO: FALHA  •  AZUL: APAGADO"
)
F3_BOARD_OFF_REFERENCE_ID = "__BOARD_OFF__"
F3_VISUAL_MASK_FALLBACK_SOURCE = "f3_current_check_masks_visual_fallback"


def _valid_image(image) -> bool:
    return image is not None and getattr(image, "size", 0) > 0


def _board_off_metadata(analyzer, project_name: str) -> dict | None:
    store = getattr(analyzer, "_strict_project_presence_store", None)
    if store is None:
        try:
            store = DisplayProjectPresenceReferenceStore(analyzer.repository)
        except Exception:
            return None
        analyzer._strict_project_presence_store = store
    try:
        metadata = store.get(project_name, DISPLAY_PROJECT_REFERENCE_BOARD_OFF)
    except Exception:
        return None
    return metadata if isinstance(metadata, dict) else None


def _board_off_file_signature(analyzer, project_name: str) -> tuple:
    metadata = _board_off_metadata(analyzer, project_name)
    path = Path(str((metadata or {}).get("image_path") or ""))
    try:
        stat = path.stat()
        return (str(path), int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return (str(path), 0, 0)


def _append_board_off_same_mask_samples(
    analyzer,
    learning: dict,
    *,
    project_name: str,
    project: dict,
    masks: list[dict],
    visual_rotation: int,
) -> dict:
    """Acrescenta a foto da placa desligada como OFF da MESMA mascara fisica."""
    if not isinstance(learning, dict):
        return learning

    metadata = _board_off_metadata(analyzer, project_name)
    path = Path(str((metadata or {}).get("image_path") or ""))
    image = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.is_file() else None
    if not _valid_image(image):
        learning["board_off_same_mask_sample_count"] = 0
        learning["board_off_same_mask_available"] = False
        return learning

    master_resolution = normalizar_resolucao_display(project.get("master_resolution"))
    if master_resolution is None:
        learning["board_off_same_mask_sample_count"] = 0
        learning["board_off_same_mask_available"] = False
        return learning

    visual_frame, visual_resolution, visual_masks = preparar_check_visual_display(
        image,
        master_resolution,
        masks,
        visual_rotation,
    )
    if not _valid_image(visual_frame):
        learning["board_off_same_mask_sample_count"] = 0
        learning["board_off_same_mask_available"] = False
        return learning

    target_width = max(1, int(visual_resolution[0]))
    target_height = max(1, int(visual_resolution[1]))
    if tuple(visual_frame.shape[:2]) != (target_height, target_width):
        visual_frame = cv2.resize(
            visual_frame,
            (target_width, target_height),
            interpolation=cv2.INTER_AREA,
        )

    visual_by_id = {
        str(mask.get("id")): mask
        for mask in visual_masks
        if isinstance(mask, dict) and mask.get("id") is not None
    }
    by_mask = learning.setdefault("by_mask", {})
    by_state = learning.setdefault(
        "by_state",
        {DISPLAY_CHECK_STATE_ON: [], DISPLAY_CHECK_STATE_OFF: []},
    )
    state_sources = learning.setdefault(
        "state_sources",
        {DISPLAY_CHECK_STATE_ON: [], DISPLAY_CHECK_STATE_OFF: []},
    )
    by_state.setdefault(DISPLAY_CHECK_STATE_ON, [])
    by_state.setdefault(DISPLAY_CHECK_STATE_OFF, [])
    state_sources.setdefault(DISPLAY_CHECK_STATE_ON, [])
    state_sources.setdefault(DISPLAY_CHECK_STATE_OFF, [])

    added = 0
    for original_mask in masks:
        if not isinstance(original_mask, dict):
            continue
        mask_id = str(original_mask.get("id") or "")
        visual_mask = visual_by_id.get(mask_id)
        if not mask_id or visual_mask is None:
            continue
        try:
            selection = display_mask_to_analysis_selection(visual_mask)
            features = extrair_features_selecao(visual_frame, selection)
        except (TypeError, ValueError):
            continue
        if int(getattr(features, "area_pixels", 0) or 0) <= 0:
            continue

        profile = by_mask.setdefault(
            mask_id,
            {
                DISPLAY_CHECK_STATE_ON: [],
                DISPLAY_CHECK_STATE_OFF: [],
                "sources": {
                    DISPLAY_CHECK_STATE_ON: [],
                    DISPLAY_CHECK_STATE_OFF: [],
                },
            },
        )
        profile.setdefault(DISPLAY_CHECK_STATE_ON, [])
        profile.setdefault(DISPLAY_CHECK_STATE_OFF, [])
        sources = profile.setdefault(
            "sources",
            {DISPLAY_CHECK_STATE_ON: [], DISPLAY_CHECK_STATE_OFF: []},
        )
        sources.setdefault(DISPLAY_CHECK_STATE_ON, [])
        sources.setdefault(DISPLAY_CHECK_STATE_OFF, [])

        source = {
            "check_id": F3_BOARD_OFF_REFERENCE_ID,
            "check_name": "PLACA DESLIGADA NO SUPORTE",
            "mask_id": mask_id,
            "state": DISPLAY_CHECK_STATE_OFF,
            "reference_kind": DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
        }
        profile[DISPLAY_CHECK_STATE_OFF].append(features)
        sources[DISPLAY_CHECK_STATE_OFF].append(source)
        by_state[DISPLAY_CHECK_STATE_OFF].append(features)
        state_sources[DISPLAY_CHECK_STATE_OFF].append(source)
        added += 1

    learning["sample_count"] = int(learning.get("sample_count", 0) or 0) + added
    learning["board_off_same_mask_sample_count"] = int(added)
    learning["board_off_same_mask_available"] = bool(added)
    learning["board_off_same_mask_source"] = DISPLAY_PROJECT_REFERENCE_BOARD_OFF
    return learning


def _install_board_off_same_mask_learning() -> None:
    cls = strict_module.F3StrictMaskConformityAnalyzer
    if bool(getattr(cls, "_display_f3_board_off_same_mask_fix", False)):
        return

    original_init = cls.__init__
    original_signature = cls._check_photo_signature
    original_build = cls._build_check_photo_learning

    def init(self, repository) -> None:
        original_init(self, repository)
        self._strict_project_presence_store = DisplayProjectPresenceReferenceStore(
            repository
        )

    def signature(self, project_name: str, project: dict, visual_rotation: int):
        base = original_signature(self, project_name, project, visual_rotation)
        return (
            base,
            "board_off_same_mask",
            _board_off_file_signature(self, project_name),
        )

    def build(self, project_name, project, masks, visual_rotation):
        learning = original_build(
            self,
            project_name,
            project,
            masks,
            visual_rotation,
        )
        return _append_board_off_same_mask_samples(
            self,
            learning,
            project_name=project_name,
            project=project,
            masks=list(masks or ()),
            visual_rotation=visual_rotation,
        )

    cls.__init__ = init
    cls._check_photo_signature = signature
    cls._build_check_photo_learning = build
    cls._display_f3_board_off_same_mask_fix = True


def _analysis_confirms_current_check(app, project_name: str) -> dict | None:
    analysis = getattr(app, "_display_auto_last_analysis", None)
    if not isinstance(analysis, dict) or not bool(analysis.get("ready")):
        return None
    if analysis.get("approved") is not True:
        return None
    if str(analysis.get("project_name") or "") != str(project_name or ""):
        return None

    try:
        context = app._display_auto_current_context()
    except Exception:
        context = None
    if not isinstance(context, dict):
        return None

    check_id = str(context.get("check_id") or "")
    if not check_id or str(analysis.get("check_id") or "") != check_id:
        return None

    try:
        active = int(analysis.get("active_mask_count", 0) or 0)
        matched = int(analysis.get("matched_mask_count", 0) or 0)
    except (TypeError, ValueError):
        active = matched = 0

    if active <= 0:
        results = [
            item
            for item in (analysis.get("mask_results") or ())
            if isinstance(item, dict)
        ]
        active = len(results)
        matched = sum(1 for item in results if bool(item.get("matched")))
    if active <= 0 or matched < active:
        return None

    return {
        "check_id": check_id,
        "check_name": str(
            context.get("check_name")
            or analysis.get("check_name")
            or check_id
        ).strip().upper(),
        "active": active,
        "matched": matched,
        "authority": str(analysis.get("reference_authority") or ""),
    }


def _install_visual_status_mask_fallback() -> None:
    if bool(getattr(visual_module, "_display_f3_mask_visual_fallback_fix", False)):
        return

    original_build = visual_module._build_visual_analysis_state

    def build(self, frame, project_name: str) -> dict:
        state = original_build(self, frame, project_name)
        if not isinstance(state, dict):
            return state
        if str(state.get("result_kind") or "") not in {"ambiguous", "unidentified"}:
            return state

        confirmed = _analysis_confirms_current_check(self, project_name)
        if confirmed is None:
            return state

        result = deepcopy(state)
        result["reference_only_result_kind"] = state.get("result_kind")
        result["reference_only_decision_mode"] = state.get("decision_mode")
        result["reference_only_best_reference"] = state.get("best_reference")
        result["reference_only_score_margin"] = state.get("score_margin")
        result.update(
            {
                "text": (
                    f"ANÁLISE VISUAL: CHECK {confirmed['check_name']} • "
                    f"máscaras {confirmed['matched']}/{confirmed['active']}"
                ),
                "color": operational_module.F3_OPERATIONAL_STATUS_COLORS["check"],
                "result_kind": "check",
                "selected_reference": f"check:{confirmed['check_id']}",
                "decision_mode": "mask_conformity_fallback",
                "relative_fallback": False,
                "check_id": confirmed["check_id"],
                "check_name": confirmed["check_name"],
                "uses_masks": True,
                "uses_check_state": True,
                "mask_conformity_fallback": True,
                "mask_fallback_source": F3_VISUAL_MASK_FALLBACK_SOURCE,
                "mask_fallback_authority": confirmed["authority"],
                "mask_matched_count": confirmed["matched"],
                "mask_active_count": confirmed["active"],
                "informational_only": True,
                "affects_result": False,
            }
        )
        return result

    visual_module._build_visual_analysis_state = build
    visual_module._display_f3_mask_visual_fallback_fix = True


def _install_preview_palette() -> None:
    overlay_module.DISPLAY_ROI_OVERLAY_COLORS.update(
        {
            "on": F3_PREVIEW_ON_BGR,
            "off": F3_PREVIEW_OFF_BGR,
            "low_light": F3_PREVIEW_LOW_LIGHT_BGR,
            "unknown": F3_PREVIEW_UNKNOWN_BGR,
        }
    )
    strict_module.F3_STRICT_FAILED_MASK_BGR = F3_PREVIEW_FAILURE_BGR
    strict_module.F3_STRICT_LOW_LIGHT_BGR = F3_PREVIEW_LOW_LIGHT_BGR
    overlay_module.DISPLAY_ROI_OVERLAY_LEGEND = F3_PREVIEW_LEGEND

    # O instalador de falhas estritas define sua propria legenda depois. Mantemos
    # a paleta pedida mesmo quando esse instalador for executado mais tarde.
    if not bool(getattr(strict_module, "_display_f3_palette_post_install_fix", False)):
        original = strict_module._install_failed_mask_overlay

        def install_failed_mask_overlay() -> None:
            original()
            overlay_module.DISPLAY_ROI_OVERLAY_COLORS.update(
                {
                    "on": F3_PREVIEW_ON_BGR,
                    "off": F3_PREVIEW_OFF_BGR,
                    "low_light": F3_PREVIEW_LOW_LIGHT_BGR,
                    "unknown": F3_PREVIEW_UNKNOWN_BGR,
                }
            )
            strict_module.F3_STRICT_FAILED_MASK_BGR = F3_PREVIEW_FAILURE_BGR
            strict_module.F3_STRICT_LOW_LIGHT_BGR = F3_PREVIEW_LOW_LIGHT_BGR
            overlay_module.DISPLAY_ROI_OVERLAY_LEGEND = F3_PREVIEW_LEGEND

        strict_module._install_failed_mask_overlay = install_failed_mask_overlay
        strict_module._display_f3_palette_post_install_fix = True


_INSTALLED = False


def instalar_correcao_confianca_mascaras_display_f3() -> None:
    """Instala as correcoes somente sobre classes e renderizadores do F3."""
    global _INSTALLED
    if _INSTALLED:
        return
    _install_board_off_same_mask_learning()
    _install_visual_status_mask_fallback()
    _install_preview_palette()
    _INSTALLED = True
