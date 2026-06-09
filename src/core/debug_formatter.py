from src.models.analysis_result import LedAnalysisResult
from src.models.led_features import LedFeatures
from src.models.led_selection import LedSelection
from src.models.output_paths import OutputPaths


FEATURES_DEBUG_ORDEM = [
    "v_mean",
    "v_max",
    "v_min",
    "v_std",
    "v_p90",
    "v_p95",
    "v_p99",
    "s_mean",
    "s_std",
    "s_p90",
    "h_mean",
    "inner_v_mean",
    "ring_v_mean",
    "center_to_ring_v",
    "inner_s_mean",
    "ring_s_mean",
    "center_to_ring_s",
    "percent_on",
    "percent_hot_220",
    "percent_hot_235",
    "percent_hot_245",
    "percent_hot_250",
    "glow_score",
]


def formatar_painel_inicial(
    features_referencia_acesa: LedFeatures | None,
    features_referencia_apagada: LedFeatures | None,
    leds_selecionados: list[LedSelection] | None = None,
    raio_atual_px: int = 15,
    salvar_resultados_analise: bool = False,
    led_selecionado: LedSelection | None = None,
) -> str:
    if leds_selecionados is None:
        leds_selecionados = [led_selecionado] if led_selecionado else []

    linhas = []
    linhas.append("FLUXO ATUAL")
    linhas.append("=" * 40)
    linhas.append("1. Configure Ref. aceso e Ref. apagado na engrenagem")
    linhas.append("2. Carregue a imagem da PCI")
    linhas.append("3. Clique em Selecionar LEDs")
    linhas.append("4. Clique em um ou mais LEDs na imagem")
    linhas.append("5. Clique em Analisar")
    linhas.append("")
    linhas.append("REFERÊNCIAS")
    linhas.append("=" * 40)
    linhas.append(f"LED aceso: {'carregado' if features_referencia_acesa else 'pendente'}")
    linhas.append(f"LED apagado: {'carregado' if features_referencia_apagada else 'pendente'}")
    linhas.append("")
    linhas.append(f"Raio atual: {raio_atual_px}px")
    linhas.append(
        "Salvar resultados: "
        + ("ativado" if salvar_resultados_analise else "desativado")
    )
    linhas.append("")
    linhas.append("SELEÇÃO")
    linhas.append("=" * 40)
    linhas.append(f"LEDs selecionados: {len(leds_selecionados)}")

    for led in leds_selecionados:
        linhas.append(f"{led.id}: x={led.centro_x} y={led.centro_y} raio={led.raio}px")

    return "\n".join(linhas)


def _adicionar_debug_led(linhas: list[str], resultado_led: LedAnalysisResult) -> None:
    features = resultado_led.features
    avaliacao_metricas = resultado_led.avaliacao_metricas

    linhas.append(f"{resultado_led.id} | {resultado_led.status} | bin={resultado_led.valor_binario} | conf={resultado_led.confianca}")
    linhas.append("-" * 42)
    linhas.append(f"Centro X: {resultado_led.centro_x}")
    linhas.append(f"Centro Y: {resultado_led.centro_y}")
    linhas.append(f"Raio: {resultado_led.raio} px")
    linhas.append(f"Área analisada: {features.area_pixels} px")
    linhas.append("")
    linhas.append("FEATURES")

    for nome_feature in FEATURES_DEBUG_ORDEM:
        linhas.append(f"{nome_feature}: {getattr(features, nome_feature)}")

    linhas.append("")
    linhas.append("COMPARAÇÃO / DECISÃO")
    linhas.append(f"distância p/ aceso: {resultado_led.distancia_on}")
    linhas.append(f"distância p/ apagado: {resultado_led.distancia_off}")
    linhas.append(f"limite_v_mean: {resultado_led.limite_v_mean}")
    linhas.append(f"limite_v_std: {resultado_led.limite_v_std}")
    linhas.append(f"limite_center_to_ring_v: {resultado_led.limite_center_to_ring_v}")
    linhas.append(f"limite_glow_score: {resultado_led.limite_glow_score}")
    linhas.append(f"limite_v_p99: {resultado_led.limite_v_p99}")
    linhas.append(f"brilho indica aceso: {resultado_led.brilho_indica_aceso}")
    linhas.append(f"similaridade indica aceso: {resultado_led.similaridade_indica_aceso}")
    linhas.append(f"pico indica aceso: {resultado_led.pico_indica_aceso}")
    linhas.append(f"contraste/glow indica aceso: {resultado_led.contraste_indica_aceso}")
    linhas.append(f"métricas indicam aceso: {resultado_led.metricas_indicam_aceso}")
    linhas.append(f"score métricas: {avaliacao_metricas.score_metricas}")
    linhas.append(f"votos aceso: {avaliacao_metricas.votos_aceso}")
    linhas.append(f"votos apagado: {avaliacao_metricas.votos_apagado}")
    linhas.append(f"Motivos: {', '.join(resultado_led.motivos)}")
    linhas.append("")


def formatar_resultado_textual(resultado_led: LedAnalysisResult, output_paths: OutputPaths) -> str:
    return formatar_resultado_textual_multiplos([resultado_led], output_paths)


def formatar_resultado_textual_multiplos(resultados_led: list[LedAnalysisResult], output_paths: OutputPaths) -> str:
    total_leds = len(resultados_led)
    leds_acesos = sum(1 for item in resultados_led if item.valor_binario == 1)
    leds_apagados = total_leds - leds_acesos

    linhas = []
    linhas.append("RESULTADO DA ANÁLISE")
    linhas.append("=" * 42)
    linhas.append(f"Total de LEDs analisados: {total_leds}")
    linhas.append(f"LEDs acesos: {leds_acesos}")
    linhas.append(f"LEDs apagados: {leds_apagados}")

    if total_leds > 0:
        confianca_media = sum(float(item.confianca) for item in resultados_led) / total_leds
        linhas.append(f"Confiança média: {round(confianca_media, 4)}")

    linhas.append("")
    linhas.append("RESUMO POR LED")
    linhas.append("=" * 42)

    for resultado_led in resultados_led:
        linhas.append(
            f"{resultado_led.id} | {resultado_led.status} | "
            f"bin={resultado_led.valor_binario} | "
            f"conf={resultado_led.confianca} | "
            f"v_mean={resultado_led.features.v_mean} | "
            f"v_max={resultado_led.features.v_max} | "
            f"glow={resultado_led.features.glow_score}"
        )

    linhas.append("")
    linhas.append("DEBUG DETALHADO")
    linhas.append("=" * 42)

    for indice, resultado_led in enumerate(resultados_led, start=1):
        if indice > 1:
            linhas.append("=" * 42)
        _adicionar_debug_led(linhas, resultado_led)

    linhas.append("")
    linhas.append("ARQUIVOS GERADOS")
    linhas.append("=" * 42)

    if output_paths.tem_arquivos_salvos():
        linhas.append(str(output_paths.caminho_resultado_imagem))
        linhas.append(str(output_paths.caminho_mascara))
        linhas.append(str(output_paths.caminho_roi_debug))
        linhas.append(str(output_paths.caminho_resultado_json))
    else:
        linhas.append("Salvamento automático desativado nas configurações.")
        linhas.append("As renderizações continuam disponíveis somente na interface.")

    return "\n".join(linhas)
