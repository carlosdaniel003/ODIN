import tkinter as tk

from src.app import LumusPCIApp


def main() -> None:
    root = tk.Tk()
    LumusPCIApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
