from __future__ import annotations

"""Treina o prior neural de pose do tracking F3 usando somente dados locais.

A rede aprende ONDE está o contorno do Display/placa. Ela não recebe labels
ON/OFF e não decide conformidade. As fotos e geometrias já salvas em Projeto
Display viram exemplos supervisionados; augmentations sintéticas simulam
translação, pequena rotação, escala e variação de iluminação.

Uso:
    python scripts/treinar_f3_tracking_neural.py --preflight
    python scripts/treinar_f3_tracking_neural.py

Dependências de treino:
    python -m pip install -r requirements-neural-training.txt

Produção consome apenas o ONNX via OpenCV DNN.
"""

import argparse
import copy
import hashlib
import json
import random
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np

from src.platform.display_f3_neural_tracking import (
    F3_NEURAL_TRACKING_INPUT_HEIGHT,
    F3_NEURAL_TRACKING_INPUT_WIDTH,
    F3_NEURAL_TRACKING_MODEL_TYPE,
    F3_NEURAL_TRACKING_OUTPUT_MAX_NORMALIZED,
    F3_NEURAL_TRACKING_OUTPUT_MIN_NORMALIZED,
    F3_NEURAL_TRACKING_SCHEMA_VERSION,
    canonical_pose_anchor_digest,
    canonical_pose_anchors,
    f3_neural_tracking_metadata_path,
    f3_neural_tracking_model_path,
)
from src.platform.display_f3_object_tracking import (
    F3DisplayObjectTracker,
    _filter_board_matrix_candidates,
)
from src.platform.display_project_repository import (
    DisplayProjectRepository,
)


# Erro absoluto permanece como telemetria, não como autoridade de promoção.
F3_TRACKING_TELEMETRY_ORIGINAL_MEAN_ERROR_PX = 20.0
F3_TRACKING_TELEMETRY_AUGMENTED_MEAN_ERROR_PX = 45.0
F3_TRACKING_TELEMETRY_AUGMENTED_P95_ERROR_PX = 90.0

# D-067: a CNN é prior de correspondência/orientação, não pose final.
F3_TRACKING_REQUIRED_ORIGINAL_SELECTION_ACCURACY = 1.0
F3_TRACKING_REQUIRED_AUGMENTED_SELECTION_ACCURACY = 1.0
F3_TRACKING_REQUIRED_P05_SELECTION_MARGIN_DIAGONAL_FRACTION = 0.03


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


def _transform_points(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    return cv2.transform(
        np.asarray(points, dtype=np.float32).reshape(-1, 1, 2),
        np.asarray(matrix, dtype=np.float32).reshape(2, 3),
    ).reshape(-1, 2)


def _reference_rows(
    repository: DisplayProjectRepository,
    project_name: str | None,
) -> tuple[dict, list[dict]]:
    name = str(
        project_name or repository.obter_projeto_ativo() or ""
    ).strip()
    tracker = F3DisplayObjectTracker(repository)
    if not tracker.configure(name):
        return (
            {
                "ready": False,
                "reason": str(tracker.reason or "tracking_not_configured"),
                "project_name": name,
            },
            [],
        )

    canonical = canonical_pose_anchors(tracker.canonical_board)
    if canonical is None:
        return (
            {
                "ready": False,
                "reason": "canonical_pose_anchors_missing",
                "project_name": name,
            },
            [],
        )

    checks = repository.listar_checks(name)
    first_check_id = ""
    first_check_name = ""
    for check in checks or ():
        if not isinstance(check, dict):
            continue
        check_id = str(check.get("id") or "").strip()
        if not check_id:
            continue
        first_check_id = check_id
        first_check_name = str(check.get("name") or check_id).strip()
        break

    rows: list[dict] = []
    invalid: list[str] = []
    diagnostics: list[dict] = []
    for key, spec in tracker.reference_specs.items():
        if not isinstance(spec, dict):
            continue
        ref_key = str(key)
        path = Path(str(spec.get("path") or ""))
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        diagnostic = {
            "key": ref_key,
            "path": str(path),
            "status": "invalid",
            "reason": "",
        }
        if image is None or getattr(image, "size", 0) == 0:
            invalid.append(ref_key)
            diagnostic["reason"] = "image_missing_or_unreadable"
            diagnostics.append(diagnostic)
            continue

        source_height, source_width = image.shape[:2]
        diagnostic["source_resolution"] = {
            "width": int(source_width),
            "height": int(source_height),
        }

        # Referências atuais já são salvas na resolução mestre. Este resize
        # preserva compatibilidade com arquivos antigos sem transformar a
        # geometria: board/masks/reference_to_canonical já vivem no espaço
        # mestre do Projeto Display.
        if image.shape[:2] != (tracker.height, tracker.width):
            image = cv2.resize(
                image,
                (int(tracker.width), int(tracker.height)),
                interpolation=(
                    cv2.INTER_AREA
                    if source_width > tracker.width
                    or source_height > tracker.height
                    else cv2.INTER_LINEAR
                ),
            )
            diagnostic["normalized_to_master_resolution"] = True
        else:
            diagnostic["normalized_to_master_resolution"] = False

        try:
            reference_to_canonical = np.asarray(
                spec.get("reference_to_canonical"),
                dtype=np.float32,
            ).reshape(2, 3)
            canonical_to_reference = cv2.invertAffineTransform(
                reference_to_canonical
            )
            reference_anchors = _transform_points(
                canonical,
                canonical_to_reference,
            )
        except Exception:
            invalid.append(ref_key)
            diagnostic["reason"] = "reference_transform_invalid"
            diagnostics.append(diagnostic)
            continue

        normalized_anchors = reference_anchors / np.asarray(
            [float(tracker.width), float(tracker.height)],
            dtype=np.float32,
        )
        diagnostic["normalized_anchor_min"] = round(
            float(np.min(normalized_anchors)),
            6,
        )
        diagnostic["normalized_anchor_max"] = round(
            float(np.max(normalized_anchors)),
            6,
        )
        diagnostic["reference_anchors"] = np.round(
            reference_anchors,
            3,
        ).tolist()

        if not np.all(np.isfinite(normalized_anchors)):
            invalid.append(ref_key)
            diagnostic["reason"] = "reference_anchors_non_finite"
            diagnostics.append(diagnostic)
            continue
        if (
            float(np.min(normalized_anchors))
            < F3_NEURAL_TRACKING_OUTPUT_MIN_NORMALIZED
            or float(np.max(normalized_anchors))
            > F3_NEURAL_TRACKING_OUTPUT_MAX_NORMALIZED
        ):
            invalid.append(ref_key)
            diagnostic["reason"] = "reference_anchors_too_far_outside_frame"
            diagnostics.append(diagnostic)
            continue

        small = cv2.resize(
            image,
            (
                F3_NEURAL_TRACKING_INPUT_WIDTH,
                F3_NEURAL_TRACKING_INPUT_HEIGHT,
            ),
            interpolation=cv2.INTER_AREA,
        )
        small_anchors = normalized_anchors * np.asarray(
            [
                float(F3_NEURAL_TRACKING_INPUT_WIDTH),
                float(F3_NEURAL_TRACKING_INPUT_HEIGHT),
            ],
            dtype=np.float32,
        )

        diagnostic["status"] = "accepted"
        diagnostic["reason"] = "reference_ready"
        diagnostics.append(diagnostic)
        rows.append(
            {
                "key": ref_key,
                "source_type": str(spec.get("source_type") or ""),
                "check_id": str(spec.get("check_id") or ""),
                "path": str(path),
                "image": small,
                "anchors": np.asarray(small_anchors, dtype=np.float32),
            }
        )

    validation_key = (
        f"check:{first_check_id}"
        if first_check_id
        else ""
    )
    validation_rows = [
        row for row in rows
        if str(row.get("key") or "") == validation_key
    ]
    train_rows = [
        row for row in rows
        if str(row.get("key") or "") != validation_key
    ]

    report = {
        "ready": bool(
            validation_rows
            and len(train_rows) >= 2
        ),
        "reason": (
            "neural_tracking_preflight_ready"
            if validation_rows and len(train_rows) >= 2
            else (
                "validation_first_check_reference_missing"
                if not validation_rows
                else "neural_tracking_training_references_insufficient"
            )
        ),
        "project_name": name,
        "master_resolution": {
            "width": int(tracker.width),
            "height": int(tracker.height),
        },
        "canonical_anchor_digest": canonical_pose_anchor_digest(
            tracker.canonical_board
        ),
        "canonical_anchors": canonical.round(3).tolist(),
        "reference_count": len(rows),
        "training_reference_count": len(train_rows),
        "validation_reference_count": len(validation_rows),
        "validation_check_id": first_check_id,
        "validation_check_name": first_check_name,
        "validation_key": validation_key,
        "training_keys": [row["key"] for row in train_rows],
        "invalid_reference_keys": invalid,
        "reference_diagnostics": diagnostics,
        "accepted_output_range_normalized": [
            F3_NEURAL_TRACKING_OUTPUT_MIN_NORMALIZED,
            F3_NEURAL_TRACKING_OUTPUT_MAX_NORMALIZED,
        ],
    }
    return report, rows


def _photometric(image: np.ndarray, rng: random.Random) -> np.ndarray:
    alpha = rng.uniform(0.82, 1.18)
    beta = rng.uniform(-18.0, 18.0)
    result = np.clip(
        image.astype(np.float32) * alpha + beta,
        0.0,
        255.0,
    ).astype(np.uint8)
    if rng.random() < 0.25:
        result = cv2.GaussianBlur(result, (3, 3), rng.uniform(0.2, 0.8))
    if rng.random() < 0.20:
        noise = np.random.default_rng(
            rng.randint(0, 2**31 - 1)
        ).normal(0.0, rng.uniform(1.0, 4.0), result.shape)
        result = np.clip(
            result.astype(np.float32) + noise.astype(np.float32),
            0.0,
            255.0,
        ).astype(np.uint8)
    return result


def _augment(
    row: dict,
    rng: random.Random,
    *,
    strong: bool,
) -> tuple[np.ndarray, np.ndarray]:
    width = F3_NEURAL_TRACKING_INPUT_WIDTH
    height = F3_NEURAL_TRACKING_INPUT_HEIGHT
    image = np.asarray(row["image"], dtype=np.uint8)
    anchors = np.asarray(row["anchors"], dtype=np.float32)

    angle_limit = 8.0 if strong else 4.0
    scale_min, scale_max = ((0.88, 1.12) if strong else (0.95, 1.05))
    tx_limit = 0.10 if strong else 0.04
    ty_limit = 0.10 if strong else 0.04

    matrix = cv2.getRotationMatrix2D(
        (width / 2.0, height / 2.0),
        rng.uniform(-angle_limit, angle_limit),
        rng.uniform(scale_min, scale_max),
    ).astype(np.float32)
    matrix[0, 2] += rng.uniform(-width * tx_limit, width * tx_limit)
    matrix[1, 2] += rng.uniform(-height * ty_limit, height * ty_limit)

    moved_anchors = _transform_points(anchors, matrix)
    # O contorno pode ficar parcialmente fora do frame; isso é válido e é
    # justamente um caso que o tracking precisa extrapolar. Só descartamos a
    # augmentation quando ela sai da faixa explicitamente suportada pelo modelo.
    min_x = F3_NEURAL_TRACKING_OUTPUT_MIN_NORMALIZED * width
    max_x = F3_NEURAL_TRACKING_OUTPUT_MAX_NORMALIZED * width
    min_y = F3_NEURAL_TRACKING_OUTPUT_MIN_NORMALIZED * height
    max_y = F3_NEURAL_TRACKING_OUTPUT_MAX_NORMALIZED * height
    if (
        np.min(moved_anchors[:, 0]) < min_x
        or np.max(moved_anchors[:, 0]) > max_x
        or np.min(moved_anchors[:, 1]) < min_y
        or np.max(moved_anchors[:, 1]) > max_y
    ):
        matrix = np.asarray(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            dtype=np.float32,
        )
        moved_anchors = anchors.copy()

    moved = cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT101,
    )
    moved = _photometric(moved, rng)

    rgb = cv2.cvtColor(moved, cv2.COLOR_BGR2RGB)
    tensor = np.ascontiguousarray(
        rgb.astype(np.float32).transpose(2, 0, 1) / np.float32(255.0),
        dtype=np.float32,
    )
    target = moved_anchors / np.asarray(
        [float(width), float(height)],
        dtype=np.float32,
    )
    return tensor, np.ascontiguousarray(target.reshape(-1), dtype=np.float32)


def _build_model(nn):
    class TinyF3PoseCNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv2d(3, 16, 5, stride=2, padding=2),
                nn.ReLU(inplace=True),
                nn.Conv2d(16, 32, 3, stride=2, padding=1),
                nn.ReLU(inplace=True),
                nn.Conv2d(32, 64, 3, stride=2, padding=1),
                nn.ReLU(inplace=True),
                nn.Conv2d(64, 96, 3, stride=2, padding=1),
                nn.ReLU(inplace=True),
            )
            self.head = nn.Sequential(
                nn.Flatten(),
                nn.Linear(96 * 7 * 12, 256),
                nn.ReLU(inplace=True),
                nn.Dropout(p=0.10),
                nn.Linear(256, 8),
                nn.Tanh(),
            )

        def forward(self, x):
            normalized = self.head(self.features(x))
            # [-1, +1] -> [-0.35, +1.35]. Isso permite representar o mesmo
            # canto físico quando ele fica pouco além da borda da câmera.
            half_range = (
                F3_NEURAL_TRACKING_OUTPUT_MAX_NORMALIZED
                - F3_NEURAL_TRACKING_OUTPUT_MIN_NORMALIZED
            ) / 2.0
            center = (
                F3_NEURAL_TRACKING_OUTPUT_MAX_NORMALIZED
                + F3_NEURAL_TRACKING_OUTPUT_MIN_NORMALIZED
            ) / 2.0
            return normalized * half_range + center

    return TinyF3PoseCNN()


def _validation_batch(
    rows: list[dict],
    *,
    count: int,
    seed: int,
    include_original: bool,
) -> tuple[np.ndarray, np.ndarray]:
    batch = []
    targets = []
    if include_original:
        for row in rows:
            rgb = cv2.cvtColor(row["image"], cv2.COLOR_BGR2RGB)
            batch.append(
                np.ascontiguousarray(
                    rgb.astype(np.float32).transpose(2, 0, 1)
                    / np.float32(255.0),
                    dtype=np.float32,
                )
            )
            anchors = np.asarray(row["anchors"], dtype=np.float32)
            targets.append(
                np.ascontiguousarray(
                    (
                        anchors
                        / np.asarray(
                            [
                                F3_NEURAL_TRACKING_INPUT_WIDTH,
                                F3_NEURAL_TRACKING_INPUT_HEIGHT,
                            ],
                            dtype=np.float32,
                        )
                    ).reshape(-1),
                    dtype=np.float32,
                )
            )

    for index in range(max(0, int(count))):
        row = rows[index % len(rows)]
        rng = random.Random(int(seed) + index * 7919)
        tensor, target = _augment(row, rng, strong=True)
        batch.append(tensor)
        targets.append(target)

    return (
        np.stack(batch, axis=0).astype(np.float32),
        np.stack(targets, axis=0).astype(np.float32),
    )


def _anchor_errors(
    predictions: np.ndarray,
    targets: np.ndarray,
    *,
    master_width: int,
    master_height: int,
) -> np.ndarray:
    scale = np.asarray(
        [float(master_width), float(master_height)],
        dtype=np.float32,
    )
    predicted = predictions.reshape(-1, 4, 2) * scale
    expected = targets.reshape(-1, 4, 2) * scale
    return np.linalg.norm(predicted - expected, axis=2)


def _evaluate(
    torch,
    model,
    batch: np.ndarray,
    targets: np.ndarray,
    *,
    master_width: int,
    master_height: int,
) -> dict:
    model.eval()
    with torch.no_grad():
        predicted = model(torch.from_numpy(batch)).cpu().numpy()
    errors = _anchor_errors(
        predicted,
        targets,
        master_width=master_width,
        master_height=master_height,
    )
    return {
        "predictions": predicted,
        "mean_anchor_error_px": float(np.mean(errors)),
        "median_anchor_error_px": float(np.median(errors)),
        "p95_anchor_error_px": float(np.percentile(errors, 95.0)),
        "max_anchor_error_px": float(np.max(errors)),
    }


def _candidate_projected_current_anchors(
    current_quad: np.ndarray,
    canonical_anchors: np.ndarray,
) -> list[np.ndarray]:
    matrices = _filter_board_matrix_candidates(
        np.asarray(current_quad, dtype=np.float32).reshape(-1, 2).tolist(),
        np.asarray(canonical_anchors, dtype=np.float32).reshape(-1, 2).tolist(),
    )
    projected: list[np.ndarray] = []
    canonical = np.asarray(
        canonical_anchors,
        dtype=np.float32,
    ).reshape(-1, 2)
    for matrix in matrices:
        try:
            inverse = cv2.invertAffineTransform(
                np.asarray(matrix, dtype=np.float32).reshape(2, 3)
            )
            current = _transform_points(canonical, inverse)
        except Exception:
            continue
        if current.shape == (4, 2) and np.all(np.isfinite(current)):
            projected.append(
                np.ascontiguousarray(current, dtype=np.float32)
            )
    return projected


def _orientation_selection_metrics(
    predictions: np.ndarray,
    targets: np.ndarray,
    *,
    canonical_anchors: np.ndarray,
    master_width: int,
    master_height: int,
) -> dict:
    """Avalia exatamente o papel produtivo da CNN D-067.

    O alvo fornece a posição geométrica verdadeira do filtro. A partir dela são
    geradas as mesmas correspondências possíveis do runtime. O target determina
    qual hipótese é geometricamente correta; a previsão neural determina qual
    hipótese seria escolhida em produção.
    """
    scale = np.asarray(
        [float(master_width), float(master_height)],
        dtype=np.float32,
    )
    predicted_px = (
        np.asarray(predictions, dtype=np.float32).reshape(-1, 4, 2)
        * scale
    )
    target_px = (
        np.asarray(targets, dtype=np.float32).reshape(-1, 4, 2)
        * scale
    )
    canonical = np.asarray(
        canonical_anchors,
        dtype=np.float32,
    ).reshape(4, 2)

    samples: list[dict] = []
    correct_count = 0
    invalid_count = 0
    predicted_margins: list[float] = []
    winner_errors: list[float] = []
    second_errors: list[float] = []

    for index, (predicted, expected) in enumerate(
        zip(predicted_px, target_px)
    ):
        candidates = _candidate_projected_current_anchors(
            expected,
            canonical,
        )
        if len(candidates) < 2:
            invalid_count += 1
            samples.append(
                {
                    "index": int(index),
                    "valid": False,
                    "reason": "orientation_candidates_insufficient",
                    "candidate_count": int(len(candidates)),
                }
            )
            continue

        target_errors = np.asarray(
            [
                float(
                    np.mean(
                        np.linalg.norm(
                            candidate - expected,
                            axis=1,
                        )
                    )
                )
                for candidate in candidates
            ],
            dtype=np.float64,
        )
        prediction_errors = np.asarray(
            [
                float(
                    np.mean(
                        np.linalg.norm(
                            candidate - predicted,
                            axis=1,
                        )
                    )
                )
                for candidate in candidates
            ],
            dtype=np.float64,
        )

        correct_index = int(np.argmin(target_errors))
        selected_index = int(np.argmin(prediction_errors))
        order = np.argsort(prediction_errors)
        best_error = float(prediction_errors[order[0]])
        second_error = float(prediction_errors[order[1]])
        margin = max(0.0, second_error - best_error)
        correct = bool(selected_index == correct_index)
        if correct:
            correct_count += 1
        predicted_margins.append(margin)
        winner_errors.append(best_error)
        second_errors.append(second_error)

        samples.append(
            {
                "index": int(index),
                "valid": True,
                "candidate_count": int(len(candidates)),
                "correct_candidate_index": correct_index,
                "selected_candidate_index": selected_index,
                "correct": correct,
                "selected_error_px": round(best_error, 4),
                "second_best_error_px": round(second_error, 4),
                "selection_margin_px": round(margin, 4),
                "target_best_error_px": round(
                    float(target_errors[correct_index]),
                    4,
                ),
            }
        )

    valid_count = len(samples) - invalid_count
    accuracy = (
        float(correct_count) / float(valid_count)
        if valid_count > 0
        else 0.0
    )
    margins = np.asarray(predicted_margins, dtype=np.float64)
    winners = np.asarray(winner_errors, dtype=np.float64)
    seconds = np.asarray(second_errors, dtype=np.float64)

    return {
        "sample_count": int(len(samples)),
        "valid_sample_count": int(valid_count),
        "invalid_sample_count": int(invalid_count),
        "correct_count": int(correct_count),
        "wrong_count": int(max(0, valid_count - correct_count)),
        "accuracy": float(accuracy),
        "mean_selection_margin_px": (
            float(np.mean(margins)) if margins.size else 0.0
        ),
        "p05_selection_margin_px": (
            float(np.percentile(margins, 5.0)) if margins.size else 0.0
        ),
        "min_selection_margin_px": (
            float(np.min(margins)) if margins.size else 0.0
        ),
        "mean_selected_error_px": (
            float(np.mean(winners)) if winners.size else 0.0
        ),
        "mean_second_best_error_px": (
            float(np.mean(seconds)) if seconds.size else 0.0
        ),
        "samples": samples,
    }


def _export_onnx(torch, model, destination: Path) -> None:
    dummy = torch.zeros(
        (
            1,
            3,
            F3_NEURAL_TRACKING_INPUT_HEIGHT,
            F3_NEURAL_TRACKING_INPUT_WIDTH,
        ),
        dtype=torch.float32,
    )
    torch.onnx.export(
        model,
        dummy,
        str(destination),
        input_names=["frame"],
        output_names=["anchors"],
        dynamic_axes={
            "frame": {0: "batch"},
            "anchors": {0: "batch"},
        },
        opset_version=13,
        dynamo=False,
    )


def _parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=None)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--samples-per-reference", type=int, default=64)
    parser.add_argument("--validation-augmentations", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=1337)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repository = DisplayProjectRepository()
    report, rows = _reference_rows(repository, args.project)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not bool(report.get("ready")):
        return 2
    if args.preflight:
        return 0

    torch, nn, DataLoader, Dataset = _load_torch()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    validation_key = str(report["validation_key"])
    train_rows = [
        row for row in rows
        if str(row.get("key") or "") != validation_key
    ]
    validation_rows = [
        row for row in rows
        if str(row.get("key") or "") == validation_key
    ]

    class PoseDataset(Dataset):
        def __init__(self):
            self.epoch = 0
            self.length = (
                len(train_rows)
                * max(1, int(args.samples_per_reference))
            )

        def __len__(self):
            return self.length

        def __getitem__(self, index):
            row = train_rows[index % len(train_rows)]
            rng = random.Random(
                int(args.seed)
                + int(self.epoch) * 1000003
                + int(index) * 9176
            )
            tensor, target = _augment(row, rng, strong=True)
            return (
                torch.from_numpy(tensor),
                torch.from_numpy(target),
            )

    dataset = PoseDataset()
    loader = DataLoader(
        dataset,
        batch_size=min(
            max(1, int(args.batch_size)),
            len(dataset),
        ),
        shuffle=True,
        num_workers=0,
    )

    original_batch, original_targets = _validation_batch(
        validation_rows,
        count=0,
        seed=args.seed,
        include_original=True,
    )
    augmented_batch, augmented_targets = _validation_batch(
        validation_rows,
        count=max(1, int(args.validation_augmentations)),
        seed=args.seed + 100003,
        include_original=True,
    )

    model = _build_model(nn).cpu()
    criterion = nn.SmoothL1Loss(beta=0.025)
    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=float(args.learning_rate),
        weight_decay=1e-5,
    )

    best_state = None
    best_score = float("inf")
    history = []

    for epoch in range(max(1, int(args.epochs))):
        dataset.epoch = epoch
        model.train()
        loss_total = 0.0
        batch_count = 0
        for batch, target in loader:
            optimizer.zero_grad(set_to_none=True)
            prediction = model(batch)
            loss = criterion(prediction, target)
            loss.backward()
            optimizer.step()
            loss_total += float(loss.item())
            batch_count += 1

        validation = _evaluate(
            torch,
            model,
            augmented_batch,
            augmented_targets,
            master_width=int(report["master_resolution"]["width"]),
            master_height=int(report["master_resolution"]["height"]),
        )
        score = float(validation["mean_anchor_error_px"])
        history.append(
            {
                "epoch": epoch + 1,
                "loss": loss_total / max(1, batch_count),
                "validation_mean_anchor_error_px": score,
                "validation_p95_anchor_error_px": float(
                    validation["p95_anchor_error_px"]
                ),
            }
        )
        print(
            f"epoch={epoch + 1:03d} "
            f"loss={history[-1]['loss']:.6f} "
            f"mean_px={score:.2f} "
            f"p95_px={validation['p95_anchor_error_px']:.2f}"
        )
        if score < best_score:
            best_score = score
            best_state = copy.deepcopy(model.state_dict())

    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()

    original = _evaluate(
        torch,
        model,
        original_batch,
        original_targets,
        master_width=int(report["master_resolution"]["width"]),
        master_height=int(report["master_resolution"]["height"]),
    )
    augmented = _evaluate(
        torch,
        model,
        augmented_batch,
        augmented_targets,
        master_width=int(report["master_resolution"]["width"]),
        master_height=int(report["master_resolution"]["height"]),
    )

    canonical_validation_anchors = np.asarray(
        report["canonical_anchors"],
        dtype=np.float32,
    ).reshape(4, 2)
    original_selection = _orientation_selection_metrics(
        original["predictions"],
        original_targets,
        canonical_anchors=canonical_validation_anchors,
        master_width=int(report["master_resolution"]["width"]),
        master_height=int(report["master_resolution"]["height"]),
    )
    augmented_selection = _orientation_selection_metrics(
        augmented["predictions"],
        augmented_targets,
        canonical_anchors=canonical_validation_anchors,
        master_width=int(report["master_resolution"]["width"]),
        master_height=int(report["master_resolution"]["height"]),
    )

    frame_diagonal_px = float(
        np.hypot(
            float(report["master_resolution"]["width"]),
            float(report["master_resolution"]["height"]),
        )
    )
    required_margin_px = (
        frame_diagonal_px
        * F3_TRACKING_REQUIRED_P05_SELECTION_MARGIN_DIAGONAL_FRACTION
    )

    original_selection_ok = bool(
        int(original_selection["valid_sample_count"]) > 0
        and int(original_selection["invalid_sample_count"]) == 0
        and float(original_selection["accuracy"])
        >= F3_TRACKING_REQUIRED_ORIGINAL_SELECTION_ACCURACY
    )
    augmented_selection_ok = bool(
        int(augmented_selection["valid_sample_count"]) > 0
        and int(augmented_selection["invalid_sample_count"]) == 0
        and float(augmented_selection["accuracy"])
        >= F3_TRACKING_REQUIRED_AUGMENTED_SELECTION_ACCURACY
        and float(augmented_selection["p05_selection_margin_px"])
        >= required_margin_px
    )
    accepted = bool(
        original_selection_ok
        and augmented_selection_ok
    )

    print()
    print("VALIDAÇÃO DE CORRESPONDÊNCIA/ORIENTAÇÃO D-067")
    print(
        "H1 original: "
        f"{original_selection['correct_count']}/"
        f"{original_selection['valid_sample_count']} correto(s) | "
        f"accuracy={original_selection['accuracy'] * 100.0:.2f}% | "
        f"margin={original_selection['min_selection_margin_px']:.2f}px"
    )
    print(
        "H1 augmentations: "
        f"{augmented_selection['correct_count']}/"
        f"{augmented_selection['valid_sample_count']} correto(s) | "
        f"accuracy={augmented_selection['accuracy'] * 100.0:.2f}% | "
        f"p05_margin={augmented_selection['p05_selection_margin_px']:.2f}px "
        f"(mínimo exigido={required_margin_px:.2f}px)"
    )
    print(
        "Telemetria de regressão: "
        f"original_mean={original['mean_anchor_error_px']:.2f}px | "
        f"aug_mean={augmented['mean_anchor_error_px']:.2f}px | "
        f"aug_p95={augmented['p95_anchor_error_px']:.2f}px"
    )

    if not accepted:
        raise RuntimeError(
            "Modelo de pose NÃO promovido: gate de correspondência/orientação "
            "D-067 reprovado. "
            f"original_accuracy={original_selection['accuracy'] * 100.0:.2f}%; "
            f"aug_accuracy={augmented_selection['accuracy'] * 100.0:.2f}%; "
            f"aug_p05_margin={augmented_selection['p05_selection_margin_px']:.2f}px; "
            f"required_margin={required_margin_px:.2f}px."
        )

    project_name = str(report["project_name"])
    output = f3_neural_tracking_model_path(repository, project_name)
    metadata_path = f3_neural_tracking_metadata_path(repository, project_name)
    output.parent.mkdir(parents=True, exist_ok=True)

    staging = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f"{output.stem}.",
            suffix=".candidate.onnx",
            dir=str(output.parent),
            delete=False,
        ) as handle:
            staging = Path(handle.name)

        _export_onnx(torch, model, staging)

        # Garante que o artefato que irá para produção abre no mesmo OpenCV DNN.
        net = cv2.dnn.readNetFromONNX(str(staging))
        net.setInput(augmented_batch[: min(8, len(augmented_batch))])
        cv_output = np.asarray(net.forward(), dtype=np.float32)
        with torch.no_grad():
            torch_output = model(
                torch.from_numpy(
                    augmented_batch[: min(8, len(augmented_batch))]
                )
            ).cpu().numpy()
        max_diff = float(np.max(np.abs(cv_output - torch_output)))
        if max_diff > 1e-4:
            raise RuntimeError(
                "ONNX divergiu do PyTorch: "
                f"max_abs_diff={max_diff:.8f}"
            )

        onnx_hash = _sha256_file(staging)
        runtime_max_snap_error_px = float(
            min(
                180.0,
                max(
                    90.0,
                    float(augmented["p95_anchor_error_px"]) * 2.0,
                ),
            )
        )
        metadata = {
            "schema_version": F3_NEURAL_TRACKING_SCHEMA_VERSION,
            "model_type": F3_NEURAL_TRACKING_MODEL_TYPE,
            "project_name": project_name,
            "onnx_path": str(output),
            "onnx_sha256": onnx_hash,
            "input_width": F3_NEURAL_TRACKING_INPUT_WIDTH,
            "input_height": F3_NEURAL_TRACKING_INPUT_HEIGHT,
            "output": "four_ordered_canonical_anchors_in_current_frame",
            "output_min_normalized": (
                F3_NEURAL_TRACKING_OUTPUT_MIN_NORMALIZED
            ),
            "output_max_normalized": (
                F3_NEURAL_TRACKING_OUTPUT_MAX_NORMALIZED
            ),
            "canonical_anchor_digest": str(
                report["canonical_anchor_digest"]
            ),
            "canonical_anchors": report["canonical_anchors"],
            "dataset": {
                "source": "configured_f3_tracking_references",
                "training_keys": list(report["training_keys"]),
                "validation_key": validation_key,
                "validation_check_id": str(
                    report["validation_check_id"]
                ),
                "validation_check_name": str(
                    report["validation_check_name"]
                ),
                "invalid_reference_keys": list(
                    report["invalid_reference_keys"]
                ),
            },
            "validation": {
                "accepted_for_runtime": True,
                "original_mean_anchor_error_px": float(
                    original["mean_anchor_error_px"]
                ),
                "original_max_anchor_error_px": float(
                    original["max_anchor_error_px"]
                ),
                "augmented_mean_anchor_error_px": float(
                    augmented["mean_anchor_error_px"]
                ),
                "augmented_median_anchor_error_px": float(
                    augmented["median_anchor_error_px"]
                ),
                "augmented_p95_anchor_error_px": float(
                    augmented["p95_anchor_error_px"]
                ),
                "augmented_max_anchor_error_px": float(
                    augmented["max_anchor_error_px"]
                ),
                "telemetry_original_mean_error_target_px": (
                    F3_TRACKING_TELEMETRY_ORIGINAL_MEAN_ERROR_PX
                ),
                "telemetry_augmented_mean_error_target_px": (
                    F3_TRACKING_TELEMETRY_AUGMENTED_MEAN_ERROR_PX
                ),
                "telemetry_augmented_p95_error_target_px": (
                    F3_TRACKING_TELEMETRY_AUGMENTED_P95_ERROR_PX
                ),
                "selection_gate": {
                    "authority": "orientation_correspondence",
                    "original": original_selection,
                    "augmented": augmented_selection,
                    "required_original_accuracy": (
                        F3_TRACKING_REQUIRED_ORIGINAL_SELECTION_ACCURACY
                    ),
                    "required_augmented_accuracy": (
                        F3_TRACKING_REQUIRED_AUGMENTED_SELECTION_ACCURACY
                    ),
                    "required_p05_margin_diagonal_fraction": (
                        F3_TRACKING_REQUIRED_P05_SELECTION_MARGIN_DIAGONAL_FRACTION
                    ),
                    "required_p05_margin_px": float(required_margin_px),
                },
                "runtime_max_snap_error_px": runtime_max_snap_error_px,
                "onnx_vs_torch_max_abs_diff": max_diff,
            },
            "training": {
                "seed": int(args.seed),
                "epochs": max(1, int(args.epochs)),
                "batch_size": max(1, int(args.batch_size)),
                "samples_per_reference": max(
                    1, int(args.samples_per_reference)
                ),
                "validation_augmentations": max(
                    1, int(args.validation_augmentations)
                ),
                "learning_rate": float(args.learning_rate),
                "history": history,
            },
            "contract": (
                "GEOMETRY_ONLY: não decide ON/OFF, OK/NG ou identidade de CHECK. "
                "O prior neural apenas desambigua a pose; o filtro estrutural "
                "e o tracking validam a geometria antes do LOCK."
            ),
        }

        staging.replace(output)
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    finally:
        if staging is not None and staging.exists():
            try:
                staging.unlink()
            except OSError:
                pass

    print()
    print("MODELO DE POSE F3 PROMOVIDO")
    print(f"ONNX: {output}")
    print(f"METADADOS: {metadata_path}")
    print(
        "Validação de orientação: "
        f"H1={original_selection['accuracy'] * 100.0:.2f}% | "
        f"aug={augmented_selection['accuracy'] * 100.0:.2f}% | "
        f"aug p05 margin={augmented_selection['p05_selection_margin_px']:.2f}px"
    )
    print(
        "Telemetria de regressão: "
        f"original mean={original['mean_anchor_error_px']:.2f}px | "
        f"aug mean={augmented['mean_anchor_error_px']:.2f}px | "
        f"aug p95={augmented['p95_anchor_error_px']:.2f}px"
    )
    print(
        "O modelo é somente geométrico. A IA Híbrida continua sendo "
        "a única autoridade semântica."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
