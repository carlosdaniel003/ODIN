from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

from linux_local_config_bootstrap import preparar_configuracao_local_linux


if sys.platform.startswith("linux"):
    preparar_configuracao_local_linux(Path(__file__).resolve().parent)


from src.platform.raspberry_pi3_production_app import (  # noqa: E402
    RaspberryPi3ProductionApp,
)
from src.platform.display_reference_roi_runtime_fix import (  # noqa: E402
    instalar_correcao_referencias_mascaras_f3,
)


instalar_correcao_referencias_mascaras_f3()


def main() -> None:
    root = tk.Tk()
    RaspberryPi3ProductionApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
