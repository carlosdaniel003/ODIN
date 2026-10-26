#!/usr/bin/env python3
"""Auditoria offline F3 de snapshots físicos (sem tocar a produção).

A fase sem projeto/modelo/geometria executa apenas diagnósticos FÍSICOS
sobre pixels reais, nunca gera OK/NG de produção. Um replay semântico
requer os três recursos locais e trata cada fotografia como snapshot
já rotacionado em 180 graus, sem aplicar rotação adicional.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "display_f3" / "CM_500_L"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"


def read_manifest(path: Path = MANIFEST_PATH) -> dict:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("schema_version de fixtures F3 desconhecido")
    if document.get("project_name") != "CM_500_L":
        raise ValueError("projeto F3 do acervo incorreto")
    orientation = document.get("orientation") or {}
    if (
        orientation.get("already_applied_rotation_degrees") != 180
        or orientation.get("additional_rotation_degrees_for_replay") != 0
    ):
        raise ValueError("fotografias fisicas ja rotacionadas: nao aplicar 180 novamente")
    return document


def load_snapshot(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"PNG F3 ilegivel: {path}")
    return image


def image_diagnostics(path: Path, image: np.ndarray) -> dict:
    channel_v = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 2]
    illuminated = channel_v >= 200
    ys, xs = np.nonzero(illuminated)
    if xs.size:
        bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
        center = [round(float(xs.mean()), 2), round(float(ys.mean()), 2)]
    else:
        bbox, center = None, None
    return {
        "file": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "width": int(image.shape[1]),
        "height": int(image.shape[0]),
        "channels": 3,
        "mean_value": round(float(channel_v.mean()), 4),
        "max_value": int(channel_v.max()),
        "pixels_v_ge_200": int(illuminated.sum()),
        "luminous_bbox": bbox,
        "luminous_center": center,
    }


def blue_pair_diagnostics(blue_ok: np.ndarray, blue_ng: np.ndarray) -> dict:
    """Comparação VISUAL diagnóstica: não identifica MASK_024 nem decide NG."""
    if blue_ok.shape != blue_ng.shape:
        return {"status": "DIFFERENT_RESOLUTION"}
    # Trabalho leve, resolução 1/4 e uma única estimativa de translação.
    def bright(image: np.ndarray) -> np.ndarray:
        value = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 2]
        shrunk = cv2.resize(
            value, (image.shape[1] // 4, image.shape[0] // 4),
            interpolation=cv2.INTER_AREA,
        )
        mask = np.clip((shrunk.astype(np.float32) - 150.0) / 70.0, 0.0, 1.0)
        return cv2.GaussianBlur(mask, (5, 5), 0)

    ok = bright(blue_ok)
    ng = bright(blue_ng)
    (shift_x, shift_y), response = cv2.phaseCorrelate(ok, ng)
    warp = np.float32([[1.0, 0.0, -shift_x], [0.0, 1.0, -shift_y]])
    registered_ng = cv2.warpAffine(
        ng, warp, (ok.shape[1], ok.shape[0]),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
    )
    # Uma comparação entre PNGs OK/NG não prova qual máscara falhou.
    missing = np.clip(ok - registered_ng, 0.0, 1.0)
    extra = np.clip(registered_ng - ok, 0.0, 1.0)
    return {
        "status": "DIAGNOSTIC_ONLY",
        "method": "phase_correlation_bright_v_quarter_resolution",
        "shift_ng_relative_to_ok_px": [
            round(float(shift_x * 4), 3), round(float(shift_y * 4), 3)
        ],
        "registration_response": round(float(response), 5),
        "missing_brightness_sum": round(float(missing.sum()), 3),
        "extra_brightness_sum": round(float(extra.sum()), 3),
        "mean_absolute_brightness_difference": round(
            float(np.abs(ok - registered_ng).mean()), 6
        ),
        "note": "Diferencas luminosas nao sao classificacao de MASK_024 nem prova OK/NG",
    }


def _geometry_for_snapshot(directory: Path, filename: str, shape: tuple) -> tuple:
    candidate = directory / f"{Path(filename).stem}.json"
    if not candidate.is_file():
        return None, f"geometry_missing:{candidate.name}"
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    masks = payload.get("masks")
    size = payload.get("frame_resolution")
    if (
        not isinstance(masks, list)
        or len(masks) != 30
        or not isinstance(size, list)
        or size != [int(shape[1]), int(shape[0])]
    ):
        return None, "geometry_incomplete_or_wrong_resolution"
    ids = [str(mask.get("id") or "") for mask in masks if isinstance(mask, dict)]
    if len(set(ids)) != 30 or not all(ids):
        return None, "geometry_duplicate_or_missing_mask_ids"
    return masks, ""


def _prepare_semantic_replay(config_path: Path | None) -> tuple:
    if config_path is None or not config_path.is_file():
        return None, None, "display_project_config_missing"
    from src.platform.display_project_repository import DisplayProjectRepository
    from src.platform.display_f3_neural_dataset import f3_neural_model_path_for_repository
    from src.platform.display_f3_neural_runtime import F3HybridCheckAnalyzer
    repository = DisplayProjectRepository(config_path)
    if repository.carregar_projeto("CM_500_L") is None:
        return None, None, "CM_500_L_missing_from_display_project_config"
    model_path = f3_neural_model_path_for_repository(repository, "CM_500_L")
    if not model_path.is_file() or not model_path.with_suffix(".json").is_file():
        return None, None, "trained_cnn_and_metadata_missing"
    # A autoridade híbrida compara as fotografias reais de treinamento
    # da mesma MASK_ID. Não fazer um replay CNN-only por falta desses
    # ativos e chamá-lo de validação da mesma autoridade de produção.
    from src.platform.display_check_presence_reference import (
        DisplayCheckPresenceReferenceStore,
    )
    reference_store = DisplayCheckPresenceReferenceStore(repository)
    checks = {
        str(item.get("name") or "").upper(): str(item.get("id") or "")
        for item in repository.listar_checks("CM_500_L")
    }
    for name in ("H1", "BLUE", "USB", "FM", "AUX"):
        check_id = checks.get(name)
        if not check_id:
            return None, None, f"check_missing:{name}"
        metadata = reference_store.get("CM_500_L", check_id) or {}
        if not Path(str(metadata.get("image_path") or "")).is_file():
            return None, None, f"check_reference_photo_missing:{name}"
    return repository, F3HybridCheckAnalyzer(repository), ""


def _semantic_replay(analyzer, repository, image, case: dict, masks: list) -> dict:
    checks = repository.listar_checks("CM_500_L")
    match = next(
        (row for row in checks if str(row.get("name") or "").upper() == case["check"]),
        None,
    )
    if match is None:
        return {"status": "BLOCKED", "reason": "check_not_configured"}
    # Os PNGs foram rotacionados pelo operador: visual_rotation=0.
    # Geometria obrigatoriamente na mesma orientacao e dimensoes do PNG.
    result = analyzer.analyze(
        image, "CM_500_L", str(match["id"]),
        visual_rotation=0,
        mask_geometry_override=masks,
        mask_geometry_resolution=(image.shape[1], image.shape[0]),
        mask_geometry_source="f3_offline_snapshot_geometry",
    )
    if result.get("ready") is not True:
        return {"status": "BLOCKED", "reason": result.get("reason")}
    masks_result = result.get("mask_results") or []
    incorrect = [
        row.get("mask_id") for row in masks_result
        if row.get("matched") is False and row.get("semantic_certain") is True
    ]
    uncertain = [
        row.get("mask_id") for row in masks_result
        if row.get("semantic_certain") is not True
    ]
    observed = (
        "INCERTO" if uncertain else
        "OK" if result.get("approved") is True else "NG"
    )
    expected = case["ground_truth"]
    failing_ids = set(case.get("failed_mask_ids") or ())
    pass_label = observed == expected and (
        expected != "NG" or failing_ids.issubset(set(incorrect))
    )
    return {
        "status": "PASS" if pass_label else "FAIL",
        "mode": "SEMANTIC_SNAPSHOT_ONLY",
        "note": "Nao representa gate fisico nem temporizacao/NG do runtime produtivo",
        "expected": expected,
        "observed": observed,
        "matched_mask_count": result.get("matched_mask_count"),
        "active_mask_count": result.get("active_mask_count"),
        "uncertain_mask_ids": uncertain,
        "incorrect_mask_ids": incorrect,
        "mask_details": [
            {
                "mask_id": row.get("mask_id"),
                "expected": row.get("expected"),
                "classified": row.get("classified"),
                "matched": row.get("matched"),
                "hybrid_resolution": row.get("hybrid_resolution"),
                "neural_confidence": row.get("neural_confidence"),
                "physical_confidence": row.get("physical_confidence"),
            } for row in masks_result
        ],
    }


def evaluate_snapshots(
    *,
    manifest_path: Path = MANIFEST_PATH,
    project_config: Path | None = None,
    geometry_dir: Path | None = None,
) -> dict:
    doc = read_manifest(manifest_path)
    folder = Path(manifest_path).parent
    repository, analyzer, blocker = _prepare_semantic_replay(project_config)
    results = []
    decoded = {}
    for case in doc["cases"]:
        path = folder / case["filename"]
        image = load_snapshot(path)
        decoded[case["filename"]] = image
        record = {
            "filename": case["filename"],
            "check": case["check"],
            "ground_truth": case["ground_truth"],
            "failed_mask_ids": case["failed_mask_ids"],
            "photo": image_diagnostics(path, image),
        }
        if blocker:
            record["semantic_replay"] = {"status": "BLOCKED", "reason": blocker}
        elif geometry_dir is None:
            record["semantic_replay"] = {
                "status": "BLOCKED", "reason": "tracked_geometry_missing"
            }
        else:
            masks, geometry_error = _geometry_for_snapshot(
                geometry_dir, case["filename"], image.shape
            )
            if geometry_error:
                record["semantic_replay"] = {
                    "status": "BLOCKED", "reason": geometry_error
                }
            else:
                record["semantic_replay"] = _semantic_replay(
                    analyzer, repository, image, case, masks
                )
        results.append(record)
    pair = blue_pair_diagnostics(
        decoded["BLUE_OK.png"], decoded["BLUE_NG_024.png"]
    )
    return {
        "schema_version": 1,
        "project_name": doc["project_name"],
        "additional_rotation_degrees": 0,
        "snapshot_count": len(results),
        "cases": results,
        "blue_ok_vs_ng": pair,
        "semantic_replay_status": (
            "BLOCKED" if any(
                record["semantic_replay"]["status"] == "BLOCKED"
                for record in results
            ) else "EXECUTED"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--project-config", type=Path)
    parser.add_argument("--geometry-dir", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    data = evaluate_snapshots(
        manifest_path=args.manifest,
        project_config=args.project_config,
        geometry_dir=args.geometry_dir,
    )
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
    print("F3 snapshots:", data["snapshot_count"])
    print("Orientação adicional:", data["additional_rotation_degrees"], "graus")
    for case in data["cases"]:
        photo = case["photo"]
        evaluation = case["semantic_replay"]
        print(
            f"{case['filename']}: {photo['width']}x{photo['height']} "
            f"V>=200 {photo['pixels_v_ge_200']} pixels; "
            f"replay={evaluation['status']} "
            f"({evaluation.get('reason', evaluation.get('observed', ''))})"
        )
    print("BLUE diferenciação:", data["blue_ok_vs_ng"])
    print("Replay semântico:", data["semantic_replay_status"])
    return int(
        data["semantic_replay_status"] == "EXECUTED"
        and any(case["semantic_replay"]["status"] != "PASS"
                for case in data["cases"])
    )


if __name__ == "__main__":
    raise SystemExit(main())
