def configurar_atalhos_tela(self) -> None:
    self.root.bind("<F11>", self.alternar_tela_cheia)
    self.root.bind("<Escape>", self.sair_tela_cheia)
    self.root.bind("<Return>", self.callbacks["capturar_frame_camera_para_analise"])
    self.root.bind("<KP_Enter>", self.callbacks["capturar_frame_camera_para_analise"])