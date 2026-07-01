from __future__ import annotations

from dataclasses import dataclass
import time

import cv2
import numpy as np

from config import DEFAULT_THRESHOLD_V
from src.core.classifier import ReferenceLedClassifier
from src.models.led_features import LedFeatures
from src.models.led_selection import LedSelection


class OperationPreparationError(RuntimeError):
    """Indica que o modo de operação ainda não pode ser executado."""


@dataclass(frozen=True)
class PreparedLed:
    id: str
    centro_x: int
    centro_y: int
    raio: int
    x1: int
    y1: int
    x2: int
    y2: int
    mascara_led: np.ndarray
    mascara_interna: np.ndarray
    mascara_anel: np.ndarray


@dataclass(frozen=True)
class OperationResult:
    ok: bool
    failed_led_ids: tuple[str, ...]
    results: tuple
    elapsed_seconds: float


class OperationEngine:
    """
    Motor de inspeção de caminho curto para produção.

    As referências, o classificador, as coordenadas e as máscaras das ROIs são
    preparados uma vez. Em cada disparo, o frame é convertido para HSV apenas
    uma vez e somente as pequenas regiões dos LEDs são avaliadas.
    """

    def __init__(self) -> None:
        self._classifier: ReferenceLedClassifier | None = None
        self._prepared_leds: tuple[PreparedLed, ...] = ()
        self._frame_width = 0
        self._frame_height = 0

    @property
    def ready(self) -> bool:
        return self._classifier is not None and bool(self._prepared_leds)

    @property
    def led_count(self) -> int:
        return len(self._prepared_leds)

    def invalidate(self) -> None:
        self._classifier = None
        self._prepared_leds = ()
        self._frame_width = 0
        self._frame_height = 0

    def prepare(
        self,
        features_reference_on: LedFeatures,
        features_reference_off: LedFeatures,
        leds: list[LedSelection],
        frame_width: int,
        frame_height: int,
    ) -> None:
        frame_width = int(frame_width)
        frame_height = int(frame_height)

        if frame_width <= 0 or frame_height <= 0:
            raise OperationPreparationError(
                "Resolução da câmera inválida."
            )

        if features_reference_on is None or features_reference_off is None:
            raise OperationPreparationError(
                "Referências de LED aceso e apagado não carregadas."
            )

        if not leds:
            raise OperationPreparationError(
                "Nenhuma posição fixa de LED foi configurada."
            )

        prepared_leds: list[PreparedLed] = []

        for led in leds:
            prepared_led = self._prepare_led(
                led,
                frame_width,
                frame_height,
            )
            if prepared_led is not None:
                prepared_leds.append(prepared_led)

        if not prepared_leds:
            raise OperationPreparationError(
                "As posições dos LEDs não são válidas para 640x480."
            )

        if len(prepared_leds) != len(leds):
            raise OperationPreparationError(
                "Uma ou mais posições de LED ficaram fora da imagem."
            )

        self._classifier = ReferenceLedClassifier(
            features_referencia_acesa=features_reference_on,
            features_referencia_apagada=features_reference_off,
        )
        self._prepared_leds = tuple(prepared_leds)
        self._frame_width = frame_width
        self._frame_height = frame_height

    def _prepare_led(
        self,
        led: LedSelection,
        frame_width: int,
        frame_height: int,
    ) -> PreparedLed | None:
        center_x = int(led.centro_x)
        center_y = int(led.centro_y)
        radius = max(2, int(led.raio))

        x1 = max(0, center_x - radius)
        y1 = max(0, center_y - radius)
        x2 = min(frame_width, center_x + radius + 1)
        y2 = min(frame_height, center_y + radius + 1)

        if x2 <= x1 or y2 <= y1:
            return None

        local_center_x = center_x - x1
        local_center_y = center_y - y1
        roi_height = y2 - y1
        roi_width = x2 - x1

        yy, xx = np.ogrid[:roi_height, :roi_width]
        squared_distance = (
            (xx - local_center_x) ** 2
            + (yy - local_center_y) ** 2
        )

        inner_radius = max(2, int(radius * 0.45))
        ring_inner_radius = max(
            inner_radius + 1,
            int(radius * 0.62),
        )

        led_mask = squared_distance <= radius**2
        inner_mask = squared_distance <= inner_radius**2
        ring_mask = (
            (squared_distance >= ring_inner_radius**2)
            & (squared_distance <= radius**2)
        )

        if not np.any(led_mask):
            return None

        return PreparedLed(
            id=str(led.id),
            centro_x=center_x,
            centro_y=center_y,
            raio=radius,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            mascara_led=led_mask,
            mascara_interna=inner_mask,
            mascara_anel=ring_mask,
        )

    def analyze(self, frame) -> OperationResult:
        if not self.ready or self._classifier is None:
            raise OperationPreparationError(
                "Motor de operação não preparado."
            )

        if frame is None or getattr(frame, "size", 0) == 0:
            raise OperationPreparationError(
                "A câmera não forneceu um frame válido."
            )

        frame_height, frame_width = frame.shape[:2]
        if (
            frame_width != self._frame_width
            or frame_height != self._frame_height
        ):
            raise OperationPreparationError(
                "A resolução da câmera mudou. Reabra a tela de operação."
            )

        started_at = time.perf_counter()
        hsv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        results = []
        failed_led_ids: list[str] = []

        for prepared_led in self._prepared_leds:
            features = self._extract_prepared_features(
                hsv_frame,
                prepared_led,
            )
            result = self._classifier.classificar_led_por_referencia(
                features_atual=features,
                centro_x=prepared_led.centro_x,
                centro_y=prepared_led.centro_y,
                raio=prepared_led.raio,
            )
            result.id = prepared_led.id
            results.append(result)

            if result.status != "ACESO":
                failed_led_ids.append(prepared_led.id)

        elapsed_seconds = time.perf_counter() - started_at
        return OperationResult(
            ok=not failed_led_ids,
            failed_led_ids=tuple(failed_led_ids),
            results=tuple(results),
            elapsed_seconds=float(elapsed_seconds),
        )

    @staticmethod
    def _extract_prepared_features(
        hsv_frame,
        prepared_led: PreparedLed,
    ) -> LedFeatures:
        roi_hsv = hsv_frame[
            prepared_led.y1:prepared_led.y2,
            prepared_led.x1:prepared_led.x2,
        ]

        if roi_hsv.size == 0:
            return LedFeatures()

        channel_h = roi_hsv[:, :, 0]
        channel_s = roi_hsv[:, :, 1]
        channel_v = roi_hsv[:, :, 2]

        pixels_h = channel_h[prepared_led.mascara_led]
        pixels_s = channel_s[prepared_led.mascara_led]
        pixels_v = channel_v[prepared_led.mascara_led]
        inner_pixels_v = channel_v[prepared_led.mascara_interna]
        inner_pixels_s = channel_s[prepared_led.mascara_interna]
        ring_pixels_v = channel_v[prepared_led.mascara_anel]
        ring_pixels_s = channel_s[prepared_led.mascara_anel]

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

        inner_v_mean = (
            float(np.mean(inner_pixels_v))
            if inner_pixels_v.size
            else 0.0
        )
        ring_v_mean = (
            float(np.mean(ring_pixels_v))
            if ring_pixels_v.size
            else 0.0
        )
        inner_s_mean = (
            float(np.mean(inner_pixels_s))
            if inner_pixels_s.size
            else 0.0
        )
        ring_s_mean = (
            float(np.mean(ring_pixels_s))
            if ring_pixels_s.size
            else 0.0
        )

        center_to_ring_v = inner_v_mean - ring_v_mean
        center_to_ring_s = inner_s_mean - ring_s_mean

        percent_on = float(
            np.count_nonzero(pixels_v >= DEFAULT_THRESHOLD_V)
            / pixels_v.size
        )
        percent_hot_220 = float(
            np.count_nonzero(pixels_v >= 220) / pixels_v.size
        )
        percent_hot_235 = float(
            np.count_nonzero(pixels_v >= 235) / pixels_v.size
        )
        percent_hot_245 = float(
            np.count_nonzero(pixels_v >= 245) / pixels_v.size
        )
        percent_hot_250 = float(
            np.count_nonzero(pixels_v >= 250) / pixels_v.size
        )

        glow_score = (
            max(0.0, center_to_ring_v) * 1.20
            + v_std * 0.70
            + max(0.0, v_p99 - v_p90) * 0.85
            + percent_hot_245 * 100.0
            + percent_hot_250 * 150.0
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
            percent_on=round(percent_on, 6),
            percent_hot_220=round(percent_hot_220, 6),
            percent_hot_235=round(percent_hot_235, 6),
            percent_hot_245=round(percent_hot_245, 6),
            percent_hot_250=round(percent_hot_250, 6),
            glow_score=round(glow_score, 4),
            area_pixels=int(pixels_v.size),
            inner_area_pixels=int(inner_pixels_v.size),
            ring_area_pixels=int(ring_pixels_v.size),
        )
