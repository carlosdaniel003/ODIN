import cv2
import numpy as np

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection


AlvoLed = LedAnalysisResult | LedSelection | None
AlvosLed = AlvoLed | list[LedAnalysisResult] | list[LedSelection]


def _normalizar_alvos(
    alvo: AlvosLed,
) -> list[LedAnalysisResult | LedSelection]:
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
        "valor_binario": int(
            getattr(alvo, "valor_binario", -1)
        ),
        "status": str(
            getattr(alvo, "status", "SELECIONADO")
        ),
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


def _obter_numero_led(alvo: AlvoLed) -> str:
    dados_alvo = _obter_dados_alvo(alvo)

    if dados_alvo is None:
        return ""

    id_led = dados_alvo["id"]

    if "_" in id_led:
        return id_led.split("_")[-1]

    return id_led


def _desenhar_marcacao_led(
    imagem,
    alvo: AlvoLed,
    com_texto: bool = True,
):
    dados_alvo = _obter_dados_alvo(alvo)

    if dados_alvo is None:
        return imagem

    centro_x = dados_alvo["centro_x"]
    centro_y = dados_alvo["centro_y"]
    raio = dados_alvo["raio"]
    valor_binario = dados_alvo["valor_binario"]
    cor = _obter_cor_bgr(alvo)
    numero_led = _obter_numero_led(alvo)

    espessura = 2
    raio_externo = raio

    if valor_binario == 0:
        espessura = 3
        raio_externo = int(raio * 1.25)

    cv2.circle(
        imagem,
        (centro_x, centro_y),
        raio_externo,
        cor,
        espessura,
    )
    cv2.drawMarker(
        imagem,
        (centro_x, centro_y),
        cor,
        markerType=cv2.MARKER_CROSS,
        markerSize=max(8, int(raio * 0.9)),
        thickness=1,
    )

    if com_texto and numero_led:
        largura_texto, altura_texto = cv2.getTextSize(
            numero_led,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            1,
        )[0]

        x_texto = max(
            4,
            centro_x - int(largura_texto / 2),
        )
        y_texto = max(
            14,
            centro_y - raio_externo - 6,
        )

        cv2.rectangle(
            imagem,
            (
                x_texto - 3,
                y_texto - altura_texto - 3,
            ),
            (
                x_texto + largura_texto + 3,
                y_texto + 3,
            ),
            (3, 7, 18),
            -1,
        )

        cv2.putText(
            imagem,
            numero_led,
            (x_texto, y_texto),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            cor,
            1,
            cv2.LINE_AA,
        )

    return imagem


def _desenhar_marcacoes_leds(
    imagem,
    alvos: AlvosLed,
    com_texto: bool = True,
):
    for alvo in _normalizar_alvos(alvos):
        _desenhar_marcacao_led(
            imagem,
            alvo,
            com_texto=com_texto,
        )

    return imagem


def criar_imagem_resultado_visual(
    imagem_original,
    resultado_led: LedAnalysisResult,
):
    return criar_imagem_resultados_visuais(
        imagem_original,
        [resultado_led],
    )


def criar_imagem_resultados_visuais(
    imagem_original,
    resultados_led: list[LedAnalysisResult],
):
    imagem_resultado = imagem_original.copy()

    for resultado_led in resultados_led:
        centro_x = resultado_led.centro_x
        centro_y = resultado_led.centro_y
        raio = resultado_led.raio

        if resultado_led.valor_binario == 1:
            cor = (0, 180, 0)
            alpha_local = 0.12
        else:
            cor = (0, 0, 255)
            alpha_local = 0.35

        camada_led = imagem_resultado.copy()
        cv2.circle(
            camada_led,
            (centro_x, centro_y),
            int(raio * 1.15),
            cor,
            -1,
        )
        imagem_resultado = cv2.addWeighted(
            camada_led,
            alpha_local,
            imagem_resultado,
            1.0 - alpha_local,
            0,
        )

    _desenhar_marcacoes_leds(
        imagem_resultado,
        resultados_led,
        com_texto=False,
    )

    return imagem_resultado


def criar_imagem_canal_v(
    imagem_original,
    alvo: AlvosLed = None,
):
    """
    Retorna o frame completo convertido para o canal V.

    As marcações são desenhadas sobre a imagem completa, sem recorte.
    """
    hsv = cv2.cvtColor(
        imagem_original,
        cv2.COLOR_BGR2HSV,
    )
    canal_v = hsv[:, :, 2]
    imagem_canal_v = cv2.cvtColor(
        canal_v,
        cv2.COLOR_GRAY2BGR,
    )

    return _desenhar_marcacoes_leds(
        imagem_canal_v,
        alvo,
    )


def criar_heatmap_intensidade(
    imagem_original,
    alvo: AlvosLed = None,
):
    hsv = cv2.cvtColor(
        imagem_original,
        cv2.COLOR_BGR2HSV,
    )
    canal_v = hsv[:, :, 2]
    canal_v_blur = cv2.GaussianBlur(
        canal_v,
        (5, 5),
        0,
    )
    canal_v_normalizado = cv2.normalize(
        canal_v_blur,
        None,
        0,
        255,
        cv2.NORM_MINMAX,
    ).astype(np.uint8)
    heatmap = cv2.applyColorMap(
        canal_v_normalizado,
        cv2.COLORMAP_JET,
    )

    return _desenhar_marcacoes_leds(
        heatmap,
        alvo,
    )


def criar_imagem_mascara(
    imagem_original,
    resultado_led: LedAnalysisResult,
):
    return criar_imagem_mascara_multiplos(
        imagem_original,
        [resultado_led],
    )


def criar_imagem_mascara_multiplos(
    imagem_original,
    alvos: AlvosLed,
):
    altura_original, largura_original = (
        imagem_original.shape[:2]
    )
    mascara = np.zeros(
        (altura_original, largura_original),
        dtype=np.uint8,
    )

    for alvo in _normalizar_alvos(alvos):
        dados_alvo = _obter_dados_alvo(alvo)

        if dados_alvo is None:
            continue

        cv2.circle(
            mascara,
            (
                dados_alvo["centro_x"],
                dados_alvo["centro_y"],
            ),
            dados_alvo["raio"],
            255,
            -1,
        )

    return mascara


def criar_imagem_mascara_visual(
    imagem_original,
    alvo: AlvosLed = None,
):
    """
    Exibe o frame completo escurecido e mantém as ROIs selecionadas
    com o conteúdo original visível.

    Isso permite identificar a posição das ROIs sem perder a visão
    completa da placa durante a câmera ao vivo.
    """
    alvos = _normalizar_alvos(alvo)
    altura_original, largura_original = (
        imagem_original.shape[:2]
    )

    imagem_mascara = cv2.convertScaleAbs(
        imagem_original,
        alpha=0.24,
        beta=0,
    )

    if not alvos:
        cv2.putText(
            imagem_mascara,
            "ROI ainda nao selecionado",
            (30, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (203, 213, 225),
            2,
            cv2.LINE_AA,
        )
        return imagem_mascara

    mascara_binaria = np.zeros(
        (altura_original, largura_original),
        dtype=np.uint8,
    )

    for item in alvos:
        dados_alvo = _obter_dados_alvo(item)

        if dados_alvo is None:
            continue

        cv2.circle(
            mascara_binaria,
            (
                dados_alvo["centro_x"],
                dados_alvo["centro_y"],
            ),
            dados_alvo["raio"],
            255,
            -1,
        )

    # Mantém o conteúdo real das ROIs em brilho normal.
    imagem_mascara[mascara_binaria > 0] = (
        imagem_original[mascara_binaria > 0]
    )

    for item in alvos:
        dados_alvo = _obter_dados_alvo(item)

        if dados_alvo is None:
            continue

        centro_x = dados_alvo["centro_x"]
        centro_y = dados_alvo["centro_y"]
        raio = dados_alvo["raio"]
        cor = _obter_cor_bgr(item)

        cv2.circle(
            imagem_mascara,
            (centro_x, centro_y),
            raio,
            cor,
            2,
        )
        cv2.circle(
            imagem_mascara,
            (centro_x, centro_y),
            max(2, int(raio * 0.45)),
            (255, 255, 0),
            1,
        )
        cv2.circle(
            imagem_mascara,
            (centro_x, centro_y),
            max(3, int(raio * 0.62)),
            (255, 0, 255),
            1,
        )
        cv2.drawMarker(
            imagem_mascara,
            (centro_x, centro_y),
            (255, 255, 255),
            cv2.MARKER_CROSS,
            14,
            1,
        )

        cv2.putText(
            imagem_mascara,
            dados_alvo["id"],
            (
                max(10, centro_x + raio + 8),
                max(25, centro_y - raio - 6),
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    return imagem_mascara


def criar_imagem_roi_debug(
    imagem_original,
    resultado_led: AlvoLed,
):
    """
    Cria apenas o recorte técnico da ROI.

    Esta função continua disponível para depuração interna. O painel
    lateral usa criar_imagem_roi_debug_ampliado(), que mantém o frame
    completo e insere este recorte como uma lupa.
    """
    altura_original, largura_original = (
        imagem_original.shape[:2]
    )
    dados_alvo = _obter_dados_alvo(resultado_led)

    if dados_alvo is None:
        return np.zeros(
            (120, 120, 3),
            dtype=np.uint8,
        )

    centro_x = dados_alvo["centro_x"]
    centro_y = dados_alvo["centro_y"]
    raio = dados_alvo["raio"]

    margem = max(raio * 3, 30)
    x1 = max(0, centro_x - margem)
    y1 = max(0, centro_y - margem)
    x2 = min(
        largura_original,
        centro_x + margem + 1,
    )
    y2 = min(
        altura_original,
        centro_y + margem + 1,
    )

    roi_debug = imagem_original[
        y1:y2,
        x1:x2,
    ].copy()

    if roi_debug.size == 0:
        return np.zeros(
            (120, 120, 3),
            dtype=np.uint8,
        )

    centro_local_x = centro_x - x1
    centro_local_y = centro_y - y1
    cor = _obter_cor_bgr(resultado_led)

    cv2.circle(
        roi_debug,
        (centro_local_x, centro_local_y),
        raio,
        cor,
        2,
    )
    cv2.circle(
        roi_debug,
        (centro_local_x, centro_local_y),
        max(2, int(raio * 0.45)),
        (255, 255, 0),
        1,
    )
    cv2.circle(
        roi_debug,
        (centro_local_x, centro_local_y),
        max(3, int(raio * 0.62)),
        (255, 0, 255),
        1,
    )
    cv2.drawMarker(
        roi_debug,
        (centro_local_x, centro_local_y),
        cor,
        cv2.MARKER_CROSS,
        12,
        1,
    )
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


def criar_imagem_roi_debug_sem_alvo(
    imagem_original,
):
    imagem_debug = imagem_original.copy()

    cv2.rectangle(
        imagem_debug,
        (18, 18),
        (
            min(imagem_debug.shape[1] - 18, 620),
            102,
        ),
        (3, 7, 18),
        -1,
    )
    cv2.putText(
        imagem_debug,
        "ROI ainda nao selecionado",
        (30, 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (56, 189, 248),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        imagem_debug,
        "Selecione um LED para exibir a lupa tecnica",
        (30, 82),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (203, 213, 225),
        1,
        cv2.LINE_AA,
    )

    return imagem_debug


def _redimensionar_preservando_proporcao(
    imagem,
    largura_maxima: int,
    altura_maxima: int,
    ampliar: bool = True,
):
    altura, largura = imagem.shape[:2]

    if largura <= 0 or altura <= 0:
        return imagem

    escala = min(
        largura_maxima / largura,
        altura_maxima / altura,
    )

    if not ampliar:
        escala = min(escala, 1.0)

    largura_final = max(
        1,
        int(round(largura * escala)),
    )
    altura_final = max(
        1,
        int(round(altura * escala)),
    )

    interpolacao = (
        cv2.INTER_NEAREST
        if escala >= 1.0
        else cv2.INTER_AREA
    )

    return cv2.resize(
        imagem,
        (largura_final, altura_final),
        interpolation=interpolacao,
    )


def criar_imagem_roi_debug_ampliado(
    imagem_original,
    alvo: AlvoLed = None,
    fator_escala: int = 5,
):
    """
    Mantém o frame completo e adiciona uma lupa da última ROI.

    O painel anterior retornava somente o recorte ampliado. Isso fazia
    parecer que parte da imagem da câmera havia desaparecido.
    """
    dados_alvo = _obter_dados_alvo(alvo)

    if dados_alvo is None:
        return criar_imagem_roi_debug_sem_alvo(
            imagem_original
        )

    imagem_debug = imagem_original.copy()
    altura, largura = imagem_debug.shape[:2]
    cor = _obter_cor_bgr(alvo)

    _desenhar_marcacao_led(
        imagem_debug,
        alvo,
        com_texto=True,
    )

    roi_debug = criar_imagem_roi_debug(
        imagem_original,
        alvo,
    )

    if roi_debug.size == 0:
        return imagem_debug

    largura_maxima_lupa = max(
        120,
        min(
            int(largura * 0.42),
            roi_debug.shape[1] * max(1, fator_escala),
        ),
    )
    altura_maxima_lupa = max(
        100,
        min(
            int(altura * 0.42),
            roi_debug.shape[0] * max(1, fator_escala),
        ),
    )

    lupa = _redimensionar_preservando_proporcao(
        roi_debug,
        largura_maxima=largura_maxima_lupa,
        altura_maxima=altura_maxima_lupa,
        ampliar=True,
    )

    altura_lupa, largura_lupa = lupa.shape[:2]
    margem = max(8, int(min(largura, altura) * 0.02))

    # Coloca a lupa no lado oposto ao LED para reduzir a obstrução.
    if dados_alvo["centro_x"] >= largura / 2:
        x1 = margem
    else:
        x1 = max(
            margem,
            largura - largura_lupa - margem,
        )

    y1 = margem + 24

    if y1 + altura_lupa + margem > altura:
        y1 = max(
            margem,
            altura - altura_lupa - margem,
        )

    x2 = min(largura, x1 + largura_lupa)
    y2 = min(altura, y1 + altura_lupa)

    lupa = lupa[
        : y2 - y1,
        : x2 - x1,
    ]

    cv2.rectangle(
        imagem_debug,
        (
            max(0, x1 - 5),
            max(0, y1 - 25),
        ),
        (
            min(largura - 1, x2 + 5),
            min(altura - 1, y2 + 5),
        ),
        (3, 7, 18),
        -1,
    )

    imagem_debug[y1:y2, x1:x2] = lupa

    cv2.rectangle(
        imagem_debug,
        (x1, y1),
        (max(x1, x2 - 1), max(y1, y2 - 1)),
        cor,
        2,
    )
    cv2.putText(
        imagem_debug,
        f"LUPA {dados_alvo['id']}",
        (x1, max(16, y1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        cor,
        1,
        cv2.LINE_AA,
    )

    return imagem_debug


def _obter_ultimo_alvo(
    alvo: AlvosLed,
):
    alvos = _normalizar_alvos(alvo)
    return alvos[-1] if alvos else None


def criar_pacote_renderizacoes_visuais(
    imagem_original,
    alvo: AlvosLed = None,
) -> dict:
    ultimo_alvo = _obter_ultimo_alvo(alvo)
    alvos = _normalizar_alvos(alvo)

    renderizacoes = {
        "canal_v": criar_imagem_canal_v(
            imagem_original,
            alvos,
        ),
        "heatmap": criar_heatmap_intensidade(
            imagem_original,
            alvos,
        ),
        "mascara": criar_imagem_mascara_visual(
            imagem_original,
            alvos,
        ),
        "roi_debug": (
            criar_imagem_roi_debug_ampliado(
                imagem_original,
                ultimo_alvo,
            )
            if ultimo_alvo is not None
            else criar_imagem_roi_debug_sem_alvo(
                imagem_original
            )
        ),
    }

    if (
        alvos
        and all(
            isinstance(item, LedAnalysisResult)
            for item in alvos
        )
    ):
        renderizacoes["overlay"] = (
            criar_imagem_resultados_visuais(
                imagem_original,
                alvos,
            )
        )
    else:
        renderizacoes["overlay"] = None

    return renderizacoes
