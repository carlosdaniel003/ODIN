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

DEFAULT_CAMERA_SETTINGS = {
    "resolution_mode": "auto",
    "width": 1920,
    "height": 1080,
    "fps_mode": "auto",
    "fps": 0,
    "format": "AUTO",
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
