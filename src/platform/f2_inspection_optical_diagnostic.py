from __future__ import annotations

"""Evidência óptica de inspeções concluídas no F2 com rastreamento ativo.

Usa somente o OperationResult e as PreparedLed que decidiram a inspeção.
Não reanalisa imagem, não classifica novamente e não altera OK/NG.
A coleta é limitada por sessão para não adicionar I/O ao ciclo contínuo.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path


F2_OPTICAL_TRACE_PATH = Path("data") / "logs" / "f2_inspection_optical_trace.jsonl"
F2_OPTICAL_TRACE_MAX_INSPECTIONS = 8


def _serializar_objeto_optico(value):
    converter = getattr(value, "to_dict", None)
    return converter() if callable(converter) else None


def registrar_diagnostico_optico_inspecao_f2(app, frame, result) -> bool:
    """Registra até oito inspeções F2 rastreadas, sempre após o julgamento.

    A autoridade de decisão é o OperationEngine: os resultados e geometrias
    registrados são os mesmos usados pelo classificador na inspeção oficial.
    """
    enabled = getattr(app, "_f2_tracking_enabled", None)
    if not callable(enabled):
        return False
    try:
        if not enabled():
            return False
    except Exception:
        return False

    count = int(getattr(app, "_f2_optical_trace_count", 0) or 0)
    if count >= F2_OPTICAL_TRACE_MAX_INSPECTIONS:
        return False
    app._f2_optical_trace_count = count + 1

    try:
        engine = getattr(app, "operacao_engine", None)
        classifier = getattr(engine, "_classifier", None)
        prepared = tuple(getattr(engine, "_prepared_leds", ()) or ())
        led_results = tuple(getattr(result, "results", ()) or ())
        cached = getattr(app, "_f2_tracking_analysis_raw_frame", None)
        matrix = getattr(
            getattr(app, "_f2_object_tracker", None),
            "last_matrix", None,
        )
        frame_shape = tuple(getattr(frame, "shape", ()) or ())
        cached_shape = tuple(getattr(cached, "shape", ()) or ())

        record = {
            "utc": datetime.now(timezone.utc).isoformat(),
            "inspection": count + 1,
            "frame_id": getattr(app, "camera_ultimo_frame_id", None),
            "tracking_frame_id": getattr(
                app, "_f2_tracking_analysis_frame_id", None,
            ),
            "frame_shape": frame_shape,
            "tracking_raw_shape": cached_shape,
            "tracking_status": getattr(
                app, "_f2_object_tracking_last_status", None,
            ),
            "tracking_method": getattr(
                getattr(app, "_f2_object_tracker", None),
                "_f2_tracking_last_method", None,
            ),
            "tracking_matrix": (
                matrix.tolist() if matrix is not None else None
            ),
            "tracking_override_depth": getattr(
                app, "_f2_tracking_analysis_override_depth", 0,
            ),
            "result_ok": bool(getattr(result, "ok", False)),
            "failed_led_ids": list(
                getattr(result, "failed_led_ids", ()) or (),
            ),
            "result_count": len(led_results),
            "prepared_count": len(prepared),
            "reference_on": _serializar_objeto_optico(
                getattr(classifier, "features_referencia_acesa", None),
            ),
            "reference_off": _serializar_objeto_optico(
                getattr(classifier, "features_referencia_apagada", None),
            ),
            "leds": [
                {
                    "result": _serializar_objeto_optico(item),
                    "prepared": {
                        "id": str(getattr(prepared[index], "id", "")),
                        "x": int(getattr(prepared[index], "centro_x", 0)),
                        "y": int(getattr(prepared[index], "centro_y", 0)),
                        "radius": int(getattr(prepared[index], "raio", 0)),
                        "bbox": [
                            int(getattr(prepared[index], key, 0))
                            for key in ("x1", "y1", "x2", "y2")
                        ],
                    } if index < len(prepared) else None,
                }
                for index, item in enumerate(led_results)
            ],
        }

        F2_OPTICAL_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with F2_OPTICAL_TRACE_PATH.open("a", encoding="utf-8") as target:
            target.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return True
    except Exception:
        # Diagnóstico observador: nunca interrompe o ciclo ou muda a decisão.
        logging.getLogger(__name__).warning(
            "Falha no diagnóstico óptico da inspeção F2", exc_info=True,
        )
        return False
