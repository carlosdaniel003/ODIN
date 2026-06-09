import base64
from datetime import datetime
import tkinter as tk
from tkinter import ttk

import cv2

from src.models.analysis_result import LedAnalysisResult
from src.models.led_selection import LedSelection

def adicionar_resultado_historico(self, resultado: LedAnalysisResult) -> None:
        chave_resultado = (
            resultado.id,
            resultado.status,
            resultado.centro_x,
            resultado.centro_y,
            resultado.raio,
            resultado.confianca,
            resultado.features.v_mean,
            resultado.features.v_max,
            resultado.features.glow_score,
        )

        if chave_resultado == self._ultimo_resultado_historico:
            return

        self._ultimo_resultado_historico = chave_resultado
        observacao = self.criar_observacao_resultado(resultado)

        self.tabela_historico.insert(
            "",
            0,
            values=(
                resultado.id,
                f"({resultado.centro_x}, {resultado.centro_y})",
                resultado.status,
                resultado.confianca,
                resultado.features.v_mean,
                resultado.features.v_max,
                resultado.features.glow_score,
                observacao,
            ),
        )
