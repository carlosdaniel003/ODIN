def limpar_lupa_canvas(self, evento=None) -> None:
    if hasattr(self, "canvas") and self.canvas is not None:
        self.canvas.delete("lupa_canvas")

    self.lupa_tk = None