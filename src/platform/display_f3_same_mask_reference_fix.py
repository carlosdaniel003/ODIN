from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import cv2

import src.platform.display_auto_check_runtime as runtime_module
import src.platform.display_f3_live_runtime_fix as live_runtime_module
from src.core.feature_extractor import extrair_features_selecao
from src.models.led_features import LedFeatures
from src.platform.display_auto_check_analyzer import (
    DISPLAY_AUTO_CLASS_LABELS,
    DISPLAY_AUTO_CLASS_LOW_LIGHT,
    DISPLAY_AUTO_FEATURE_WEIGHTS,
    display_mask_to_analysis_selection,
)
from src.platform.display_check_presence_reference import (
    DisplayCheckPresenceReferenceStore,
    avaliar_referencia_presenca_display,
)
from src.platform.display_mask_geometry import (
    sincronizar_formato_mascara_display,
)
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_IGNORE,
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
    mascaras_geometria_check_display,
    normalizar_mascaras_display,
    normalizar_resolucao_display,
)
from src.platform.display_visual_reference_status import (
    DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
    DisplayProjectPresenceReferenceStore,
)
from src.platform.display_visual_rotation import preparar_check_visual_display


# As fotos salvas em Gerenciar CHECKS são o aprendizado positivo/funcional do
# F3. Cada máscara marcada ACESO/APAGADO na foto real do CHECK vira uma amostra
# rotulada automaticamente. A foto "PLACA DESLIGADA NO SUPORTE" acrescenta uma
# referência OFF da MESMA máscara física. Isso elimina o fallback entre máscaras
# para segmentos que ficam ON em todos os CHECKS (ex.: um segmento comum a H1,
# BLUE, USB e AUX).
F3_SAME_MASK_REFERENCE_SOURCE = "f3_check_photos_same_mask"
F3_STATE_SAMPLE_FALLBACK_SOURCE = "f3_check_photos_class_pool"
F3_CHECK_PHOTO_LEARNING_SOURCE = "f3_check_photos_learning"

# Mantém a margem conservadora que já vinha sendo usada no F3: empate óptico
# não produz OK nem NG, apenas mantém a busca.
F3_CHECK_PHOTO_MIN_CONFIDENCE = 0.58
F3_CHECK_PHOTO_AMBIGUOUS_SEPARATION = 0.16

# POUCA LUZ deixa de depender de uma terceira referência manual. Ela só é
# inferida quando a leitura fica de forma estável entre exemplos reais APAGADO
# e ACESO da mesma máscara física.
F3_LOW_LIGHT_MIN_INTERPOLATION = 0.22
F3_LOW_LIGHT_MAX_INTERPOLATION = 0.72
F3_LOW_LIGHT_MAX_BINARY_SEPARATION = 0.45
F3_LOW_LIGHT_MIN_ENERGY_SPAN = 10.0


def _feature_distance(current: LedFeatures, reference: LedFeatures) -> float:
    distance = 0.0
    for name, weight in DISPLAY_AUTO_FEATURE_WEIGHTS.items():
        distance += abs(
            float(getattr(current, name, 0.0))
            - float(getattr(reference, name, 0.0))
        ) * float(weight)
    return float(distance)


def _nearest_reference(
    current: LedFeatures,
    references: list[LedFeatures],
) -> tuple[LedFeatures | None, int | None, float | None]:
    if not references:
        return None, None, None
    distances = [
        _feature_distance(current, reference)
        for reference in references
    ]
    index = min(range(len(distances)), key=distances.__getitem__)
    return references[index], int(index), float(distances[index])


def _separation(distance_on: float, distance_off: float) -> float:
    denominator = max(1e-9, float(distance_on) + float(distance_off))
    return abs(float(distance_on) - float(distance_off)) / denominator


def _optical_energy(features: LedFeatures) -> float:
    """Escalar de brilho/glow usado apenas para detectar estado intermediário."""
    return float(
        (0.14 * float(getattr(features, "v_mean", 0.0)))
        + (0.16 * float(getattr(features, "v_max", 0.0)))
        + (0.24 * float(getattr(features, "v_p95", 0.0)))
        + (0.24 * float(getattr(features, "v_p99", 0.0)))
        + (0.22 * float(getattr(features, "glow_score", 0.0)) * 3.0)
    )


def _low_light_from_real_pair(
    current: LedFeatures,
    on_reference: LedFeatures,
    off_reference: LedFeatures,
    distance_on: float,
    distance_off: float,
) -> tuple[bool, float | None]:
    """Detecta pouca luz somente entre APAGADO/ACESO reais da mesma máscara."""
    on_energy = _optical_energy(on_reference)
    off_energy = _optical_energy(off_reference)
    current_energy = _optical_energy(current)
    span = float(on_energy - off_energy)
    if span < F3_LOW_LIGHT_MIN_ENERGY_SPAN:
        return False, None

    interpolation = (current_energy - off_energy) / max(1e-9, span)
    if not (
        F3_LOW_LIGHT_MIN_INTERPOLATION
        <= interpolation
        <= F3_LOW_LIGHT_MAX_INTERPOLATION
    ):
        return False, float(interpolation)

    separation = _separation(distance_on, distance_off)
    if separation > F3_LOW_LIGHT_MAX_BINARY_SEPARATION:
        return False, float(interpolation)

    return True, float(interpolation)


def classificar_mascara_por_referencias_locais_f3(
    *,
    current: LedFeatures,
    on_references: list[LedFeatures],
    off_references: list[LedFeatures],
    low_light_references: list[LedFeatures] | None = None,
    detect_low_light: bool = True,
) -> dict | None:
    """Classifica usando exclusivamente amostras extraídas das fotos dos CHECKS.

    ``low_light_references`` é mantido apenas por compatibilidade de assinatura;
    o F3 não consulta mais o bloco manual de Referências e aprendizado.
    """
    del low_light_references

    on_reference, on_index, distance_on = _nearest_reference(
        current,
        list(on_references or ()),
    )
    off_reference, off_index, distance_off = _nearest_reference(
        current,
        list(off_references or ()),
    )
    if (
        on_reference is None
        or off_reference is None
        or distance_on is None
        or distance_off is None
    ):
        return None

    state = (
        DISPLAY_CHECK_STATE_ON
        if float(distance_on) < float(distance_off)
        else DISPLAY_CHECK_STATE_OFF
    )
    separation = _separation(float(distance_on), float(distance_off))
    confidence = min(0.99, 0.50 + (0.49 * separation))
    low_light_interpolation = None

    if detect_low_light:
        is_low_light, low_light_interpolation = _low_light_from_real_pair(
            current,
            on_reference,
            off_reference,
            float(distance_on),
            float(distance_off),
        )
        if is_low_light:
            state = DISPLAY_AUTO_CLASS_LOW_LIGHT
            centrality = 1.0 - min(
                1.0,
                abs(float(low_light_interpolation) - 0.47) / 0.25,
            )
            confidence = min(0.90, 0.60 + (0.30 * centrality))

    if (
        state != DISPLAY_AUTO_CLASS_LOW_LIGHT
        and separation < F3_CHECK_PHOTO_AMBIGUOUS_SEPARATION
    ):
        confidence = min(
            confidence,
            F3_CHECK_PHOTO_MIN_CONFIDENCE - 0.01,
        )

    return {
        "state": state,
        "label": DISPLAY_AUTO_CLASS_LABELS[state],
        "confidence": round(float(confidence), 4),
        "distances": {
            DISPLAY_CHECK_STATE_ON: round(float(distance_on), 4),
            DISPLAY_CHECK_STATE_OFF: round(float(distance_off), 4),
        },
        "reference_source": F3_SAME_MASK_REFERENCE_SOURCE,
        "reference_separation": round(float(separation), 4),
        "nearest_reference_indexes": {
            DISPLAY_CHECK_STATE_ON: on_index,
            DISPLAY_CHECK_STATE_OFF: off_index,
        },
        "reference_counts": {
            DISPLAY_CHECK_STATE_ON: len(on_references or ()),
            DISPLAY_CHECK_STATE_OFF: len(off_references or ()),
            DISPLAY_AUTO_CLASS_LOW_LIGHT: 0,
        },
        "low_light_interpolation": (
            None
            if low_light_interpolation is None
            else round(float(low_light_interpolation), 4)
        ),
    }


class F3SameMaskReferenceAnalyzer:
    """Analisador F3 treinado automaticamente pelas fotos reais dos CHECKS."""

    def __init__(self, repository) -> None:
        self.repository = repository
        self.presence_store = DisplayCheckPresenceReferenceStore(repository)
        self.project_presence_store = DisplayProjectPresenceReferenceStore(
            repository
        )
        self._check_photo_cache_key = None
        self._check_photo_cache = None

    @staticmethod
    def _not_ready(reason: str, **extra) -> dict:
        return {
            "ready": False,
            "approved": None,
            "reason": str(reason),
            "mask_results": [],
            "reference_authority": F3_CHECK_PHOTO_LEARNING_SOURCE,
            **extra,
        }

    def invalidate_learning_cache(self) -> None:
        """Compatibilidade com o runtime: invalida o dataset das fotos dos CHECKS."""
        self._check_photo_cache_key = None
        self._check_photo_cache = None

    def _check_photo_signature(
        self,
        project_name: str,
        project: dict,
        visual_rotation: int,
    ):
        checks_signature = []
        for check in self.repository.listar_checks(project_name):
            check_id = str(check.get("id") or "")
            states = check.get("mask_states", {})
            states_signature = tuple(
                sorted(
                    (str(mask_id), str(state))
                    for mask_id, state in (
                        states.items() if isinstance(states, dict) else ()
                    )
                )
            )
            metadata = self.presence_store.get(project_name, check_id)
            image_signature = ("", 0, 0)
            if isinstance(metadata, dict):
                path = Path(str(metadata.get("image_path") or ""))
                try:
                    stat = path.stat()
                    image_signature = (
                        str(path),
                        int(stat.st_mtime_ns),
                        int(stat.st_size),
                    )
                except OSError:
                    image_signature = (str(path), 0, 0)
            checks_signature.append(
                (check_id, states_signature, image_signature)
            )

        board_off_metadata = self.project_presence_store.get(
            project_name,
            DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
        )
        board_off_image_signature = ("", 0, 0)
        board_off_geometry_signature = ""
        if isinstance(board_off_metadata, dict):
            path = Path(str(board_off_metadata.get("image_path") or ""))
            try:
                stat = path.stat()
                board_off_image_signature = (
                    str(path),
                    int(stat.st_mtime_ns),
                    int(stat.st_size),
                )
            except OSError:
                board_off_image_signature = (str(path), 0, 0)
            board_off_geometry_signature = repr(
                (
                    board_off_metadata.get("masks_reference", []),
                    board_off_metadata.get("mask_overrides_reference", {}),
                )
            )

        return (
            str(project_name),
            int(visual_rotation),
            str(project.get("updated_at") or ""),
            tuple(checks_signature),
            board_off_image_signature,
            board_off_geometry_signature,
        )

    def _check_reference_context(
        self,
        project_name: str,
        check_id: str,
        project: dict,
        masks: list[dict],
        visual_rotation: int,
    ) -> tuple[object | None, dict[str, dict], bool]:
        metadata = self.presence_store.get(project_name, check_id)
        if not isinstance(metadata, dict):
            return None, {}, False

        path = Path(str(metadata.get("image_path") or ""))
        image = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.is_file() else None
        if image is None or getattr(image, "size", 0) == 0:
            return None, {}, True

        master_resolution = normalizar_resolucao_display(
            project.get("master_resolution")
        )
        if master_resolution is None:
            return None, {}, True

        try:
            reference_check = self.repository.carregar_check(
                project_name,
                check_id,
            )
        except Exception:
            reference_check = None
        reference_masks = mascaras_geometria_check_display(
            project,
            reference_check,
        )
        if not reference_masks:
            reference_masks = list(masks or [])

        visual_frame, _visual_resolution, visual_masks = preparar_check_visual_display(
            image,
            master_resolution,
            reference_masks,
            visual_rotation,
        )
        if visual_frame is None or getattr(visual_frame, "size", 0) == 0:
            return None, {}, True

        mask_by_id = {
            str(mask.get("id")): mask
            for mask in visual_masks
            if isinstance(mask, dict) and mask.get("id") is not None
        }
        return visual_frame, mask_by_id, True

    def _board_off_reference_context(
        self,
        project_name: str,
        project: dict,
        masks: list[dict],
        visual_rotation: int,
    ) -> tuple[object | None, dict[str, dict], bool]:
        """Carrega a placa desligada como OFF da própria máscara física.

        Somente geometria explicitamente salva sobre a foto de placa desligada é
        aceita. Não projetamos coordenadas canônicas por suposição, porque um
        deslocamento de poucos pixels é suficiente para contaminar um segmento.
        """
        metadata = self.project_presence_store.get(
            project_name,
            DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
        )
        if not isinstance(metadata, dict):
            return None, {}, False

        path = Path(str(metadata.get("image_path") or ""))
        image = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.is_file() else None
        if image is None or getattr(image, "size", 0) == 0:
            return None, {}, True

        master_resolution = normalizar_resolucao_display(
            project.get("master_resolution")
        )
        if master_resolution is None:
            return None, {}, True

        reference_masks = []
        if "masks_reference" in metadata:
            reference_masks = normalizar_mascaras_display(
                deepcopy(metadata.get("masks_reference", []))
            )
        if not reference_masks:
            overrides = metadata.get("mask_overrides_reference", {})
            if isinstance(overrides, dict):
                for base in masks or ():
                    if not isinstance(base, dict):
                        continue
                    mask_id = str(base.get("id") or "")
                    raw = overrides.get(mask_id)
                    if not isinstance(raw, dict):
                        continue
                    item = sincronizar_formato_mascara_display(
                        deepcopy(base),
                        deepcopy(raw),
                    )
                    item["id"] = mask_id
                    reference_masks.append(item)

        if not reference_masks:
            return None, {}, True

        visual_frame, _visual_resolution, visual_masks = preparar_check_visual_display(
            image,
            master_resolution,
            reference_masks,
            visual_rotation,
        )
        if visual_frame is None or getattr(visual_frame, "size", 0) == 0:
            return None, {}, True

        mask_by_id = {
            str(mask.get("id")): mask
            for mask in visual_masks
            if isinstance(mask, dict) and mask.get("id") is not None
        }
        return visual_frame, mask_by_id, True

    def _build_check_photo_learning(
        self,
        project_name: str,
        project: dict,
        masks: list[dict],
        visual_rotation: int,
    ) -> dict:
        by_mask: dict[str, dict] = {
            str(mask.get("id")): {
                DISPLAY_CHECK_STATE_ON: [],
                DISPLAY_CHECK_STATE_OFF: [],
                "sources": {
                    DISPLAY_CHECK_STATE_ON: [],
                    DISPLAY_CHECK_STATE_OFF: [],
                },
            }
            for mask in masks
            if isinstance(mask, dict) and mask.get("id") is not None
        }
        by_state = {
            DISPLAY_CHECK_STATE_ON: [],
            DISPLAY_CHECK_STATE_OFF: [],
        }
        state_sources = {
            DISPLAY_CHECK_STATE_ON: [],
            DISPLAY_CHECK_STATE_OFF: [],
        }
        photo_count = 0
        sample_count = 0

        for check in self.repository.listar_checks(project_name):
            check_id = str(check.get("id") or "")
            if not check_id:
                continue

            states = (
                check.get("mask_states", {})
                if isinstance(check.get("mask_states"), dict)
                else {}
            )
            reference_frame, reference_masks, configured = (
                self._check_reference_context(
                    project_name,
                    check_id,
                    project,
                    masks,
                    visual_rotation,
                )
            )
            if not configured or reference_frame is None:
                continue

            photo_count += 1
            check_name = str(check.get("name") or check_id)
            for mask_id, profile in by_mask.items():
                state = str(states.get(mask_id) or "")
                if state not in (
                    DISPLAY_CHECK_STATE_ON,
                    DISPLAY_CHECK_STATE_OFF,
                ):
                    continue

                visual_mask = reference_masks.get(mask_id)
                if visual_mask is None:
                    continue

                try:
                    selection = display_mask_to_analysis_selection(visual_mask)
                    features = extrair_features_selecao(
                        reference_frame,
                        selection,
                    )
                except (TypeError, ValueError):
                    continue

                if int(getattr(features, "area_pixels", 0) or 0) <= 0:
                    continue

                source = {
                    "check_id": check_id,
                    "check_name": check_name,
                    "mask_id": mask_id,
                    "state": state,
                }
                profile[state].append(features)
                profile["sources"][state].append(source)
                by_state[state].append(features)
                state_sources[state].append(source)
                sample_count += 1

        board_off_frame, board_off_masks, board_off_configured = (
            self._board_off_reference_context(
                project_name,
                project,
                masks,
                visual_rotation,
            )
        )
        board_off_sample_count = 0
        if board_off_frame is not None:
            for mask_id, profile in by_mask.items():
                visual_mask = board_off_masks.get(mask_id)
                if visual_mask is None:
                    continue
                try:
                    selection = display_mask_to_analysis_selection(visual_mask)
                    features = extrair_features_selecao(
                        board_off_frame,
                        selection,
                    )
                except (TypeError, ValueError):
                    continue
                if int(getattr(features, "area_pixels", 0) or 0) <= 0:
                    continue

                # Importante: a referência de placa desligada entra SOMENTE no
                # perfil local da mesma máscara. Não alimenta o pool global OFF,
                # pois o objetivo é justamente impedir comparação cruzada entre
                # segmentos fisicamente diferentes.
                source = {
                    "check_id": "BOARD_OFF",
                    "check_name": "PLACA DESLIGADA NO SUPORTE",
                    "reference_kind": DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                    "mask_id": mask_id,
                    "state": DISPLAY_CHECK_STATE_OFF,
                }
                profile[DISPLAY_CHECK_STATE_OFF].append(features)
                profile["sources"][DISPLAY_CHECK_STATE_OFF].append(source)
                board_off_sample_count += 1

        return {
            "by_mask": by_mask,
            "by_state": by_state,
            "state_sources": state_sources,
            "photo_count": int(photo_count),
            "sample_count": int(sample_count),
            "board_off_reference_configured": bool(board_off_configured),
            "board_off_sample_count": int(board_off_sample_count),
        }

    def _check_photo_learning(
        self,
        project_name: str,
        project: dict,
        masks: list[dict],
        visual_rotation: int,
    ) -> dict:
        cache_key = self._check_photo_signature(
            project_name,
            project,
            visual_rotation,
        )
        if cache_key == self._check_photo_cache_key:
            return self._check_photo_cache or {}

        learning = self._build_check_photo_learning(
            project_name,
            project,
            masks,
            visual_rotation,
        )
        self._check_photo_cache_key = cache_key
        self._check_photo_cache = learning
        return learning

    @staticmethod
    def _source_for_index(sources: list[dict], index):
        try:
            source_index = int(index)
        except (TypeError, ValueError):
            return None
        if source_index < 0 or source_index >= len(sources):
            return None
        return dict(sources[source_index])

    def _references_for_mask(
        self,
        mask_id: str,
        learning: dict,
    ) -> tuple[list[LedFeatures], list[LedFeatures], str, dict]:
        by_mask = learning.get("by_mask", {})
        by_state = learning.get("by_state", {})
        profile = by_mask.get(mask_id, {}) if isinstance(by_mask, dict) else {}

        local_on = list(profile.get(DISPLAY_CHECK_STATE_ON, []) or [])
        local_off = list(profile.get(DISPLAY_CHECK_STATE_OFF, []) or [])
        global_on = list(by_state.get(DISPLAY_CHECK_STATE_ON, []) or [])
        global_off = list(by_state.get(DISPLAY_CHECK_STATE_OFF, []) or [])

        complete_local_pair = bool(local_on and local_off)
        if complete_local_pair:
            return (
                local_on,
                local_off,
                F3_SAME_MASK_REFERENCE_SOURCE,
                {
                    "profile": profile,
                    "local_on": True,
                    "local_off": True,
                    "complete_local_pair": True,
                },
            )

        # Depois de incorporar a placa desligada como OFF local, este fallback
        # fica restrito principalmente a máscaras que nunca possuem exemplo ON
        # próprio em nenhum CHECK. Não existe retorno ao bloco manual.
        on_references = local_on or global_on
        off_references = local_off or global_off
        return (
            on_references,
            off_references,
            F3_STATE_SAMPLE_FALLBACK_SOURCE,
            {
                "profile": profile,
                "local_on": bool(local_on),
                "local_off": bool(local_off),
                "complete_local_pair": False,
            },
        )

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

        masks = mascaras_geometria_check_display(project, check)
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

        learning = self._check_photo_learning(
            project_name,
            project,
            masks,
            visual_rotation,
        )
        by_state = learning.get("by_state", {})
        on_samples = list(by_state.get(DISPLAY_CHECK_STATE_ON, []) or [])
        off_samples = list(by_state.get(DISPLAY_CHECK_STATE_OFF, []) or [])
        if not on_samples or not off_samples:
            return self._not_ready(
                "checks_sem_amostras_aceso_apagado",
                project_name=str(project_name),
                check_id=str(check_id),
                check_photo_count=int(learning.get("photo_count", 0) or 0),
                check_photo_sample_count=int(learning.get("sample_count", 0) or 0),
                check_photo_on_sample_count=len(on_samples),
                check_photo_off_sample_count=len(off_samples),
            )

        use_geometry_override = bool(
            mask_geometry_override
            and frame is not None
            and getattr(frame, "size", 0) > 0
        )
        if use_geometry_override:
            # O tracking já projetou as máscaras para o frame RAW real. Não
            # giramos nem warpamos novamente: isso evita o duplo deslocamento de
            # alguns segmentos na borda do display (ex.: falso ON em MASK_020).
            visual_frame = frame
            visual_masks = [
                item
                for item in (mask_geometry_override or ())
                if isinstance(item, dict) and str(item.get("id") or "")
            ]
            frame_h, frame_w = visual_frame.shape[:2]
            visual_resolution = (int(frame_w), int(frame_h))
            if isinstance(mask_geometry_resolution, (list, tuple)) and len(mask_geometry_resolution) >= 2:
                try:
                    expected_resolution = (
                        int(mask_geometry_resolution[0]),
                        int(mask_geometry_resolution[1]),
                    )
                except (TypeError, ValueError):
                    expected_resolution = visual_resolution
                if expected_resolution != visual_resolution:
                    use_geometry_override = False

        if not use_geometry_override:
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
        local_pair_count = 0
        local_used_count = 0
        pool_fallback_count = 0

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

            (
                on_references,
                off_references,
                reference_source,
                reference_context,
            ) = self._references_for_mask(mask_id, learning)

            classified = classificar_mascara_por_referencias_locais_f3(
                current=features,
                on_references=on_references,
                off_references=off_references,
                detect_low_light=bool(
                    reference_context.get("complete_local_pair")
                ),
            )
            if classified is None:
                return self._not_ready(
                    "checks_sem_amostras_para_mascara",
                    project_name=str(project_name),
                    check_id=str(check_id),
                    mask_id=mask_id,
                )

            nearest = classified.get("nearest_reference_indexes", {})
            profile = reference_context.get("profile", {})
            if reference_context.get("complete_local_pair"):
                local_pair_count += 1
                local_used_count += 1
                on_sources = (
                    profile.get("sources", {}).get(DISPLAY_CHECK_STATE_ON, [])
                    if isinstance(profile, dict)
                    else []
                )
                off_sources = (
                    profile.get("sources", {}).get(DISPLAY_CHECK_STATE_OFF, [])
                    if isinstance(profile, dict)
                    else []
                )
            else:
                pool_fallback_count += 1
                # Para o estado local existente preservamos a origem por máscara;
                # para o ausente usamos a origem do pool global de fotos.
                state_sources = learning.get("state_sources", {})
                profile_sources = (
                    profile.get("sources", {})
                    if isinstance(profile, dict)
                    else {}
                )
                on_sources = (
                    profile_sources.get(DISPLAY_CHECK_STATE_ON, [])
                    if reference_context.get("local_on")
                    else state_sources.get(DISPLAY_CHECK_STATE_ON, [])
                )
                off_sources = (
                    profile_sources.get(DISPLAY_CHECK_STATE_OFF, [])
                    if reference_context.get("local_off")
                    else state_sources.get(DISPLAY_CHECK_STATE_OFF, [])
                )

            item = {
                "mask_id": mask_id,
                "expected": expected,
                "expected_label": DISPLAY_AUTO_CLASS_LABELS[expected],
                "classified": classified["state"],
                "classified_label": classified["label"],
                "matched": bool(classified["state"] == expected),
                "confidence": classified["confidence"],
                "distances": classified["distances"],
                "features": features.to_dict(),
                "reference_source": reference_source,
                "reference_separation": classified["reference_separation"],
                "nearest_reference_indexes": nearest,
                "reference_counts": classified["reference_counts"],
                "low_light_interpolation": classified.get(
                    "low_light_interpolation"
                ),
                "reference_checks": {
                    DISPLAY_CHECK_STATE_ON: self._source_for_index(
                        list(on_sources or ()),
                        nearest.get(DISPLAY_CHECK_STATE_ON),
                    ),
                    DISPLAY_CHECK_STATE_OFF: self._source_for_index(
                        list(off_sources or ()),
                        nearest.get(DISPLAY_CHECK_STATE_OFF),
                    ),
                },
            }
            results.append(item)

        approved = all(bool(item.get("matched")) for item in results)
        metadata = self.presence_store.get(project_name, check_id)
        presence = avaliar_referencia_presenca_display(frame, metadata)
        presence["decision_authority"] = False
        presence["role"] = "check_photo_learning_diagnostic"

        return {
            "ready": True,
            "approved": bool(approved),
            "reason": (
                "check_conforme_aprendizado_fotos_checks"
                if approved
                else "check_nao_conforme_aprendizado_fotos_checks"
            ),
            "project_name": str(project_name),
            "check_id": str(check_id),
            "check_name": str(check.get("name") or check_id),
            "mask_results": results,
            "active_mask_count": len(results),
            "matched_mask_count": sum(
                1 for item in results if bool(item.get("matched"))
            ),
            "ignored_mask_count": sum(
                1
                for mask in masks
                if states.get(str(mask.get("id"))) == DISPLAY_CHECK_STATE_IGNORE
            ),
            "reference_authority": F3_CHECK_PHOTO_LEARNING_SOURCE,
            "check_photo_count": int(learning.get("photo_count", 0) or 0),
            "check_photo_sample_count": int(learning.get("sample_count", 0) or 0),
            "check_photo_on_sample_count": len(on_samples),
            "check_photo_off_sample_count": len(off_samples),
            "board_off_reference_configured": bool(
                learning.get("board_off_reference_configured", False)
            ),
            "board_off_same_mask_sample_count": int(
                learning.get("board_off_sample_count", 0) or 0
            ),
            "same_mask_reference_pair_count": int(local_pair_count),
            "same_mask_reference_used_count": int(local_used_count),
            "check_photo_pool_fallback_used_count": int(pool_fallback_count),
            "presence_reference": presence,
            "live_geometry_override": bool(use_geometry_override),
            "live_geometry_source": (
                str(mask_geometry_source or "")
                if use_geometry_override
                else ""
            ),
        }


_INSTALLED = False


def instalar_referencias_por_mesma_mascara_display_f3() -> None:
    """Instala no F3 o aprendizado automático vindo das fotos dos CHECKS."""
    global _INSTALLED
    if _INSTALLED:
        return

    runtime_module.DisplayAutomaticCheckAnalyzer = F3SameMaskReferenceAnalyzer
    live_runtime_module.DisplayAutomaticCheckAnalyzer = F3SameMaskReferenceAnalyzer
    _INSTALLED = True
