from pathlib import Path 

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = DATA_DIR / "config"
RESULTS_DIR = DATA_DIR / "resultados"
CAPTURES_DIR = DATA_DIR / "capturas"

CONFIG_FILE = CONFIG_DIR / "lumus_pci_config.json"

DEFAULT_THRESHOLD_V = 160
DEFAULT_MIN_PERCENT_ON = 0.12
DEFAULT_RADIUS_PX = 15
MIN_RADIUS_PX = 3
MAX_RADIUS_PX = 50
DEFAULT_SAVE_ANALYSIS_RESULTS = False

# Configurações da câmera.
#
# Os controles de panorâmica, inclinação, contraste, nitidez e saturação
# dependem do suporte oferecido pelo driver da câmera. Quando o ajuste está
# desativado, o LumusPCI preserva o valor padrão negociado pelo driver.
DEFAULT_CAMERA_SETTINGS = {
    "pan_enabled": False,
    "pan": 0.0,
    "tilt_enabled": False,
    "tilt": 0.0,
    "contrast_enabled": False,
    "contrast": 128.0,
    "sharpness_enabled": False,
    "sharpness": 128.0,
    "saturation_enabled": False,
    "saturation": 128.0,
    "rotation": 0,
}

CAMERA_PAN_MIN = -180
CAMERA_PAN_MAX = 180
CAMERA_TILT_MIN = -180
CAMERA_TILT_MAX = 180
CAMERA_IMAGE_CONTROL_MIN = 0
CAMERA_IMAGE_CONTROL_MAX = 255
CAMERA_ROTATIONS = (0, 90, 180, 270)

MAX_DISPLAY_WIDTH = 1100
MAX_DISPLAY_HEIGHT = 650
