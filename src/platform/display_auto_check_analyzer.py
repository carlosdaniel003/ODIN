from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import cv2

from src.core.classifier import ReferenceLedClassifier
from src.core.feature_extractor import extrair_features_selecao
from src.core.roi_geometry import (
    TIPO_ROI_CIRCULO,
    TIPO_ROI_SEGMENTO,
    raio_compatibilidade_segmento,
)
from src.models.led_features import LedFeatures
from src.models.led_selection import LedSelection
from src.platform.display_mask_geometry import converter_mascara_legada_para_editor
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_IGNORE,
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
    normalizar_resolucao_display,
)
from src.platform.display_reference_store import (
    DISPLAY_REFERENCE_TYPES,
    DisplayReferenceLearningStore,
    display_learning_path_for_repository,
)
from src.platform.display_visual_rotation import preparar_check_visual_display


DISPLAY_AUTO_CLASS_LOW_LIGHT = "low_light"
DISPLAY_AUTO_CLASS_LABELS = {
    DISPLAY_CHECK_STATE_ON: "ACESO",
    DISPLAY_CHECK_STATE_OFF: "APAGADO",
    DISPLAY_AUTO_CLASS_LOW_LIGHT: "POUCA LUZ",
}

# Distância mantida apenas para detectar a classe opcional POUCA LUZ.
# A decisão ACESO/APAGADO usa exatamente o ReferenceLedClassifier já validado
# no fluxo normal do ODIN.
DISPLAY_AUTO_FEATURE_WEIGHTS = {
    "v_mean": 0.08,
    "v_max": 0.45,
    "v_std": 1.15,
    "v_p95": 0.55,
    "v_p99": 0.75,
    "s_mean": 0.22,
    "s_std": 0.35,
    "center_to_ring_v": 1.35,
    "center_to_ring_s": 0.35,
    "percent_hot_235": 120.0,
    "percent_hot_245": 180.0,
    "percent_hot_250": 240.0,
    "glow_score": 1.85,
}

# POUCA LUZ só substitui a decisão binária quando estiver claramente mais
# próxima da própria referência do que de ACESO/APAGADO.
DISPLAY_AUTO_LOW_LIGHT_DISTANCE_RATIO = 0.85


@dataclass(frozen=True)
class DisplayStateClassification:
    state: str
    label: str
    confidence: float
    distances: dict[str, float]


class DisplayLearnedStateClassifier:
    """Classificação F3 alinhada ao classificador validado do ODIN."""

    def __init__(
        self,
        learned_on: LedFeatures,
        learned_off: LedFeatures,
        learned_low_light: LedFeatures | None = None,
    ) -> None:
        if learned_on is None or learned_off is None:
            raise ValueError(
                "O aprendizado Display precisa de ACESO e APAGADO."
            )

        self.learned_on = learned_on
        self.learned_off = learned_off
        self.learned_low_light = learned_low_light
        self._binary_classifier = ReferenceLedClassifier(
            features_referencia_acesa=learned_on,
            features_referencia_apagada=learned_off,
        )

    @staticmethod
    def _distance(current: LedFeatures, reference: LedFeatures) -> float:
        distance = 0.0
        for name, weight in DISPLAY_AUTO_FEATURE_WEIGHTS.items():
            distance += abs(
                float(getattr(current, name, 0.0))
                - float(getattr(reference, name, 0.0))
            ) * float(weight)
        return float(distance)

    def classify(
        self,
        features: LedFeatures,
        selection: LedSelection | None = None,
    ) -> DisplayStateClassification:
        center_x = int(getattr(selection, "centro_x", 0) or 0)
        center_y = int(getattr(selection, "centro_y", 0) or 0)
        radius = max(1, int(getattr(selection, "raio", 1) or 1))

        # Mesma decisão óptica usada no modo normal: brilho, similaridade,
        # picos, contraste, glow, métricas e limiares dinâmicos.
        binary = self._binary_classifier.classificar_led_por_referencia(
            features_atual=features,
            centro_x=center_x,
            centro_y=center_y,
            raio=radius,
        )
        binary_state = (
            DISPLAY_CHECK_STATE_ON
            if int(getattr(binary, "valor_binario", 0) or 0) == 1
            else DISPLAY_CHECK_STATE_OFF
        )
        confidence = float(getattr(binary, "confianca", 0.50) or 0.50)

        distance_on = float(getattr(binary, "distancia_on", 0.0) or 0.0)
        distance_off = float(getattr(binary, "distancia_off", 0.0) or 0.0)
        distances = {
            DISPLAY_CHECK_STATE_ON: distance_on,
            DISPLAY_CHECK_STATE_OFF: distance_off,
        }

        state = binary_state

        if self.learned_low_light is not None:
            low_distance = self._distance(features, self.learned_low_light)
            distances[DISPLAY_AUTO_CLASS_LOW_LIGHT] = low_distance
            binary_best = min(distance_on, distance_off)

            if (
                binary_best > 1e-9
                and low_distance
                <= binary_best * DISPLAY_AUTO_LOW_LIGHT_DISTANCE_RATIO
            ):
                state = DISPLAY_AUTO_CLASS_LOW_LIGHT
                ordered = sorted(distances.values())
                best = ordered[0]
                second = ordered[1]
                denominator = max(1e-9, best + second)
                confidence = max(
                    0.50,
                    min(0.99, float(second / denominator)),
                )

        return DisplayStateClassification(
            state=state,
            label=DISPLAY_AUTO_CLASS_LABELS[state],
            confidence=round(float(confidence), 4),
            distances={
                key: round(float(value), 4)
                for key, value in distances.items()
            },
        )


def display_mask_to_analysis_selection(mask: dict) -> LedSelection:
    """Converte a geometria persistida do Display para o extrator comum."""
    item = converter_mascara_legada_para_editor(deepcopy(mask))
    kind = str(item.get("type", "")).lower()
    mask_id = str(item.get("id") or "DISPLAY_MASK")

    if kind == "circle":
        return LedSelection(
            id=mask_id,
            centro_x=int(item.get("cx", 0)),
            centro_y=int(item.get("cy", 0)),
            raio=max(2, int(item.get("radius", 2))),
            tipo_roi=TIPO_ROI_CIRCULO,
        )

    if kind == "segment":
        width = max(1, int(item.get("width", 1)))
        height = max(1, int(item.get("height", 1)))
        return LedSelection(
            id=mask_id,
            centro_x=int(item.get("cx", 0)),
            centro_y=int(item.get("cy", 0)),
            raio=raio_compatibilidade_segmento(width, height),
            tipo_roi=TIPO_ROI_SEGMENTO,
            largura=width,
            altura=height,
            angulo=float(item.get("angle", 0.0) or 0.0),
        )

    if kind == "polygon":
        points = [
            (float(point[0]), float(point[1]))
            for point in item.get("points", [])
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ]
        if len(points) < 3:
            raise ValueError(f"Máscara {mask_id} possui polígono inválido.")
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        cx = (min(xs) + max(xs)) / 2.0
        cy = (min(ys) + max(ys)) / 2.0
        width = max(1, int(round(max(xs) - min(xs))))
        height = max(1, int(round(max(ys) - min(ys))))
        return LedSelection(
            id=mask_id,
            centro_x=int(round(cx)),
            centro_y=int(round(cy)),
            raio=raio_compatibilidade_segmento(width, height),
            tipo_roi=TIPO_ROI_SEGMENTO,
            largura=width,
            altura=height,
            angulo=0.0,
            pontos_segmento_livre=[
                (x - cx, y - cy)
                for x, y in points
            ],
        )

    raise ValueError(f"Máscara {mask_id} possui tipo não suportado.")


class DisplayAutomaticCheckAnalyzer:
    """Analisa somente Projeto Display, CHECK atual e aprendizado Display."""

    def __init__(self, repository) -> None:
        self.repository = repository
        self.store = DisplayReferenceLearningStore(
            display_learning_path_for_repository(repository)
        )
        self._profile_cache_key = None
        self._profile_cache = None

    def invalidate_learning_cache(self) -> None:
        self._profile_cache_key = None
        self._profile_cache = None

    def _learning_cache_key(self, project_name: str):
        path = self.store.config_file
        try:
            stat = path.stat()
            signature = (int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            signature = (0, 0)
        return str(project_name), signature

    def _classifier_for_project(
        self,
        project_name: str,
    ) -> DisplayLearnedStateClassifier | None:
        cache_key = self._learning_cache_key(project_name)
        if cache_key == self._profile_cache_key:
            return self._profile_cache

        learned = {
            state: self.store.learned_features(project_name, state)
            for state in DISPLAY_REFERENCE_TYPES
        }
        classifier = None
        learned_on = learned.get(DISPLAY_CHECK_STATE_ON)
        learned_off = learned.get(DISPLAY_CHECK_STATE_OFF)
        if learned_on is not None and learned_off is not None:
            classifier = DisplayLearnedStateClassifier(
                learned_on=learned_on,
                learned_off=learned_off,
                learned_low_light=learned.get(DISPLAY_AUTO_CLASS_LOW_LIGHT),
            )
        self._profile_cache_key = cache_key
        self._profile_cache = classifier
        return classifier

    @staticmethod
    def _not_ready(reason: str, **extra) -> dict:
        return {
            "ready": False,
            "approved": None,
            "reason": str(reason),
            "mask_results": [],
            **extra,
        }

    def analyze(
        self,
        frame,
        project_name: str,
        check_id: str,
        visual_rotation: int = 0,
    ) -> dict:
        if frame is None or getattr(frame, "size", 0) == 0:
            return self._not_ready("camera_sem_frame")

        project = self.repository.carregar_projeto(project_name)
        if project is None:
            return self._not_ready("projeto_display_inexistente")

        check = self.repository.carregar_check(project_name, check_id)
        if check is None:
            return self._not_ready("check_display_inexistente")

        master_resolution = normalizar_resolucao_display(
            project.get("master_resolution")
        )
        if master_resolution is None:
            return self._not_ready("resolucao_mestra_ausente")

        masks = list(project.get("masks", []) or [])
        overrides = (
            check.get("mask_overrides_reference", {})
            if isinstance(check.get("mask_overrides_reference"), dict)
            else {}
        )
        if overrides:
            masks = [
                deepcopy(overrides.get(str(mask.get("id"))))
                if isinstance(overrides.get(str(mask.get("id"))), dict)
                else mask
                for mask in masks
                if isinstance(mask, dict)
            ]
        states = (
            check.get("mask_states", {})
            if isinstance(check.get("mask_states"), dict)
            else {}
        )
        active_masks = [
            mask
            for mask in masks
            if states.get(str(mask.get("id"))) in (
                DISPLAY_CHECK_STATE_ON,
                DISPLAY_CHECK_STATE_OFF,
            )
        ]
        if not active_masks:
            return self._not_ready(
                "check_sem_mascaras_ativas",
                project_name=str(project_name),
                check_id=str(check_id),
            )

        classifier = self._classifier_for_project(project_name)
        if classifier is None:
            return self._not_ready(
                "aprendizado_incompleto",
                project_name=str(project_name),
                check_id=str(check_id),
            )

        visual_frame, visual_resolution, visual_masks = preparar_check_visual_display(
            frame,
            master_resolution,
            masks,
            visual_rotation,
        )
        if visual_frame is None or getattr(visual_frame, "size", 0) == 0:
            return self._not_ready("camera_sem_frame_visual")

        target_width = max(1, int(visual_resolution[0]))
        target_height = max(1, int(visual_resolution[1]))
        if tuple(visual_frame.shape[:2]) != (target_height, target_width):
            interpolation = (
                cv2.INTER_AREA
                if (
                    visual_frame.shape[1] > target_width
                    or visual_frame.shape[0] > target_height
                )
                else cv2.INTER_LINEAR
            )
            visual_frame = cv2.resize(
                visual_frame,
                (target_width, target_height),
                interpolation=interpolation,
            )

        mask_by_id = {
            str(mask.get("id")): mask
            for mask in visual_masks
            if isinstance(mask, dict) and mask.get("id") is not None
        }

        results = []
        for original_mask in active_masks:
            mask_id = str(original_mask.get("id"))
            expected = str(states.get(mask_id))
            visual_mask = mask_by_id.get(mask_id)
            if visual_mask is None:
                return self._not_ready(
                    "mascara_visual_nao_encontrada",
                    project_name=str(project_name),
                    check_id=str(check_id),
                    mask_id=mask_id,
                )

            try:
                selection = display_mask_to_analysis_selection(visual_mask)
                features = extrair_features_selecao(visual_frame, selection)
            except (TypeError, ValueError):
                return self._not_ready(
                    "mascara_invalida",
                    project_name=str(project_name),
                    check_id=str(check_id),
                    mask_id=mask_id,
                )

            if int(getattr(features, "area_pixels", 0) or 0) <= 0:
                return self._not_ready(
                    "mascara_fora_do_frame",
                    project_name=str(project_name),
                    check_id=str(check_id),
                    mask_id=mask_id,
                )

            classification = classifier.classify(
                features,
                selection=selection,
            )
            matched = classification.state == expected
            results.append(
                {
                    "mask_id": mask_id,
                    "expected": expected,
                    "expected_label": DISPLAY_AUTO_CLASS_LABELS[expected],
                    "classified": classification.state,
                    "classified_label": classification.label,
                    "matched": bool(matched),
                    "confidence": classification.confidence,
                    "distances": classification.distances,
                    "features": features.to_dict(),
                }
            )

        approved = all(item["matched"] for item in results)
        return {
            "ready": True,
            "approved": bool(approved),
            "reason": "check_conforme" if approved else "check_nao_conforme",
            "project_name": str(project_name),
            "check_id": str(check_id),
            "check_name": str(check.get("name") or check_id),
            "mask_results": results,
            "active_mask_count": len(results),
            "matched_mask_count": sum(1 for item in results if item["matched"]),
            "ignored_mask_count": sum(
                1
                for mask in masks
                if states.get(str(mask.get("id"))) == DISPLAY_CHECK_STATE_IGNORE
            ),
        }
