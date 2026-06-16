import json
from pathlib import Path

from config import (
    CAMERA_IMAGE_CONTROL_MAX,
    CAMERA_IMAGE_CONTROL_MIN,
    CAMERA_PAN_MAX,
    CAMERA_PAN_MIN,
    CAMERA_ROTATIONS,
    CAMERA_TILT_MAX,
    CAMERA_TILT_MIN,
    CONFIG_FILE,
    DEFAULT_CAMERA_SETTINGS,
    DEFAULT_RADIUS_PX,
    DEFAULT_SAVE_ANALYSIS_RESULTS,
    DEFAULT_THRESHOLD_V,
    MAX_RADIUS_PX,
    MIN_RADIUS_PX,
)
from src.models.led_features import LedFeatures
from src.models.led_selection import LedSelection
from src.models.reference_sample import ReferenceSample


class ConfigRepository:
    def __init__(self, config_file: Path = CONFIG_FILE) -> None:
        self.config_file = config_file

    def carregar_configuracao_existente_sem_alerta(self) -> dict:
        if not self.config_file.exists():
            return {}

        try:
            with open(self.config_file, "r", encoding="utf-8") as arquivo:
                dados = json.load(arquivo)

            return dados if isinstance(dados, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _limitar_float(valor, minimo: float, maximo: float, padrao: float) -> float:
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            numero = float(padrao)

        return min(float(maximo), max(float(minimo), numero))

    @classmethod
    def normalizar_configuracoes_camera(
        cls,
        configuracoes_camera: dict | None,
    ) -> dict:
        origem = configuracoes_camera if isinstance(configuracoes_camera, dict) else {}
        padrao = DEFAULT_CAMERA_SETTINGS

        try:
            rotacao = int(origem.get("rotation", padrao["rotation"]))
        except (TypeError, ValueError):
            rotacao = int(padrao["rotation"])

        if rotacao not in CAMERA_ROTATIONS:
            rotacao = int(padrao["rotation"])

        return {
            "pan_enabled": bool(
                origem.get("pan_enabled", padrao["pan_enabled"])
            ),
            "pan": cls._limitar_float(
                origem.get("pan", padrao["pan"]),
                CAMERA_PAN_MIN,
                CAMERA_PAN_MAX,
                padrao["pan"],
            ),
            "tilt_enabled": bool(
                origem.get("tilt_enabled", padrao["tilt_enabled"])
            ),
            "tilt": cls._limitar_float(
                origem.get("tilt", padrao["tilt"]),
                CAMERA_TILT_MIN,
                CAMERA_TILT_MAX,
                padrao["tilt"],
            ),
            "contrast_enabled": bool(
                origem.get(
                    "contrast_enabled",
                    padrao["contrast_enabled"],
                )
            ),
            "contrast": cls._limitar_float(
                origem.get("contrast", padrao["contrast"]),
                CAMERA_IMAGE_CONTROL_MIN,
                CAMERA_IMAGE_CONTROL_MAX,
                padrao["contrast"],
            ),
            "sharpness_enabled": bool(
                origem.get(
                    "sharpness_enabled",
                    padrao["sharpness_enabled"],
                )
            ),
            "sharpness": cls._limitar_float(
                origem.get("sharpness", padrao["sharpness"]),
                CAMERA_IMAGE_CONTROL_MIN,
                CAMERA_IMAGE_CONTROL_MAX,
                padrao["sharpness"],
            ),
            "saturation_enabled": bool(
                origem.get(
                    "saturation_enabled",
                    padrao["saturation_enabled"],
                )
            ),
            "saturation": cls._limitar_float(
                origem.get("saturation", padrao["saturation"]),
                CAMERA_IMAGE_CONTROL_MIN,
                CAMERA_IMAGE_CONTROL_MAX,
                padrao["saturation"],
            ),
            "rotation": rotacao,
        }

    def obter_configuracoes_sistema(self) -> dict:
        configuracao = self.carregar_configuracao_existente_sem_alerta()
        settings = configuracao.get("settings", {})

        if not isinstance(settings, dict):
            settings = {}

        return {
            "save_analysis_results": bool(
                settings.get(
                    "save_analysis_results",
                    DEFAULT_SAVE_ANALYSIS_RESULTS,
                )
            ),
            "default_radius_px": int(
                configuracao.get(
                    "default_radius_px",
                    DEFAULT_RADIUS_PX,
                )
            ),
            "camera": self.normalizar_configuracoes_camera(
                settings.get("camera")
            ),
        }

    def obter_salvar_resultados_analise(self) -> bool:
        settings = self.obter_configuracoes_sistema()
        return bool(settings["save_analysis_results"])

    def obter_raio_padrao_led(
        self,
        raio_maximo_px: int = MAX_RADIUS_PX,
    ) -> int:
        settings = self.obter_configuracoes_sistema()
        raio_configurado = int(
            settings.get("default_radius_px", DEFAULT_RADIUS_PX)
        )
        return min(
            raio_maximo_px,
            max(MIN_RADIUS_PX, raio_configurado),
        )

    def obter_configuracoes_camera(self) -> dict:
        settings = self.obter_configuracoes_sistema()
        return dict(settings["camera"])

    def salvar_configuracoes_sistema(
        self,
        salvar_resultados_analise: bool,
        raio_atual_px: int | None = None,
        configuracoes_camera: dict | None = None,
    ) -> dict:
        configuracao = self.carregar_configuracao_existente_sem_alerta()

        if not configuracao:
            configuracao = {
                "project": "LumusPCI",
                "version": "0.7.0",
                "inspection_method": (
                    "single_selected_led_reference_classifier_modular"
                ),
                "threshold_v": DEFAULT_THRESHOLD_V,
            }

        settings = configuracao.get("settings", {})

        if not isinstance(settings, dict):
            settings = {}

        settings["save_analysis_results"] = bool(
            salvar_resultados_analise
        )

        if configuracoes_camera is not None:
            settings["camera"] = self.normalizar_configuracoes_camera(
                configuracoes_camera
            )
        elif "camera" not in settings:
            settings["camera"] = self.normalizar_configuracoes_camera(None)

        configuracao["settings"] = settings

        if raio_atual_px is not None:
            configuracao["default_radius_px"] = int(raio_atual_px)

        self.config_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.config_file, "w", encoding="utf-8") as arquivo:
            json.dump(
                configuracao,
                arquivo,
                indent=4,
                ensure_ascii=False,
            )

        return configuracao

    def salvar_referencias(
        self,
        caminho_referencia_acesa: str | None,
        features_referencia_acesa: LedFeatures,
        caminho_referencia_apagada: str | None,
        features_referencia_apagada: LedFeatures,
        raio_atual_px: int,
    ) -> dict:
        configuracao_existente = (
            self.carregar_configuracao_existente_sem_alerta()
        )
        settings = configuracao_existente.get(
            "settings",
            {
                "save_analysis_results": DEFAULT_SAVE_ANALYSIS_RESULTS,
                "camera": self.normalizar_configuracoes_camera(None),
            },
        )

        if not isinstance(settings, dict):
            settings = {}

        settings.setdefault(
            "save_analysis_results",
            DEFAULT_SAVE_ANALYSIS_RESULTS,
        )
        settings["camera"] = self.normalizar_configuracoes_camera(
            settings.get("camera")
        )

        fixed_leds = configuracao_existente.get("fixed_leds", [])

        configuracao_final = {
            "project": "LumusPCI",
            "version": "0.7.0",
            "inspection_method": (
                "single_selected_led_reference_classifier_modular"
            ),
            "threshold_v": DEFAULT_THRESHOLD_V,
            "default_radius_px": int(raio_atual_px),
            "settings": settings,
            "fixed_leds": fixed_leds,
            "reference_on": {
                "image_path": caminho_referencia_acesa,
                "features": features_referencia_acesa.to_dict(),
            },
            "reference_off": {
                "image_path": caminho_referencia_apagada,
                "features": features_referencia_apagada.to_dict(),
            },
        }

        self.config_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.config_file, "w", encoding="utf-8") as arquivo:
            json.dump(
                configuracao_final,
                arquivo,
                indent=4,
                ensure_ascii=False,
            )

        return configuracao_final

    def carregar_referencias(
        self,
    ) -> tuple[ReferenceSample, ReferenceSample, dict]:
        configuracao = self.carregar_configuracao_existente_sem_alerta()
        referencia_acesa = ReferenceSample.from_dict(
            configuracao.get("reference_on", {})
        )
        referencia_apagada = ReferenceSample.from_dict(
            configuracao.get("reference_off", {})
        )
        return referencia_acesa, referencia_apagada, configuracao

    def salvar_leds_fixos(
        self,
        leds_fixos: list[LedSelection],
    ) -> dict:
        configuracao = self.carregar_configuracao_existente_sem_alerta()

        if not configuracao:
            configuracao = {
                "project": "LumusPCI",
                "version": "0.7.0",
                "inspection_method": (
                    "single_selected_led_reference_classifier_modular"
                ),
                "threshold_v": DEFAULT_THRESHOLD_V,
            }

        settings = configuracao.get("settings", {})

        if not isinstance(settings, dict):
            settings = {}

        settings.setdefault(
            "save_analysis_results",
            DEFAULT_SAVE_ANALYSIS_RESULTS,
        )
        settings["camera"] = self.normalizar_configuracoes_camera(
            settings.get("camera")
        )

        configuracao["settings"] = settings
        configuracao["fixed_leds"] = [
            led_fixo.to_dict()
            for led_fixo in leds_fixos
        ]

        self.config_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.config_file, "w", encoding="utf-8") as arquivo:
            json.dump(
                configuracao,
                arquivo,
                indent=4,
                ensure_ascii=False,
            )

        return configuracao

    def carregar_leds_fixos(self) -> list[LedSelection]:
        configuracao = self.carregar_configuracao_existente_sem_alerta()
        dados_leds_fixos = configuracao.get("fixed_leds", [])

        leds_fixos = []

        for dados_led_fixo in dados_leds_fixos:
            led_fixo = LedSelection.from_dict(dados_led_fixo)

            if led_fixo is not None:
                leds_fixos.append(led_fixo)

        return leds_fixos
