import tkinter as tk

from src.platform.raspberry_pi3_profile import RaspberryPi3ODINApp


def main() -> None:
    root = tk.Tk()
    RaspberryPi3ODINApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
