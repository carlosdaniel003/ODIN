from __future__ import annotations

"""Calibração física multi-frame dos thresholds da CNN do Display F3.

Este módulo é offline/engenharia. Ele nunca treina a CNN e nunca participa do
hot path produtivo. Sua única responsabilidade é incorporar evidência física H1
de múltiplos frames congelados à calibração do artefato ONNX já promovido.

Os rótulos vêm do mask_states do H1 configurado. A classificação publicada no
DEBUG (ON/OFF/INCERTO) é somente observação e nunca vira rótulo de treino.
"""

from copy import deepcopy
import hashlib
import json
import tempfile
from pathlib import Path

import numpy as np

from src.platform.display_f3_neural_dataset import (
    F3_NEURAL_MIN_PHYSICAL_H1_CALIBRATION_FRAMES,
    F3_NEURAL_MODEL_METADATA_SCHEMA_VERSION,
    F3_NEURAL_PHYSICAL_THRESHOLD_CALIBRATION_SOURCE,
    F3_NEURAL_THRESHOLD_CALIBRATION_SOURCE,
    F3_NEURAL_THRESHOLD_CALIBRATION_SOURCES,
)
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
)


F3_NEURAL_PHYSICAL_H1_DEBUG_REPORT_MARKER = (
    "[RESUMO OPERACIONAL - LEIA PRIMEIRO]"
)
F3_NEURAL_H1_AUTHORITY = "f3_h1_neural_segment_detector"
F3_NEURAL_MODEL_TYPE = "f3_segment_on_off_cnn"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _debug_line_value(report_text: str, key: str) -> str:
    prefix = f"{str(key or '').strip()}="
    for line in str(report_text or "").splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _split_debug_reports(text: str) -> list[str]:
    value = str(text or "")
    marker = F3_NEURAL_PHYSICAL_H1_DEBUG_REPORT_MARKER
    pieces = value.split(marker)
    if len(pieces) <= 1:
        return [value] if value.strip() else []
    return [
        marker + piece
        for piece in pieces[1:]
        if piece.strip()
    ]


def _json_objects_after_key(text: str, key: str) -> list[dict]:
    marker = json.dumps(str(key))
    decoder = json.JSONDecoder()
    cursor = 0
    values: list[dict] = []
    source = str(text or "")

    while True:
        index = source.find(marker, cursor)
        if index < 0:
            break
        colon = source.find(":", index + len(marker))
        if colon < 0:
            break
        start = source.find("{", colon + 1)
        if start < 0:
            break
        try:
            value, consumed = decoder.raw_decode(source[start:])
        except json.JSONDecodeError:
            cursor = index + len(marker)
            continue
        if isinstance(value, dict):
            values.append(value)
        cursor = start + max(1, int(consumed))
    return values


def parse_physical_h1_debug_text(
    text: str,
    *,
    source_name: str = "",
) -> list[dict]:
    """Extrai snapshots de last_auto_analysis de um ou vários DEBUGs colados."""
    snapshots: list[dict] = []
    source_file = (
        str(source_name or "")
        .replace("\\", "/")
        .rsplit("/", 1)[-1]
    )
    for report_index, report in enumerate(
        _split_debug_reports(text),
        start=1,
    ):
        frame_hash = _debug_line_value(
            report,
            "frame_sha256_24",
        )
        captured_at = _debug_line_value(
            report,
            "capturado_em",
        )
        analyses = _json_objects_after_key(
            report,
            "last_auto_analysis",
        )
        for analysis_index, analysis in enumerate(analyses, start=1):
            if frame_hash:
                frame_key = frame_hash
            else:
                serialized = json.dumps(
                    analysis.get("mask_results") or [],
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                frame_key = hashlib.sha256(
                    serialized.encode("utf-8")
                ).hexdigest()[:24]
            snapshots.append(
                {
                    "source_file": source_file,
                    "report_index": int(report_index),
                    "analysis_index": int(analysis_index),
                    "captured_at": str(captured_at or ""),
                    "frame_hash": str(frame_key),
                    "analysis": analysis,
                }
            )
    return snapshots


def _read_metadata(path: Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Metadata neural inválido: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise RuntimeError("Metadata neural não é um objeto JSON.")
    return value


def _base_augmented_calibration(metadata: dict) -> dict:
    calibration = (
        metadata.get("threshold_calibration")
        if isinstance(metadata.get("threshold_calibration"), dict)
        else {}
    )
    source = str(calibration.get("source") or "").strip()
    if source == F3_NEURAL_THRESHOLD_CALIBRATION_SOURCE:
        return deepcopy(calibration)
    if source == F3_NEURAL_PHYSICAL_THRESHOLD_CALIBRATION_SOURCE:
        base = calibration.get("base_augmented_calibration")
        if (
            isinstance(base, dict)
            and str(base.get("source") or "").strip()
            == F3_NEURAL_THRESHOLD_CALIBRATION_SOURCE
        ):
            return deepcopy(base)
    raise RuntimeError(
        "Metadata neural não contém calibração H1 aumentada de base "
        "compatível com a calibração física multi-frame."
    )


def _expected_h1_states(
    repository,
    project_name: str,
    validation_check_id: str,
) -> dict[str, str]:
    try:
        checks = repository.listar_checks(project_name)
    except Exception as exc:
        raise RuntimeError(
            "Não foi possível carregar os CHECKS do Projeto Display."
        ) from exc

    check = next(
        (
            item
            for item in checks
            if isinstance(item, dict)
            and str(item.get("id") or "").strip()
            == str(validation_check_id)
        ),
        None,
    )
    if not isinstance(check, dict):
        raise RuntimeError(
            "CHECK H1 reservado do metadata não existe mais no projeto."
        )

    states = (
        check.get("mask_states")
        if isinstance(check.get("mask_states"), dict)
        else {}
    )
    expected = {
        str(mask_id).strip(): str(state).strip().lower()
        for mask_id, state in states.items()
        if str(mask_id).strip()
        and str(state).strip().lower()
        in (DISPLAY_CHECK_STATE_OFF, DISPLAY_CHECK_STATE_ON)
    }
    if not expected:
        raise RuntimeError(
            "CHECK H1 reservado não possui máscaras ON/OFF configuradas."
        )
    return expected


def _probability_close(left, right, *, tolerance: float = 2e-6) -> bool:
    try:
        a = float(left)
        b = float(right)
    except (TypeError, ValueError):
        return False
    return bool(
        np.isfinite(a)
        and np.isfinite(b)
        and abs(a - b) <= float(tolerance)
    )


def _validate_debug_model(
    *,
    model_status: dict,
    metadata: dict,
    base_calibration: dict,
    project_name: str,
) -> None:
    if not isinstance(model_status, dict) or model_status.get("ready") is not True:
        raise RuntimeError(
            "DEBUG físico H1 não contém um modelo neural pronto."
        )
    if str(model_status.get("project_name") or "").strip() != str(project_name):
        raise RuntimeError(
            "DEBUG físico H1 pertence a outro Projeto Display."
        )
    if str(model_status.get("model_type") or "").strip() != F3_NEURAL_MODEL_TYPE:
        raise RuntimeError(
            "DEBUG físico H1 pertence a outro tipo de modelo neural."
        )

    try:
        reported_size = int(model_status.get("input_size", 0) or 0)
        metadata_size = int(metadata.get("input_size", 0) or 0)
    except (TypeError, ValueError):
        reported_size = 0
        metadata_size = -1
    if reported_size != metadata_size or reported_size <= 0:
        raise RuntimeError(
            "DEBUG físico H1 usa input_size diferente do artefato atual."
        )

    current_calibration = (
        metadata.get("threshold_calibration")
        if isinstance(metadata.get("threshold_calibration"), dict)
        else {}
    )
    reported_source = str(
        model_status.get("threshold_calibration_source") or ""
    ).strip()
    if reported_source == F3_NEURAL_THRESHOLD_CALIBRATION_SOURCE:
        expected_calibration = base_calibration
    elif reported_source == F3_NEURAL_PHYSICAL_THRESHOLD_CALIBRATION_SOURCE:
        expected_calibration = current_calibration
    else:
        raise RuntimeError(
            "DEBUG físico H1 usa origem de calibração neural incompatível."
        )

    checks = (
        (
            "off_max_on_probability",
            model_status.get("off_max_on_probability"),
            expected_calibration.get("off_max_on_probability"),
        ),
        (
            "on_min_on_probability",
            model_status.get("on_min_on_probability"),
            expected_calibration.get("on_min_on_probability"),
        ),
        (
            "uncertainty_gap",
            model_status.get("threshold_calibration_gap"),
            expected_calibration.get("uncertainty_gap"),
        ),
    )
    for label, reported, expected in checks:
        if not _probability_close(reported, expected):
            raise RuntimeError(
                "DEBUG físico H1 não pertence à mesma calibração do modelo "
                f"atual: {label} divergente."
            )

    try:
        reported_samples = int(
            model_status.get("threshold_calibration_sample_count", 0) or 0
        )
        expected_samples = int(
            expected_calibration.get("sample_count", 0) or 0
        )
        reported_augmentations = int(
            model_status.get(
                "threshold_calibration_augmentations_per_reference",
                0,
            )
            or 0
        )
        expected_augmentations = int(
            expected_calibration.get(
                "augmentations_per_reference",
                0,
            )
            or 0
        )
    except (TypeError, ValueError):
        reported_samples = -1
        expected_samples = -2
        reported_augmentations = -1
        expected_augmentations = -2

    if (
        reported_samples != expected_samples
        or reported_augmentations != expected_augmentations
    ):
        raise RuntimeError(
            "DEBUG físico H1 não pertence ao mesmo lote de calibração "
            "do artefato atual."
        )

    reported_hash = str(
        model_status.get("onnx_sha256") or ""
    ).strip().lower()
    expected_hash = str(metadata.get("onnx_sha256") or "").strip().lower()
    if reported_hash and reported_hash != expected_hash:
        raise RuntimeError(
            "DEBUG físico H1 pertence a outro ONNX."
        )


def _physical_summary(
    frames: list[dict],
    *,
    project_name: str,
    validation_check_id: str,
    model_sha256: str,
    minimum_frames: int,
) -> dict:
    unique: dict[str, dict] = {}
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        frame_hash = str(frame.get("frame_hash") or "").strip()
        if frame_hash:
            unique[frame_hash] = deepcopy(frame)

    ordered = list(unique.values())
    if len(ordered) < int(minimum_frames):
        raise RuntimeError(
            "Calibração física H1 exige ao menos "
            f"{int(minimum_frames)} frames congelados únicos; "
            f"recebidos={len(ordered)}."
        )

    off_rows: list[dict] = []
    on_rows: list[dict] = []
    for frame in ordered:
        for item in frame.get("masks") or ():
            state = str(item.get("state") or "").strip().lower()
            row = {
                "frame_hash": str(frame.get("frame_hash") or ""),
                "captured_at": str(frame.get("captured_at") or ""),
                "mask_id": str(item.get("mask_id") or ""),
                "state": state,
                "p_on": float(item.get("p_on")),
            }
            if state == DISPLAY_CHECK_STATE_OFF:
                off_rows.append(row)
            elif state == DISPLAY_CHECK_STATE_ON:
                on_rows.append(row)

    if not off_rows or not on_rows:
        raise RuntimeError(
            "Calibração física H1 exige exemplos físicos ON e OFF."
        )

    worst_off = max(off_rows, key=lambda item: float(item["p_on"]))
    worst_on = min(on_rows, key=lambda item: float(item["p_on"]))
    max_off = float(worst_off["p_on"])
    min_on = float(worst_on["p_on"])
    gap = float(min_on - max_off)
    if not np.isfinite(gap) or gap <= 0.0:
        raise RuntimeError(
            "Frames físicos H1 não separam OFF/ON: "
            f"max_OFF_P(ON)={max_off:.6f}, "
            f"min_ON_P(ON)={min_on:.6f}."
        )

    return {
        "source": "f3_debug_technical_frozen_frames",
        "separable": True,
        "project_name": str(project_name),
        "validation_check_id": str(validation_check_id),
        "model_sha256": str(model_sha256 or "").strip().lower(),
        "minimum_frame_count": int(minimum_frames),
        "frame_count": len(ordered),
        "frame_hashes": [
            str(frame.get("frame_hash") or "")
            for frame in ordered
        ],
        "sample_count": len(off_rows) + len(on_rows),
        "class_counts": {
            "off": len(off_rows),
            "on": len(on_rows),
        },
        "max_off_on_probability": max_off,
        "min_on_on_probability": min_on,
        "uncertainty_gap": gap,
        "worst_off": worst_off,
        "worst_on": worst_on,
        "frames": ordered,
    }


def collect_physical_h1_debug_calibration(
    debug_paths,
    *,
    repository,
    project_name: str,
    validation_check_id: str,
    metadata: dict,
    minimum_frames: int = F3_NEURAL_MIN_PHYSICAL_H1_CALIBRATION_FRAMES,
) -> dict:
    """Valida DEBUGs físicos e retorna extremos ON/OFF de frames H1 únicos."""
    base_calibration = _base_augmented_calibration(metadata)
    expected_states = _expected_h1_states(
        repository,
        project_name,
        validation_check_id,
    )
    current_calibration = (
        metadata.get("threshold_calibration")
        if isinstance(metadata.get("threshold_calibration"), dict)
        else {}
    )

    frames_by_hash: dict[str, dict] = {}
    if (
        str(current_calibration.get("source") or "").strip()
        == F3_NEURAL_PHYSICAL_THRESHOLD_CALIBRATION_SOURCE
    ):
        existing = current_calibration.get("physical_h1")
        if isinstance(existing, dict):
            for frame in existing.get("frames") or ():
                if not isinstance(frame, dict):
                    continue
                frame_hash = str(frame.get("frame_hash") or "").strip()
                if frame_hash:
                    frames_by_hash[frame_hash] = deepcopy(frame)

    accepted_new = 0
    for raw_path in debug_paths:
        path = Path(raw_path)
        if not path.is_file():
            raise RuntimeError(
                f"Arquivo DEBUG físico H1 não encontrado: {path}"
            )
        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
        for snapshot in parse_physical_h1_debug_text(
            text,
            source_name=str(path),
        ):
            analysis = snapshot.get("analysis")
            if not isinstance(analysis, dict):
                continue
            if str(analysis.get("check_id") or "").strip() != str(
                validation_check_id
            ):
                continue
            if str(analysis.get("project_name") or "").strip() != str(
                project_name
            ):
                raise RuntimeError(
                    "DEBUG físico H1 pertence a outro Projeto Display."
                )
            if (
                analysis.get("ready") is not True
                or analysis.get("neural_visual_authority") is not True
                or str(analysis.get("reference_authority") or "").strip()
                != F3_NEURAL_H1_AUTHORITY
                or analysis.get("conventional_visual_authority_used") is True
            ):
                raise RuntimeError(
                    "Snapshot H1 não foi produzido pela autoridade neural "
                    "exclusiva."
                )

            _validate_debug_model(
                model_status=analysis.get("neural_model") or {},
                metadata=metadata,
                base_calibration=base_calibration,
                project_name=project_name,
            )

            rows: list[dict] = []
            seen: set[str] = set()
            for item in analysis.get("mask_results") or ():
                if not isinstance(item, dict):
                    continue
                mask_id = str(item.get("mask_id") or "").strip()
                if not mask_id or mask_id in seen:
                    raise RuntimeError(
                        "DEBUG físico H1 possui ID de máscara vazio/duplicado."
                    )
                seen.add(mask_id)
                expected = str(item.get("expected") or "").strip().lower()
                configured = expected_states.get(mask_id)
                if configured is None or expected != configured:
                    raise RuntimeError(
                        "DEBUG físico H1 não corresponde ao gabarito atual: "
                        f"{mask_id}."
                    )
                probabilities = item.get("neural_probabilities")
                if not isinstance(probabilities, dict):
                    raise RuntimeError(
                        f"DEBUG físico H1 sem probabilidades para {mask_id}."
                    )
                try:
                    p_on = float(probabilities.get("on"))
                except (TypeError, ValueError):
                    p_on = float("nan")
                if not np.isfinite(p_on) or p_on < 0.0 or p_on > 1.0:
                    raise RuntimeError(
                        f"P(ON) físico inválido para {mask_id}."
                    )
                rows.append(
                    {
                        "mask_id": mask_id,
                        "state": configured,
                        "p_on": p_on,
                    }
                )

            if seen != set(expected_states):
                missing = sorted(set(expected_states) - seen)
                extra = sorted(seen - set(expected_states))
                raise RuntimeError(
                    "DEBUG físico H1 não contém exatamente as máscaras "
                    f"reservadas. missing={missing}, extra={extra}"
                )

            frame_hash = str(snapshot.get("frame_hash") or "").strip()
            if frame_hash in frames_by_hash:
                continue
            frames_by_hash[frame_hash] = {
                "frame_hash": frame_hash,
                "captured_at": str(snapshot.get("captured_at") or ""),
                "source_file": str(snapshot.get("source_file") or ""),
                "analysis_approved_before_recalibration": bool(
                    analysis.get("approved") is True
                ),
                "analysis_reason_before_recalibration": str(
                    analysis.get("reason") or ""
                ),
                "masks": rows,
            }
            accepted_new += 1

    if accepted_new <= 0 and not frames_by_hash:
        raise RuntimeError(
            "Nenhum snapshot neural H1 válido foi encontrado nos DEBUGs."
        )

    return _physical_summary(
        list(frames_by_hash.values()),
        project_name=project_name,
        validation_check_id=validation_check_id,
        model_sha256=str(metadata.get("onnx_sha256") or ""),
        minimum_frames=minimum_frames,
    )


def combine_augmented_and_physical_calibration(
    base_calibration: dict,
    physical_h1: dict,
) -> dict:
    """Combina extremos de forma conservadora; não usa midpoint manual."""
    if (
        str(base_calibration.get("source") or "").strip()
        != F3_NEURAL_THRESHOLD_CALIBRATION_SOURCE
        or base_calibration.get("separable") is not True
    ):
        raise RuntimeError(
            "Calibração aumentada de base inválida para combinação física."
        )
    if physical_h1.get("separable") is not True:
        raise RuntimeError(
            "Calibração física H1 não é separável."
        )

    base_max_off = float(base_calibration["max_off_on_probability"])
    base_min_on = float(base_calibration["min_on_on_probability"])
    physical_max_off = float(physical_h1["max_off_on_probability"])
    physical_min_on = float(physical_h1["min_on_on_probability"])

    max_off = max(base_max_off, physical_max_off)
    min_on = min(base_min_on, physical_min_on)
    gap = float(min_on - max_off)
    if not np.isfinite(gap) or gap <= 0.0:
        raise RuntimeError(
            "Calibração combinada H1 não separa OFF/ON: "
            f"max_OFF_P(ON)={max_off:.6f}, "
            f"min_ON_P(ON)={min_on:.6f}."
        )

    base_counts = base_calibration.get("class_counts") or {}
    physical_counts = physical_h1.get("class_counts") or {}
    class_counts = {
        "off": int(base_counts.get("off", 0) or 0)
        + int(physical_counts.get("off", 0) or 0),
        "on": int(base_counts.get("on", 0) or 0)
        + int(physical_counts.get("on", 0) or 0),
    }
    off_threshold = float(
        np.nextafter(np.float64(max_off), np.float64(1.0))
    )
    on_threshold = float(
        np.nextafter(np.float64(min_on), np.float64(0.0))
    )
    if off_threshold >= on_threshold:
        raise RuntimeError(
            "Gap físico H1 insuficiente após proteção numérica."
        )

    return {
        "source": F3_NEURAL_PHYSICAL_THRESHOLD_CALIBRATION_SOURCE,
        "separable": True,
        "reference_sample_count": int(
            base_calibration.get("reference_sample_count", 0) or 0
        ),
        "augmentations_per_reference": int(
            base_calibration.get("augmentations_per_reference", 0) or 0
        ),
        "sample_count": int(base_calibration.get("sample_count", 0) or 0)
        + int(physical_h1.get("sample_count", 0) or 0),
        "class_counts": class_counts,
        "max_off_on_probability": max_off,
        "min_on_on_probability": min_on,
        "uncertainty_gap": gap,
        "off_max_on_probability": off_threshold,
        "on_min_on_probability": on_threshold,
        "base_augmented_calibration": deepcopy(base_calibration),
        "physical_h1": deepcopy(physical_h1),
    }


def recalibrate_physical_h1_thresholds(
    *,
    repository,
    project_name: str,
    model_path: Path,
    debug_paths,
) -> dict:
    """Atualiza apenas o metadata do ONNX usando >=5 frames físicos H1."""
    model_path = Path(model_path)
    metadata_path = model_path.with_suffix(".json")
    if not model_path.is_file() or not metadata_path.is_file():
        raise RuntimeError(
            "Recalibração física H1 exige ONNX e metadata schema 3 já "
            "promovidos pelo treino neural."
        )

    metadata = _read_metadata(metadata_path)
    try:
        schema = int(metadata.get("schema_version", 0) or 0)
    except (TypeError, ValueError):
        schema = 0
    if schema != F3_NEURAL_MODEL_METADATA_SCHEMA_VERSION:
        raise RuntimeError(
            "Recalibração física H1 exige metadata neural schema 3."
        )
    if str(metadata.get("project_name") or "").strip() != str(project_name):
        raise RuntimeError(
            "ONNX/metadata pertencem a outro Projeto Display."
        )
    if str(metadata.get("model_type") or "").strip() != F3_NEURAL_MODEL_TYPE:
        raise RuntimeError("Tipo de modelo neural incompatível.")

    declared_hash = str(metadata.get("onnx_sha256") or "").strip().lower()
    actual_hash = _sha256_file(model_path).lower()
    if not declared_hash or declared_hash != actual_hash:
        raise RuntimeError(
            "ONNX atual não corresponde ao SHA-256 declarado no metadata."
        )

    split = (
        metadata.get("split")
        if isinstance(metadata.get("split"), dict)
        else {}
    )
    validation_check_id = str(
        split.get("validation_check_id") or ""
    ).strip()
    if (
        str(split.get("strategy") or "")
        != "hold_out_first_check_for_n1"
        or not validation_check_id
    ):
        raise RuntimeError(
            "Metadata não preserva o H1 como CHECK reservado."
        )

    calibration = (
        metadata.get("threshold_calibration")
        if isinstance(metadata.get("threshold_calibration"), dict)
        else {}
    )
    current_source = str(calibration.get("source") or "").strip()
    if current_source not in F3_NEURAL_THRESHOLD_CALIBRATION_SOURCES:
        raise RuntimeError(
            "Origem da calibração atual não é compatível com N1."
        )

    base_calibration = _base_augmented_calibration(metadata)
    physical_h1 = collect_physical_h1_debug_calibration(
        debug_paths,
        repository=repository,
        project_name=project_name,
        validation_check_id=validation_check_id,
        metadata=metadata,
    )
    combined = combine_augmented_and_physical_calibration(
        base_calibration,
        physical_h1,
    )

    diagnostics_path = (
        model_path.parent
        / "diagnostics"
        / f"{model_path.stem}_physical_h1_calibration_latest.json"
    )
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "purpose": "f3_neural_h1_physical_multiframe_calibration",
                "base_augmented_calibration": base_calibration,
                "physical_h1": physical_h1,
                "combined_threshold_calibration": combined,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    updated = deepcopy(metadata)
    updated["suggested_thresholds"] = {
        "off_max_on_probability": combined["off_max_on_probability"],
        "on_min_on_probability": combined["on_min_on_probability"],
    }
    updated["threshold_calibration"] = combined
    validation = (
        deepcopy(updated.get("validation"))
        if isinstance(updated.get("validation"), dict)
        else {}
    )
    validation["physical_h1_multiframe_calibration"] = {
        "accepted": True,
        "frame_count": int(physical_h1["frame_count"]),
        "sample_count": int(physical_h1["sample_count"]),
        "max_off_on_probability": float(
            physical_h1["max_off_on_probability"]
        ),
        "min_on_on_probability": float(
            physical_h1["min_on_on_probability"]
        ),
        "uncertainty_gap": float(physical_h1["uncertainty_gap"]),
        "diagnostics_path": str(diagnostics_path),
        "frames_are_calibration_not_retest_holdout": True,
    }
    updated["validation"] = validation
    updated["note"] = (
        "H1 permaneceu integralmente fora da otimização. A faixa "
        "OFF/INCERTO/ON combina o H1 reservado aumentado com pelo menos "
        "cinco frames físicos congelados H1. Esses frames físicos são dados "
        "de calibração e não contam como reteste independente posterior."
    )

    staging_metadata = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f"{metadata_path.stem}.physical-calibration.",
            suffix=".candidate.json",
            dir=str(metadata_path.parent),
            delete=False,
            mode="w",
            encoding="utf-8",
        ) as handle:
            staging_metadata = Path(handle.name)
            json.dump(
                updated,
                handle,
                indent=2,
                ensure_ascii=False,
            )
        staging_metadata.replace(metadata_path)
        staging_metadata = None
    finally:
        if isinstance(staging_metadata, Path):
            try:
                staging_metadata.unlink(missing_ok=True)
            except OSError:
                pass

    return {
        "metadata": updated,
        "model_path": str(model_path),
        "metadata_path": str(metadata_path),
        "diagnostics_path": str(diagnostics_path),
        "physical_h1": physical_h1,
        "threshold_calibration": combined,
    }
