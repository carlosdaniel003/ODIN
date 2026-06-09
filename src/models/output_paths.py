from dataclasses import dataclass
from pathlib import Path


@dataclass
class OutputPaths:
    caminho_resultado_imagem: Path | None = None
    caminho_mascara: Path | None = None
    caminho_roi_debug: Path | None = None
    caminho_resultado_json: Path | None = None

    def tem_arquivos_salvos(self) -> bool:
        return any(
            caminho is not None
            for caminho in [
                self.caminho_resultado_imagem,
                self.caminho_mascara,
                self.caminho_roi_debug,
                self.caminho_resultado_json,
            ]
        )

    def to_dict(self) -> dict:
        return {
            "output_image": str(self.caminho_resultado_imagem) if self.caminho_resultado_imagem else None,
            "output_mask": str(self.caminho_mascara) if self.caminho_mascara else None,
            "output_roi_debug": str(self.caminho_roi_debug) if self.caminho_roi_debug else None,
            "output_json": str(self.caminho_resultado_json) if self.caminho_resultado_json else None,
        }
