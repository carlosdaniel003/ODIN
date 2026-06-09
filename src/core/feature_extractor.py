import cv2
import numpy as np

from config import DEFAULT_THRESHOLD_V
from src.models.led_features import LedFeatures


def validar_centro_led(
    centro_x: int,
    centro_y: int,
    raio: int,
    largura_original: int,
    altura_original: int,
) -> bool:
    if centro_x - raio < 0:
        return False
    if centro_y - raio < 0:
        return False
    if centro_x + raio >= largura_original:
        return False
    if centro_y + raio >= altura_original:
        return False
    return True


def extrair_features_referencia_led(imagem) -> LedFeatures:
    altura, largura = imagem.shape[:2]
    centro_x = int(largura / 2)
    centro_y = int(altura / 2)
    raio = max(3, int(min(largura, altura) * 0.45))

    return extrair_features_led(imagem, centro_x, centro_y, raio)


def extrair_features_led(imagem, centro_x: int, centro_y: int, raio: int) -> LedFeatures:
    altura, largura = imagem.shape[:2]

    x1 = max(0, centro_x - raio)
    y1 = max(0, centro_y - raio)
    x2 = min(largura, centro_x + raio + 1)
    y2 = min(altura, centro_y + raio + 1)

    roi = imagem[y1:y2, x1:x2]

    if roi.size == 0:
        return LedFeatures()

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    canal_h = hsv[:, :, 0]
    canal_s = hsv[:, :, 1]
    canal_v = hsv[:, :, 2]

    altura_roi, largura_roi = canal_v.shape[:2]
    centro_local_x = centro_x - x1
    centro_local_y = centro_y - y1

    yy, xx = np.ogrid[:altura_roi, :largura_roi]
    distancia_quadrada = (xx - centro_local_x) ** 2 + (yy - centro_local_y) ** 2

    raio_interno = max(2, int(raio * 0.45))
    raio_anel_interno = max(raio_interno + 1, int(raio * 0.62))

    mascara_led = distancia_quadrada <= raio**2
    mascara_interna = distancia_quadrada <= raio_interno**2
    mascara_anel = (distancia_quadrada >= raio_anel_interno**2) & (distancia_quadrada <= raio**2)

    pixels_h = canal_h[mascara_led]
    pixels_s = canal_s[mascara_led]
    pixels_v = canal_v[mascara_led]
    pixels_v_interno = canal_v[mascara_interna]
    pixels_s_interno = canal_s[mascara_interna]
    pixels_v_anel = canal_v[mascara_anel]
    pixels_s_anel = canal_s[mascara_anel]

    if pixels_v.size == 0:
        return LedFeatures()

    v_mean = float(np.mean(pixels_v))
    v_max = float(np.max(pixels_v))
    v_min = float(np.min(pixels_v))
    v_std = float(np.std(pixels_v))
    v_p90 = float(np.percentile(pixels_v, 90))
    v_p95 = float(np.percentile(pixels_v, 95))
    v_p99 = float(np.percentile(pixels_v, 99))

    s_mean = float(np.mean(pixels_s))
    s_std = float(np.std(pixels_s))
    s_p90 = float(np.percentile(pixels_s, 90))
    h_mean = float(np.mean(pixels_h))

    inner_v_mean = float(np.mean(pixels_v_interno)) if pixels_v_interno.size else 0.0
    ring_v_mean = float(np.mean(pixels_v_anel)) if pixels_v_anel.size else 0.0
    inner_s_mean = float(np.mean(pixels_s_interno)) if pixels_s_interno.size else 0.0
    ring_s_mean = float(np.mean(pixels_s_anel)) if pixels_s_anel.size else 0.0

    center_to_ring_v = inner_v_mean - ring_v_mean
    center_to_ring_s = inner_s_mean - ring_s_mean

    percent_on_default = float(np.sum(pixels_v >= DEFAULT_THRESHOLD_V) / pixels_v.size)
    percent_hot_220 = float(np.sum(pixels_v >= 220) / pixels_v.size)
    percent_hot_235 = float(np.sum(pixels_v >= 235) / pixels_v.size)
    percent_hot_245 = float(np.sum(pixels_v >= 245) / pixels_v.size)
    percent_hot_250 = float(np.sum(pixels_v >= 250) / pixels_v.size)

    glow_score = (
        (max(0.0, center_to_ring_v) * 1.20)
        + (v_std * 0.70)
        + (max(0.0, v_p99 - v_p90) * 0.85)
        + (percent_hot_245 * 100.0)
        + (percent_hot_250 * 150.0)
    )

    return LedFeatures(
        v_mean=round(v_mean, 4),
        v_max=round(v_max, 4),
        v_min=round(v_min, 4),
        v_std=round(v_std, 4),
        v_p90=round(v_p90, 4),
        v_p95=round(v_p95, 4),
        v_p99=round(v_p99, 4),
        s_mean=round(s_mean, 4),
        s_std=round(s_std, 4),
        s_p90=round(s_p90, 4),
        h_mean=round(h_mean, 4),
        inner_v_mean=round(inner_v_mean, 4),
        ring_v_mean=round(ring_v_mean, 4),
        center_to_ring_v=round(center_to_ring_v, 4),
        inner_s_mean=round(inner_s_mean, 4),
        ring_s_mean=round(ring_s_mean, 4),
        center_to_ring_s=round(center_to_ring_s, 4),
        percent_on=round(percent_on_default, 6),
        percent_hot_220=round(percent_hot_220, 6),
        percent_hot_235=round(percent_hot_235, 6),
        percent_hot_245=round(percent_hot_245, 6),
        percent_hot_250=round(percent_hot_250, 6),
        glow_score=round(glow_score, 4),
        area_pixels=int(pixels_v.size),
        inner_area_pixels=int(pixels_v_interno.size),
        ring_area_pixels=int(pixels_v_anel.size),
    )
