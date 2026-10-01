from __future__ import annotations

from config import (
    CAMERA_BRIGHTNESS_MAX,
    CAMERA_BRIGHTNESS_MIN,
    CAMERA_EXPOSURE_MAX,
    CAMERA_EXPOSURE_MIN,
    CAMERA_FOCUS_MAX,
    CAMERA_FOCUS_MIN,
    CAMERA_GAIN_MAX,
    CAMERA_GAIN_MIN,
    CAMERA_GAMMA_MAX,
    CAMERA_GAMMA_MIN,
    CAMERA_WHITE_BALANCE_MAX,
    CAMERA_WHITE_BALANCE_MIN,
    CAMERA_ZOOM_MAX,
    CAMERA_ZOOM_MIN,
    DEFAULT_CAMERA_SETTINGS,
)
from src.infra.config_repository import ConfigRepository


_CONTROLES_AVANCADOS = (
    ("exposure", CAMERA_EXPOSURE_MIN, CAMERA_EXPOSURE_MAX),
    ("gain", CAMERA_GAIN_MIN, CAMERA_GAIN_MAX),
    ("focus", CAMERA_FOCUS_MIN, CAMERA_FOCUS_MAX),
    (
        "white_balance",
        CAMERA_WHITE_BALANCE_MIN,
        CAMERA_WHITE_BALANCE_MAX,
    ),
    ("brightness", CAMERA_BRIGHTNESS_MIN, CAMERA_BRIGHTNESS_MAX),
    ("gamma", CAMERA_GAMMA_MIN, CAMERA_GAMMA_MAX),
    ("zoom", CAMERA_ZOOM_MIN, CAMERA_ZOOM_MAX),
)

_PATCH_INSTALADO = False


def _limitar_float(valor, minimo: float, maximo: float, padrao: float) -> float:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        numero = float(padrao)
    return min(float(maximo), max(float(minimo), numero))


def normalizar_controles_avancados(
    resultado: dict,
    origem: dict | None,
) -> dict:
    origem = origem if isinstance(origem, dict) else {}
    padrao = DEFAULT_CAMERA_SETTINGS

    resultado.update(
        {
            "exposure_auto": bool(
                origem.get("exposure_auto", padrao["exposure_auto"])
            ),
            "focus_auto": bool(
                origem.get("focus_auto", padrao["focus_auto"])
            ),
            "white_balance_auto": bool(
                origem.get(
                    "white_balance_auto",
                    padrao["white_balance_auto"],
                )
            ),
        }
    )

    for nome, minimo, maximo in _CONTROLES_AVANCADOS:
        resultado[f"{nome}_enabled"] = bool(
            origem.get(
                f"{nome}_enabled",
                padrao[f"{nome}_enabled"],
            )
        )
        resultado[nome] = _limitar_float(
            origem.get(nome, padrao[nome]),
            minimo,
            maximo,
            padrao[nome],
        )

    return resultado


def instalar_normalizacao_config_repository() -> None:
    global _PATCH_INSTALADO

    if _PATCH_INSTALADO:
        return

    normalizador_original = (
        ConfigRepository.normalizar_configuracoes_camera.__func__
    )

    def normalizar_estendido(cls, configuracoes_camera):
        resultado = normalizador_original(
            cls,
            configuracoes_camera,
        )
        return normalizar_controles_avancados(
            resultado,
            configuracoes_camera,
        )

    ConfigRepository.normalizar_configuracoes_camera = classmethod(
        normalizar_estendido
    )
    _PATCH_INSTALADO = True
