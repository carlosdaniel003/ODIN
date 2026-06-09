import json
from pathlib import Path

from config import CONFIG_FILE, DEFAULT_SAVE_ANALYSIS_RESULTS, DEFAULT_THRESHOLD_V
from src.models.led_features import LedFeatures
from src.models.reference_sample import ReferenceSample


class ConfigRepository:
    def __init__(self, config_file: Path = CONFIG_FILE) -> None:
        self.config_file = config_file

    def carregar_configuracao_existente_sem_alerta(self) -> dict:
        if not self.config_file.exists():
            return {}

        try:
            with open(self.config_file, "r", encoding="utf-8") as arquivo:
                return json.load(arquivo)
        except Exception:
            return {}

    def obter_configuracoes_sistema(self) -> dict:
        configuracao = self.carregar_configuracao_existente_sem_alerta()
        settings = configuracao.get("settings", {})

        return {
            "save_analysis_results": bool(
                settings.get("save_analysis_results", DEFAULT_SAVE_ANALYSIS_RESULTS)
            ),
        }

    def obter_salvar_resultados_analise(self) -> bool:
        settings = self.obter_configuracoes_sistema()
        return bool(settings["save_analysis_results"])

    def salvar_configuracoes_sistema(self, salvar_resultados_analise: bool) -> dict:
        configuracao = self.carregar_configuracao_existente_sem_alerta()

        if not configuracao:
            configuracao = {
                "project": "LumusPCI",
                "version": "0.7.0",
                "inspection_method": "single_selected_led_reference_classifier_modular",
                "threshold_v": DEFAULT_THRESHOLD_V,
            }

        settings = configuracao.get("settings", {})
        settings["save_analysis_results"] = bool(salvar_resultados_analise)
        configuracao["settings"] = settings

        self.config_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.config_file, "w", encoding="utf-8") as arquivo:
            json.dump(configuracao, arquivo, indent=4, ensure_ascii=False)

        return configuracao

    def salvar_referencias(
        self,
        caminho_referencia_acesa: str | None,
        features_referencia_acesa: LedFeatures,
        caminho_referencia_apagada: str | None,
        features_referencia_apagada: LedFeatures,
        raio_atual_px: int,
    ) -> dict:
        configuracao_existente = self.carregar_configuracao_existente_sem_alerta()
        settings = configuracao_existente.get(
            "settings",
            {
                "save_analysis_results": DEFAULT_SAVE_ANALYSIS_RESULTS,
            },
        )

        configuracao_final = {
            "project": "LumusPCI",
            "version": "0.7.0",
            "inspection_method": "single_selected_led_reference_classifier_modular",
            "threshold_v": DEFAULT_THRESHOLD_V,
            "default_radius_px": raio_atual_px,
            "settings": settings,
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
            json.dump(configuracao_final, arquivo, indent=4, ensure_ascii=False)

        return configuracao_final

    def carregar_referencias(self) -> tuple[ReferenceSample, ReferenceSample, dict]:
        configuracao = self.carregar_configuracao_existente_sem_alerta()
        referencia_acesa = ReferenceSample.from_dict(configuracao.get("reference_on", {}))
        referencia_apagada = ReferenceSample.from_dict(configuracao.get("reference_off", {}))
        return referencia_acesa, referencia_apagada, configuracao
