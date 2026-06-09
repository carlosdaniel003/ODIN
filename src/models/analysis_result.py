from dataclasses import dataclass

from src.models.led_features import LedFeatures
from src.models.metric_evaluation import MetricEvaluation


@dataclass
class LedAnalysisResult:
    id: str
    status: str
    valor_binario: int
    centro_x: int
    centro_y: int
    raio: int
    features: LedFeatures
    limite_v_mean: float
    limite_v_std: float
    limite_center_to_ring_v: float
    limite_glow_score: float
    limite_v_p99: float
    distancia_on: float
    distancia_off: float
    brilho_indica_aceso: bool
    similaridade_indica_aceso: bool
    pico_indica_aceso: bool
    contraste_indica_aceso: bool
    metricas_indicam_aceso: bool
    avaliacao_metricas: MetricEvaluation
    motivos: list[str]
    confianca: float

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "valor_binario": self.valor_binario,
            "centro_x": self.centro_x,
            "centro_y": self.centro_y,
            "raio": self.raio,
            "features": self.features.to_dict(),
            "limite_v_mean": self.limite_v_mean,
            "limite_v_std": self.limite_v_std,
            "limite_center_to_ring_v": self.limite_center_to_ring_v,
            "limite_glow_score": self.limite_glow_score,
            "limite_v_p99": self.limite_v_p99,
            "distancia_on": self.distancia_on,
            "distancia_off": self.distancia_off,
            "brilho_indica_aceso": self.brilho_indica_aceso,
            "similaridade_indica_aceso": self.similaridade_indica_aceso,
            "pico_indica_aceso": self.pico_indica_aceso,
            "contraste_indica_aceso": self.contraste_indica_aceso,
            "metricas_indicam_aceso": self.metricas_indicam_aceso,
            "avaliacao_metricas": self.avaliacao_metricas.to_dict(),
            "motivos": self.motivos,
            "confianca": self.confianca,
        }
