from dataclasses import asdict, dataclass


@dataclass
class LedSelection:
    id: str
    centro_x: int
    centro_y: int
    raio: int
    centro_x_normalizado: float | None = None
    centro_y_normalizado: float | None = None
    raio_normalizado: float | None = None
    largura_base: int | None = None
    altura_base: int | None = None

    @classmethod
    def from_dict(cls, dados: dict | None) -> "LedSelection | None":
        if not dados:
            return None

        normalizado = dados.get("normalized", {})
        resolucao_base = dados.get("base_resolution", {})

        if not isinstance(normalizado, dict):
            normalizado = {}

        if not isinstance(resolucao_base, dict):
            resolucao_base = {}

        def obter_float(*nomes):
            for nome in nomes:
                valor = dados.get(nome, normalizado.get(nome))

                if valor is not None:
                    try:
                        return float(valor)
                    except (TypeError, ValueError):
                        return None

            return None

        def obter_int(*nomes):
            for nome in nomes:
                valor = dados.get(nome, resolucao_base.get(nome))

                if valor is not None:
                    try:
                        return int(valor)
                    except (TypeError, ValueError):
                        return None

            return None

        return cls(
            id=str(dados.get("id", "LED_SELECIONADO")),
            centro_x=int(dados["centro_x"]),
            centro_y=int(dados["centro_y"]),
            raio=int(dados["raio"]),
            centro_x_normalizado=obter_float(
                "centro_x_normalizado",
                "x",
            ),
            centro_y_normalizado=obter_float(
                "centro_y_normalizado",
                "y",
            ),
            raio_normalizado=obter_float(
                "raio_normalizado",
                "radius",
            ),
            largura_base=obter_int("largura_base", "width"),
            altura_base=obter_int("altura_base", "height"),
        )

    def possui_coordenadas_normalizadas(self) -> bool:
        return (
            self.centro_x_normalizado is not None
            and self.centro_y_normalizado is not None
            and self.raio_normalizado is not None
        )

    def com_normalizacao(
        self,
        largura_base: int,
        altura_base: int,
    ) -> "LedSelection":
        largura_base = max(1, int(largura_base))
        altura_base = max(1, int(altura_base))

        return LedSelection(
            id=self.id,
            centro_x=int(self.centro_x),
            centro_y=int(self.centro_y),
            raio=int(self.raio),
            centro_x_normalizado=float(self.centro_x) / largura_base,
            centro_y_normalizado=float(self.centro_y) / altura_base,
            raio_normalizado=float(self.raio) / largura_base,
            largura_base=largura_base,
            altura_base=altura_base,
        )

    def adaptar_para_resolucao(
        self,
        largura_destino: int,
        altura_destino: int,
        raio_minimo: int,
        raio_maximo: int,
    ) -> "LedSelection":
        largura_destino = max(1, int(largura_destino))
        altura_destino = max(1, int(altura_destino))

        if self.possui_coordenadas_normalizadas():
            centro_x = int(round(self.centro_x_normalizado * largura_destino))
            centro_y = int(round(self.centro_y_normalizado * altura_destino))
            raio = int(round(self.raio_normalizado * largura_destino))
        elif self.largura_base and self.altura_base:
            escala_x = largura_destino / max(1, int(self.largura_base))
            escala_y = altura_destino / max(1, int(self.altura_base))
            escala_raio = min(escala_x, escala_y)
            centro_x = int(round(self.centro_x * escala_x))
            centro_y = int(round(self.centro_y * escala_y))
            raio = int(round(self.raio * escala_raio))
        else:
            centro_x = int(self.centro_x)
            centro_y = int(self.centro_y)
            raio = int(self.raio)

        raio = min(
            int(raio_maximo),
            max(int(raio_minimo), raio),
        )

        return LedSelection(
            id=self.id,
            centro_x=centro_x,
            centro_y=centro_y,
            raio=raio,
            centro_x_normalizado=self.centro_x_normalizado,
            centro_y_normalizado=self.centro_y_normalizado,
            raio_normalizado=self.raio_normalizado,
            largura_base=self.largura_base,
            altura_base=self.altura_base,
        )

    def to_dict(self) -> dict:
        dados = {
            "id": self.id,
            "centro_x": int(self.centro_x),
            "centro_y": int(self.centro_y),
            "raio": int(self.raio),
        }

        if self.possui_coordenadas_normalizadas():
            dados["normalized"] = {
                "x": float(self.centro_x_normalizado),
                "y": float(self.centro_y_normalizado),
                "radius": float(self.raio_normalizado),
            }

        if self.largura_base and self.altura_base:
            dados["base_resolution"] = {
                "width": int(self.largura_base),
                "height": int(self.altura_base),
            }

        return dados
