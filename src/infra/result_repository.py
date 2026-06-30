import json
from datetime import datetime

from config import RESULTS_DIR
from src.core.visual_renderer import (
    criar_imagem_mascara,
    criar_imagem_mascara_multiplos,
    criar_imagem_resultado_visual,
    criar_imagem_resultados_visuais,
    criar_imagem_roi_debug,
)
from src.infra.image_io import salvar_imagem_opencv
from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection
from src.models.output_paths import OutputPaths


class ResultRepository:
    def salvar_resultado_analise(
        self,
        imagem_original,
        resultado_led: LedAnalysisResult,
        caminho_imagem_atual: str | None,
        caminho_referencia_acesa: str | None,
        caminho_referencia_apagada: str | None,
        features_referencia_acesa,
        features_referencia_apagada,
        led_selecionado: LedSelection,
        salvar_resultados_analise: bool,
    ) -> OutputPaths:
        return self.salvar_resultado_analise_multiplos(
            imagem_original=imagem_original,
            resultados_led=[resultado_led],
            caminho_imagem_atual=caminho_imagem_atual,
            caminho_referencia_acesa=caminho_referencia_acesa,
            caminho_referencia_apagada=caminho_referencia_apagada,
            features_referencia_acesa=features_referencia_acesa,
            features_referencia_apagada=features_referencia_apagada,
            leds_selecionados=[led_selecionado],
            salvar_resultados_analise=salvar_resultados_analise,
        )

    def salvar_resultado_analise_multiplos(
        self,
        imagem_original,
        resultados_led: list[LedAnalysisResult],
        caminho_imagem_atual: str | None,
        caminho_referencia_acesa: str | None,
        caminho_referencia_apagada: str | None,
        features_referencia_acesa,
        features_referencia_apagada,
        leds_selecionados: list[LedSelection],
        salvar_resultados_analise: bool,
    ) -> OutputPaths:
        if not salvar_resultados_analise:
            return OutputPaths()

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        caminho_resultado_imagem = RESULTS_DIR / f"analise_led_{timestamp}_resultado.png"
        caminho_mascara = RESULTS_DIR / f"analise_led_{timestamp}_mascara.png"
        caminho_roi_debug = RESULTS_DIR / f"analise_led_{timestamp}_roi_debug.png"
        caminho_resultado_json = RESULTS_DIR / f"analise_led_{timestamp}.json"

        imagem_resultado = criar_imagem_resultados_visuais(imagem_original, resultados_led)
        mascara = criar_imagem_mascara_multiplos(imagem_original, resultados_led)
        roi_debug = criar_imagem_roi_debug(imagem_original, resultados_led[-1]) if resultados_led else None

        salvar_imagem_opencv(caminho_resultado_imagem, imagem_resultado)
        salvar_imagem_opencv(caminho_mascara, mascara)

        if roi_debug is not None:
            salvar_imagem_opencv(caminho_roi_debug, roi_debug)

        resultado_json = {
            "project": "ODIN",
            "version": "0.9.0",
            "inspection_method": "multi_selected_led_reference_classifier_modular",
            "image": caminho_imagem_atual,
            "reference_on": caminho_referencia_acesa,
            "reference_off": caminho_referencia_apagada,
            "reference_on_features": features_referencia_acesa.to_dict() if features_referencia_acesa else None,
            "reference_off_features": features_referencia_apagada.to_dict() if features_referencia_apagada else None,
            "selected_leds": [led.to_dict() for led in leds_selecionados],
            "results": [resultado.to_dict() for resultado in resultados_led],
            "summary": {
                "total_leds": len(resultados_led),
                "leds_on": sum(1 for resultado in resultados_led if resultado.valor_binario == 1),
                "leds_off": sum(1 for resultado in resultados_led if resultado.valor_binario == 0),
            },
            "output_image": str(caminho_resultado_imagem),
            "output_mask": str(caminho_mascara),
            "output_roi_debug": str(caminho_roi_debug),
        }

        with open(caminho_resultado_json, "w", encoding="utf-8") as arquivo:
            json.dump(resultado_json, arquivo, indent=4, ensure_ascii=False)

        return OutputPaths(
            caminho_resultado_imagem=caminho_resultado_imagem,
            caminho_mascara=caminho_mascara,
            caminho_roi_debug=caminho_roi_debug,
            caminho_resultado_json=caminho_resultado_json,
        )
