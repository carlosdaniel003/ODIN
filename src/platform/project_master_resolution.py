from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog

from src.platform.desktop_camera_service import DesktopCameraService
from src.platform.led_project_repository import normalizar_resolucao_mestra


class ProjectMasterResolutionMixin:
    """Mantém câmera e ROIs no modo de captura salvo com cada projeto."""

    def __init__(self, *args, **kwargs) -> None:
        self._resolucao_mestra_projeto_ativa: tuple[int, int] | None = None
        self._resolucao_mestra_projeto_nome = ""
        self._reiniciando_camera_resolucao_mestra = False
        self._resolucao_mestra_producao: tuple[int, int] | None = None
        self._ultimo_projeto_escolhido_carregar_leds: str | None = None
        super().__init__(*args, **kwargs)
        self._atualizar_resolucao_mestra_projeto_ativa()

    @staticmethod
    def _resolucao_frame(frame) -> tuple[int, int] | None:
        if frame is None or not getattr(frame, "size", 0):
            return None
        altura, largura = frame.shape[:2]
        if largura <= 0 or altura <= 0:
            return None
        return int(largura), int(altura)

    def _obter_resolucao_mestra_projeto(
        self,
        projeto: str | None = None,
    ) -> tuple[int, int] | None:
        obter = getattr(
            self.config_repository,
            "obter_resolucao_mestra_projeto_led",
            None,
        )
        if not callable(obter):
            return None
        try:
            resolucao = obter(projeto=projeto)
        except TypeError:
            resolucao = obter(projeto)
        except Exception:
            return None
        return normalizar_resolucao_mestra(resolucao)

    def _atualizar_resolucao_mestra_projeto_ativa(
        self,
        projeto: str | None = None,
    ) -> tuple[int, int] | None:
        nome = str(
            projeto
            or getattr(self, "projeto_led_ativo", "")
            or ""
        ).strip()
        resolucao = self._obter_resolucao_mestra_projeto(nome or None)
        self._resolucao_mestra_projeto_nome = nome
        self._resolucao_mestra_projeto_ativa = resolucao
        return resolucao

    def _atualizar_config_camera_para_resolucao_mestra(
        self,
        resolucao: tuple[int, int] | None,
    ) -> None:
        if resolucao is None:
            return
        configuracoes = dict(getattr(self, "configuracoes_camera", {}) or {})
        configuracoes.update(
            {
                "resolution_mode": "custom",
                "width": int(resolucao[0]),
                "height": int(resolucao[1]),
            }
        )
        self.configuracoes_camera = configuracoes

    def _obter_resolucao_camera_real(self) -> tuple[int, int] | None:
        service = getattr(self, "camera_service", None)
        if service is not None:
            try:
                snapshot = service.obter_snapshot()
            except Exception:
                snapshot = None
            resolucao = getattr(snapshot, "resolucao", None)
            normalizada = normalizar_resolucao_mestra(resolucao)
            if normalizada is not None:
                return normalizada

        if bool(getattr(self, "camera_ativa", False)):
            return self._resolucao_frame(
                getattr(self, "camera_frame_atual", None)
            )
        return None

    def _obter_resolucao_camera_solicitada(self) -> tuple[int, int] | None:
        service = getattr(self, "camera_service", None)
        if service is None:
            return None
        try:
            snapshot = service.obter_snapshot()
        except Exception:
            return None
        return normalizar_resolucao_mestra(
            getattr(snapshot, "resolucao_solicitada", None)
        )

    def _obter_resolucao_edicao_atual(self) -> tuple[int, int] | None:
        real = self._obter_resolucao_camera_real()
        if real is not None:
            return real

        imagem = getattr(self, "imagem_original", None)
        resolucao_imagem = self._resolucao_frame(imagem)
        if resolucao_imagem is not None:
            return resolucao_imagem

        try:
            largura = int(getattr(self, "largura_original", 0) or 0)
            altura = int(getattr(self, "altura_original", 0) or 0)
        except (TypeError, ValueError):
            return None
        return normalizar_resolucao_mestra((largura, altura))

    def _travar_servico_na_resolucao_mestra(
        self,
        service,
        resolucao: tuple[int, int] | None,
    ) -> None:
        if service is None or resolucao is None:
            return
        travar = getattr(service, "definir_resolucao_travada", None)
        if callable(travar):
            travar(int(resolucao[0]), int(resolucao[1]))

    def _camera_ja_esta_na_resolucao(
        self,
        resolucao: tuple[int, int],
    ) -> bool:
        atual = self._obter_resolucao_camera_real()
        if atual is not None:
            return atual == resolucao
        solicitada = self._obter_resolucao_camera_solicitada()
        return solicitada == resolucao

    def obter_parametros_camera_dinamicos(self) -> tuple[int, int, int]:
        largura, altura, fps = super().obter_parametros_camera_dinamicos()
        resolucao = (
            self._resolucao_mestra_projeto_ativa
            or self._atualizar_resolucao_mestra_projeto_ativa()
        )
        if resolucao is None:
            return largura, altura, fps
        return int(resolucao[0]), int(resolucao[1]), int(fps)

    @staticmethod
    def _classe_camera_com_resolucao_travada(
        classe_base: type,
        resolucao: tuple[int, int],
    ) -> type:
        largura, altura = int(resolucao[0]), int(resolucao[1])

        class CameraServiceResolucaoMestre(classe_base):
            _odin_project_master_resolution = (largura, altura)

            def __init__(self, *args, **kwargs) -> None:
                super().__init__(*args, **kwargs)
                travar = getattr(self, "definir_resolucao_travada", None)
                if callable(travar):
                    travar(largura, altura)

        CameraServiceResolucaoMestre.__name__ = (
            f"{classe_base.__name__}Projeto{largura}x{altura}"
        )
        CameraServiceResolucaoMestre.__qualname__ = (
            CameraServiceResolucaoMestre.__name__
        )
        return CameraServiceResolucaoMestre

    def iniciar_tela_ao_vivo(self) -> None:
        resolucao = (
            self._resolucao_mestra_projeto_ativa
            or self._atualizar_resolucao_mestra_projeto_ativa()
        )
        if resolucao is None:
            return super().iniciar_tela_ao_vivo()

        self._atualizar_config_camera_para_resolucao_mestra(resolucao)
        classe_atual = getattr(self, "CAMERA_SERVICE_CLASS", None)
        if classe_atual is None:
            service = getattr(self, "camera_service", None)
            classe_atual = (
                type(service)
                if service is not None
                else DesktopCameraService
            )
        classe_travada = self._classe_camera_com_resolucao_travada(
            classe_atual,
            resolucao,
        )
        self.CAMERA_SERVICE_CLASS = classe_travada
        try:
            resultado = super().iniciar_tela_ao_vivo()
        finally:
            self.CAMERA_SERVICE_CLASS = classe_atual

        self._atualizar_config_camera_para_resolucao_mestra(resolucao)
        self._travar_servico_na_resolucao_mestra(
            getattr(self, "camera_service", None),
            resolucao,
        )
        return resultado

    def _reiniciar_camera_para_resolucao_mestra(
        self,
        resolucao: tuple[int, int],
    ) -> bool:
        if self._reiniciando_camera_resolucao_mestra:
            return False

        service = getattr(self, "camera_service", None)
        if (
            service is not None
            and getattr(self, "indice_camera_selecionada", None) is None
        ):
            try:
                self.indice_camera_selecionada = int(service.indice_camera)
            except Exception:
                pass

        self._reiniciando_camera_resolucao_mestra = True
        try:
            self._atualizar_config_camera_para_resolucao_mestra(resolucao)
            self.parar_tela_ao_vivo(manter_imagem=True)
            self.iniciar_tela_ao_vivo()
        finally:
            self._reiniciando_camera_resolucao_mestra = False
        return True

    def _aplicar_resolucao_mestra_projeto(
        self,
        projeto: str | None = None,
        reiniciar_se_necessario: bool = True,
    ) -> bool:
        """Retorna True somente quando foi necessário reiniciar a câmera."""
        resolucao = self._atualizar_resolucao_mestra_projeto_ativa(projeto)
        if resolucao is None:
            return False

        self._atualizar_config_camera_para_resolucao_mestra(resolucao)
        service = getattr(self, "camera_service", None)
        camera_ativa = bool(getattr(self, "camera_ativa", False))

        if (
            camera_ativa
            and service is not None
            and self._camera_ja_esta_na_resolucao(resolucao)
        ):
            # Já está no modo correto: nenhum set, stop, start ou reconnect.
            self._travar_servico_na_resolucao_mestra(service, resolucao)
            return False

        if camera_ativa and reiniciar_se_necessario:
            return self._reiniciar_camera_para_resolucao_mestra(resolucao)
        return False

    def _salvar_resolucao_mestra_do_projeto_atual(
        self,
        projeto: str,
        resolucao: tuple[int, int] | None,
    ) -> bool:
        if resolucao is None:
            return False
        definir = getattr(
            self.config_repository,
            "definir_resolucao_mestra_projeto_led",
            None,
        )
        if not callable(definir):
            return False
        try:
            sucesso = bool(
                definir(projeto, int(resolucao[0]), int(resolucao[1]))
            )
        except Exception:
            return False
        if sucesso and projeto == getattr(self, "projeto_led_ativo", None):
            self._atualizar_resolucao_mestra_projeto_ativa(projeto)
        return sucesso

    def _salvar_leds_no_projeto(
        self,
        nome_projeto: str,
        parent=None,
        confirmar_substituicao: bool = True,
    ) -> bool:
        resolucao_salva = self._obter_resolucao_edicao_atual()
        salvo = super()._salvar_leds_no_projeto(
            nome_projeto,
            parent=parent,
            confirmar_substituicao=confirmar_substituicao,
        )
        if not salvo:
            return False

        self._salvar_resolucao_mestra_do_projeto_atual(
            nome_projeto,
            resolucao_salva,
        )
        self._aplicar_resolucao_mestra_projeto(
            nome_projeto,
            reiniciar_se_necessario=False,
        )
        return True

    @staticmethod
    def _widgets_recursivos(root):
        for filho in root.winfo_children():
            yield filho
            yield from ProjectMasterResolutionMixin._widgets_recursivos(filho)

    def _instalar_botao_resolucao_mestra_carregar_leds(
        self,
        tentativa: int = 0,
    ) -> None:
        janela = None
        for filho in self.root.winfo_children():
            if not isinstance(filho, tk.Toplevel):
                continue
            try:
                if filho.title() == "Gerenciar configurações de LEDs":
                    janela = filho
                    break
            except tk.TclError:
                continue

        if janela is None:
            if tentativa < 30:
                self.root.after(
                    20,
                    lambda: self._instalar_botao_resolucao_mestra_carregar_leds(
                        tentativa + 1
                    ),
                )
            return

        lista = None
        botao_referencia = None
        for widget in self._widgets_recursivos(janela):
            if isinstance(widget, tk.Listbox) and lista is None:
                lista = widget
            if isinstance(widget, tk.Button):
                try:
                    if str(widget.cget("text")) == "✎  Renomear":
                        botao_referencia = widget
                except tk.TclError:
                    pass

        if lista is None or botao_referencia is None:
            if tentativa < 30:
                self.root.after(
                    20,
                    lambda: self._instalar_botao_resolucao_mestra_carregar_leds(
                        tentativa + 1
                    ),
                )
            return

        frame_acoes = botao_referencia.master
        for filho in frame_acoes.winfo_children():
            if isinstance(filho, tk.Button):
                try:
                    if bool(getattr(filho, "_odin_master_resolution_button", False)):
                        return
                except Exception:
                    pass

        def projeto_selecionado() -> str | None:
            selecao = lista.curselection()
            if not selecao:
                return None
            nomes = self.config_repository.listar_projetos_led()
            indice = int(selecao[0])
            if indice < 0 or indice >= len(nomes):
                return None
            return nomes[indice]

        def atualizar_texto(_evento=None) -> None:
            nome = projeto_selecionado()
            resolucao = self._obter_resolucao_mestra_projeto(nome) if nome else None
            texto = "▣  Resolução mestre"
            if resolucao is not None:
                texto += f"  {resolucao[0]}x{resolucao[1]}"
            try:
                botao.configure(text=texto)
            except tk.TclError:
                pass

        def definir_resolucao() -> None:
            nome = projeto_selecionado()
            if nome is None:
                messagebox.showwarning(
                    "Seleção necessária",
                    "Selecione um projeto para definir a resolução mestre.",
                    parent=janela,
                )
                return

            atual = self._obter_resolucao_mestra_projeto(nome)
            sugerida = (
                atual
                or self._obter_resolucao_camera_real()
                or self._obter_resolucao_edicao_atual()
                or (1920, 1080)
            )
            texto = simpledialog.askstring(
                "Resolução mestre do projeto",
                (
                    f"Projeto: {nome}\n\n"
                    "Informe a resolução que a câmera deverá usar sempre que "
                    "este projeto for carregado.\n\n"
                    "Exemplos: 640x480, 1280x720, 1920x1080"
                ),
                initialvalue=f"{sugerida[0]}x{sugerida[1]}",
                parent=janela,
            )
            if texto is None:
                return

            resolucao = normalizar_resolucao_mestra(texto)
            if resolucao is None:
                messagebox.showwarning(
                    "Resolução inválida",
                    "Use o formato LARGURAxALTURA, por exemplo 640x480.",
                    parent=janela,
                )
                return

            if not self._salvar_resolucao_mestra_do_projeto_atual(
                nome,
                resolucao,
            ):
                messagebox.showerror(
                    "Falha ao salvar",
                    "Não foi possível salvar a resolução mestre do projeto.",
                    parent=janela,
                )
                return

            atualizar_texto()
            if nome == getattr(self, "projeto_led_ativo", None):
                reiniciou = self._aplicar_resolucao_mestra_projeto(
                    nome,
                    reiniciar_se_necessario=True,
                )
                sufixo = (
                    " A câmera está sendo reiniciada nesse modo."
                    if reiniciou
                    else " A câmera já está nesse modo; não foi reiniciada."
                )
            else:
                sufixo = ""

            messagebox.showinfo(
                "Resolução mestre",
                (
                    f"Projeto {nome}: resolução mestre definida como "
                    f"{resolucao[0]}x{resolucao[1]}.{sufixo}"
                ),
                parent=janela,
            )

        botao = tk.Button(
            frame_acoes,
            text="▣  Resolução mestre",
            command=definir_resolucao,
            font=("Segoe UI", 9, "bold"),
            bg="#3D2F0B",
            fg="#FDE68A",
            activebackground="#5A430C",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            padx=12,
            pady=8,
            cursor="hand2",
            anchor="w",
        )
        botao._odin_master_resolution_button = True
        botao.pack(
            fill=tk.X,
            pady=(0, 7),
            before=botao_referencia,
        )
        lista.bind("<<ListboxSelect>>", atualizar_texto, add="+")
        atualizar_texto()

    def _selecionar_projeto_led_existente(self, projetos: list[str]):
        self.root.after(
            20,
            self._instalar_botao_resolucao_mestra_carregar_leds,
        )
        selecionado = super()._selecionar_projeto_led_existente(projetos)
        self._ultimo_projeto_escolhido_carregar_leds = selecionado
        return selecionado

    def carregar_leds_fixos(self) -> None:
        self._ultimo_projeto_escolhido_carregar_leds = None
        resultado = super().carregar_leds_fixos()
        nome = self._ultimo_projeto_escolhido_carregar_leds
        if nome is None:
            return resultado

        reiniciou = self._aplicar_resolucao_mestra_projeto(
            nome,
            reiniciar_se_necessario=True,
        )
        resolucao = self._resolucao_mestra_projeto_ativa
        if resolucao is not None:
            try:
                if reiniciou:
                    self.view.atualizar_status(
                        f"Projeto {nome}: ajustando câmera para a resolução "
                        f"mestre {resolucao[0]}x{resolucao[1]}..."
                    )
            except Exception:
                pass
        return resultado

    def _resolucao_mestra_compativel_com_frame_producao(self) -> bool:
        mestre = self._resolucao_mestra_producao
        if mestre is None:
            mestre = self._resolucao_mestra_projeto_ativa
        if mestre is None:
            return True
        atual = self._resolucao_frame(getattr(self, "camera_frame_atual", None))
        return atual is None or atual == mestre

    def _mostrar_erro_resolucao_mestra_producao(self) -> None:
        mestre = self._resolucao_mestra_producao or self._resolucao_mestra_projeto_ativa
        atual = self._resolucao_frame(getattr(self, "camera_frame_atual", None))
        if mestre is None:
            return
        texto_atual = "sem frame" if atual is None else f"{atual[0]}x{atual[1]}"
        mensagem = (
            "RESOLUÇÃO DA CÂMERA ALTERADA\n"
            f"Projeto: {mestre[0]}x{mestre[1]} | Câmera: {texto_atual}"
        )
        janela = getattr(self, "operacao_window", None)
        if janela is not None:
            try:
                janela.show_error(
                    mensagem,
                    total=int(getattr(self, "operacao_total", 0)),
                    ok_count=int(getattr(self, "operacao_ok", 0)),
                    ng_count=int(getattr(self, "operacao_ng", 0)),
                )
                janela.set_preview_status(
                    "Frame rejeitado • resolução fora do projeto",
                    "#FCA5A5",
                )
            except Exception:
                pass
        engine = getattr(self, "operacao_engine", None)
        invalidate = getattr(engine, "invalidate", None)
        if callable(invalidate):
            invalidate()

    def abrir_tela_operacao(self) -> None:
        self._resolucao_mestra_producao = (
            self._atualizar_resolucao_mestra_projeto_ativa()
        )
        self._aplicar_resolucao_mestra_projeto(
            getattr(self, "projeto_led_ativo", None),
            reiniciar_se_necessario=True,
        )
        service = getattr(self, "camera_service", None)
        self._travar_servico_na_resolucao_mestra(
            service,
            self._resolucao_mestra_producao,
        )
        return super().abrir_tela_operacao()

    def preparar_tela_operacao(self) -> None:
        if (
            bool(getattr(self, "operacao_ativa", False))
            and not self._resolucao_mestra_compativel_com_frame_producao()
        ):
            self._mostrar_erro_resolucao_mestra_producao()
            return
        return super().preparar_tela_operacao()

    def disparar_inspecao_operacao(self) -> None:
        if (
            bool(getattr(self, "operacao_ativa", False))
            and not self._resolucao_mestra_compativel_com_frame_producao()
        ):
            self._mostrar_erro_resolucao_mestra_producao()
            return
        return super().disparar_inspecao_operacao()

    def _synchronize_masks_with_current_frame(
        self,
        force: bool = False,
        schedule_operation_prepare: bool = True,
    ) -> None:
        if (
            bool(getattr(self, "operacao_ativa", False))
            and not self._resolucao_mestra_compativel_com_frame_producao()
        ):
            return
        return super()._synchronize_masks_with_current_frame(
            force=force,
            schedule_operation_prepare=schedule_operation_prepare,
        )
