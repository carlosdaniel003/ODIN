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
    f3_neural_model_path_for_repository,
)
from src.platform.display_project_repository import (
    DisplayProjectRepository,
)


F3_NEURAL_REQUIRED_VALIDATION_ACCURACY = 1.0
F3_NEURAL_REQUIRED_CLASS_ACCURACY = 1.0


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
) -> np.ndarray:
    """Augmentation leve focada nos defeitos físicos relatados no F3."""
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

    if rng.random() < 0.25:
        rgb = cv2.GaussianBlur(
            rgb,
            (3, 3),
            0,
        )

    if rng.random() < 0.45:
        noise = np.random.default_rng(
            rng.randrange(1, 2**31)
        ).normal(
            0.0,
            rng.uniform(0.006, 0.025),
            rgb.shape,
        ).astype(np.float32)
        rgb = np.clip(rgb + noise, 0.0, 1.0)

    # Hard negative: um OFF pode receber um ponto/reflexo claro sem virar ON.
    # O reflexo não cobre deliberadamente toda a máscara, para não ensinar um
    # defeito artificial indistinguível de um segmento realmente energizado.
    if int(label) == 0 and rng.random() < 0.35:
        overlay = np.zeros_like(rgb, dtype=np.float32)
        center = (
            rng.randrange(
                max(1, width // 5),
                max(2, width - width // 5),
            ),
            rng.randrange(
                max(1, height // 5),
                max(2, height - height // 5),
            ),
        )
        axes = (
            rng.randrange(
                2,
                max(3, width // 7),
            ),
            rng.randrange(
                2,
                max(3, height // 7),
            ),
        )
        intensity = rng.uniform(0.45, 0.95)
        cv2.ellipse(
            overlay,
            center,
            axes,
            rng.uniform(0.0, 180.0),
            0.0,
            360.0,
            (intensity, intensity, intensity),
            thickness=-1,
        )
        rgb = np.clip(
            rgb + overlay,
            0.0,
            1.0,
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


def _validate_candidate(
    *,
    cv_logits: np.ndarray,
    torch_logits: np.ndarray,
    metrics: dict,
) -> None:
    if cv_logits.shape != torch_logits.shape:
        raise RuntimeError(
            "ONNX incompatível com OpenCV DNN: "
            f"saída {tuple(cv_logits.shape)}; "
            f"esperado {tuple(torch_logits.shape)}"
        )
    if cv_logits.ndim != 2 or cv_logits.shape[1] != 2:
        raise RuntimeError(
            "ONNX incompatível com OpenCV DNN: "
            f"saída {tuple(cv_logits.shape)}"
        )

    max_abs_diff = float(
        np.max(np.abs(cv_logits - torch_logits))
        if cv_logits.size
        else 0.0
    )
    if max_abs_diff > 1e-4:
        raise RuntimeError(
            "ONNX divergiu do modelo PyTorch acima da tolerância: "
            f"max_abs_diff={max_abs_diff:.8f}"
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
    print(json.dumps(report, indent=2, ensure_ascii=False))


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

    if bool(args.preflight):
        _print_preflight(preflight)
        return preflight

    if not bool(preflight.get("ready")):
        raise RuntimeError(
            "Preflight neural N1 não está pronto:\n"
            + json.dumps(preflight, indent=2, ensure_ascii=False)
        )

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
        torch.onnx.export(
            model,
            dummy,
            str(staging_model),
            input_names=["segments"],
            output_names=["logits"],
            dynamic_axes={
                "segments": {0: "batch"},
                "logits": {0: "batch"},
            },
            opset_version=13,
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

        onnx_sha256 = _sha256_file(staging_model)
        metadata_path = output.with_suffix(".json")
        manifest = builder.manifest(str(dataset["project_name"]))
        metadata = {
            "schema_version": 2,
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
                "off_max_on_probability": 0.20,
                "on_min_on_probability": 0.80,
            },
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
                "accepted_for_physical_h1_retest": True,
            },
            "training": {
                "seed": int(args.seed),
                "epochs_requested": int(args.epochs),
                "epochs_completed": len(history),
                "batch_size": int(args.batch_size),
                "learning_rate": float(args.learning_rate),
                "history": history,
            },
            "note": (
                "H1 ficou integralmente fora do treino e atingiu 100% nas "
                "máscaras configuradas antes da promoção do ONNX. Isso ainda "
                "não substitui o reteste físico de produção."
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
