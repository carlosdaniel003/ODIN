import tkinter as tk

from src.platform.gpio_raspberry_app import (
    GPIOEnabledRaspberryPi3ODINApp,
)


def main() -> None:
    root = tk.Tk()
    GPIOEnabledRaspberryPi3ODINApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
