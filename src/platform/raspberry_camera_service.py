"""Compatibilidade com o antigo nome de CameraService Raspberry."""

from src.platform.desktop_camera_service import DesktopCameraService


RaspberryPi3CameraService = DesktopCameraService

__all__ = ["RaspberryPi3CameraService", "DesktopCameraService"]
