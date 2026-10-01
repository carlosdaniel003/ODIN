import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
LEGACY_CONFIG_DIR = DATA_DIR / "config"
CONFIG_DIR = Path(
    os.environ.get("ODIN_CONFIG_DIR", str(LEGACY_CONFIG_DIR))
).expanduser()
RESULTS_DIR = DATA_DIR / "resultados"
CAPTURES_DIR = DATA_DIR / "capturas"

LEGACY_CONFIG_FILE = LEGACY_CONFIG_DIR / "odin_pci_config.json"
CONFIG_FILE = CONFIG_DIR / "odin_pci_config.json"

DEFAULT_THRESHOLD_V = 160
DEFAULT_MIN_PERCENT_ON = 0.12
DEFAULT_RADIUS_PX = 15
MIN_RADIUS_PX = 3
MAX_RADIUS_PX = 50
DEFAULT_SAVE_ANALYSIS_RESULTS = False

CAMERA_RESOLUTION_PRESETS = {
    "auto": {
        "label": "Automática recomendada",
        "width": 1920,
        "height": 1080,
    },
    "hd": {
        "label": "1280x720",
        "width": 1280,
        "height": 720,
    },
    "full_hd": {
        "label": "1920x1080",
        "width": 1920,
        "height": 1080,
    },
    "qhd": {
        "label": "2560x1440",
        "width": 2560,
        "height": 1440,
    },
    "uhd": {
        "label": "3840x2160",
        "width": 3840,
        "height": 2160,
    },
    "custom": {
        "label": "Personalizada",
        "width": 1920,
        "height": 1080,
    },
}

CAMERA_RESOLUTION_MODES = tuple(CAMERA_RESOLUTION_PRESETS.keys())
CAMERA_WIDTH_MIN = 320
CAMERA_WIDTH_MAX = 7680
CAMERA_HEIGHT_MIN = 240
CAMERA_HEIGHT_MAX = 4320

CAMERA_FPS_PRESETS = ("Automático", "10", "15", "20", "30")
CAMERA_FPS_MIN = 0
CAMERA_FPS_MAX = 120
CAMERA_FORMATS = ("AUTO", "MJPG", "YUY2")

CAMERA_PAN_MIN = -180
CAMERA_PAN_MAX = 180
CAMERA_TILT_MIN = -180
CAMERA_TILT_MAX = 180
CAMERA_IMAGE_CONTROL_MIN = 0
CAMERA_IMAGE_CONTROL_MAX = 255
CAMERA_EXPOSURE_MIN = -13
CAMERA_EXPOSURE_MAX = 2047
CAMERA_GAIN_MIN = 0
CAMERA_GAIN_MAX = 255
CAMERA_FOCUS_MIN = 0
CAMERA_FOCUS_MAX = 255
CAMERA_WHITE_BALANCE_MIN = 2000
CAMERA_WHITE_BALANCE_MAX = 7500
CAMERA_BRIGHTNESS_MIN = 0
CAMERA_BRIGHTNESS_MAX = 255
CAMERA_GAMMA_MIN = 1
CAMERA_GAMMA_MAX = 500
# Logitech BRIO/DirectShow expõe o zoom UVC como percentual: 100 = 1x,
# 500 = 5x. Outros backends podem rejeitar a propriedade; o runtime confirma
# suporte por readback antes de considerar o ajuste aplicado.
CAMERA_ZOOM_MIN = 100
CAMERA_ZOOM_MAX = 500
CAMERA_ROTATIONS = (0, 90, 180, 270)

DEFAULT_CAMERA_SETTINGS = {
    "resolution_mode": "full_hd",
    "width": 1920,
    "height": 1080,
    "fps_mode": "manual",
    "fps": 20,
    "format": "MJPG",
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
    "exposure_auto": True,
    "exposure_enabled": False,
    "exposure": 100.0,
    "gain_enabled": False,
    "gain": 0.0,
    "focus_auto": True,
    "focus_enabled": False,
    "focus": 0.0,
    "white_balance_auto": True,
    "white_balance_enabled": False,
    "white_balance": 4500.0,
    "brightness_enabled": False,
    "brightness": 128.0,
    "gamma_enabled": False,
    "gamma": 100.0,
    "zoom_enabled": False,
    "zoom": 100.0,
    "rotation": 0,
}

MAX_DISPLAY_WIDTH = 1100
MAX_DISPLAY_HEIGHT = 650
