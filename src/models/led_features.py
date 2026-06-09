from dataclasses import asdict, dataclass


@dataclass
class LedFeatures:
    v_mean: float = 0.0
    v_max: float = 0.0
    v_min: float = 0.0
    v_std: float = 0.0
    v_p90: float = 0.0
    v_p95: float = 0.0
    v_p99: float = 0.0
    s_mean: float = 0.0
    s_std: float = 0.0
    s_p90: float = 0.0
    h_mean: float = 0.0
    inner_v_mean: float = 0.0
    ring_v_mean: float = 0.0
    center_to_ring_v: float = 0.0
    inner_s_mean: float = 0.0
    ring_s_mean: float = 0.0
    center_to_ring_s: float = 0.0
    percent_on: float = 0.0
    percent_hot_220: float = 0.0
    percent_hot_235: float = 0.0
    percent_hot_245: float = 0.0
    percent_hot_250: float = 0.0
    glow_score: float = 0.0
    area_pixels: int = 0
    inner_area_pixels: int = 0
    ring_area_pixels: int = 0

    @classmethod
    def from_dict(cls, dados: dict | None) -> "LedFeatures":
        if not dados:
            return cls()

        campos = cls.__dataclass_fields__.keys()
        return cls(**{campo: dados.get(campo, getattr(cls(), campo)) for campo in campos})

    def to_dict(self) -> dict:
        return asdict(self)
