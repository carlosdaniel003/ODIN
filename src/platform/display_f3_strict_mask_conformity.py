from __future__ import annotations

"""Autoridade estrita de conformidade das mascaras do Display F3.

A foto salva de um CHECK continua util para presenca/estado visual, mas nao pode
ser a propria referencia que aprova os segmentos daquele CHECK. Caso contrario,
uma placa defeituosa fotografada durante a configuracao ensina o defeito como se
fosse o padrao correto.

Esta camada mantem ``mask_states`` como gabarito funcional e classifica cada
mascara contra exemplos ACESO/APAGADO vindos de OUTROS CHECKS. Qualquer mascara
configurada que divergir bloqueia o OK. O overlay e o status apenas exibem a
falha; eles nao participam do julgamento.
"""

import cv2

import src.platform.display_auto_check_runtime as runtime_module
import src.platform.display_f3_live_runtime_fix as live_runtime_module
import src.platform.display_f3_mask_status as mask_status_module
import src.platform.display_live_roi_overlay as overlay_module
from src.platform.display_auto_check_analyzer import DISPLAY_AUTO_CLASS_LOW_LIGHT
from src.platform.display_f3_same_mask_reference_fix import (
    F3SameMaskReferenceAnalyzer,
)
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
)


F3_STRICT_MASK_AUTHORITY = "f3_strict_cross_check_mask_states"
F3_STRICT_FAILED_MASK_BGR = (235, 99, 37)  # #2563EB
F3_STRICT_LOW_LIGHT_BGR = (21, 204, 250)   # #FACC15
F3_STRICT_FAILED_FILL_ALPHA = 0.24


def _normalized_check_id(value) -> str:
    return str(value or "").strip().upper()


def _filter_feature_source_pairs(features, sources, excluded_check_id: str):
    feature_list = list(features or ())
    source_list = list(sources or ())
    kept_features = []
    kept_sources = []

    for index, feature in enumerate(feature_list):
        source = source_list[index] if index < len(source_list) else {}
        source = dict(source) if isinstance(source, dict) else {}
        if (
            excluded_check_id
            and _normalized_check_id(source.get("check_id")) == excluded_check_id
        ):
            continue
        kept_features.append(feature)
        kept_sources.append(source)

    return kept_features, kept_sources


def filtrar_aprendizado_sem_check_atual_f3(
    learning: dict | None,
    check_id: str,
) -> dict:
    """Remove a foto do proprio CHECK de todos os pools usados para classifica-lo."""
    data = learning if isinstance(learning, dict) else {}
    excluded = _normalized_check_id(check_id)

    filtered_by_mask = {}
    source_by_mask = data.get("by_mask", {})
    if isinstance(source_by_mask, dict):
        for mask_id, raw_profile in source_by_mask.items():
            profile = raw_profile if isinstance(raw_profile, dict) else {}
            raw_sources = (
                profile.get("sources", {})
                if isinstance(profile.get("sources"), dict)
                else {}
            )
            filtered_profile = {
                DISPLAY_CHECK_STATE_ON: [],
                DISPLAY_CHECK_STATE_OFF: [],
                "sources": {
                    DISPLAY_CHECK_STATE_ON: [],
                    DISPLAY_CHECK_STATE_OFF: [],
                },
            }
            for state in (DISPLAY_CHECK_STATE_ON, DISPLAY_CHECK_STATE_OFF):
                features, sources = _filter_feature_source_pairs(
                    profile.get(state, []),
                    raw_sources.get(state, []),
                    excluded,
                )
                filtered_profile[state] = features
                filtered_profile["sources"][state] = sources
            filtered_by_mask[str(mask_id)] = filtered_profile

    filtered_by_state = {
        DISPLAY_CHECK_STATE_ON: [],
        DISPLAY_CHECK_STATE_OFF: [],
    }
    filtered_state_sources = {
        DISPLAY_CHECK_STATE_ON: [],
        DISPLAY_CHECK_STATE_OFF: [],
    }
    raw_by_state = data.get("by_state", {})
    raw_state_sources = data.get("state_sources", {})
    raw_by_state = raw_by_state if isinstance(raw_by_state, dict) else {}
    raw_state_sources = (
        raw_state_sources if isinstance(raw_state_sources, dict) else {}
    )

    for state in (DISPLAY_CHECK_STATE_ON, DISPLAY_CHECK_STATE_OFF):
        features, sources = _filter_feature_source_pairs(
            raw_by_state.get(state, []),
            raw_state_sources.get(state, []),
            excluded,
        )
        filtered_by_state[state] = features
        filtered_state_sources[state] = sources

    remaining_photos = {
        _normalized_check_id(source.get("check_id"))
        for sources in filtered_state_sources.values()
        for source in sources
        if isinstance(source, dict) and _normalized_check_id(source.get("check_id"))
    }
    sample_count = sum(len(items) for items in filtered_by_state.values())

    return {
        "by_mask": filtered_by_mask,
        "by_state": filtered_by_state,
        "state_sources": filtered_state_sources,
        "photo_count": len(remaining_photos),
        "sample_count": int(sample_count),
        "excluded_check_id": excluded,
        "self_reference_excluded": True,
    }


def resumir_falhas_mascaras_f3(analysis: dict | None) -> dict:
    data = analysis if isinstance(analysis, dict) else {}
    results = [
        item
        for item in (data.get("mask_results") or ())
        if isinstance(item, dict)
    ]
    failed = [item for item in results if not bool(item.get("matched"))]
    missing_on = [
        item
        for item in failed
        if str(item.get("expected") or "") == DISPLAY_CHECK_STATE_ON
        and str(item.get("classified") or "") == DISPLAY_CHECK_STATE_OFF
    ]
    unexpected_on = [
        item
        for item in failed
        if str(item.get("expected") or "") == DISPLAY_CHECK_STATE_OFF
        and str(item.get("classified") or "") == DISPLAY_CHECK_STATE_ON
    ]
    low_light = [
        item
        for item in failed
        if str(item.get("classified") or "") == DISPLAY_AUTO_CLASS_LOW_LIGHT
    ]

    expected_on_count = sum(
        1 for item in results if str(item.get("expected") or "") == DISPLAY_CHECK_STATE_ON
    )
    expected_off_count = sum(
        1 for item in results if str(item.get("expected") or "") == DISPLAY_CHECK_STATE_OFF
    )
    classified_on_count = sum(
        1 for item in results if str(item.get("classified") or "") == DISPLAY_CHECK_STATE_ON
    )
    classified_off_count = sum(
        1 for item in results if str(item.get("classified") or "") == DISPLAY_CHECK_STATE_OFF
    )

    return {
        "failed_mask_ids": [str(item.get("mask_id") or "") for item in failed],
        "missing_on_mask_ids": [str(item.get("mask_id") or "") for item in missing_on],
        "unexpected_on_mask_ids": [
            str(item.get("mask_id") or "") for item in unexpected_on
        ],
        "low_light_mask_ids": [str(item.get("mask_id") or "") for item in low_light],
        "expected_on_mask_count": int(expected_on_count),
        "expected_off_mask_count": int(expected_off_count),
        "classified_on_mask_count": int(classified_on_count),
        "classified_off_mask_count": int(classified_off_count),
    }


class F3StrictMaskConformityAnalyzer(F3SameMaskReferenceAnalyzer):
    """Classifica o CHECK sem permitir que sua propria foto o aprove."""

    def __init__(self, repository) -> None:
        self._strict_current_check_id = ""
        super().__init__(repository)

    def _check_photo_learning(
        self,
        project_name: str,
        project: dict,
        masks: list[dict],
        visual_rotation: int,
    ) -> dict:
        global_learning = super()._check_photo_learning(
            project_name,
            project,
            masks,
            visual_rotation,
        )
        return filtrar_aprendizado_sem_check_atual_f3(
            global_learning,
            self._strict_current_check_id,
        )

    def analyze(
        self,
        frame,
        project_name: str,
        check_id: str,
        visual_rotation: int = 0,
    ) -> dict:
        previous = self._strict_current_check_id
        self._strict_current_check_id = _normalized_check_id(check_id)
        try:
            analysis = super().analyze(
                frame=frame,
                project_name=project_name,
                check_id=check_id,
                visual_rotation=visual_rotation,
            )
        finally:
            self._strict_current_check_id = previous

        if not isinstance(analysis, dict):
            return analysis

        analysis["reference_authority"] = F3_STRICT_MASK_AUTHORITY
        analysis["self_reference_excluded"] = True
        analysis["excluded_reference_check_id"] = _normalized_check_id(check_id)

        if not bool(analysis.get("ready")):
            return analysis

        summary = resumir_falhas_mascaras_f3(analysis)
        analysis.update(summary)

        failed_ids = list(summary.get("failed_mask_ids") or ())
        if failed_ids:
            # Uma unica mascara configurada divergente basta para impedir OK.
            # O debounce/politica do runtime continua decidindo quando a falha
            # confirmada vira NG oficial; esta camada nunca reduz esse debounce.
            analysis["approved"] = False
            analysis["reason"] = "check_diverge_mascara_configurada"
        else:
            analysis["approved"] = True
            analysis["reason"] = "check_conforme_mascaras_configuradas"
        return analysis


def _failure_items(analysis: dict | None) -> dict[str, dict]:
    data = analysis if isinstance(analysis, dict) else {}
    result = {}
    for item in data.get("mask_results", []) or []:
        if not isinstance(item, dict) or bool(item.get("matched")):
            continue
        mask_id = str(item.get("mask_id") or "")
        if mask_id:
            result[mask_id] = {
                "expected": str(item.get("expected") or ""),
                "classified": str(item.get("classified") or ""),
                "expected_label": str(item.get("expected_label") or ""),
                "classified_label": str(item.get("classified_label") or ""),
            }
    return result


def _install_failed_mask_overlay() -> None:
    if bool(getattr(overlay_module, "_display_f3_strict_failure_overlay", False)):
        return

    original_context = overlay_module._overlay_context
    original_render = overlay_module.renderizar_overlay_rois_display_f3

    def overlay_context(window, visual_rotation: int):
        context = original_context(window, visual_rotation)
        if not isinstance(context, dict):
            return context
        app = overlay_module._app_from_window(window)
        analysis = getattr(app, "_display_auto_last_analysis", None) if app else None
        result = dict(context)
        # O contexto base só publica classifications quando a analise pertence ao
        # CHECK logico atual. Assim nao reaproveitamos uma falha do CHECK anterior.
        result["failed_masks"] = (
            _failure_items(analysis)
            if dict(result.get("classifications") or {})
            else {}
        )
        return result

    def render(frame, context):
        rendered = original_render(frame, context)
        if rendered is None or getattr(rendered, "size", 0) == 0:
            return rendered
        if not isinstance(context, dict):
            return rendered

        failed = dict(context.get("failed_masks") or {})
        resolution = context.get("resolution")
        masks = tuple(context.get("masks") or ())
        if not failed or not isinstance(resolution, (list, tuple)) or len(resolution) < 2:
            return rendered

        source_width = max(1, int(resolution[0]))
        source_height = max(1, int(resolution[1]))
        frame_height, frame_width = rendered.shape[:2]
        sx = frame_width / float(source_width)
        sy = frame_height / float(source_height)

        tint = rendered.copy()
        geometries = []
        for mask in masks:
            if not isinstance(mask, dict):
                continue
            mask_id = str(mask.get("id") or "")
            failure = failed.get(mask_id)
            if not isinstance(failure, dict):
                continue
            classified = str(failure.get("classified") or "")
            color = (
                F3_STRICT_LOW_LIGHT_BGR
                if classified == DISPLAY_AUTO_CLASS_LOW_LIGHT
                else F3_STRICT_FAILED_MASK_BGR
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
                geometries.append(("circle", (center, axes), color, mask_id))
            else:
                polygon = overlay_module._scaled_polygon(mask, sx, sy)
                if polygon is None or len(polygon) < 3:
                    continue
                cv2.fillPoly(tint, [polygon], color, lineType=cv2.LINE_AA)
                geometries.append(("polygon", polygon, color, mask_id))

        if not geometries:
            return rendered

        cv2.addWeighted(
            tint,
            F3_STRICT_FAILED_FILL_ALPHA,
            rendered,
            1.0 - F3_STRICT_FAILED_FILL_ALPHA,
            0.0,
            dst=rendered,
        )
        thickness = max(3, int(round(min(frame_width, frame_height) / 220.0)))
        font_scale = max(0.42, min(0.8, min(frame_width, frame_height) / 1400.0))

        for kind, geometry, color, mask_id in geometries:
            if kind == "circle":
                center, axes = geometry
                cv2.ellipse(
                    rendered,
                    center,
                    axes,
                    0,
                    0,
                    360,
                    color,
                    thickness,
                    cv2.LINE_AA,
                )
                anchor = center
            else:
                polygon = geometry
                cv2.polylines(
                    rendered,
                    [polygon],
                    True,
                    color,
                    thickness,
                    cv2.LINE_AA,
                )
                moments = cv2.moments(polygon)
                if abs(float(moments.get("m00", 0.0))) > 1e-9:
                    anchor = (
                        int(moments["m10"] / moments["m00"]),
                        int(moments["m01"] / moments["m00"]),
                    )
                else:
                    point = polygon.reshape(-1, 2)[0]
                    anchor = (int(point[0]), int(point[1]))

            cv2.putText(
                rendered,
                f"NG {mask_id}",
                (max(2, anchor[0] - 24), max(14, anchor[1] - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                font_scale,
                color,
                max(1, thickness // 2),
                cv2.LINE_AA,
            )

        return rendered

    overlay_module._overlay_context = overlay_context
    overlay_module.renderizar_overlay_rois_display_f3 = render
    overlay_module.DISPLAY_ROI_OVERLAY_LEGEND = (
        "VERDE: ACESO  •  VERMELHO: APAGADO  •  AMARELO: POUCA LUZ  •  "
        "AZUL FORTE: MÁSCARA NG"
    )
    overlay_module._display_f3_strict_failure_overlay = True


def _install_failed_mask_status() -> None:
    if bool(getattr(mask_status_module, "_display_f3_strict_failure_status", False)):
        return

    original_format = mask_status_module.formatar_status_mascaras_f3

    def format_status(analysis: dict | None, context: dict | None):
        text, color = original_format(analysis, context)
        if not isinstance(analysis, dict) or not bool(analysis.get("ready")):
            return text, color
        failures = _failure_items(analysis)
        if not failures:
            return text, color

        first_id, failure = next(iter(failures.items()))
        expected = str(
            failure.get("expected_label") or failure.get("expected") or "?"
        ).upper()
        classified = str(
            failure.get("classified_label") or failure.get("classified") or "?"
        ).upper()
        suffix = f" • FALHA {first_id}: {expected}→{classified}"
        remaining = len(failures) - 1
        if remaining > 0:
            suffix += f" (+{remaining})"
        return text + suffix, "#60A5FA"

    mask_status_module.formatar_status_mascaras_f3 = format_status
    mask_status_module._display_f3_strict_failure_status = True


def _install_manual_debug_authority() -> None:
    # O Debug Tecnico continua mostrando o gabarito fotografico como diagnostico,
    # mas a secao de aprendizado usa a mesma autoridade estrita da producao.
    try:
        import src.platform.display_f3_manual_snapshot_debug as debug_module

        debug_module.F3SameMaskReferenceAnalyzer = F3StrictMaskConformityAnalyzer
        debug_module._display_f3_strict_mask_authority = True
    except Exception:
        pass


def _install_positive_probe_authority() -> None:
    """Impede H1/BLUE de avançarem por auto-referencia da foto do proprio CHECK."""
    try:
        import src.platform.display_f3_live_diagnostic_trace as trace_module

        trace_module.F3ExactCheckTemplateAnalyzer = F3StrictMaskConformityAnalyzer
        trace_module._display_f3_strict_positive_probe = True
    except Exception:
        pass

    # A camada historica da sonda restaura um alias capturado no import. Mantemos
    # esse alias coerente caso algum instalador seja reinvocado no mesmo processo.
    try:
        import src.platform.display_f3_h1_single_frame_probe as probe_module

        probe_module.LearnedDisplayAutomaticCheckAnalyzer = (
            F3StrictMaskConformityAnalyzer
        )
    except Exception:
        pass


_INSTALLED = False


def instalar_conformidade_estrita_mascaras_display_f3() -> None:
    """Torna a conformidade por mascara a autoridade final somente do F3."""
    global _INSTALLED

    # Estas atribuicoes sao idempotentes e ficam fora do guard para que nenhuma
    # camada historica consiga recolocar o analisador fotografico/generico depois.
    runtime_module.DisplayAutomaticCheckAnalyzer = F3StrictMaskConformityAnalyzer
    live_runtime_module.DisplayAutomaticCheckAnalyzer = F3StrictMaskConformityAnalyzer
    _install_positive_probe_authority()

    if _INSTALLED:
        return

    _install_failed_mask_overlay()
    _install_failed_mask_status()
    _install_manual_debug_authority()
    _INSTALLED = True
