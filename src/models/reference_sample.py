from dataclasses import dataclass

from src.models.led_features import LedFeatures


@dataclass
class ReferenceSample:
    image_path: str | None
    features: LedFeatures | None

    @classmethod
    def from_dict(cls, dados: dict | None) -> "ReferenceSample":
        if not dados:
            return cls(image_path=None, features=None)

        features = dados.get("features")
        return cls(
            image_path=dados.get("image_path"),
            features=LedFeatures.from_dict(features) if features else None,
        )

    def to_dict(self) -> dict:
        return {
            "image_path": self.image_path,
            "features": self.features.to_dict() if self.features else None,
        }
