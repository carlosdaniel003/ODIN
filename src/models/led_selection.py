from dataclasses import asdict, dataclass


@dataclass
class LedSelection:
    id: str
    centro_x: int
    centro_y: int
    raio: int

    @classmethod
    def from_dict(cls, dados: dict | None) -> "LedSelection | None":
        if not dados:
            return None

        return cls(
            id=str(dados.get("id", "LED_SELECIONADO")),
            centro_x=int(dados["centro_x"]),
            centro_y=int(dados["centro_y"]),
            raio=int(dados["raio"]),
        )

    def to_dict(self) -> dict:
        return asdict(self)
