import cv2
import numpy as np

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection


AlvoLed = LedAnalysisResult | LedSelection | None
AlvosLed = AlvoLed | list[LedAnalysisResult] | list[LedSelection]


def _normalizar_alvos(alvo: AlvosLed) -> list[LedAnalysisResult | LedSelection]:
    if alvo is None:
        return []

    if isinstance(alvo, list):
        return [item for item in alvo if item is not None]

    return [alvo]


def _obter_dados_alvo(alvo: AlvoLed):
    if alvo is None:
        return None

    return {
        "id": str(getattr(alvo, "id", "LED")),
        "centro_x": int(alvo.centro_x),
        "centro_y": int(alvo.centro_y),
        "raio": int(alvo.raio),
        "valor_binario": int(getattr(alvo, "valor_binario", -1)),
        "status": str(getattr(alvo, "status", "SELECIONADO")),
        "confianca": getattr(alvo, "confianca", None),
    }


def _obter_cor_bgr(alvo: AlvoLed):
    dados_alvo = _obter_dados_alvo(alvo)

    if dados_alvo is None:
        return (56, 189, 248)

    if dados_alvo["valor_binario"] == 1:
        return (0, 255, 0)

    if dados_alvo["valor_binario"] == 0:
        return (0, 0, 255)

    return (248, 189, 56)


def _desenhar_marcacao_led(imagem, alvo: AlvoLed, com_texto: bool = True):
    dados_alvo = _obter_dados_alvo(alvo)

    if dados_alvo is None:
        return imagem

    centro_x = dados_alvo["centro_x"]
    centro_y = dados_alvo["centro_y"]
    raio = dados_alvo["raio"]
    cor = _obter_cor_bgr(alvo)

    cv2.circle(imagem, (centro_x, centro_y), raio, cor, 2)
    cv2.circle(imagem, (centro_x, centro_y), max(2, int(raio * 0.45)), (255, 255, 0), 1)
    cv2.circle(imagem, (centro_x, centro_y), max(3, int(raio * 0.62)), (255, 0, 255), 1)
    cv2.drawMarker(
        imagem,
        (centro_x, centro_y),
        cor,
        markerType=cv2.MARKER_CROSS,
        markerSize=max(12, int(raio * 1.2)),
        thickness=2,
    )

    if com_texto:
        texto = f"{dados_alvo['id']} {dados_alvo['status']}"
        cv2.putText(
            imagem,
            texto,
            (max(10, centro_x + raio + 10), max(28, centro_y - raio - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            cor,
            2,
            cv2.LINE_AA,
        )

    return imagem


def _desenhar_marcacoes_leds(imagem, alvos: AlvosLed, com_texto: bool = True):
    for alvo in _normalizar_alvos(alvos):
        _desenhar_marcacao_led(imagem, alvo, com_texto=com_texto)

    return imagem


def criar_imagem_resultado_visual(imagem_original, resultado_led: LedAnalysisResult):
    return criar_imagem_resultados_visuais(imagem_original, [resultado_led])


def criar_imagem_resultados_visuais(imagem_original, resultados_led: list[LedAnalysisResult]):
    imagem_resultado = imagem_original.copy()
    overlay = imagem_resultado.copy()

    for resultado_led in resultados_led:
        centro_x = resultado_led.centro_x
        centro_y = resultado_led.centro_y
        raio = resultado_led.raio
        cor = (0, 255, 0) if resultado_led.valor_binario == 1 else (0, 0, 255)
        cv2.circle(overlay, (centro_x, centro_y), raio, cor, -1)

    imagem_resultado = cv2.addWeighted(overlay, 0.35, imagem_resultado, 0.65, 0)
    _desenhar_marcacoes_leds(imagem_resultado, resultados_led, com_texto=True)

    return imagem_resultado


def criar_imagem_canal_v(imagem_original, alvo: AlvosLed = None):
    hsv = cv2.cvtColor(imagem_original, cv2.COLOR_BGR2HSV)
    canal_v = hsv[:, :, 2]
    imagem_canal_v = cv2.cvtColor(canal_v, cv2.COLOR_GRAY2BGR)
    return _desenhar_marcacoes_leds(imagem_canal_v, alvo)


def criar_heatmap_intensidade(imagem_original, alvo: AlvosLed = None):
    hsv = cv2.cvtColor(imagem_original, cv2.COLOR_BGR2HSV)
    canal_v = hsv[:, :, 2]
    canal_v_blur = cv2.GaussianBlur(canal_v, (5, 5), 0)
    canal_v_normalizado = cv2.normalize(canal_v_blur, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    heatmap = cv2.applyColorMap(canal_v_normalizado, cv2.COLORMAP_JET)
    return _desenhar_marcacoes_leds(heatmap, alvo)


def criar_imagem_mascara(imagem_original, resultado_led: LedAnalysisResult):
    return criar_imagem_mascara_multiplos(imagem_original, [resultado_led])


def criar_imagem_mascara_multiplos(imagem_original, alvos: AlvosLed):
    altura_original, largura_original = imagem_original.shape[:2]
    mascara = np.zeros((altura_original, largura_original), dtype=np.uint8)

    for alvo in _normalizar_alvos(alvos):
        dados_alvo = _obter_dados_alvo(alvo)
        if dados_alvo is None:
            continue

        cv2.circle(
            mascara,
            (dados_alvo["centro_x"], dados_alvo["centro_y"]),
            dados_alvo["raio"],
            255,
            -1,
        )

    return mascara


def criar_imagem_mascara_visual(imagem_original, alvo: AlvosLed = None):
    altura_original, largura_original = imagem_original.shape[:2]
    imagem_mascara = np.zeros((altura_original, largura_original, 3), dtype=np.uint8)
    alvos = _normalizar_alvos(alvo)

    if not alvos:
        cv2.putText(
            imagem_mascara,
            "ROI ainda nao selecionado",
            (30, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (148, 163, 184),
            2,
            cv2.LINE_AA,
        )
        return imagem_mascara

    for item in alvos:
        dados_alvo = _obter_dados_alvo(item)
        if dados_alvo is None:
            continue

        centro_x = dados_alvo["centro_x"]
        centro_y = dados_alvo["centro_y"]
        raio = dados_alvo["raio"]
        cor = _obter_cor_bgr(item)

        cv2.circle(imagem_mascara, (centro_x, centro_y), raio, cor, -1)
        cv2.circle(imagem_mascara, (centro_x, centro_y), raio, (255, 255, 255), 2)
        cv2.circle(imagem_mascara, (centro_x, centro_y), max(2, int(raio * 0.45)), (255, 255, 0), 1)
        cv2.circle(imagem_mascara, (centro_x, centro_y), max(3, int(raio * 0.62)), (255, 0, 255), 1)
        cv2.drawMarker(imagem_mascara, (centro_x, centro_y), (255, 255, 255), cv2.MARKER_CROSS, 14, 1)
        cv2.putText(
            imagem_mascara,
            dados_alvo["id"],
            (max(10, centro_x + raio + 8), max(25, centro_y - raio - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    return imagem_mascara


def criar_imagem_roi_debug(imagem_original, resultado_led: AlvoLed):
    altura_original, largura_original = imagem_original.shape[:2]
    dados_alvo = _obter_dados_alvo(resultado_led)

    if dados_alvo is None:
        return np.zeros((120, 120, 3), dtype=np.uint8)

    centro_x = dados_alvo["centro_x"]
    centro_y = dados_alvo["centro_y"]
    raio = dados_alvo["raio"]

    margem = max(raio * 3, 30)
    x1 = max(0, centro_x - margem)
    y1 = max(0, centro_y - margem)
    x2 = min(largura_original, centro_x + margem)
    y2 = min(altura_original, centro_y + margem)

    roi_debug = imagem_original[y1:y2, x1:x2].copy()
    centro_local_x = centro_x - x1
    centro_local_y = centro_y - y1
    cor = _obter_cor_bgr(resultado_led)

    cv2.circle(roi_debug, (centro_local_x, centro_local_y), raio, cor, 2)
    cv2.circle(roi_debug, (centro_local_x, centro_local_y), max(2, int(raio * 0.45)), (255, 255, 0), 1)
    cv2.circle(roi_debug, (centro_local_x, centro_local_y), max(3, int(raio * 0.62)), (255, 0, 255), 1)
    cv2.drawMarker(roi_debug, (centro_local_x, centro_local_y), cor, cv2.MARKER_CROSS, 12, 1)
    cv2.putText(
        roi_debug,
        dados_alvo["id"],
        (5, 18),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        cor,
        1,
        cv2.LINE_AA,
    )

    return roi_debug


def criar_imagem_roi_debug_ampliado(imagem_original, alvo: AlvoLed = None, fator_escala: int = 5):
    roi_debug = criar_imagem_roi_debug(imagem_original, alvo)

    if roi_debug.size == 0:
        return roi_debug

    altura_roi, largura_roi = roi_debug.shape[:2]
    largura_final = max(largura_roi * fator_escala, 220)
    altura_final = max(altura_roi * fator_escala, 160)

    return cv2.resize(
        roi_debug,
        (largura_final, altura_final),
        interpolation=cv2.INTER_NEAREST,
    )


def _obter_ultimo_alvo(alvo: AlvosLed):
    alvos = _normalizar_alvos(alvo)
    return alvos[-1] if alvos else None


def criar_pacote_renderizacoes_visuais(imagem_original, alvo: AlvosLed = None) -> dict:
    ultimo_alvo = _obter_ultimo_alvo(alvo)
    alvos = _normalizar_alvos(alvo)

    renderizacoes = {
        "canal_v": criar_imagem_canal_v(imagem_original, alvos),
        "heatmap": criar_heatmap_intensidade(imagem_original, alvos),
        "mascara": criar_imagem_mascara_visual(imagem_original, alvos),
    }

    if ultimo_alvo is not None:
        renderizacoes["roi_debug"] = criar_imagem_roi_debug_ampliado(imagem_original, ultimo_alvo)
    else:
        renderizacoes["roi_debug"] = None

    if alvos and all(isinstance(item, LedAnalysisResult) for item in alvos):
        renderizacoes["overlay"] = criar_imagem_resultados_visuais(imagem_original, alvos)
    else:
        renderizacoes["overlay"] = None

    return renderizacoes
