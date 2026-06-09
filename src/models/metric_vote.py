from dataclasses import asdict, dataclass


@dataclass
class MetricVote:
    metrica: str
    usada: bool
    atual: float
    ref_aceso: float
    ref_apagado: float
    motivo: str | None = None
    limite: float | None = None
    indica: str | None = None
    peso: float | None = None

    def to_dict(self) -> dict:
        return {chave: valor for chave, valor in asdict(self).items() if valor is not None}
