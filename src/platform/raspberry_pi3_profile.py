"""Compatibilidade com o antigo perfil Raspberry.

O produto canônico é Desktop Windows/Linux. Este módulo permanece somente para
consumidores históricos até a auditoria da Etapa 7.
"""

from src.platform.desktop_camera_service import DesktopCameraService
from src.platform.desktop_profile import DesktopODINApp


RaspberryPi3CameraService = DesktopCameraService
RaspberryPi3ODINApp = DesktopODINApp

__all__ = ["RaspberryPi3CameraService", "RaspberryPi3ODINApp"]
