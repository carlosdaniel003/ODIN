"""Adapter canônico de câmera para Windows/Linux desktop.

A implementação de baixo nível ainda reside no módulo legado durante a migração,
mas novos consumidores não devem depender do nome Raspberry.
"""

from src.platform.raspberry_camera_service import RaspberryPi3CameraService


DesktopCameraService = RaspberryPi3CameraService

__all__ = ["DesktopCameraService"]
