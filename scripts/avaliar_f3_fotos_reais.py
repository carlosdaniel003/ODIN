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
from contextlib import contextmanager
from copy import deepcopy
from math import ceil
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

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



@contextmanager
def staged_private_assets(archive: Path):
    """Monta ZIP local em diretório temporário, sem versionar ativos privados."""
    with TemporaryDirectory(prefix="f3-snapshot-offline-") as workdir:
        root = Path(workdir)
        source_prefix = "enviar/"
        required = (
            "odin_display_projects.json",
            "odin_display_check_presence.json",
            "cm_500_l_segments.onnx",
            "cm_500_l_segments.json",
        )
        with ZipFile(archive) as package:
            names = set(package.namelist())
            for item in required:
                if source_prefix + item not in names:
                    raise ValueError(f"ZIP sem ativo obrigatorio: {item}")
            (root / "display_check_presence").mkdir()
            (root / "models" / "f3_neural").mkdir(parents=True)
            (root / "odin_display_projects.json").write_bytes(
                package.read(source_prefix + "odin_display_projects.json")
            )
            for suffix in (".onnx", ".json"):
                (root / "models" / "f3_neural" / ("cm_500_l_segments" + suffix)).write_bytes(
                    package.read(source_prefix + "cm_500_l_segments" + suffix)
                )
            references = json.loads(
                package.read(source_prefix + "odin_display_check_presence.json")
            )
            for row in (references.get("references") or {}).values():
                if not isinstance(row, dict):
                    continue
                filename = Path(
                    str(row.get("image_path") or "").replace("\\", "/")
                ).name
                path_in_zip = source_prefix + "display_check_presence/" + filename
                if filename and path_in_zip in names:
                    dest = root / "display_check_presence" / filename
                    dest.write_bytes(package.read(path_in_zip))
                    row["image_path"] = str(dest)
            (root / "odin_display_check_presence.json").write_text(
                json.dumps(references, ensure_ascii=False), encoding="utf-8"
            )
        yield root / "odin_display_projects.json"


def _mask_map_for_orientation(project: dict, image_shape: tuple, degrees: int):
    """Converte geometria canônica para a orientação da FOTO, sem girá-la."""
    from src.platform.display_mask_geometry import (
        converter_mascara_legada_para_editor,
        pontos_mascara_display,
    )

    height, width = image_shape[:2]
    masks = []
    for original in project.get("masks") or ():
        mask = converter_mascara_legada_para_editor(deepcopy(original))
        if degrees == 180:
            if str(mask.get("type") or "") == "circle":
                mask["cx"] = width - 1 - float(mask["cx"])
                mask["cy"] = height - 1 - float(mask["cy"])
            else:
                points = pontos_mascara_display(mask)
                mask = {
                    "id": mask["id"],
                    "type": "polygon",
                    "points": [[width - 1 - float(x), height - 1 - float(y)]
                               for x, y in points],
                }
        masks.append(mask)
    return masks


def _draw_mask_reduced(target, mask: dict, reduction: int) -> None:
    """Rasterização com OpenCV, exclusiva do teste offline."""
    from src.platform.display_mask_geometry import pontos_mascara_display

    if str(mask.get("type") or "") == "circle":
        cv2.circle(
            target,
            (int(round(float(mask["cx"]) / reduction)),
             int(round(float(mask["cy"]) / reduction))),
            max(1, int(round(float(mask["radius"]) / reduction))),
            255, -1,
        )
    else:
        points = pontos_mascara_display(mask)
        if len(points) >= 3:
            polygon = np.rint(
                np.asarray(points, dtype=np.float32) / reduction
            ).astype(np.int32)
            cv2.fillPoly(target, [polygon], 255)


def _apply_translation_to_masks(masks: list[dict], dx: float, dy: float) -> list[dict]:
    translated = deepcopy(masks)
    from src.platform.display_mask_geometry import pontos_mascara_display
    for mask in translated:
        if str(mask.get("type") or "") == "circle":
            mask["cx"] = float(mask["cx"]) + dx
            mask["cy"] = float(mask["cy"]) + dy
        else:
            points = pontos_mascara_display(mask)
            mask["type"] = "polygon"
            mask["points"] = [
                [float(x) + dx, float(y) + dy] for x, y in points
            ]
    return translated


def estimate_snapshot_geometry(
    image: np.ndarray, project: dict, check: dict, *,
    orientations: tuple[int, ...] = (0, 180),
    reduction: int = 4,
) -> tuple[list[dict] | None, dict]:
    """Hipótese de pose por luz: apenas diagnóstico OFFLINE, nunca autoridade.

    Procura translação no espaço do PNG e testa orientação DAS MÁSCARAS,
    não gira imagem. O score usa todas as máscaras, ON positivo e OFF
    negativo, para reduzir encaixe artificial no padrão esperado. Uma
    segmentação NG pode perder um ON: não exige presença de 100% das luzes.
    """
    if image is None or image.ndim != 3 or reduction < 1:
        return None, {"status": "BLOCKED", "reason": "invalid_photo"}
    h, w = image.shape[:2]
    size = (w // reduction, h // reduction)
    value = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 2]
    lowres = cv2.resize(value, size, interpolation=cv2.INTER_AREA)
    emission = np.clip((lowres.astype(np.float32) - 155.0) / 90.0, 0.0, 1.0)
    states = check.get("mask_states") or {}
    observations = []
    for degrees in orientations:
        masks = _mask_map_for_orientation(project, image.shape, degrees)
        on_full = np.zeros((size[1], size[0]), dtype=np.uint8)
        off_full = np.zeros_like(on_full)
        on_count = 0
        for mask in masks:
            state = states.get(str(mask.get("id") or ""))
            if state == "on":
                _draw_mask_reduced(on_full, mask, reduction)
                on_count += 1
            elif state == "off":
                _draw_mask_reduced(off_full, mask, reduction)
        combined = cv2.bitwise_or(on_full, off_full)
        ys, xs = np.nonzero(combined)
        if not len(xs) or on_count < 3:
            continue
        x1, x2 = int(xs.min()), int(xs.max()) + 1
        y1, y2 = int(ys.min()), int(ys.max()) + 1
        on = on_full[y1:y2, x1:x2].astype(np.float32) / 255.0
        off = off_full[y1:y2, x1:x2].astype(np.float32) / 255.0
        if on.shape[1] > size[0] or on.shape[0] > size[1]:
            continue
        on_scores = cv2.matchTemplate(emission, on, cv2.TM_CCORR) / max(
            1.0, float(on.sum())
        )
        off_scores = cv2.matchTemplate(emission, off, cv2.TM_CCORR) / max(
            1.0, float(off.sum())
        )
        objective = on_scores - 0.40 * off_scores
        row, col = np.unravel_index(int(np.argmax(objective)), objective.shape)
        on_value = float(on_scores[row, col])
        off_value = float(off_scores[row, col])
        dx = float((int(col) - x1) * reduction)
        dy = float((int(row) - y1) * reduction)
        observations.append({
            "orientation_masks_degrees": degrees,
            "shift_px": [dx, dy],
            "score": float(objective[row, col]),
            "mean_expected_on": on_value,
            "mean_expected_off": off_value,
            "masks": masks,
            "on_count": on_count,
        })
    observations.sort(key=lambda row: row["score"], reverse=True)
    if not observations:
        return None, {"status": "BLOCKED", "reason": "no_luminous_geometry"}
    best = observations[0]
    margin = (
        best["score"] - observations[1]["score"]
        if len(observations) > 1 else None
    )
    # Só medições suficientemente separáveis são reportadas como
    # pose preliminar; todos os demais casos falham fechados.
    sufficient = (
        best["mean_expected_on"] >= 0.65
        and best["mean_expected_on"] - best["mean_expected_off"] >= 0.40
        and best["score"] >= 0.50
    )
    # Outro giro parecido na mesma fotografia pode ser indistinguível.
    # Não fabricar pose determinada nesse cenário.
    ambiguous = bool(margin is not None and margin < 0.04)
    report = {
        "status": "DIAGNOSTIC_ONLY" if sufficient and not ambiguous else "BLOCKED",
        "reason": ("estimated_luminous_translation" if sufficient and not ambiguous
                   else "ambiguous_orientation" if ambiguous
                   else "insufficient_luminous_support"),
        "orientation_masks_degrees": best["orientation_masks_degrees"],
        "additional_photo_rotation_degrees": 0,
        "translation_px": best["shift_px"],
        "on_brightness": round(best["mean_expected_on"], 5),
        "off_brightness": round(best["mean_expected_off"], 5),
        "objective": round(best["score"], 5),
        "orientation_margin": None if margin is None else round(margin, 5),
        "method": "expected_state_luminous_correlation_offline_only",
        "warning": "Pose estimada pelas luzes esperadas; NG nao pode ser aprovado por ela",
    }
    if report["status"] == "BLOCKED":
        return None, report
    masks = _apply_translation_to_masks(
        best["masks"], best["shift_px"][0], best["shift_px"][1]
    )
    return masks, report


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


def summarize_hybrid_snapshot_evidence(mask_results: list[dict]) -> dict:
    """Exibe o motivo do bloqueio sem criar uma segunda decisão OK/NG.

    A fonte de verdade continua sendo o F3HybridCheckAnalyzer. O relatório
    registra somente metadados já calculados (sem ROIs, imagens ou pesos).
    """
    reasons = {}
    blockers = {}
    details = []
    for item in mask_results:
        mask_id = str(item.get("mask_id") or "")
        resolution = str(item.get("hybrid_resolution") or "unknown")
        reasons[resolution] = reasons.get(resolution, 0) + 1
        core = item.get("physical_core_emission")
        if not isinstance(core, dict):
            core = {}
        neural_probabilities = item.get("neural_probabilities")
        if not isinstance(neural_probabilities, dict):
            neural_probabilities = {}
        detail = {
            "mask_id": mask_id,
            "expected": item.get("expected"),
            "classified": item.get("classified"),
            "matched": item.get("matched"),
            "semantic_certain": item.get("semantic_certain") is True,
            "hybrid_resolution": resolution,
            "neural_classified": item.get("neural_classified"),
            "neural_certain": item.get("neural_certain"),
            "neural_confidence": item.get("neural_confidence"),
            "neural_probabilities": {
                key: neural_probabilities.get(key)
                for key in ("on", "off")
                if key in neural_probabilities
            },
            "physical_classified": item.get("physical_classified"),
            "physical_confidence": item.get("physical_confidence"),
            "physical_reference_source": item.get("physical_reference_source"),
            "physical_reference_separation": item.get("physical_reference_separation"),
            "physical_local_authoritative": item.get("physical_local_authoritative"),
            "physical_disagreed_with_core": item.get("physical_disagreed_with_core"),
            "physical_core_emission": {
                key: core.get(key)
                for key in (
                    "state", "reason", "current_inner_v_mean",
                    "off_reference_ceiling", "on_reference_floor",
                    "reference_on_count", "reference_off_count",
                )
                if key in core
            },
            "calibrated_physical_over_weak_neural": item.get(
                "calibrated_physical_over_weak_neural"
            ),
        }
        details.append(detail)
        if item.get("semantic_certain") is not True:
            blockers[mask_id] = {
                "hybrid_resolution": resolution,
                "neural_classified": detail["neural_classified"],
                "physical_classified": detail["physical_classified"],
                "physical_reference_source": detail["physical_reference_source"],
                "physical_local_authoritative": detail["physical_local_authoritative"],
                "core_state": detail["physical_core_emission"].get("state"),
                "core_reason": detail["physical_core_emission"].get("reason"),
            }
    return {
        "hybrid_resolution_counts": dict(sorted(reasons.items())),
        "unresolved_mask_evidence": blockers,
        "mask_details": details,
    }


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
        **summarize_hybrid_snapshot_evidence(masks_result),
    }


def evaluate_snapshots(
    *,
    manifest_path: Path = MANIFEST_PATH,
    project_config: Path | None = None,
    geometry_dir: Path | None = None,
    estimate_geometry: bool = False,
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
        else:
            if geometry_dir is not None:
                masks, geometry_error = _geometry_for_snapshot(
                    geometry_dir, case["filename"], image.shape
                )
                record["geometry"] = {
                    "status": "VALIDATED_INPUT" if not geometry_error else "BLOCKED",
                    "reason": geometry_error,
                }
            elif estimate_geometry:
                project = repository.carregar_projeto("CM_500_L") or {}
                check = next(
                    (item for item in repository.listar_checks("CM_500_L")
                     if str(item.get("name") or "").upper() == case["check"]),
                    None,
                )
                masks, estimation = (
                    estimate_snapshot_geometry(image, project, check)
                    if isinstance(check, dict)
                    else (None, {"status": "BLOCKED", "reason": "check_not_configured"})
                )
                record["geometry"] = estimation
                geometry_error = (
                    "" if masks is not None
                    else str(estimation.get("reason") or "geometry_not_estimated")
                )
            else:
                masks, geometry_error = None, "tracked_geometry_missing"
            if geometry_error:
                record["semantic_replay"] = {
                    "status": "BLOCKED", "reason": geometry_error
                }
            else:
                record["semantic_replay"] = _semantic_replay(
                    analyzer, repository, image, case, masks
                )
                if estimate_geometry and geometry_dir is None:
                    predicted = record["semantic_replay"]
                    predicted["status"] = (
                        "PROVISIONAL_" + str(predicted["status"])
                    )
                    predicted["warning"] = (
                        "Diagnostico sobre pose estimada. Nao valida OK/NG produtivo."
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
    parser.add_argument("--asset-zip", type=Path,
                        help="ZIP privado enviar.zip; usado apenas em pasta temporaria")
    parser.add_argument("--estimate-geometry", action="store_true",
                        help="Somente diagnostico de pose luminosa, nunca prova OK/NG")
    parser.add_argument("--geometry-dir", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.asset_zip:
        with staged_private_assets(args.asset_zip) as staged:
            data = evaluate_snapshots(
                manifest_path=args.manifest,
                project_config=staged,
                geometry_dir=args.geometry_dir,
                estimate_geometry=args.estimate_geometry,
            )
    else:
        data = evaluate_snapshots(
            manifest_path=args.manifest,
            project_config=args.project_config,
            geometry_dir=args.geometry_dir,
            estimate_geometry=args.estimate_geometry,
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
