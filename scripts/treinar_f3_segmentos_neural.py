from __future__ import annotations

"""Treina a CNN ON/OFF dos segmentos do Display F3 com dados reais locais.

N1.3 mantém o primeiro CHECK fora do treino e o usa como validação
independente. Assim segmentos recortados da mesma foto não podem aparecer
simultaneamente em treino e validação.

Uso recomendado:
    python scripts/treinar_f3_segmentos_neural.py --preflight
    python scripts/treinar_f3_segmentos_neural.py

Dependências de treinamento (não entram no runtime produtivo):
    python -m pip install -r requirements-neural-training.txt

O artefato de produção é ONNX e é consumido pelo OpenCV DNN já presente no
ODIN. Nenhuma API, nuvem ou serviço pago participa do fluxo.
"""

import argparse
import hashlib
import json
import random
import shutil
import sys
import tempfile
from pathlib import Path

# Quando o arquivo é executado diretamente (`python scripts/...py`), o Python
# coloca apenas a pasta `scripts` no sys.path. Adicionamos explicitamente a
# raiz do repositório para que os imports `src.*` funcionem da mesma forma no
# Windows, Linux e nos testes/CI.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np

from src.platform.display_f3_neural_dataset import (
    F3NeuralDatasetBuilder,
    F3_NEURAL_INPUT_SIZE,
    F3_NEURAL_MODEL_METADATA_SCHEMA_VERSION,
    F3_NEURAL_THRESHOLD_CALIBRATION_SOURCE,
    f3_neural_model_path_for_repository,
)
from src.platform.display_project_repository import (
    DisplayProjectRepository,
)


F3_NEURAL_REQUIRED_VALIDATION_ACCURACY = 1.0
F3_NEURAL_REQUIRED_CLASS_ACCURACY = 1.0
F3_NEURAL_CALIBRATION_AUGMENTATIONS_PER_REFERENCE = 16
F3_NEURAL_CALIBRATION_DIAGNOSTIC_TOP_K = 5


def _load_torch():
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, Dataset
    except Exception as exc:
        raise RuntimeError(
            "PyTorch não está disponível. Instale somente no ambiente de "
            "treino com: python -m pip install -r "
            "requirements-neural-training.txt"
        ) from exc
    return torch, nn, DataLoader, Dataset


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _class_counts(samples, indices) -> dict[str, int]:
    counts = {"off": 0, "on": 0}
    for index in indices:
        label = int(samples[index]["label"])
        counts["on" if label == 1 else "off"] += 1
    return counts


def _check_ids(samples, indices) -> list[str]:
    values: list[str] = []
    seen = set()
    for index in indices:
        check_id = str(samples[index].get("check_id") or "").strip()
        if check_id and check_id not in seen:
            seen.add(check_id)
            values.append(check_id)
    return values


def _mask_id_sort_key(mask_id: str):
    text = str(mask_id or "").strip()
    suffix = text.rsplit("_", 1)[-1]
    try:
        number = int(suffix)
    except (TypeError, ValueError):
        number = 10**9
    return number, text


def _ordered_check_catalog(
    repository: DisplayProjectRepository,
    project_name: str,
    samples: list[dict],
) -> list[dict]:
    catalog: list[dict] = []
    seen: set[str] = set()
    try:
        checks = repository.listar_checks(project_name)
    except Exception:
        checks = []

    for check in checks:
        if not isinstance(check, dict):
            continue
        check_id = str(check.get("id") or "").strip()
        if not check_id or check_id in seen:
            continue
        seen.add(check_id)
        catalog.append(
            {
                "check_id": check_id,
                "check_name": str(
                    check.get("name") or check_id
                ).strip(),
            }
        )

    for item in samples:
        check_id = str(item.get("check_id") or "").strip()
        if not check_id or check_id in seen:
            continue
        seen.add(check_id)
        catalog.append(
            {
                "check_id": check_id,
                "check_name": str(
                    item.get("check_name") or check_id
                ).strip(),
            }
        )
    return catalog


def _build_mask_state_coverage(
    repository: DisplayProjectRepository,
    project_name: str,
    samples: list[dict],
    train_indices: list[int],
    val_indices: list[int],
) -> dict:
    """Audita cobertura ON/OFF por máscara física e por CHECK.

    Esta função é estritamente diagnóstica: não altera split, labels, pesos,
    treino, calibração ou decisão de promoção.
    """
    checks = _ordered_check_catalog(
        repository,
        project_name,
        samples,
    )
    states_by_check: dict[tuple[str, str], set[str]] = {}
    all_mask_ids: set[str] = set()

    for item in samples:
        mask_id = str(item.get("mask_id") or "").strip()
        check_id = str(item.get("check_id") or "").strip()
        state = str(item.get("state") or "").strip().lower()
        if not mask_id or not check_id or state not in ("on", "off"):
            continue
        all_mask_ids.add(mask_id)
        states_by_check.setdefault(
            (check_id, mask_id),
            set(),
        ).add(state)

    def states_for(indices: list[int], mask_id: str) -> set[str]:
        values: set[str] = set()
        for index in indices:
            item = samples[index]
            if str(item.get("mask_id") or "").strip() != mask_id:
                continue
            state = str(item.get("state") or "").strip().lower()
            if state in ("on", "off"):
                values.add(state)
        return values

    rows: list[dict] = []
    validation_unseen: list[str] = []
    single_state_training: list[str] = []
    both_states_training: list[str] = []
    no_training_state: list[str] = []

    for mask_id in sorted(all_mask_ids, key=_mask_id_sort_key):
        check_states = {}
        for check in checks:
            check_id = str(check["check_id"])
            values = sorted(
                states_by_check.get((check_id, mask_id), set())
            )
            check_states[check_id] = (
                values[0]
                if len(values) == 1
                else ("mixed" if values else "missing")
            )

        train_states = states_for(train_indices, mask_id)
        validation_states = states_for(val_indices, mask_id)
        validation_seen = bool(
            validation_states
            and validation_states.issubset(train_states)
        )

        if not train_states:
            status = "no_training_state"
            no_training_state.append(mask_id)
        elif validation_states and not validation_seen:
            status = "validation_state_unseen_in_training"
            validation_unseen.append(mask_id)
        elif train_states == {"off", "on"}:
            status = "both_states_seen_in_training"
            both_states_training.append(mask_id)
        else:
            status = "single_state_seen_in_training"
            single_state_training.append(mask_id)

        rows.append(
            {
                "mask_id": mask_id,
                "checks": check_states,
                "training_states": sorted(train_states),
                "training_off_count": sum(
                    1
                    for index in train_indices
                    if str(samples[index].get("mask_id") or "").strip()
                    == mask_id
                    and str(samples[index].get("state") or "")
                    .strip()
                    .lower()
                    == "off"
                ),
                "training_on_count": sum(
                    1
                    for index in train_indices
                    if str(samples[index].get("mask_id") or "").strip()
                    == mask_id
                    and str(samples[index].get("state") or "")
                    .strip()
                    .lower()
                    == "on"
                ),
                "validation_states": sorted(validation_states),
                "validation_state_seen_in_training": validation_seen,
                "status": status,
            }
        )

    summary = {
        "mask_count": len(rows),
        "both_states_seen_in_training_count": len(
            both_states_training
        ),
        "single_state_seen_in_training_count": len(
            single_state_training
        ),
        "validation_state_unseen_in_training_count": len(
            validation_unseen
        ),
        "no_training_state_count": len(no_training_state),
        "both_states_seen_in_training_mask_ids": both_states_training,
        "single_state_seen_in_training_mask_ids": single_state_training,
        "validation_state_unseen_in_training_mask_ids": validation_unseen,
        "no_training_state_mask_ids": no_training_state,
    }

    return {
        "schema_version": 1,
        "purpose": "f3_neural_mask_state_coverage_audit",
        "project_name": str(project_name or ""),
        "checks": checks,
        "summary": summary,
        "masks": rows,
    }


def _write_mask_state_coverage(
    report: dict,
    destination: Path,
) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return destination


def _format_mask_state_coverage(report: dict) -> str:
    checks = [
        item
        for item in (report.get("checks") or ())
        if isinstance(item, dict)
    ]
    rows = [
        item
        for item in (report.get("masks") or ())
        if isinstance(item, dict)
    ]
    if not rows:
        return "MATRIZ ON/OFF POR MÁSCARA: sem amostras."

    def short_state(value: object) -> str:
        state = str(value or "").strip().lower()
        return {
            "on": "ON",
            "off": "OFF",
            "mixed": "MIX",
            "missing": "--",
        }.get(state, "--")

    header = ["MÁSCARA"]
    header.extend(
        str(item.get("check_name") or item.get("check_id") or "")[:8]
        for item in checks
    )
    header.extend(["TREINO", "VAL VISTA?", "STATUS"])

    widths = [10]
    widths.extend([8] * len(checks))
    widths.extend([9, 10, 34])

    def render(values):
        return " | ".join(
            str(value).ljust(width)
            for value, width in zip(values, widths)
        )

    lines = [
        "MATRIZ ON/OFF POR MÁSCARA FÍSICA",
        render(header),
        "-+-".join("-" * width for width in widths),
    ]

    for row in rows:
        check_states = (
            row.get("checks")
            if isinstance(row.get("checks"), dict)
            else {}
        )
        train_states = [
            str(value).upper()
            for value in (row.get("training_states") or ())
        ]
        values = [str(row.get("mask_id") or "")]
        values.extend(
            short_state(check_states.get(str(check.get("check_id") or "")))
            for check in checks
        )
        values.extend(
            [
                "/".join(train_states) if train_states else "--",
                (
                    "SIM"
                    if row.get("validation_state_seen_in_training")
                    else "NÃO"
                ),
                str(row.get("status") or ""),
            ]
        )
        lines.append(render(values))

    summary = (
        report.get("summary")
        if isinstance(report.get("summary"), dict)
        else {}
    )
    lines.extend(
        [
            "",
            "RESUMO DE COBERTURA:",
            (
                "  ambas as classes no treino: "
                f"{summary.get('both_states_seen_in_training_count', 0)}"
            ),
            (
                "  somente uma classe no treino: "
                f"{summary.get('single_state_seen_in_training_count', 0)}"
            ),
            (
                "  estado exigido pela validação nunca visto no treino: "
                f"{summary.get('validation_state_unseen_in_training_count', 0)}"
            ),
            (
                "  sem estado de treino: "
                f"{summary.get('no_training_state_count', 0)}"
            ),
        ]
    )
    unseen = list(
        summary.get(
            "validation_state_unseen_in_training_mask_ids",
            [],
        )
        or []
    )
    if unseen:
        lines.append(
            "  máscaras com estado de validação inédito: "
            + ", ".join(unseen)
        )
    return "\n".join(lines)


def _resolve_validation_check(
    repository: DisplayProjectRepository,
    project_name: str,
    samples: list[dict],
    requested: str | None,
) -> tuple[str, str] | None:
    available = {
        str(item.get("check_id") or "").strip()
        for item in samples
        if str(item.get("check_id") or "").strip()
    }
    if not available:
        return None

    try:
        checks = repository.listar_checks(project_name)
    except Exception:
        checks = []

    if requested:
        target = str(requested).strip().lower()
        for check in checks:
            if not isinstance(check, dict):
                continue
            check_id = str(check.get("id") or "").strip()
            check_name = str(check.get("name") or check_id).strip()
            if check_id not in available:
                continue
            if target in {
                check_id.lower(),
                check_name.lower(),
            }:
                return check_id, check_name
        return None

    # N1 é deliberadamente o primeiro CHECK da ordem configurada. Se ele não
    # possui foto/amostras, o preflight deve falhar; nunca deslocamos
    # silenciosamente a validação para BLUE/USB/AUX.
    first = next(
        (
            check
            for check in checks
            if isinstance(check, dict)
            and str(check.get("id") or "").strip()
        ),
        None,
    )
    if isinstance(first, dict):
        first_id = str(first.get("id") or "").strip()
        first_name = str(first.get("name") or first_id).strip()
        if first_id in available:
            return first_id, first_name
        return None

    return None


def preparar_preflight(
    repository: DisplayProjectRepository,
    builder: F3NeuralDatasetBuilder,
    project_name: str | None,
    *,
    validation_check: str | None = None,
) -> tuple[dict, dict, list[int], list[int]]:
    dataset = builder.collect(project_name)
    name = str(dataset.get("project_name") or project_name or "")
    samples = list(dataset.get("samples") or ())

    report = {
        "ready": False,
        "reason": str(dataset.get("reason") or "dataset_indisponivel"),
        "project_name": name,
        "sample_count": int(dataset.get("sample_count", 0) or 0),
        "class_counts": dict(dataset.get("class_counts") or {}),
        "checks_used": list(dataset.get("checks_used") or ()),
        "missing_reference_check_ids": list(
            dataset.get("missing_reference_check_ids") or ()
        ),
        "invalid_sample_ids": list(dataset.get("invalid_sample_ids") or ()),
        "split_strategy": "hold_out_first_check_for_n1",
    }
    if not bool(dataset.get("ready")):
        return dataset, report, [], []

    validation = _resolve_validation_check(
        repository,
        name,
        samples,
        validation_check,
    )
    if validation is None:
        report["reason"] = (
            "validation_check_not_found"
            if validation_check
            else "first_check_reference_missing"
        )
        return dataset, report, [], []

    validation_check_id, validation_check_name = validation
    val_indices = [
        index
        for index, item in enumerate(samples)
        if str(item.get("check_id") or "").strip() == validation_check_id
    ]
    val_set = set(val_indices)
    train_indices = [
        index
        for index in range(len(samples))
        if index not in val_set
    ]

    report.update(
        {
            "validation_check_id": validation_check_id,
            "validation_check_name": validation_check_name,
            "train_check_ids": _check_ids(samples, train_indices),
            "validation_check_ids": _check_ids(samples, val_indices),
            "train_count": len(train_indices),
            "validation_count": len(val_indices),
            "train_class_counts": _class_counts(samples, train_indices),
            "validation_class_counts": _class_counts(samples, val_indices),
        }
    )

    coverage = _build_mask_state_coverage(
        repository,
        name,
        samples,
        train_indices,
        val_indices,
    )
    report["state_coverage"] = coverage
    report["state_coverage_summary"] = dict(
        coverage.get("summary") or {}
    )

    if not train_indices:
        report["reason"] = "dataset_sem_treino_independente_do_h1"
        return dataset, report, [], val_indices
    if not val_indices:
        report["reason"] = "h1_sem_amostras_de_validacao"
        return dataset, report, train_indices, []

    train_classes = {
        int(samples[index]["label"])
        for index in train_indices
    }
    val_classes = {
        int(samples[index]["label"])
        for index in val_indices
    }
    if train_classes != {0, 1}:
        report["reason"] = "treino_sem_duas_classes_fora_do_h1"
        return dataset, report, train_indices, val_indices
    if val_classes != {0, 1}:
        report["reason"] = "h1_validacao_sem_duas_classes"
        return dataset, report, train_indices, val_indices

    report["ready"] = True
    report["reason"] = "preflight_neural_n1_pronto"
    return dataset, report, train_indices, val_indices


def _augment_sample(
    tensor: np.ndarray,
    label: int,
    rng: random.Random,
    *,
    diagnostic: dict | None = None,
) -> np.ndarray:
    """Augmentation leve focada nos defeitos físicos relatados no F3.

    `diagnostic` apenas registra os mesmos valores aleatórios já usados pela
    transformação. Nenhuma chamada extra ao RNG é feita, para que instrumentar
    a calibração não altere a amostra gerada.
    """
    hwc = np.ascontiguousarray(
        tensor.transpose(1, 2, 0),
        dtype=np.float32,
    )
    height, width = hwc.shape[:2]

    angle = rng.uniform(-3.0, 3.0)
    scale = rng.uniform(0.96, 1.04)
    dx = rng.uniform(-2.5, 2.5)
    dy = rng.uniform(-2.5, 2.5)
    matrix = cv2.getRotationMatrix2D(
        (width / 2.0, height / 2.0),
        angle,
        scale,
    )
    matrix[0, 2] += dx
    matrix[1, 2] += dy
    hwc = cv2.warpAffine(
        hwc,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    if hwc.ndim == 2:
        hwc = hwc[..., None]

    rgb = np.clip(hwc[..., :3], 0.0, 1.0)
    mask = np.clip(hwc[..., 3:4], 0.0, 1.0)

    alpha = rng.uniform(0.78, 1.22)
    beta = rng.uniform(-0.10, 0.10)
    rgb = np.clip(rgb * alpha + beta, 0.0, 1.0)

    gamma = rng.uniform(0.78, 1.28)
    rgb = np.power(
        np.clip(rgb, 1e-5, 1.0),
        gamma,
    )

    blur_draw = rng.random()
    blur_applied = blur_draw < 0.25
    if blur_applied:
        rgb = cv2.GaussianBlur(
            rgb,
            (3, 3),
            0,
        )

    noise_draw = rng.random()
    noise_applied = noise_draw < 0.45
    noise_seed = None
    noise_sigma = None
    if noise_applied:
        noise_seed = rng.randrange(1, 2**31)
        noise_sigma = rng.uniform(0.006, 0.025)
        noise = np.random.default_rng(
            noise_seed
        ).normal(
            0.0,
            noise_sigma,
            rgb.shape,
        ).astype(np.float32)
        rgb = np.clip(rgb + noise, 0.0, 1.0)

    reflection_draw = None
    reflection_applied = False
    reflection_center = None
    reflection_axes = None
    reflection_intensity = None
    reflection_angle = None

    # Hard negative: um OFF pode receber um ponto/reflexo claro sem virar ON.
    # O reflexo não cobre deliberadamente toda a máscara, para não ensinar um
    # defeito artificial indistinguível de um segmento realmente energizado.
    if int(label) == 0:
        reflection_draw = rng.random()
        reflection_applied = reflection_draw < 0.35
        if reflection_applied:
            reflection_center = (
                rng.randrange(
                    max(1, width // 5),
                    max(2, width - width // 5),
                ),
                rng.randrange(
                    max(1, height // 5),
                    max(2, height - height // 5),
                ),
            )
            reflection_axes = (
                rng.randrange(
                    2,
                    max(3, width // 7),
                ),
                rng.randrange(
                    2,
                    max(3, height // 7),
                ),
            )
            reflection_intensity = rng.uniform(0.45, 0.95)
            reflection_angle = rng.uniform(0.0, 180.0)
            overlay = np.zeros_like(rgb, dtype=np.float32)
            cv2.ellipse(
                overlay,
                reflection_center,
                reflection_axes,
                reflection_angle,
                0.0,
                360.0,
                (
                    reflection_intensity,
                    reflection_intensity,
                    reflection_intensity,
                ),
                thickness=-1,
            )
            rgb = np.clip(
                rgb + overlay,
                0.0,
                1.0,
            )

    if diagnostic is not None:
        diagnostic.clear()
        diagnostic.update(
            {
                "angle_deg": float(angle),
                "scale": float(scale),
                "dx_px": float(dx),
                "dy_px": float(dy),
                "brightness_alpha": float(alpha),
                "brightness_beta": float(beta),
                "gamma": float(gamma),
                "blur_draw": float(blur_draw),
                "blur_applied": bool(blur_applied),
                "noise_draw": float(noise_draw),
                "noise_applied": bool(noise_applied),
                "noise_seed": (
                    int(noise_seed)
                    if noise_seed is not None
                    else None
                ),
                "noise_sigma": (
                    float(noise_sigma)
                    if noise_sigma is not None
                    else None
                ),
                "reflection_draw": (
                    float(reflection_draw)
                    if reflection_draw is not None
                    else None
                ),
                "reflection_applied": bool(reflection_applied),
                "reflection_center": (
                    list(reflection_center)
                    if reflection_center is not None
                    else None
                ),
                "reflection_axes": (
                    list(reflection_axes)
                    if reflection_axes is not None
                    else None
                ),
                "reflection_intensity": (
                    float(reflection_intensity)
                    if reflection_intensity is not None
                    else None
                ),
                "reflection_angle_deg": (
                    float(reflection_angle)
                    if reflection_angle is not None
                    else None
                ),
            }
        )

    out = np.concatenate(
        (
            rgb,
            (mask >= 0.5).astype(np.float32),
        ),
        axis=2,
    )
    return np.ascontiguousarray(
        out.transpose(2, 0, 1),
        dtype=np.float32,
    )

def _softmax_logits(logits: np.ndarray) -> np.ndarray:
    values = np.asarray(logits, dtype=np.float32)
    if values.ndim != 2 or values.shape[1] != 2:
        raise RuntimeError(
            "Logits de calibração inválidos: "
            f"shape={tuple(values.shape)}"
        )
    values = values - np.max(values, axis=1, keepdims=True)
    exp = np.exp(values)
    denominator = np.maximum(
        np.sum(exp, axis=1, keepdims=True),
        np.float32(1e-9),
    )
    return exp / denominator


def _calibration_sample_detail(
    item: dict,
    *,
    sample_index: int,
    kind: str,
    augmentation_index: int | None,
    augmentation_seed: int | None,
    transform: dict | None,
) -> dict:
    return {
        "sample_index": int(sample_index),
        "project_name": str(item.get("project_name") or ""),
        "check_id": str(item.get("check_id") or ""),
        "check_name": str(item.get("check_name") or ""),
        "mask_id": str(item.get("mask_id") or ""),
        "state": str(item.get("state") or ""),
        "label": int(item.get("label", 0) or 0),
        "reference_image_path": str(
            item.get("reference_image_path") or ""
        ),
        "kind": str(kind),
        "augmentation_index": (
            int(augmentation_index)
            if augmentation_index is not None
            else None
        ),
        "augmentation_seed": (
            int(augmentation_seed)
            if augmentation_seed is not None
            else None
        ),
        "transform": dict(transform or {}),
    }


def _build_calibration_batch_with_details(
    samples: list[dict],
    indices: list[int],
    *,
    augmentations_per_reference: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """Monta o mesmo batch de calibração e registra a origem de cada tensor."""
    augmentation_count = int(augmentations_per_reference)
    if augmentation_count < 1:
        raise RuntimeError(
            "Calibração neural N1 exige ao menos uma variação por referência."
        )

    tensors: list[np.ndarray] = []
    labels: list[int] = []
    details: list[dict] = []

    for order, sample_index in enumerate(indices):
        item = samples[sample_index]
        tensor = np.asarray(item["tensor"], dtype=np.float32)
        label = int(item["label"])
        tensors.append(np.ascontiguousarray(tensor, dtype=np.float32))
        labels.append(label)
        details.append(
            _calibration_sample_detail(
                item,
                sample_index=sample_index,
                kind="original",
                augmentation_index=None,
                augmentation_seed=None,
                transform=None,
            )
        )

        for augmentation_index in range(augmentation_count):
            augmentation_seed = (
                int(seed)
                + 7000001
                + int(sample_index) * 9176
                + int(order) * 104729
                + int(augmentation_index) * 1009
            )
            rng = random.Random(augmentation_seed)
            transform: dict = {}
            tensors.append(
                _augment_sample(
                    tensor,
                    label,
                    rng,
                    diagnostic=transform,
                )
            )
            labels.append(label)
            details.append(
                _calibration_sample_detail(
                    item,
                    sample_index=sample_index,
                    kind="augmented",
                    augmentation_index=augmentation_index,
                    augmentation_seed=augmentation_seed,
                    transform=transform,
                )
            )

    if not tensors:
        raise RuntimeError("Calibração neural N1 ficou sem amostras H1.")

    return (
        np.ascontiguousarray(np.stack(tensors, axis=0), dtype=np.float32),
        np.asarray(labels, dtype=np.int64),
        details,
    )


def _build_calibration_batch(
    samples: list[dict],
    indices: list[int],
    *,
    augmentations_per_reference: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    batch, labels, _details = _build_calibration_batch_with_details(
        samples,
        indices,
        augmentations_per_reference=augmentations_per_reference,
        seed=seed,
    )
    return batch, labels


def _safe_diagnostic_token(value: object) -> str:
    text = str(value or "").strip()
    cleaned = "".join(
        char if char.isalnum() or char in ("-", "_") else "_"
        for char in text
    )
    return cleaned.strip("_") or "item"


def _calibration_preview_image(tensor: np.ndarray) -> np.ndarray:
    array = np.asarray(tensor, dtype=np.float32)
    if array.shape[0] < 4:
        raise RuntimeError(
            "Tensor de diagnóstico neural precisa ter RGB + máscara."
        )

    rgb = np.clip(
        array[:3].transpose(1, 2, 0),
        0.0,
        1.0,
    )
    bgr = cv2.cvtColor(
        np.rint(rgb * 255.0).astype(np.uint8),
        cv2.COLOR_RGB2BGR,
    )
    preview = cv2.resize(
        bgr,
        (192, 192),
        interpolation=cv2.INTER_NEAREST,
    )

    mask = (array[3] >= 0.5).astype(np.uint8) * 255
    mask_big = cv2.resize(
        mask,
        (192, 192),
        interpolation=cv2.INTER_NEAREST,
    )
    contours, _hierarchy = cv2.findContours(
        mask_big,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    if contours:
        cv2.drawContours(
            preview,
            contours,
            -1,
            (255, 255, 255),
            1,
        )
    return preview


def _write_calibration_diagnostics(
    *,
    batch: np.ndarray,
    labels: np.ndarray,
    details: list[dict],
    logits: np.ndarray,
    destination: Path,
    top_k: int = F3_NEURAL_CALIBRATION_DIAGNOSTIC_TOP_K,
) -> dict:
    """Persiste apenas as amostras extremas que explicam a calibração.

    Esta função é estritamente diagnóstica. Não altera logits, labels, thresholds
    nem a decisão de promoção do modelo.
    """
    probabilities = _softmax_logits(logits)
    labels_array = np.asarray(labels, dtype=np.int64).reshape(-1)
    tensors = np.asarray(batch, dtype=np.float32)

    total = int(probabilities.shape[0])
    if (
        tensors.shape[0] != total
        or labels_array.shape[0] != total
        or len(details) != total
    ):
        raise RuntimeError(
            "Diagnóstico de calibração inconsistente: batch, labels, "
            "detalhes e logits possuem tamanhos diferentes."
        )

    p_on = probabilities[:, 1]
    off_indices = [
        int(index)
        for index in np.where(labels_array == 0)[0].tolist()
    ]
    on_indices = [
        int(index)
        for index in np.where(labels_array == 1)[0].tolist()
    ]
    if not off_indices or not on_indices:
        raise RuntimeError(
            "Diagnóstico de calibração exige exemplos OFF e ON."
        )

    off_ranked = sorted(
        off_indices,
        key=lambda index: float(p_on[index]),
        reverse=True,
    )
    on_ranked = sorted(
        on_indices,
        key=lambda index: float(p_on[index]),
    )

    destination = Path(destination)
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)

    def item_record(index: int, rank: int, group: str) -> dict:
        detail = dict(details[index])
        probability = float(p_on[index])
        mask_id = _safe_diagnostic_token(detail.get("mask_id"))
        kind = _safe_diagnostic_token(detail.get("kind"))
        augmentation_index = detail.get("augmentation_index")
        variant = (
            "original"
            if augmentation_index is None
            else f"aug{int(augmentation_index):02d}"
        )
        filename = (
            f"{group}_rank{rank:02d}_{mask_id}_{kind}_{variant}_"
            f"pon_{probability:.6f}.png"
        )
        image_path = destination / filename
        if not cv2.imwrite(
            str(image_path),
            _calibration_preview_image(tensors[index]),
        ):
            raise RuntimeError(
                f"Falha ao salvar diagnóstico neural: {image_path}"
            )
        return {
            "rank": int(rank),
            "batch_index": int(index),
            "p_on": probability,
            "image_file": filename,
            **detail,
        }

    limit = max(1, int(top_k))
    top_off = [
        item_record(index, rank, "off")
        for rank, index in enumerate(off_ranked[:limit], start=1)
    ]
    top_on = [
        item_record(index, rank, "on")
        for rank, index in enumerate(on_ranked[:limit], start=1)
    ]

    max_off = float(p_on[off_ranked[0]])
    min_on = float(p_on[on_ranked[0]])
    report = {
        "schema_version": 1,
        "purpose": "f3_neural_h1_calibration_diagnostics",
        "sample_count": total,
        "class_counts": {
            "off": len(off_indices),
            "on": len(on_indices),
        },
        "max_off_on_probability": max_off,
        "min_on_on_probability": min_on,
        "raw_gap": float(min_on - max_off),
        "separable": bool(max_off < min_on),
        "top_k": limit,
        "worst_off": top_off[0],
        "worst_on": top_on[0],
        "top_off": top_off,
        "top_on": top_on,
    }

    report_path = destination / "calibration_diagnostics.json"
    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report["report_path"] = str(report_path)
    report["directory"] = str(destination)
    return report

def _calibrate_thresholds_from_logits(
    logits: np.ndarray,
    labels: np.ndarray,
    *,
    reference_sample_count: int,
    augmentations_per_reference: int,
) -> dict:
    """Deriva a banda INCERTO do gap empírico OFF/ON do H1 reservado."""
    probabilities = _softmax_logits(logits)
    labels_array = np.asarray(labels, dtype=np.int64).reshape(-1)
    if probabilities.shape[0] != labels_array.shape[0]:
        raise RuntimeError(
            "Calibração neural inconsistente: quantidade de logits e rótulos "
            "não coincide."
        )

    p_on = probabilities[:, 1]
    off_values = p_on[labels_array == 0]
    on_values = p_on[labels_array == 1]
    if off_values.size <= 0 or on_values.size <= 0:
        raise RuntimeError(
            "Calibração neural N1 exige exemplos OFF e ON no H1 reservado."
        )

    max_off = float(np.max(off_values))
    min_on = float(np.min(on_values))
    gap = float(min_on - max_off)
    if not np.isfinite(gap) or gap <= 0.0:
        raise RuntimeError(
            "Modelo neural não separou OFF/ON nas variações do H1 reservado: "
            f"max_OFF_P(ON)={max_off:.6f}, min_ON_P(ON)={min_on:.6f}."
        )

    off_threshold = float(np.nextafter(np.float64(max_off), np.float64(1.0)))
    on_threshold = float(np.nextafter(np.float64(min_on), np.float64(0.0)))
    if off_threshold >= on_threshold:
        raise RuntimeError(
            "Gap neural de calibração insuficiente após proteção numérica."
        )

    return {
        "source": F3_NEURAL_THRESHOLD_CALIBRATION_SOURCE,
        "separable": True,
        "reference_sample_count": int(reference_sample_count),
        "augmentations_per_reference": int(augmentations_per_reference),
        "sample_count": int(labels_array.size),
        "class_counts": {
            "off": int(off_values.size),
            "on": int(on_values.size),
        },
        "max_off_on_probability": max_off,
        "min_on_on_probability": min_on,
        "uncertainty_gap": gap,
        "off_max_on_probability": off_threshold,
        "on_min_on_probability": on_threshold,
    }


def _build_model(nn):
    class TinyF3SegmentCNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv2d(4, 16, 3, padding=1),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2),
                nn.Conv2d(16, 32, 3, padding=1),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2),
                nn.Conv2d(32, 64, 3, padding=1),
                nn.ReLU(inplace=True),
                nn.AdaptiveAvgPool2d((1, 1)),
            )
            self.classifier = nn.Linear(64, 2)

        def forward(self, x):
            x = self.features(x)
            x = x.flatten(1)
            return self.classifier(x)

    return TinyF3SegmentCNN()


def _metrics_from_predictions(
    samples: list[dict],
    indices: list[int],
    predictions: list[int],
) -> dict:
    total = len(indices)
    correct = 0
    by_class = {
        0: {"total": 0, "correct": 0},
        1: {"total": 0, "correct": 0},
    }
    check_rows: dict[str, list[bool]] = {}

    for sample_index, predicted in zip(indices, predictions):
        expected = int(samples[sample_index]["label"])
        matched = int(predicted) == expected
        correct += int(matched)
        by_class[expected]["total"] += 1
        by_class[expected]["correct"] += int(matched)
        check_id = str(samples[sample_index].get("check_id") or "")
        check_rows.setdefault(check_id, []).append(bool(matched))

    class_accuracy = {}
    for label, name in ((0, "off"), (1, "on")):
        row = by_class[label]
        class_accuracy[name] = (
            row["correct"] / float(max(1, row["total"]))
            if row["total"] > 0
            else 0.0
        )

    exact_checks = {
        check_id: bool(rows) and all(rows)
        for check_id, rows in check_rows.items()
    }
    return {
        "accuracy": correct / float(max(1, total)),
        "correct": int(correct),
        "total": int(total),
        "class_accuracy": class_accuracy,
        "exact_checks": exact_checks,
        "all_validation_checks_exact": bool(exact_checks)
        and all(exact_checks.values()),
    }


def _evaluate_model(torch, model, samples, indices) -> tuple[dict, np.ndarray]:
    if not indices:
        return (
            {
                "accuracy": 0.0,
                "correct": 0,
                "total": 0,
                "class_accuracy": {"off": 0.0, "on": 0.0},
                "exact_checks": {},
                "all_validation_checks_exact": False,
            },
            np.empty((0, 2), dtype=np.float32),
        )

    batch = np.stack(
        [
            np.asarray(samples[index]["tensor"], dtype=np.float32)
            for index in indices
        ],
        axis=0,
    )
    with torch.no_grad():
        logits = model(torch.from_numpy(batch)).cpu().numpy()
    predictions = np.asarray(logits).argmax(axis=1).astype(np.int64).tolist()
    return (
        _metrics_from_predictions(samples, indices, predictions),
        np.asarray(logits, dtype=np.float32),
    )


def _export_onnx_candidate(
    torch,
    model,
    dummy,
    destination: Path,
) -> None:
    """Exporta ONNX simples compatível com OpenCV sem depender de onnxscript.

    PyTorch 2.14 usa o exporter Dynamo por padrão, que exige o pacote adicional
    `onnxscript`. O ODIN não precisa dele para esta CNN simples. Mantemos o
    exporter TorchScript/legacy explicitamente para reduzir dependências do
    ambiente de treino e preservar `dynamic_axes` + opset 13.
    """
    torch.onnx.export(
        model,
        dummy,
        str(destination),
        input_names=["segments"],
        output_names=["logits"],
        dynamic_axes={
            "segments": {0: "batch"},
            "logits": {0: "batch"},
        },
        opset_version=13,
        dynamo=False,
    )


def _validate_logit_equivalence(
    *,
    cv_logits: np.ndarray,
    torch_logits: np.ndarray,
    label: str,
) -> float:
    if cv_logits.shape != torch_logits.shape:
        raise RuntimeError(
            "ONNX incompatível com OpenCV DNN em "
            f"{label}: saída {tuple(cv_logits.shape)}; "
            f"esperado {tuple(torch_logits.shape)}"
        )
    if cv_logits.ndim != 2 or cv_logits.shape[1] != 2:
        raise RuntimeError(
            "ONNX incompatível com OpenCV DNN em "
            f"{label}: saída {tuple(cv_logits.shape)}"
        )
    max_abs_diff = float(
        np.max(np.abs(cv_logits - torch_logits))
        if cv_logits.size
        else 0.0
    )
    if max_abs_diff > 1e-4:
        raise RuntimeError(
            "ONNX divergiu do modelo PyTorch acima da tolerância em "
            f"{label}: max_abs_diff={max_abs_diff:.8f}"
        )
    return max_abs_diff


def _validate_candidate(
    *,
    cv_logits: np.ndarray,
    torch_logits: np.ndarray,
    metrics: dict,
) -> None:
    _validate_logit_equivalence(
        cv_logits=cv_logits,
        torch_logits=torch_logits,
        label="validação H1 original",
    )

    if float(metrics.get("accuracy", 0.0)) < F3_NEURAL_REQUIRED_VALIDATION_ACCURACY:
        raise RuntimeError(
            "Modelo neural não atingiu 100% na foto H1 mantida fora do treino: "
            f"{float(metrics.get('accuracy', 0.0)):.4f}"
        )
    class_accuracy = metrics.get("class_accuracy") or {}
    for label in ("off", "on"):
        if float(class_accuracy.get(label, 0.0)) < F3_NEURAL_REQUIRED_CLASS_ACCURACY:
            raise RuntimeError(
                "Modelo neural não atingiu 100% da classe "
                f"{label.upper()} na validação H1: "
                f"{float(class_accuracy.get(label, 0.0)):.4f}"
            )
    if not bool(metrics.get("all_validation_checks_exact")):
        raise RuntimeError(
            "Modelo neural não reproduziu integralmente todas as máscaras "
            "do CHECK H1 de validação."
        )


def _print_preflight(report: dict) -> None:
    compact = {
        key: value
        for key, value in report.items()
        if key != "state_coverage"
    }
    print(json.dumps(compact, indent=2, ensure_ascii=False))
    coverage = report.get("state_coverage")
    if isinstance(coverage, dict):
        print()
        print(_format_mask_state_coverage(coverage))


def treinar(args) -> dict:
    repository = DisplayProjectRepository(Path(args.config))
    builder = F3NeuralDatasetBuilder(
        repository,
        input_size=args.input_size,
    )
    dataset, preflight, train_indices, val_indices = preparar_preflight(
        repository,
        builder,
        args.project,
        validation_check=args.validation_check,
    )
    output = (
        Path(args.output)
        if args.output
        else f3_neural_model_path_for_repository(
            repository,
            str(dataset.get("project_name") or args.project or ""),
        )
    )
    preflight["output_path"] = str(output)
    coverage = preflight.get("state_coverage")
    if isinstance(coverage, dict):
        coverage_path = (
            output.parent
            / "diagnostics"
            / f"{output.stem}_state_coverage.json"
        )
        _write_mask_state_coverage(
            coverage,
            coverage_path,
        )
        preflight["state_coverage_path"] = str(coverage_path)

    if bool(args.preflight):
        _print_preflight(preflight)
        return preflight

    if not bool(preflight.get("ready")):
        raise RuntimeError(
            "Preflight neural N1 não está pronto:\n"
            + json.dumps(preflight, indent=2, ensure_ascii=False)
        )

    if isinstance(coverage, dict):
        print(_format_mask_state_coverage(coverage))
        print(
            "Auditoria de cobertura salva em: "
            f"{preflight.get('state_coverage_path')}"
        )
        print()

    torch, nn, DataLoader, Dataset = _load_torch()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    samples = list(dataset["samples"])

    class SegmentDataset(Dataset):
        def __init__(
            self,
            indices,
            *,
            augment: bool,
            seed: int,
        ):
            self.indices = list(indices)
            self.augment = bool(augment)
            self.seed = int(seed)
            self.epoch = 0

        def __len__(self):
            return len(self.indices)

        def __getitem__(self, index):
            sample_index = self.indices[index]
            item = samples[sample_index]
            tensor = np.asarray(
                item["tensor"],
                dtype=np.float32,
            )
            label = int(item["label"])
            if self.augment:
                rng = random.Random(
                    self.seed
                    + self.epoch * 1000003
                    + sample_index * 9176
                    + index * 37
                )
                tensor = _augment_sample(
                    tensor,
                    label,
                    rng,
                )
            return (
                torch.from_numpy(tensor),
                torch.tensor(
                    label,
                    dtype=torch.long,
                ),
            )

    train_dataset = SegmentDataset(
        train_indices,
        augment=True,
        seed=args.seed,
    )
    train_loader = DataLoader(
        train_dataset,
        batch_size=min(
            args.batch_size,
            max(1, len(train_dataset)),
        ),
        shuffle=True,
        num_workers=0,
    )

    train_counts = np.bincount(
        np.asarray(
            [int(samples[index]["label"]) for index in train_indices],
            dtype=np.int64,
        ),
        minlength=2,
    )
    total = float(max(1, train_counts.sum()))
    weights = [
        total / max(1.0, 2.0 * float(train_counts[0])),
        total / max(1.0, 2.0 * float(train_counts[1])),
    ]

    model = _build_model(nn).cpu()
    criterion = nn.CrossEntropyLoss(
        weight=torch.tensor(
            weights,
            dtype=torch.float32,
        )
    )
    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=float(args.learning_rate),
        weight_decay=1e-4,
    )

    best_state = None
    best_val_accuracy = -1.0
    history = []
    perfect_epochs = 0

    for epoch in range(int(args.epochs)):
        train_dataset.epoch = epoch
        model.train()
        train_total = 0
        train_correct = 0
        train_loss = 0.0

        for batch, target in train_loader:
            optimizer.zero_grad(set_to_none=True)
            logits = model(batch)
            loss = criterion(logits, target)
            loss.backward()
            optimizer.step()

            train_loss += float(loss.item()) * int(target.shape[0])
            train_total += int(target.shape[0])
            train_correct += int(
                (logits.argmax(dim=1) == target).sum().item()
            )

        model.eval()
        val_metrics, _ = _evaluate_model(
            torch,
            model,
            samples,
            val_indices,
        )
        train_accuracy = (
            train_correct / float(max(1, train_total))
        )
        val_accuracy = float(val_metrics["accuracy"])
        history.append(
            {
                "epoch": epoch + 1,
                "train_loss": (
                    train_loss / float(max(1, train_total))
                ),
                "train_accuracy": train_accuracy,
                "validation_accuracy": val_accuracy,
                "validation_class_accuracy": dict(
                    val_metrics["class_accuracy"]
                ),
                "validation_exact_checks": dict(
                    val_metrics["exact_checks"]
                ),
            }
        )
        print(
            f"[{epoch + 1:03d}/{args.epochs:03d}] "
            f"train={train_accuracy:.3f} "
            f"h1_val={val_accuracy:.3f}"
        )

        if val_accuracy > best_val_accuracy:
            best_val_accuracy = val_accuracy
            best_state = {
                key: value.detach().clone()
                for key, value in model.state_dict().items()
            }

        if (
            val_accuracy >= F3_NEURAL_REQUIRED_VALIDATION_ACCURACY
            and bool(val_metrics.get("all_validation_checks_exact"))
        ):
            perfect_epochs += 1
        else:
            perfect_epochs = 0

        if (
            int(args.early_stop_perfect_epochs) > 0
            and perfect_epochs >= int(args.early_stop_perfect_epochs)
        ):
            print(
                "Early stop: H1 mantido fora do treino permaneceu "
                f"100% por {perfect_epochs} épocas."
            )
            break

    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()

    validation_metrics, torch_validation_logits = _evaluate_model(
        torch,
        model,
        samples,
        val_indices,
    )
    (
        calibration_batch,
        calibration_labels,
        calibration_details,
    ) = _build_calibration_batch_with_details(
        samples,
        val_indices,
        augmentations_per_reference=int(
            args.calibration_augmentations_per_reference
        ),
        seed=int(args.seed),
    )
    with torch.no_grad():
        torch_calibration_logits = (
            model(torch.from_numpy(calibration_batch)).cpu().numpy()
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    staging_model = None
    staging_metadata = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f"{output.stem}.",
            suffix=".candidate.onnx",
            dir=str(output.parent),
            delete=False,
        ) as handle:
            staging_model = Path(handle.name)

        dummy = torch.zeros(
            (
                1,
                4,
                int(args.input_size),
                int(args.input_size),
            ),
            dtype=torch.float32,
        )
        _export_onnx_candidate(
            torch,
            model,
            dummy,
            staging_model,
        )

        net = cv2.dnn.readNetFromONNX(str(staging_model))
        validation_batch = np.stack(
            [
                np.asarray(samples[index]["tensor"], dtype=np.float32)
                for index in val_indices
            ],
            axis=0,
        )
        net.setInput(validation_batch)
        cv_logits = np.asarray(net.forward(), dtype=np.float32)
        _validate_candidate(
            cv_logits=cv_logits,
            torch_logits=torch_validation_logits,
            metrics=validation_metrics,
        )

        net.setInput(calibration_batch)
        cv_calibration_logits = np.asarray(net.forward(), dtype=np.float32)
        calibration_onnx_diff = _validate_logit_equivalence(
            cv_logits=cv_calibration_logits,
            torch_logits=torch_calibration_logits,
            label="calibração H1 aumentada",
        )
        diagnostics_dir = (
            output.parent
            / "diagnostics"
            / f"{output.stem}_calibration_latest"
        )
        calibration_diagnostics = _write_calibration_diagnostics(
            batch=calibration_batch,
            labels=calibration_labels,
            details=calibration_details,
            logits=cv_calibration_logits,
            destination=diagnostics_dir,
        )
        worst_off = calibration_diagnostics["worst_off"]
        worst_on = calibration_diagnostics["worst_on"]
        print(
            "Diagnóstico calibração • pior OFF: "
            f"{worst_off['mask_id']} P(ON)={worst_off['p_on']:.6f} "
            f"• {worst_off['kind']} "
            f"aug={worst_off['augmentation_index']}"
        )
        print(
            "Diagnóstico calibração • pior ON: "
            f"{worst_on['mask_id']} P(ON)={worst_on['p_on']:.6f} "
            f"• {worst_on['kind']} "
            f"aug={worst_on['augmentation_index']}"
        )
        print(
            "Diagnóstico calibração salvo em: "
            f"{calibration_diagnostics['directory']}"
        )

        try:
            threshold_calibration = _calibrate_thresholds_from_logits(
                cv_calibration_logits,
                calibration_labels,
                reference_sample_count=len(val_indices),
                augmentations_per_reference=int(
                    args.calibration_augmentations_per_reference
                ),
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"{exc}\n"
                "Amostras extremas e parâmetros foram preservados em: "
                f"{calibration_diagnostics['directory']}"
            ) from exc

        onnx_sha256 = _sha256_file(staging_model)
        metadata_path = output.with_suffix(".json")
        manifest = builder.manifest(str(dataset["project_name"]))
        metadata = {
            "schema_version": F3_NEURAL_MODEL_METADATA_SCHEMA_VERSION,
            "model_type": "f3_segment_on_off_cnn",
            "project_name": str(dataset["project_name"]),
            "onnx_path": str(output),
            "onnx_sha256": onnx_sha256,
            "input_size": int(args.input_size),
            "channels": [
                "r",
                "g",
                "b",
                "segment_mask",
            ],
            "labels": {
                "off": 0,
                "on": 1,
            },
            "suggested_thresholds": {
                "off_max_on_probability": threshold_calibration[
                    "off_max_on_probability"
                ],
                "on_min_on_probability": threshold_calibration[
                    "on_min_on_probability"
                ],
            },
            "threshold_calibration": threshold_calibration,
            "dataset": {
                "source": manifest.get("source"),
                "sample_count": manifest.get("sample_count"),
                "class_counts": manifest.get("class_counts"),
                "checks_used": list(
                    manifest.get("checks_used") or ()
                ),
                "missing_reference_check_ids": list(
                    manifest.get("missing_reference_check_ids") or ()
                ),
                "invalid_sample_ids": list(
                    manifest.get("invalid_sample_ids") or ()
                ),
            },
            "split": {
                "strategy": "hold_out_first_check_for_n1",
                "validation_check_id": preflight["validation_check_id"],
                "validation_check_name": preflight["validation_check_name"],
                "train_check_ids": list(preflight["train_check_ids"]),
                "train_count": int(preflight["train_count"]),
                "validation_count": int(preflight["validation_count"]),
                "train_class_counts": dict(preflight["train_class_counts"]),
                "validation_class_counts": dict(
                    preflight["validation_class_counts"]
                ),
            },
            "validation": {
                **validation_metrics,
                "required_accuracy": F3_NEURAL_REQUIRED_VALIDATION_ACCURACY,
                "required_class_accuracy": F3_NEURAL_REQUIRED_CLASS_ACCURACY,
                "onnx_vs_torch_max_abs_diff": float(
                    np.max(
                        np.abs(cv_logits - torch_validation_logits)
                    )
                    if cv_logits.size
                    else 0.0
                ),
                "calibration_onnx_vs_torch_max_abs_diff": float(
                    calibration_onnx_diff
                ),
                "accepted_for_physical_h1_retest": True,
            },
            "training": {
                "seed": int(args.seed),
                "epochs_requested": int(args.epochs),
                "epochs_completed": len(history),
                "batch_size": int(args.batch_size),
                "learning_rate": float(args.learning_rate),
                "calibration_augmentations_per_reference": int(
                    args.calibration_augmentations_per_reference
                ),
                "history": history,
            },
            "note": (
                "H1 ficou integralmente fora do treino. A promoção exige "
                "100% nas máscaras originais e separação OFF/ON também nas "
                "variações de calibração; os extremos observados delimitam "
                "a faixa INCERTO. Isso ainda não substitui o reteste físico "
                "de produção."
            ),
        }

        with tempfile.NamedTemporaryFile(
            prefix=f"{metadata_path.stem}.",
            suffix=".candidate.json",
            dir=str(output.parent),
            delete=False,
            mode="w",
            encoding="utf-8",
        ) as handle:
            staging_metadata = Path(handle.name)
            json.dump(
                metadata,
                handle,
                indent=2,
                ensure_ascii=False,
            )

        # O treino é offline. Ainda assim, cada arquivo é promovido por replace
        # atômico e o runtime valida SHA-256, então uma dupla parcialmente
        # atualizada falha fechada em vez de usar artefatos incompatíveis.
        staging_model.replace(output)
        staging_model = None
        staging_metadata.replace(metadata_path)
        staging_metadata = None

    finally:
        for candidate in (staging_model, staging_metadata):
            if isinstance(candidate, Path):
                try:
                    candidate.unlink(missing_ok=True)
                except OSError:
                    pass

    print(f"Modelo: {output}")
    print(f"Metadados: {output.with_suffix('.json')}")
    print(
        "Validação H1 independente: "
        f"{validation_metrics['correct']}/{validation_metrics['total']} "
        f"({validation_metrics['accuracy'] * 100:.1f}%)"
    )
    print(
        "Classes H1: "
        f"OFF={validation_metrics['class_accuracy']['off'] * 100:.1f}% "
        f"ON={validation_metrics['class_accuracy']['on'] * 100:.1f}%"
    )
    print(
        "Calibração H1: "
        f"OFF<=P(ON) {threshold_calibration['off_max_on_probability']:.6f} | "
        f"ON>=P(ON) {threshold_calibration['on_min_on_probability']:.6f} | "
        f"gap={threshold_calibration['uncertainty_gap']:.6f}"
    )
    print(
        "Artefato liberado para RETESTE FÍSICO H1; "
        "a validação de produção ainda está pendente."
    )
    return metadata


def _parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Treina a CNN local ON/OFF dos segmentos do Display F3."
        )
    )
    parser.add_argument(
        "--config",
        default="data/config/odin_display_projects.json",
        help="Arquivo do DisplayProjectRepository.",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Projeto Display. Se omitido, usa o projeto ativo.",
    )
    parser.add_argument(
        "--validation-check",
        default=None,
        help=(
            "CHECK mantido integralmente fora do treino. "
            "No N1 o padrão é o primeiro CHECK configurado."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Destino .onnx. Padrão: diretório de modelos "
            "associado ao DisplayProjectRepository."
        ),
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help=(
            "Valida fotos, classes e split H1 sem importar PyTorch "
            "nem alterar o modelo produtivo."
        ),
    )
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--calibration-augmentations-per-reference",
        type=int,
        default=F3_NEURAL_CALIBRATION_AUGMENTATIONS_PER_REFERENCE,
        help=(
            "Variações determinísticas por segmento do H1 reservado usadas "
            "somente para calibrar a faixa OFF/INCERTO/ON."
        ),
    )
    parser.add_argument(
        "--input-size",
        type=int,
        default=F3_NEURAL_INPUT_SIZE,
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=1e-3,
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--early-stop-perfect-epochs",
        type=int,
        default=5,
        help=(
            "Encerra após N épocas consecutivas com H1 100%% exato. "
            "Use 0 para desabilitar."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    treinar(_parse_args())
