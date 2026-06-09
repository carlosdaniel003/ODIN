from dataclasses import dataclass

from src.models.metric_vote import MetricVote


@dataclass
class MetricEvaluation:
    score_metricas: float
    peso_total: float
    peso_aceso: float
    votos_aceso: int
    votos_apagado: int
    detalhes: list[MetricVote]

    def to_dict(self) -> dict:
        return {
            "score_metricas": self.score_metricas,
            "peso_total": self.peso_total,
            "peso_aceso": self.peso_aceso,
            "votos_aceso": self.votos_aceso,
            "votos_apagado": self.votos_apagado,
            "detalhes": [item.to_dict() for item in self.detalhes],
        }
