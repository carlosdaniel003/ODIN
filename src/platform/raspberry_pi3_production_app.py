"""Compatibilidade com o antigo nome de composição Raspberry.

O runtime canônico é DesktopProductionApp. Este alias permanece somente para
consumidores históricos até a Etapa 7.
"""

from src.platform.desktop_production_app import DesktopProductionApp


RaspberryPi3ProductionApp = DesktopProductionApp

__all__ = ["RaspberryPi3ProductionApp", "DesktopProductionApp"]
