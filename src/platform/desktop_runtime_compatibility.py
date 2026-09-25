from __future__ import annotations

import tkinter as tk

from config import MAX_RADIUS_PX, MIN_RADIUS_PX
from src.models.led_selection import LedSelection


DESKTOP_CAMERA_FPS = 30


class DesktopRuntimeCompatibilityMixin:
    """Correções de interação, projetos e rotação exclusivas do desktop."""

    def __init__(self, *args, **kwargs) -> None:
        self._renderizando_resultado_azul = False
        super().__init__(*args, **kwargs)
        self._fixar_camera_em_30_fps()

    def _fixar_camera_em_30_fps(self) -> None:
        """Migra configurações antigas em AUTO/15 FPS para 30 FPS manual."""
        configuracoes = dict(getattr(self, "configuracoes_camera", {}) or {})
        alterado = (
            str(configuracoes.get("fps_mode", "")).lower() != "manual"
            or int(configuracoes.get("fps", 0) or 0) != DESKTOP_CAMERA_FPS
        )
        configuracoes["fps_mode"] = "manual"
        configuracoes["fps"] = DESKTOP_CAMERA_FPS
        self.configuracoes_camera = configuracoes

        if not alterado:
            return

        try:
            self.configuracao_atual = (
                self.config_repository.salvar_configuracoes_sistema(
                    salvar_resultados_analise=self.salvar_resultados_analise,
                    raio_atual_px=self.raio_atual_px,
                    configuracoes_camera=configuracoes,
                )
            )
            self.configuracoes_camera = (
                self.config_repository.obter_configuracoes_camera()
            )
        except Exception:
            # A câmera ainda será aberta em 30 FPS pelo perfil desktop mesmo
            # se o arquivo estiver temporariamente sem permissão de escrita.
            self.configuracoes_camera = configuracoes

    @staticmethod
    def _iterar_widgets(widget):
        yield widget
        try:
            filhos = widget.winfo_children()
        except tk.TclError:
            filhos = ()
        for filho in filhos:
            yield from DesktopRuntimeCompatibilityMixin._iterar_widgets(filho)

    def abrir_configuracoes(self) -> None:
        super().abrir_configuracoes()

        # Mantém o nome da configuração alinhado ao comportamento real: somente
        # fotografias NG, tanto no desenvolvimento quanto na Produção F2.
        try:
            for janela in self.root.winfo_children():
                if not isinstance(janela, tk.Toplevel):
                    continue
                try:
                    if janela.title() != "Configurações - ODIN":
                        continue
                except tk.TclError:
                    continue

                for widget in self._iterar_widgets(janela):
                    if isinstance(widget, tk.Checkbutton):
                        try:
                            texto = str(widget.cget("text"))
                        except tk.TclError:
                            continue
                        if texto == "Salvar resultados da análise automaticamente":
                            widget.configure(
                                text=(
                                    "Salvar fotos de placas NG automaticamente "
                                    "(Produção F2 e desenvolvimento)"
                                )
                            )
                    elif isinstance(widget, tk.Label):
                        try:
                            texto = str(widget.cget("text"))
                        except tk.TclError:
                            continue
                        if texto.startswith("Com a opção desativada"):
                            widget.configure(
                                text=(
                                    "Quando ativado, somente placas NG geram uma "
                                    "fotografia em data/resultados/ng. Placas OK "
                                    "não são gravadas."
                                )
                            )
                break
        except tk.TclError:
            pass

    def analisar_led_selecionado(self) -> None:
        # O fluxo base cria uma visualização vermelha. No perfil desktop ela é
        # substituída, após a análise, pela mesma placa com os pontos NG em azul.
        if self._renderizando_resultado_azul:
            return super().analisar_led_selecionado()

        resultados_antes = getattr(self, "resultados_led_atual", None)
        self._renderizando_resultado_azul = True
        try:
            retorno = super().analisar_led_selecionado()
        finally:
            self._renderizando_resultado_azul = False

        resultados = getattr(self, "resultados_led_atual", None)
        imagem_original = getattr(self, "imagem_original", None)
        resultado_novo = resultados is not resultados_antes and bool(resultados)

        if (
            resultado_novo
            and imagem_original is not None
            and getattr(imagem_original, "size", 0) > 0
        ):
            try:
                imagem_visual = (
                    self.result_repository.criar_visualizacao_ng(
                        imagem_original,
                        resultados,
                    )
                )
                self.view.preparar_imagem_para_exibicao(imagem_visual)
                self.view.desenhar_canvas(
                    self.leds_selecionados,
                    resultados,
                )
            except Exception:
                pass

        return retorno

    @staticmethod
    def _copiar_led(led: LedSelection) -> LedSelection:
        return LedSelection(
            id=str(led.id),
            centro_x=int(led.centro_x),
            centro_y=int(led.centro_y),
            raio=int(led.raio),
            centro_x_normalizado=led.centro_x_normalizado,
            centro_y_normalizado=led.centro_y_normalizado,
            raio_normalizado=led.raio_normalizado,
            largura_base=led.largura_base,
            altura_base=led.altura_base,
        )

    def _restaurar_interacao_parametrizacao(self) -> None:
        janela_operacao = getattr(self, "operacao_window", None)
        if janela_operacao is not None:
            try:
                janela_operacao.hide()
            except Exception:
                pass

        try:
            self.root.configure(cursor="")
        except tk.TclError:
            pass

        try:
            self.root.update_idletasks()
            canvas = getattr(self.view, "canvas", None)
            if canvas is not None:
                canvas.focus_set()
            else:
                self.root.focus_force()
        except tk.TclError:
            pass

    def fechar_tela_operacao(self) -> None:
        super().fechar_tela_operacao()
        try:
            self.root.after_idle(self._restaurar_interacao_parametrizacao)
        except tk.TclError:
            pass

    def carregar_leds_fixos(self) -> None:
        """Fecha a gestão após Adicionar e inicia imediatamente a seleção."""
        repository = self.config_repository
        adicionar_original = repository.adicionar_projeto_led

        def adicionar_e_avancar(nome_projeto: str) -> bool:
            criado = adicionar_original(nome_projeto)
            if not criado:
                return False

            for widget in self.root.winfo_children():
                if not isinstance(widget, tk.Toplevel):
                    continue
                try:
                    if widget.title() != "Gerenciar configurações de LEDs":
                        continue
                except tk.TclError:
                    continue

                def fechar_gestao(janela=widget) -> None:
                    try:
                        janela.grab_release()
                    except tk.TclError:
                        pass
                    try:
                        janela.destroy()
                    except tk.TclError:
                        pass

                widget.after_idle(fechar_gestao)
                break

            return True

        repository.adicionar_projeto_led = adicionar_e_avancar
        try:
            super().carregar_leds_fixos()
        finally:
            repository.adicionar_projeto_led = adicionar_original

    def _capturar_mascaras_para_rotacao(self):
        if not getattr(self, "camera_ativa", False):
            return None

        frame = getattr(self, "camera_frame_atual", None)
        if frame is None or getattr(frame, "size", 0) == 0:
            return None

        altura, largura = frame.shape[:2]
        if largura <= 0 or altura <= 0:
            return None

        origem = list(getattr(self, "leds_manuais_camera", []) or ())
        if not origem:
            origem = list(getattr(self, "leds_selecionados", []) or ())

        if not origem:
            origem = self.config_repository.carregar_leds_fixos()
            origem = [
                led.adaptar_para_resolucao(
                    largura_destino=largura,
                    altura_destino=altura,
                    raio_minimo=MIN_RADIUS_PX,
                    raio_maximo=MAX_RADIUS_PX,
                )
                for led in origem
            ]

        if not origem:
            return None

        return (
            [self._copiar_led(led) for led in origem],
            int(largura),
            int(altura),
        )

    @staticmethod
    def _rotacionar_mascaras(
        leds: list[LedSelection],
        largura: int,
        altura: int,
        rotacao_anterior: int,
        rotacao_atual: int,
    ) -> tuple[list[LedSelection], int, int]:
        delta = (int(rotacao_atual) - int(rotacao_anterior)) % 360
        if delta not in (0, 90, 180, 270):
            return leds, largura, altura

        if delta in (90, 270):
            nova_largura, nova_altura = altura, largura
        else:
            nova_largura, nova_altura = largura, altura

        transformados: list[LedSelection] = []
        for led in leds:
            x = int(led.centro_x)
            y = int(led.centro_y)

            if delta == 90:
                novo_x = altura - 1 - y
                novo_y = x
            elif delta == 180:
                novo_x = largura - 1 - x
                novo_y = altura - 1 - y
            elif delta == 270:
                novo_x = y
                novo_y = largura - 1 - x
            else:
                novo_x = x
                novo_y = y

            novo_x = min(nova_largura - 1, max(0, novo_x))
            novo_y = min(nova_altura - 1, max(0, novo_y))
            raio = min(
                MAX_RADIUS_PX,
                max(MIN_RADIUS_PX, int(led.raio)),
            )

            transformados.append(
                LedSelection(
                    id=str(led.id),
                    centro_x=novo_x,
                    centro_y=novo_y,
                    raio=raio,
                ).com_normalizacao(
                    largura_base=nova_largura,
                    altura_base=nova_altura,
                )
            )

        return transformados, nova_largura, nova_altura

    def salvar_configuracoes_sistema(
        self,
        salvar_resultados_analise: bool,
        raio_configurado_px: int | None = None,
        configuracoes_camera: dict | None = None,
    ) -> None:
        rotacao_anterior = int(
            (getattr(self, "configuracoes_camera", {}) or {}).get(
                "rotation",
                0,
            )
        )
        configuracoes_camera = dict(configuracoes_camera or {})
        configuracoes_camera["fps_mode"] = "manual"
        configuracoes_camera["fps"] = DESKTOP_CAMERA_FPS
        rotacao_solicitada = int(
            configuracoes_camera.get(
                "rotation",
                rotacao_anterior,
            )
        )
        captura_mascaras = (
            self._capturar_mascaras_para_rotacao()
            if rotacao_solicitada != rotacao_anterior
            else None
        )

        super().salvar_configuracoes_sistema(
            salvar_resultados_analise=salvar_resultados_analise,
            raio_configurado_px=raio_configurado_px,
            configuracoes_camera=configuracoes_camera,
        )

        if captura_mascaras is None:
            return

        leds, largura, altura = captura_mascaras
        transformados, nova_largura, nova_altura = self._rotacionar_mascaras(
            leds=leds,
            largura=largura,
            altura=altura,
            rotacao_anterior=rotacao_anterior,
            rotacao_atual=rotacao_solicitada,
        )
        if not transformados:
            return

        projeto = getattr(self, "projeto_led_ativo", None)
        if not projeto:
            projeto = self.config_repository.obter_projeto_led_ativo()

        self.config_repository.salvar_leds_fixos_por_projeto(
            leds_fixos=transformados,
            largura_base=nova_largura,
            altura_base=nova_altura,
            projeto=projeto,
        )

        self.leds_fixos_configurados = (
            self.config_repository.carregar_leds_fixos(projeto=projeto)
        )
        self.leds_selecionados = [
            self._copiar_led(led)
            for led in transformados
        ]
        self.leds_manuais_camera = []
        self.guias_leds_fixos_visiveis = True
        self.selecao_manual_camera_ativa = False
        self.resultados_led_atual = []
        self.view.selecao_manual_camera_visivel = False
        self.view.atualizar_estado_selecao_led(False)
        self.view.atualizar_faixa_resultado()
        self.view.atualizar_status(
            f"Rotação alterada para {rotacao_solicitada}°. "
            f"As {len(transformados)} máscaras do projeto ativo foram "
            "reposicionadas e salvas automaticamente."
        )


# Nome canônico desktop; implementação única preservada durante a migração.
DesktopRuntimeCompatibilityMixin = DesktopRuntimeCompatibilityMixin

