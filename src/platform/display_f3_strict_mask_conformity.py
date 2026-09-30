from __future__ import annotations

"""Autoridade estrita de conformidade das mascaras do Display F3.

A foto salva de um CHECK continua util para presenca/estado visual, mas nao pode
ser a propria referencia que aprova os segmentos daquele CHECK. Caso contrario,
uma placa defeituosa fotografada durante a configuracao ensina o defeito como se
fosse o padrao correto.

Esta camada mantem ``mask_states`` como gabarito funcional e usa prioritariamente
exemplos ACESO/APAGADO vindos de OUTROS CHECKS. A foto do proprio CHECK continua
fora dos pools globais e nunca fornece referencia OFF para se autoaprovar. Uma
referencia ON do proprio CHECK so pode voltar ao pool LOCAL da mesma mascara
quando sua emissao e fisicamente discriminante de todas as referencias OFF da
mesma mascara. Isso preserva a rejeicao estrita sem transformar variacoes de
brilho entre funcoes em falso APAGADO. Qualquer mascara configurada que divergir
bloqueia o OK. O overlay e o status apenas exibem a falha; eles nao participam
do julgamento.
"""

import cv2

import src.platform.display_auto_check_runtime as runtime_module
import src.platform.display_f3_live_runtime_fix as live_runtime_module
import src.platform.display_f3_mask_status as mask_status_module
import src.platform.display_live_roi_overlay as overlay_module
from src.platform.display_auto_check_analyzer import DISPLAY_AUTO_CLASS_LOW_LIGHT
from src.platform.display_f3_same_mask_reference_fix import (
    F3SameMaskReferenceAnalyzer,
    F3_LOW_LIGHT_MIN_ENERGY_SPAN,
    _optical_energy,
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


def reinjetar_on_proprio_validado_f3(
    global_learning: dict | None,
    filtered_learning: dict | None,
    check_id: str,
) -> dict:
    """Reintroduz somente ON proprio que prove emissao contra OFF da mesma mascara.

    A exclusao integral da foto atual evita autoaprendizado de defeito, mas pode
    gerar falso OFF quando a mesma mascara possui intensidade/cor diferente entre
    funcoes. A excecao abaixo e propositalmente assimetrica:

    - nunca reintroduz OFF do CHECK atual;
    - nunca alimenta o pool global;
    - exige ao menos uma referencia OFF da MESMA mascara vinda de outra captura;
    - exige separacao de energia optica maior ou igual ao limiar fisico ja usado
      pelo aprendizado de pouca luz.

    Assim uma foto configurada com segmento esperado ON, porem realmente apagado,
    continua incapaz de ensinar o defeito como correto.
    """
    result = filtered_learning if isinstance(filtered_learning, dict) else {}
    global_data = global_learning if isinstance(global_learning, dict) else {}
    current_check_id = _normalized_check_id(check_id)
    if not current_check_id:
        result["validated_self_on_mask_ids"] = ()
        result["validated_self_on_reference_count"] = 0
        result["self_reference_policy"] = "exclude_current_except_validated_self_on"
        return result

    global_by_mask = (
        global_data.get("by_mask", {})
        if isinstance(global_data.get("by_mask"), dict)
        else {}
    )
    filtered_by_mask = (
        result.get("by_mask", {})
        if isinstance(result.get("by_mask"), dict)
        else {}
    )

    validated_mask_ids = []
    validated_reference_count = 0

    for mask_id, filtered_profile in filtered_by_mask.items():
        if not isinstance(filtered_profile, dict):
            continue
        global_profile = global_by_mask.get(str(mask_id), {})
        if not isinstance(global_profile, dict):
            continue

        global_sources = (
            global_profile.get("sources", {})
            if isinstance(global_profile.get("sources"), dict)
            else {}
        )
        on_features = list(global_profile.get(DISPLAY_CHECK_STATE_ON, []) or ())
        on_sources = list(global_sources.get(DISPLAY_CHECK_STATE_ON, []) or ())
        off_references = list(
            filtered_profile.get(DISPLAY_CHECK_STATE_OFF, []) or ()
        )
        if not off_references:
            continue

        try:
            off_energy_ceiling = max(
                _optical_energy(reference)
                for reference in off_references
            )
        except Exception:
            continue

        profile_sources = filtered_profile.get("sources")
        if not isinstance(profile_sources, dict):
            profile_sources = {
                DISPLAY_CHECK_STATE_ON: [],
                DISPLAY_CHECK_STATE_OFF: [],
            }
            filtered_profile["sources"] = profile_sources
        local_on_sources = profile_sources.setdefault(
            DISPLAY_CHECK_STATE_ON,
            [],
        )
        local_on_features = filtered_profile.setdefault(
            DISPLAY_CHECK_STATE_ON,
            [],
        )

        for index, feature in enumerate(on_features):
            source = on_sources[index] if index < len(on_sources) else {}
            source = dict(source) if isinstance(source, dict) else {}
            if _normalized_check_id(source.get("check_id")) != current_check_id:
                continue

            try:
                energy_gap = float(_optical_energy(feature)) - float(
                    off_energy_ceiling
                )
            except Exception:
                continue
            if energy_gap < float(F3_LOW_LIGHT_MIN_ENERGY_SPAN):
                continue

            validated_source = dict(source)
            validated_source["validated_self_on"] = True
            validated_source["validation"] = (
                "optical_energy_above_other_same_mask_off"
            )
            validated_source["energy_gap_to_off_ceiling"] = round(
                float(energy_gap),
                4,
            )
            local_on_features.append(feature)
            local_on_sources.append(validated_source)
            validated_reference_count += 1
            if str(mask_id) not in validated_mask_ids:
                validated_mask_ids.append(str(mask_id))

    result["validated_self_on_mask_ids"] = tuple(validated_mask_ids)
    result["validated_self_on_reference_count"] = int(
        validated_reference_count
    )
    result["self_reference_policy"] = "exclude_current_except_validated_self_on"
    return result


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
        self._strict_validated_self_on_mask_ids = ()
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
        filtered_learning = filtrar_aprendizado_sem_check_atual_f3(
            global_learning,
            self._strict_current_check_id,
        )
        filtered_learning = reinjetar_on_proprio_validado_f3(
            global_learning,
            filtered_learning,
            self._strict_current_check_id,
        )
        self._strict_validated_self_on_mask_ids = tuple(
            filtered_learning.get("validated_self_on_mask_ids", ()) or ()
        )
        return filtered_learning

    def analyze(
        self,
        frame,
        project_name: str,
        check_id: str,
        visual_rotation: int = 0,
        *,
        mask_geometry_override=None,
        mask_geometry_resolution=None,
        mask_geometry_source: str = "",
    ) -> dict:
        previous = getattr(self, "_strict_current_check_id", "")
        previous_validated = getattr(
            self,
            "_strict_validated_self_on_mask_ids",
            (),
        )
        self._strict_current_check_id = _normalized_check_id(check_id)
        self._strict_validated_self_on_mask_ids = ()
        validated_self_on_mask_ids = ()
        try:
            analysis = super().analyze(
                frame=frame,
                project_name=project_name,
                check_id=check_id,
                visual_rotation=visual_rotation,
                mask_geometry_override=mask_geometry_override,
                mask_geometry_resolution=mask_geometry_resolution,
                mask_geometry_source=mask_geometry_source,
            )
            validated_self_on_mask_ids = tuple(
                self._strict_validated_self_on_mask_ids or ()
            )
        finally:
            self._strict_current_check_id = previous
            self._strict_validated_self_on_mask_ids = previous_validated

        if not isinstance(analysis, dict):
            return analysis

        analysis["reference_authority"] = F3_STRICT_MASK_AUTHORITY
        analysis["self_reference_excluded"] = True
        analysis["excluded_reference_check_id"] = _normalized_check_id(check_id)
        analysis["self_reference_policy"] = (
            "exclude_current_except_validated_self_on"
        )
        analysis["validated_self_on_mask_ids"] = list(
            validated_self_on_mask_ids
        )
        analysis["validated_self_on_reference_count"] = len(
            validated_self_on_mask_ids
        )

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
    effective_declared = "effective_failed_mask_ids" in data
    effective_failed = {
        str(mask_id)
        for mask_id in (data.get("effective_failed_mask_ids") or ())
        if str(mask_id)
    }
    effective_classifications = {
        str(mask_id): str(state).strip().lower()
        for mask_id, state in dict(
            data.get("effective_classifications") or {}
        ).items()
        if str(mask_id)
    }

    result = {}
    for item in data.get("mask_results", []) or []:
        if not isinstance(item, dict):
            continue
        mask_id = str(item.get("mask_id") or "")
        if not mask_id:
            continue

        is_failed = (
            mask_id in effective_failed
            if effective_declared
            else item.get("matched") is False
        )
        if not is_failed:
            continue

        result[mask_id] = {
            "expected": str(item.get("expected") or ""),
            "classified": effective_classifications.get(
                mask_id,
                str(item.get("classified") or "").strip().lower(),
            ),
            "expected_label": str(item.get("expected_label") or ""),
            "classified_label": str(item.get("classified_label") or ""),
        }
    return result


def _install_failed_mask_overlay() -> None:
    """Publica falhas no contexto; o renderer final decide toda a apresentação."""
    if bool(getattr(overlay_module, "_display_f3_strict_failure_overlay", False)):
        return

    original_context = overlay_module._overlay_context

    def overlay_context(window, visual_rotation: int):
        context = original_context(window, visual_rotation)
        if not isinstance(context, dict):
            return context
        app = overlay_module._app_from_window(window)
        analysis = getattr(app, "_display_auto_last_analysis", None) if app else None
        result = dict(context)
        result["failed_masks"] = (
            _failure_items(analysis)
            if dict(result.get("classifications") or {})
            else {}
        )
        if isinstance(analysis, dict) and "effective_failed_mask_ids" in analysis:
            result["effective_failed_mask_ids"] = tuple(
                str(mask_id)
                for mask_id in (
                    analysis.get("effective_failed_mask_ids") or ()
                )
                if str(mask_id)
            )
            result["effective_classifications"] = dict(
                analysis.get("effective_classifications") or {}
            )
            result["ui_mask_authority"] = str(
                analysis.get("ui_mask_authority")
                or "effective_mask_results_v1"
            )
        return result

    overlay_module._overlay_context = overlay_context
    overlay_module._display_f3_strict_failure_overlay = True


def _install_failed_mask_status() -> None:
    if bool(getattr(mask_status_module, "_display_f3_strict_failure_status", False)):
        return

    original_format = mask_status_module.formatar_status_mascaras_f3

    def format_status(analysis: dict | None, context: dict | None):
        text, color = original_format(analysis, context)
        if not isinstance(analysis, dict) or not bool(analysis.get("ready")):
            return text, color

        validating = tuple(
            str(mask_id)
            for mask_id in (
                analysis.get("effective_validating_mask_ids") or ()
            )
            if str(mask_id)
        )
        confirmed = tuple(
            str(mask_id)
            for mask_id in (
                analysis.get("effective_confirmed_failed_mask_ids") or ()
            )
            if str(mask_id)
        )
        if validating and not confirmed:
            phase = analysis.get("intermittent_phase_evidence")
            counts = (
                phase.get("failure_counts")
                if isinstance(phase, dict)
                and isinstance(phase.get("failure_counts"), dict)
                else {}
            )
            progress = max(
                (int(counts.get(mask_id, 0) or 0) for mask_id in validating),
                default=0,
            )
            limit = int(
                runtime_module.DisplayAutomaticCheckF3Mixin
                .DISPLAY_AUTO_INTERMITTENT_FAILURE_SAMPLES
            )
            suffix = (
                f" • VALIDANDO {validating[0]} "
                f"{progress}/{limit}"
            )
            if len(validating) > 1:
                suffix += f" (+{len(validating) - 1})"
            return text + suffix, "#FDE68A"

        failures = _failure_items(analysis)
        if confirmed:
            failures = {
                mask_id: failure
                for mask_id, failure in failures.items()
                if mask_id in set(confirmed)
            }
        if not failures:
            return text, color

        first_id, failure = next(iter(failures.items()))
        expected = str(
            failure.get("expected_label") or failure.get("expected") or "?"
        ).upper()
        classified = str(
            failure.get("classified_label") or failure.get("classified") or "?"
        ).upper()
        suffix = f" • FALHA {first_id}"
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
