from __future__ import annotations

"""Treina a primeira CNN de segmentos do Display F3 usando a configuração real.

Uso:
    python scripts/treinar_f3_segmentos_neural.py --project CM_500_L

Dependências de treinamento (não entram no runtime produtivo):
    pip install -r requirements-neural-training.txt

O artefato de produção é ONNX e será consumido pelo OpenCV DNN já presente no
ODIN. Nenhuma API, nuvem ou serviço pago participa do fluxo.
"""

import argparse
import json
import random
from pathlib import Path

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


def _load_torch():
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, Dataset
    except Exception as exc:
        raise RuntimeError(
            "PyTorch não está disponível. Instale somente no ambiente de "
            "treino com: pip install -r requirements-neural-training.txt"
        ) from exc
    return torch, nn, DataLoader, Dataset


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


def _stratified_split(
    labels: list[int],
    seed: int,
    val_ratio: float = 0.20,
):
    rng = random.Random(seed)
    train_indices: list[int] = []
    val_indices: list[int] = []

    for target in sorted(set(labels)):
        indices = [
            index
            for index, value in enumerate(labels)
            if value == target
        ]
        rng.shuffle(indices)
        if len(indices) <= 1:
            train_indices.extend(indices)
            continue

        val_count = max(
            1,
            int(round(len(indices) * float(val_ratio))),
        )
        val_count = min(
            val_count,
            len(indices) - 1,
        )
        val_indices.extend(indices[:val_count])
        train_indices.extend(indices[val_count:])

    rng.shuffle(train_indices)
    rng.shuffle(val_indices)
    if not val_indices:
        val_indices = list(train_indices[-1:])
        train_indices = list(
            train_indices[:-1] or train_indices
        )
    return train_indices, val_indices


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


def treinar(args) -> dict:
    torch, nn, DataLoader, Dataset = _load_torch()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    repository = DisplayProjectRepository(
        Path(args.config)
    )
    builder = F3NeuralDatasetBuilder(
        repository,
        input_size=args.input_size,
    )
    dataset = builder.collect(args.project)
    if not bool(dataset.get("ready")):
        raise RuntimeError(
            "Dataset neural não está pronto: "
            f"{dataset.get('reason')}. "
            f"Amostras={dataset.get('sample_count')} "
            f"classes={dataset.get('class_counts')} "
            "CHECKS sem foto="
            f"{dataset.get('missing_reference_check_ids')}"
        )

    samples = list(dataset["samples"])
    labels = [
        int(item["label"])
        for item in samples
    ]
    train_indices, val_indices = _stratified_split(
        labels,
        args.seed,
    )

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
    val_dataset = SegmentDataset(
        val_indices,
        augment=False,
        seed=args.seed + 1,
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
    val_loader = DataLoader(
        val_dataset,
        batch_size=min(
            args.batch_size,
            max(1, len(val_dataset)),
        ),
        shuffle=False,
        num_workers=0,
    )

    counts = np.bincount(
        np.asarray(labels, dtype=np.int64),
        minlength=2,
    )
    total = float(max(1, counts.sum()))
    weights = [
        total / max(
            1.0,
            2.0 * float(counts[0]),
        ),
        total / max(
            1.0,
            2.0 * float(counts[1]),
        ),
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

    for epoch in range(int(args.epochs)):
        train_dataset.epoch = epoch
        model.train()
        train_total = 0
        train_correct = 0
        train_loss = 0.0

        for batch, target in train_loader:
            optimizer.zero_grad(
                set_to_none=True
            )
            logits = model(batch)
            loss = criterion(
                logits,
                target,
            )
            loss.backward()
            optimizer.step()

            train_loss += (
                float(loss.item())
                * int(target.shape[0])
            )
            train_total += int(target.shape[0])
            train_correct += int(
                (
                    logits.argmax(dim=1)
                    == target
                ).sum().item()
            )

        model.eval()
        val_total = 0
        val_correct = 0
        val_loss = 0.0
        with torch.no_grad():
            for batch, target in val_loader:
                logits = model(batch)
                loss = criterion(
                    logits,
                    target,
                )
                val_loss += (
                    float(loss.item())
                    * int(target.shape[0])
                )
                val_total += int(target.shape[0])
                val_correct += int(
                    (
                        logits.argmax(dim=1)
                        == target
                    ).sum().item()
                )

        train_accuracy = (
            train_correct
            / float(max(1, train_total))
        )
        val_accuracy = (
            val_correct
            / float(max(1, val_total))
        )
        history.append(
            {
                "epoch": epoch + 1,
                "train_loss": (
                    train_loss
                    / float(max(1, train_total))
                ),
                "train_accuracy": train_accuracy,
                "val_loss": (
                    val_loss
                    / float(max(1, val_total))
                ),
                "val_accuracy": val_accuracy,
            }
        )
        print(
            f"[{epoch + 1:03d}/{args.epochs:03d}] "
            f"train={train_accuracy:.3f} "
            f"val={val_accuracy:.3f}"
        )

        if val_accuracy > best_val_accuracy:
            best_val_accuracy = val_accuracy
            best_state = {
                key: value.detach().clone()
                for key, value
                in model.state_dict().items()
            }

    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()

    project_name = str(dataset["project_name"])
    output = (
        Path(args.output)
        if args.output
        else f3_neural_model_path_for_repository(
            repository,
            project_name,
        )
    )
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

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
        str(output),
        input_names=["segments"],
        output_names=["logits"],
        dynamic_axes={
            "segments": {0: "batch"},
            "logits": {0: "batch"},
        },
        opset_version=13,
    )

    # O runtime do ODIN já possui OpenCV. Falhe ainda no treino se o artefato
    # exportado não puder ser carregado pelo mesmo backend do F3.
    net = cv2.dnn.readNetFromONNX(
        str(output)
    )
    probe_indices = train_indices[:2]
    if not probe_indices:
        probe_indices = val_indices[:1]
    probe = np.stack(
        [
            np.asarray(
                samples[index]["tensor"],
                dtype=np.float32,
            )
            for index in probe_indices
        ],
        axis=0,
    )
    net.setInput(probe)
    logits = net.forward()
    if (
        logits.ndim != 2
        or logits.shape[1] != 2
    ):
        raise RuntimeError(
            "ONNX incompatível com OpenCV DNN: "
            f"saída {tuple(logits.shape)}"
        )

    metadata_path = output.with_suffix(
        ".json"
    )
    manifest = builder.manifest(
        project_name
    )
    metadata = {
        "schema_version": 1,
        "model_type": "f3_segment_on_off_cnn",
        "project_name": project_name,
        "onnx_path": str(output),
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
            "sample_count": manifest.get(
                "sample_count"
            ),
            "class_counts": manifest.get(
                "class_counts"
            ),
            "checks_used": list(
                manifest.get("checks_used")
                or ()
            ),
            "missing_reference_check_ids": list(
                manifest.get(
                    "missing_reference_check_ids"
                )
                or ()
            ),
        },
        "training": {
            "seed": int(args.seed),
            "epochs": int(args.epochs),
            "batch_size": int(args.batch_size),
            "learning_rate": float(
                args.learning_rate
            ),
            "train_count": len(
                train_indices
            ),
            "validation_count": len(
                val_indices
            ),
            (
                "best_validation_accuracy_"
                "on_configured_references"
            ): float(
                best_val_accuracy
            ),
            "history": history,
        },
        "note": (
            "A validação real é o reteste físico H1. "
            "Acurácia sobre referências configuradas/"
            "augmentadas não mede sozinha generalização "
            "de produção."
        ),
    }
    metadata_path.write_text(
        json.dumps(
            metadata,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"Modelo: {output}")
    print(
        f"Metadados: {metadata_path}"
    )
    print(
        f"Amostras: {dataset['sample_count']} "
        f"ON={dataset['class_counts']['on']} "
        f"OFF={dataset['class_counts']['off']}"
    )
    return metadata


def _parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Treina a CNN local ON/OFF dos "
            "segmentos do Display F3."
        )
    )
    parser.add_argument(
        "--config",
        default=(
            "data/config/"
            "odin_display_projects.json"
        ),
        help=(
            "Arquivo do "
            "DisplayProjectRepository."
        ),
    )
    parser.add_argument(
        "--project",
        default=None,
        help=(
            "Projeto Display. Se omitido, "
            "usa o projeto ativo."
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
        "--epochs",
        type=int,
        default=45,
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
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
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
    )
    return parser.parse_args()


if __name__ == "__main__":
    treinar(_parse_args())
