from __future__ import annotations

"""Dataset neural do Display F3 construído a partir da configuração existente.

Esta camada não decide produção. Ela transforma os ativos já configurados no F3
(foto de cada CHECK, máscara local, ``mask_states`` e contorno local) em amostras
rotuladas para treinamento de um classificador CNN por segmento.

O runtime neural consumirá o mesmo preprocessamento para evitar diferença entre
treino e produção.
"""

from copy import deepcopy
from pathlib import Path
import re

import cv2
import numpy as np

from src.platform.display_check_presence_reference import (
    DisplayCheckPresenceReferenceStore,
)
from src.platform.display_mask_geometry import (
    bbox_mascara_display,
    converter_mascara_legada_para_editor,
    pontos_mascara_display,
)
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_IGNORE,
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
    DisplayProjectRepository,
    mascaras_geometria_check_display,
    normalizar_mascaras_display,
    normalizar_nome_projeto_display,
    normalizar_resolucao_display,
)


F3_NEURAL_DATASET_SCHEMA_VERSION = 1
F3_NEURAL_MODEL_METADATA_SCHEMA_VERSION = 3
F3_NEURAL_THRESHOLD_CALIBRATION_SOURCE = (
    "held_out_h1_augmented_probability_gap"
)
F3_NEURAL_INPUT_SIZE = 48
F3_NEURAL_CONTEXT_RATIO = 0.65
F3_NEURAL_BOARD_OFF_CHECK_ID = "BOARD_OFF"
F3_NEURAL_BOARD_OFF_CHECK_NAME = "PLACA OFF"
F3_NEURAL_BOARD_OFF_REFERENCE_KIND = "board_off"
F3_NEURAL_LABELS = {
    DISPLAY_CHECK_STATE_OFF: 0,
    DISPLAY_CHECK_STATE_ON: 1,
}


def _slug_model_name(value: str) -> str:
    text = re.sub(
        r"[^A-Za-z0-9_-]+",
        "_",
        str(value or "").strip(),
    )
    return text.strip("_").lower() or "display"


def f3_neural_model_path_for_repository(
    repository: DisplayProjectRepository,
    project_name: str,
) -> Path:
    """Destino local canônico do ONNX por Projeto Display.

    No layout do repositório (data/config/*.json), modelos ficam em data/models.
    No JIG, onde o repository aponta para ~/.config/odin/*.json, ficam ao lado
    da configuração em ~/.config/odin/models. Assim o runtime nunca depende do
    diretório atual do processo.
    """
    config_file = Path(
        getattr(
            repository,
            "config_file",
            "data/config/odin_display_projects.json",
        )
    )
    parent = config_file.parent
    if parent.name == "config" and parent.parent.name == "data":
        model_root = parent.parent / "models" / "f3_neural"
    else:
        model_root = parent / "models" / "f3_neural"
    return model_root / (
        f"{_slug_model_name(project_name)}_segments.onnx"
    )


def _valid_image(image) -> bool:
    return image is not None and getattr(image, "size", 0) > 0


def _prepare_bgr(image, resolution: tuple[int, int] | None = None):
    if not _valid_image(image):
        return None
    frame = image.copy()
    if frame.ndim == 2:
        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    elif frame.ndim == 3 and frame.shape[2] == 4:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    elif frame.ndim != 3 or frame.shape[2] != 3:
        return None

    if resolution is not None:
        width, height = int(resolution[0]), int(resolution[1])
        if width <= 0 or height <= 0:
            return None
        if frame.shape[:2] != (height, width):
            interpolation = (
                cv2.INTER_AREA
                if frame.shape[1] > width or frame.shape[0] > height
                else cv2.INTER_LINEAR
            )
            frame = cv2.resize(
                frame,
                (width, height),
                interpolation=interpolation,
            )
    return frame


def _rasterizar_mascara(mask: dict, width: int, height: int) -> np.ndarray:
    canvas = np.zeros((int(height), int(width)), dtype=np.uint8)
    item = converter_mascara_legada_para_editor(deepcopy(mask))
    kind = str(item.get("type") or "").strip().lower()

    if kind == "circle":
        try:
            center = (
                int(round(float(item["cx"]))),
                int(round(float(item["cy"]))),
            )
            radius = max(1, int(round(float(item["radius"]))))
        except (KeyError, TypeError, ValueError):
            return canvas
        cv2.circle(canvas, center, radius, 255, thickness=-1)
        return canvas

    points = pontos_mascara_display(item)
    if len(points) < 3:
        return canvas
    polygon = np.asarray(
        [[int(round(x)), int(round(y))] for x, y in points],
        dtype=np.int32,
    )
    cv2.fillPoly(canvas, [polygon], 255)
    return canvas


def extrair_tensor_segmento_f3(
    frame,
    mask: dict,
    *,
    input_size: int = F3_NEURAL_INPUT_SIZE,
    context_ratio: float = F3_NEURAL_CONTEXT_RATIO,
) -> np.ndarray | None:
    """Extrai RGB + canal binário da máscara em um crop com contexto.

    Retorno: ``float32`` em CHW, quatro canais, faixa 0..1.
    O quarto canal informa à CNN exatamente qual geometria desenhada pelo usuário
    é o segmento alvo; os pixels ao redor permanecem disponíveis para aprender
    reflexo/halo/contexto sem transformar o fundo em autoridade.
    """
    image = _prepare_bgr(frame)
    if image is None or not isinstance(mask, dict):
        return None

    size = max(16, int(input_size))
    height, width = image.shape[:2]
    item = converter_mascara_legada_para_editor(deepcopy(mask))
    x1f, y1f, x2f, y2f = bbox_mascara_display(item)
    box_width = max(1.0, float(x2f) - float(x1f))
    box_height = max(1.0, float(y2f) - float(y1f))
    pad = max(
        3.0,
        max(box_width, box_height) * max(0.0, float(context_ratio)),
    )

    x1 = max(0, int(np.floor(float(x1f) - pad)))
    y1 = max(0, int(np.floor(float(y1f) - pad)))
    x2 = min(width, int(np.ceil(float(x2f) + pad)) + 1)
    y2 = min(height, int(np.ceil(float(y2f) + pad)) + 1)
    if x2 <= x1 or y2 <= y1:
        return None

    full_mask = _rasterizar_mascara(item, width, height)
    if not np.any(full_mask[y1:y2, x1:x2]):
        return None

    crop = image[y1:y2, x1:x2]
    crop_mask = full_mask[y1:y2, x1:x2]
    if not _valid_image(crop):
        return None

    crop = cv2.resize(
        crop,
        (size, size),
        interpolation=cv2.INTER_LINEAR,
    )
    crop_mask = cv2.resize(
        crop_mask,
        (size, size),
        interpolation=cv2.INTER_NEAREST,
    )
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    mask_channel = (crop_mask.astype(np.float32) / 255.0)[..., None]
    tensor = np.concatenate((rgb, mask_channel), axis=2)
    return np.ascontiguousarray(
        tensor.transpose(2, 0, 1),
        dtype=np.float32,
    )


class F3NeuralDatasetBuilder:
    """Converte referências já configuradas do F3 em amostras ON/OFF."""

    def __init__(
        self,
        repository: DisplayProjectRepository,
        *,
        input_size: int = F3_NEURAL_INPUT_SIZE,
        context_ratio: float = F3_NEURAL_CONTEXT_RATIO,
    ) -> None:
        self.repository = repository
        self.presence_store = DisplayCheckPresenceReferenceStore(repository)
        self.input_size = max(16, int(input_size))
        self.context_ratio = max(0.0, float(context_ratio))

    def _reference_image(
        self,
        metadata: dict | None,
        resolution: tuple[int, int],
    ):
        if not isinstance(metadata, dict):
            return None
        path = Path(str(metadata.get("image_path") or ""))
        if not path.is_file():
            return None
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        return _prepare_bgr(image, resolution)

    def _board_off_reference_context(
        self,
        project_name: str,
        resolution: tuple[int, int],
    ) -> tuple[dict | None, object | None, list[dict]]:
        """Carrega a referência OFF física já configurada no próprio F3.

        O import fica local porque display_visual_reference_status também
        compõe UI/runtime F3. O dataset é usado offline e não deve criar ciclo
        de import durante o carregamento do runtime neural.
        """
        try:
            from src.platform.display_visual_reference_status import (
                DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
                DisplayProjectPresenceReferenceStore,
            )
        except Exception:
            return None, None, []

        try:
            metadata = DisplayProjectPresenceReferenceStore(
                self.repository
            ).get(
                project_name,
                DISPLAY_PROJECT_REFERENCE_BOARD_OFF,
            )
        except Exception:
            metadata = None
        if not isinstance(metadata, dict):
            return None, None, []

        image = self._reference_image(metadata, resolution)
        if image is None:
            return metadata, None, []

        # Somente geometria explicitamente salva sobre a foto de placa
        # desligada é aceita. Não projetamos as máscaras canônicas por
        # suposição, pois poucos pixels de erro já podem misturar a luz do
        # segmento vizinho com o alvo.
        masks: list[dict] = []
        if "masks_reference" in metadata:
            masks = normalizar_mascaras_display(
                deepcopy(metadata.get("masks_reference", []))
            )

        if not masks:
            overrides = metadata.get("mask_overrides_reference", {})
            if isinstance(overrides, dict):
                masks = normalizar_mascaras_display(
                    [
                        deepcopy(mask)
                        for mask in overrides.values()
                        if isinstance(mask, dict)
                    ]
                )

        return metadata, image, masks

    def collect(self, project_name: str | None = None) -> dict:
        name = normalizar_nome_projeto_display(
            project_name or self.repository.obter_projeto_ativo()
        )
        project = self.repository.carregar_projeto(name)
        if project is None:
            return self._empty_result(
                name,
                "projeto_display_inexistente",
            )

        resolution = normalizar_resolucao_display(
            project.get("master_resolution")
        )
        if resolution is None:
            return self._empty_result(
                name,
                "resolucao_mestra_ausente",
            )

        samples: list[dict] = []
        checks_used: list[str] = []
        missing_references: list[str] = []
        invalid_samples: list[str] = []
        class_counts = {
            DISPLAY_CHECK_STATE_OFF: 0,
            DISPLAY_CHECK_STATE_ON: 0,
        }

        for check in project.get("checks", []) or ():
            if not isinstance(check, dict):
                continue
            check_id = str(check.get("id") or "").strip()
            if not check_id:
                continue
            check_name = str(
                check.get("name") or check_id
            ).strip().upper()
            metadata = self.presence_store.get(name, check_id)
            image = self._reference_image(metadata, resolution)
            if image is None:
                missing_references.append(check_id)
                continue

            local_masks = mascaras_geometria_check_display(
                project,
                check,
            )
            states = (
                check.get("mask_states", {})
                if isinstance(check.get("mask_states"), dict)
                else {}
            )
            used_in_check = False
            for mask in local_masks:
                if not isinstance(mask, dict):
                    continue
                mask_id = str(mask.get("id") or "").strip()
                state = str(
                    states.get(mask_id)
                    or DISPLAY_CHECK_STATE_IGNORE
                )
                if state not in F3_NEURAL_LABELS:
                    continue

                tensor = extrair_tensor_segmento_f3(
                    image,
                    mask,
                    input_size=self.input_size,
                    context_ratio=self.context_ratio,
                )
                if tensor is None:
                    invalid_samples.append(
                        f"{check_id}:{mask_id}"
                    )
                    continue

                class_counts[state] += 1
                used_in_check = True
                samples.append(
                    {
                        "project_name": name,
                        "check_id": check_id,
                        "check_name": check_name,
                        "source_kind": "check_reference",
                        "mask_id": mask_id,
                        "state": state,
                        "label": int(F3_NEURAL_LABELS[state]),
                        "tensor": tensor,
                        "reference_image_path": str(
                            (metadata or {}).get("image_path") or ""
                        ),
                        "mask_geometry": deepcopy(mask),
                        "board_points_reference": deepcopy(
                            check.get("board_points_reference") or []
                        ),
                    }
                )
            if used_in_check:
                checks_used.append(check_id)

        board_off_metadata, board_off_image, board_off_masks = (
            self._board_off_reference_context(
                name,
                resolution,
            )
        )
        board_off_configured = isinstance(board_off_metadata, dict)
        board_off_geometry_configured = bool(board_off_masks)
        board_off_sample_count = 0
        board_off_invalid_mask_ids: list[str] = []

        if board_off_image is not None and board_off_masks:
            board_points = deepcopy(
                (board_off_metadata or {}).get(
                    "board_points_reference",
                    [],
                )
            )
            for mask in board_off_masks:
                if not isinstance(mask, dict):
                    continue
                mask_id = str(mask.get("id") or "").strip()
                if not mask_id:
                    continue

                tensor = extrair_tensor_segmento_f3(
                    board_off_image,
                    mask,
                    input_size=self.input_size,
                    context_ratio=self.context_ratio,
                )
                if tensor is None:
                    board_off_invalid_mask_ids.append(mask_id)
                    invalid_samples.append(
                        f"{F3_NEURAL_BOARD_OFF_CHECK_ID}:{mask_id}"
                    )
                    continue

                class_counts[DISPLAY_CHECK_STATE_OFF] += 1
                board_off_sample_count += 1
                samples.append(
                    {
                        "project_name": name,
                        "check_id": F3_NEURAL_BOARD_OFF_CHECK_ID,
                        "check_name": F3_NEURAL_BOARD_OFF_CHECK_NAME,
                        "reference_kind": (
                            F3_NEURAL_BOARD_OFF_REFERENCE_KIND
                        ),
                        "source_kind": "board_off_reference",
                        "mask_id": mask_id,
                        "state": DISPLAY_CHECK_STATE_OFF,
                        "label": int(
                            F3_NEURAL_LABELS[
                                DISPLAY_CHECK_STATE_OFF
                            ]
                        ),
                        "tensor": tensor,
                        "reference_image_path": str(
                            (board_off_metadata or {}).get(
                                "image_path"
                            )
                            or ""
                        ),
                        "mask_geometry": deepcopy(mask),
                        "board_points_reference": board_points,
                    }
                )

        ready = bool(
            samples
            and class_counts[DISPLAY_CHECK_STATE_ON] > 0
            and class_counts[DISPLAY_CHECK_STATE_OFF] > 0
        )
        reason = (
            "dataset_pronto"
            if ready
            else (
                "dataset_sem_duas_classes"
                if samples
                else "dataset_sem_amostras"
            )
        )
        return {
            "schema_version": F3_NEURAL_DATASET_SCHEMA_VERSION,
            "ready": ready,
            "reason": reason,
            "project_name": name,
            "master_resolution": {
                "width": int(resolution[0]),
                "height": int(resolution[1]),
            },
            "input_size": int(self.input_size),
            "channels": ("r", "g", "b", "segment_mask"),
            "source": "configured_f3_check_references",
            "checks_used": tuple(checks_used),
            "auxiliary_sources_used": (
                (F3_NEURAL_BOARD_OFF_CHECK_ID,)
                if board_off_sample_count > 0
                else ()
            ),
            "board_off_reference_configured": bool(
                board_off_configured
            ),
            "board_off_geometry_configured": bool(
                board_off_geometry_configured
            ),
            "board_off_sample_count": int(
                board_off_sample_count
            ),
            "board_off_invalid_mask_ids": tuple(
                board_off_invalid_mask_ids
            ),
            "missing_reference_check_ids": tuple(missing_references),
            "invalid_sample_ids": tuple(invalid_samples),
            "class_counts": class_counts,
            "sample_count": len(samples),
            "samples": samples,
        }

    def manifest(self, project_name: str | None = None) -> dict:
        """Versão serializável do dataset para auditoria/treino."""
        result = self.collect(project_name)
        manifest_samples = []
        for sample in result.get("samples", []) or ():
            item = {
                key: deepcopy(value)
                for key, value in sample.items()
                if key != "tensor"
            }
            tensor = sample.get("tensor")
            if isinstance(tensor, np.ndarray):
                item["tensor_shape"] = list(tensor.shape)
            manifest_samples.append(item)

        output = {
            key: deepcopy(value)
            for key, value in result.items()
            if key != "samples"
        }
        output["samples"] = manifest_samples
        return output

    def _empty_result(
        self,
        project_name: str,
        reason: str,
    ) -> dict:
        return {
            "schema_version": F3_NEURAL_DATASET_SCHEMA_VERSION,
            "ready": False,
            "reason": str(reason),
            "project_name": str(project_name or ""),
            "master_resolution": None,
            "input_size": int(self.input_size),
            "channels": ("r", "g", "b", "segment_mask"),
            "source": "configured_f3_check_references",
            "checks_used": (),
            "auxiliary_sources_used": (),
            "board_off_reference_configured": False,
            "board_off_geometry_configured": False,
            "board_off_sample_count": 0,
            "board_off_invalid_mask_ids": (),
            "missing_reference_check_ids": (),
            "invalid_sample_ids": (),
            "class_counts": {
                DISPLAY_CHECK_STATE_OFF: 0,
                DISPLAY_CHECK_STATE_ON: 0,
            },
            "sample_count": 0,
            "samples": [],
        }
