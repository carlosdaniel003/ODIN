from __future__ import annotations

from dataclasses import dataclass

from src.core.segment_low_light import STATUS_ACESO, STATUS_APAGADO


# Calibração conservadora para o JIG LED/F2.
# O falso positivo observado com a placa desligada apresentava muito contraste
# e glow por reflexão do encapsulamento, mas somente 7%..26% da ROI acima de
# V=160 e no máximo ~3,5% dos pixels em V>=250. Um LED realmente emitindo no
# JIG ocupa uma fração significativamente maior da ROI.
F2_PHYSICAL_MIN_PERCENT_ON = 0.35
F2_PHYSICAL_STRONG_PERCENT_ON = 0.75
F2_PHYSICAL_MIN_HOT_245 = 0.050
F2_PHYSICAL_MIN_HOT_250 = 0.040
F2_PHYSICAL_REFERENCE_HOT_RATIO = 0.35

# Quando a referência ON possui núcleo quase branco e anel colorido, sua
# assinatura também é física: brilho de reflexo sem esse núcleo não basta.
# O gatilho depende da referência do projeto, não da cor vermelha do JIG.
F2_CHROMATIC_MAX_REFERENCE_INNER_S = 90.0
F2_CHROMATIC_MIN_REFERENCE_RING_CORE_GAP = 80.0
F2_CHROMATIC_MIN_INNER_S_RISE_RATIO = 0.60
F2_CHROMATIC_MAX_RETAINED_GAP_RATIO = 0.25


@dataclass(frozen=True)
class F2PhysicalEmissionEvaluation:
    emitted: bool
    percent_on: float
    percent_hot_245: float
    percent_hot_250: float
    min_percent_on: float
    min_hot_245: float
    min_hot_250: float
    chromatic_mismatch: bool = False
    reference_chromatic_gap: float = 0.0
    current_chromatic_gap: float = 0.0
    inner_s_mean: float = 0.0


def _positive(value) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _hot_threshold(reference_on, feature_name: str, absolute_floor: float) -> float:
    reference_value = _positive(getattr(reference_on, feature_name, 0.0))
    return max(
        float(absolute_floor),
        reference_value * F2_PHYSICAL_REFERENCE_HOT_RATIO,
    )


def avaliar_emissao_fisica_f2(features, reference_on=None) -> F2PhysicalEmissionEvaluation:
    """Distingue emissão real de reflexo/contraste no encapsulamento do LED.

    A decisão base por referência continua responsável por comparar ACESO e
    APAGADO. Esta guarda entra depois apenas para impedir que uma região com
    poucos pixels saturados e alto contraste geométrico seja tratada como LED
    fisicamente aceso.
    """
    percent_on = _positive(getattr(features, "percent_on", 0.0))
    percent_hot_245 = _positive(getattr(features, "percent_hot_245", 0.0))
    percent_hot_250 = _positive(getattr(features, "percent_hot_250", 0.0))

    min_hot_245 = _hot_threshold(
        reference_on,
        "percent_hot_245",
        F2_PHYSICAL_MIN_HOT_245,
    )
    min_hot_250 = _hot_threshold(
        reference_on,
        "percent_hot_250",
        F2_PHYSICAL_MIN_HOT_250,
    )

    broad_light = percent_on >= F2_PHYSICAL_MIN_PERCENT_ON
    very_broad_light = percent_on >= F2_PHYSICAL_STRONG_PERCENT_ON
    hot_core = (
        percent_hot_245 >= min_hot_245
        or percent_hot_250 >= min_hot_250
    )

    # Duas formas de confirmar emissão:
    # 1) a maior parte da ROI está claramente iluminada; ou
    # 2) existe área iluminada suficiente acompanhada de um núcleo quente.
    # Reflexos do suporte/encapsulamento no debug desligado não satisfazem
    # nenhuma das duas condições.
    luminosity_emitted = very_broad_light or (broad_light and hot_core)

    # Os LEDs do projeto que produzem um núcleo claro e pouco saturado não
    # podem ser aprovados por vermelho saturado/reflexos igualmente brilhantes.
    # Exigimos DUAS evidências de perda do núcleo: forte aumento da saturação
    # interna e desaparecimento do contraste de saturação núcleo/anel. LEDs
    # verdadeiramente coloridos (referência ON sem núcleo claro) não entram
    # nessa guarda.
    ref_inner_s = _positive(getattr(reference_on, "inner_s_mean", 0.0))
    ref_ring_s = _positive(getattr(reference_on, "ring_s_mean", 0.0))
    inner_s = _positive(getattr(features, "inner_s_mean", 0.0))
    ring_s = _positive(getattr(features, "ring_s_mean", 0.0))
    reference_gap = ref_ring_s - ref_inner_s
    current_gap = ring_s - inner_s
    reference_expects_clear_core = bool(
        reference_on is not None
        and ref_inner_s <= F2_CHROMATIC_MAX_REFERENCE_INNER_S
        and reference_gap >= F2_CHROMATIC_MIN_REFERENCE_RING_CORE_GAP
    )
    chromatic_mismatch = bool(
        reference_expects_clear_core
        and inner_s - ref_inner_s
        >= reference_gap * F2_CHROMATIC_MIN_INNER_S_RISE_RATIO
        and current_gap <= reference_gap * F2_CHROMATIC_MAX_RETAINED_GAP_RATIO
    )
    emitted = luminosity_emitted and not chromatic_mismatch

    return F2PhysicalEmissionEvaluation(
        emitted=bool(emitted),
        percent_on=percent_on,
        percent_hot_245=percent_hot_245,
        percent_hot_250=percent_hot_250,
        min_percent_on=float(F2_PHYSICAL_MIN_PERCENT_ON),
        min_hot_245=float(min_hot_245),
        min_hot_250=float(min_hot_250),
        chromatic_mismatch=chromatic_mismatch,
        reference_chromatic_gap=float(reference_gap),
        current_chromatic_gap=float(current_gap),
        inner_s_mean=float(inner_s),
    )


def aplicar_guarda_emissao_fisica_f2(result, reference_on=None):
    """Demove falso ACESO para APAGADO sem alterar o classificador compartilhado.

    POUCA_LUZ não é alterado aqui. A função deve ser chamada depois do
    diagnóstico opcional de pouca luz; assim uma emissão fraca conhecida pode
    continuar sendo reportada como POUCA_LUZ em vez de ser confundida com
    ausência total de emissão.
    """
    if str(getattr(result, "status", "")).strip().upper() != STATUS_ACESO:
        return result

    evaluation = avaliar_emissao_fisica_f2(
        getattr(result, "features", None),
        reference_on=reference_on,
    )
    if evaluation.emitted:
        return result

    result.status = STATUS_APAGADO
    result.valor_binario = 0
    result.falha_luminosidade = False
    result.indice_luminosidade = 0.0
    result.score_falha_luminosidade = 0.0

    reasons = list(getattr(result, "motivos", ()) or ())
    if evaluation.chromatic_mismatch:
        reasons.append(
            "F2 LED: núcleo cromático incompatível com referência ACESO "
            f"(S_interno={evaluation.inner_s_mean:.1f}, "
            f"contraste_S={evaluation.current_chromatic_gap:.1f}, "
            f"referência={evaluation.reference_chromatic_gap:.1f})"
        )
    else:
        reasons.append(
            "F2 LED: sem emissão física suficiente "
            f"(area={evaluation.percent_on:.3f}/{evaluation.min_percent_on:.3f}, "
            f"hot245={evaluation.percent_hot_245:.3f}/{evaluation.min_hot_245:.3f}, "
            f"hot250={evaluation.percent_hot_250:.3f}/{evaluation.min_hot_250:.3f})"
        )
    result.motivos = reasons
    return result
