from __future__ import annotations

from copy import deepcopy
import tkinter as tk

from src.platform.display_check_sequence_runtime import DisplayCheckSequenceRuntime
from src.platform.display_production_f3_window import DisplayProductionF3Window
from src.platform.display_project_config import DisplayProjectConfigWindow
from src.platform.display_project_repository import (
    DisplayProjectRepository,
    normalizar_resolucao_display,
)
from src.platform.display_visual_rotation import obter_rotacao_visual_display
from src.platform.raspberry_pi3_settings import (
    OPERATION_PREVIEW_HEIGHT,
    OPERATION_PREVIEW_WIDTH,
)


class DisplayProductionF3Mixin:
    """Runtime isolado da Produção Display F3.

    Projeto Display, máscaras, CHECKS, progresso operacional e contadores são
    exclusivos do F3. Nenhum estado da Produção F2 é usado para avançar a
    sequência.
    """

    DISPLAY_F3_PREVIEW_INTERVAL_MS = 90
    DISPLAY_F3_RESULT_HOLD_MS = 1200
    DISPLAY_F3_BUTTON_BG = "#0E7490"
    DISPLAY_F3_BUTTON_ACTIVE_BG = "#0891B2"

    def __init__(self, *args, **kwargs) -> None:
        self.display_f3_window: DisplayProductionF3Window | None = None
        self.display_f3_ativo = False
        self.display_f3_after_id = None
        self.display_f3_result_after_id = None
        # Evidência terminal de NG: o canvas/visor congelam no frame que
        # efetivamente fechou o debounce de reprovação. A câmera física continua
        # capturando em camera_frame_atual apenas para detectar retirada/EMPTY.
        self._display_f3_ng_evidence_frozen = False
        self._display_f3_ng_evidence_snapshot = None
        self.display_project_repository: DisplayProjectRepository | None = None
        self.display_check_runtime = DisplayCheckSequenceRuntime()
        self._display_project_config_window: DisplayProjectConfigWindow | None = None
        super().__init__(*args, **kwargs)
        self.display_project_repository = DisplayProjectRepository()
        self._instalar_modo_display_f3()
        self._atualizar_resumo_projeto_display_f3()

    def _criar_janela_producao_display_f3(self) -> DisplayProductionF3Window:
        return DisplayProductionF3Window(
            root=self.root,
            on_close=self.fechar_tela_producao_display_f3,
            on_configure=self.abrir_configuracao_projeto_display,
            on_discard=self.descartar_placa_display_f3,
            preview_width=max(480, int(OPERATION_PREVIEW_WIDTH)),
            preview_height=max(360, int(OPERATION_PREVIEW_HEIGHT)),
        )

    def _f2_esta_aberto(self) -> bool:
        if bool(getattr(self, "operacao_ativa", False)):
            return True
        janela = getattr(self, "operacao_window", None)
        if janela is None:
            return False
        try:
            return bool(janela.visible)
        except Exception:
            return False

    def _instalar_modo_display_f3(self) -> None:
        self.display_f3_window = self._criar_janela_producao_display_f3()

        self.root.bind(
            "<F3>",
            lambda _event: self.abrir_tela_producao_display_f3(),
            add="+",
        )

        parent = getattr(self.view, "frame_topo_direita", self.root)
        self.botao_operacao_display_f3 = tk.Button(
            parent,
            text="DISPLAY  F3",
            command=self.abrir_tela_producao_display_f3,
            font=("DejaVu Sans", 10, "bold"),
            bg=self.DISPLAY_F3_BUTTON_BG,
            fg="#FFFFFF",
            activebackground=self.DISPLAY_F3_BUTTON_ACTIVE_BG,
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=16,
            pady=8,
            cursor="hand2",
        )

        if parent is self.root:
            self.botao_operacao_display_f3.place(
                relx=1.0,
                x=-188,
                y=16,
                anchor="ne",
            )
            self.botao_operacao_display_f3.lift()
        else:
            self.botao_operacao_display_f3.pack(
                side=tk.RIGHT,
                padx=(0, 8),
                pady=18,
            )

    def _obter_rotacao_visual_display_f3(self) -> int:
        return obter_rotacao_visual_display(getattr(self, "view", None))

    def _obter_frame_para_configuracao_display(self):
        frame = getattr(self, "camera_frame_atual", None)
        if frame is None or getattr(frame, "size", 0) == 0:
            return None
        try:
            return frame.copy()
        except Exception:
            return frame

    def _ao_fechar_configuracao_projeto_display(self) -> None:
        self._display_project_config_window = None
        janela = self.display_f3_window
        if janela is not None and self.display_f3_ativo:
            try:
                janela.container.focus_force()
            except Exception:
                pass

    def abrir_configuracao_projeto_display(self) -> None:
        existente = self._display_project_config_window
        if existente is not None and existente.visible:
            try:
                existente.window.lift()
                existente.window.focus_force()
            except Exception:
                pass
            return

        repository = self.display_project_repository
        if repository is None:
            repository = DisplayProjectRepository()
            self.display_project_repository = repository

        self._display_project_config_window = DisplayProjectConfigWindow(
            root=self.root,
            repository=repository,
            frame_provider=self._obter_frame_para_configuracao_display,
            on_change=self._atualizar_resumo_projeto_display_f3,
            on_close=self._ao_fechar_configuracao_projeto_display,
        )

    def _renderizar_fluxo_checks_display_f3(self) -> None:
        janela = self.display_f3_window
        if janela is None:
            return
        try:
            janela.set_check_sequence(self.display_check_runtime.snapshot())
        except Exception:
            pass

    def _atualizar_resumo_projeto_display_f3(self) -> None:
        repository = self.display_project_repository
        janela = self.display_f3_window
        if repository is None or janela is None:
            return

        nome = repository.obter_projeto_ativo()
        projeto = repository.carregar_projeto(nome) if nome else None
        if projeto is None:
            self.display_check_runtime.configurar_checks([])
            try:
                janela.set_project_info(None, None, 0, 0)
                janela.set_check_sequence(self.display_check_runtime.snapshot())
            except Exception:
                pass
            return

        resolucao = normalizar_resolucao_display(
            projeto.get("master_resolution")
        )
        mascaras = projeto.get("masks", [])
        checks = projeto.get("checks", [])
        self.display_check_runtime.configurar_checks(
            checks if isinstance(checks, list) else []
        )
        try:
            janela.set_project_info(
                projeto.get("name"),
                resolucao,
                len(mascaras) if isinstance(mascaras, list) else 0,
                len(checks) if isinstance(checks, list) else 0,
            )
            janela.set_check_sequence(self.display_check_runtime.snapshot())
        except Exception:
            pass

    def _congelar_evidencia_ng_display_f3(self) -> None:
        """Congela a evidência visual do NG sem parar a aquisição da câmera."""
        if bool(getattr(self, "_display_f3_ng_evidence_frozen", False)):
            return

        janela = self.display_f3_window
        pending_frame = getattr(self, "_display_f3_pending_ng_frame", None)
        frame = (
            pending_frame
            if pending_frame is not None and getattr(pending_frame, "size", 0) > 0
            else getattr(self, "camera_frame_atual", None)
        )
        pending_analysis = getattr(self, "_display_f3_pending_ng_analysis", None)
        analysis = (
            pending_analysis
            if isinstance(pending_analysis, dict)
            else getattr(self, "_display_auto_last_analysis", None)
        )
        pending_context = getattr(self, "_display_f3_pending_ng_context", None)
        if isinstance(pending_context, dict):
            context = pending_context
        else:
            try:
                context = self._display_auto_current_context()
            except Exception:
                context = None

        # O renderer semântico consulta _display_auto_last_analysis. Reafirmamos
        # a mesma análise associada ao frame preservado antes de desenhar.
        if isinstance(analysis, dict):
            self._display_auto_last_analysis = analysis

        evidence_frame = None
        if frame is not None and getattr(frame, "size", 0) > 0:
            try:
                evidence_frame = frame.copy()
            except Exception:
                evidence_frame = frame

        # Ainda estamos no CHECK que falhou. Publicamos também o resumo de
        # máscaras usando analysis+context preservados deste MESMO frame. O
        # wrapper normal de status roda depois do processo automático e seria
        # tarde demais: nesse ponto o runtime já teria voltado internamente ao H1.
        if janela is not None and isinstance(analysis, dict) and isinstance(context, dict):
            try:
                from src.platform.display_f3_mask_status import (
                    formatar_status_mascaras_f3,
                )

                mask_text, mask_color = formatar_status_mascaras_f3(
                    analysis,
                    context,
                )
                janela.set_mask_analysis_status(mask_text, mask_color)
                self._display_f3_mask_status_snapshot = {
                    "text": mask_text,
                    "color": mask_color,
                    "check_id": str(context.get("check_id") or ""),
                    "check_name": str(context.get("check_name") or ""),
                    "ready": bool(analysis.get("ready")),
                    "approved": analysis.get("approved"),
                    "matched_mask_count": int(
                        analysis.get("matched_mask_count", 0) or 0
                    ),
                    "active_mask_count": int(
                        analysis.get("active_mask_count", 0) or 0
                    ),
                }
            except Exception:
                pass

        # Forçamos um último render antes de o runtime voltar ao H1, garantindo
        # que câmera e visor recebam exatamente as classificações/cores do frame
        # responsável pelo NG.
        if janela is not None and evidence_frame is not None:
            try:
                janela.update_camera_preview(
                    evidence_frame,
                    visual_rotation=self._obter_rotacao_visual_display_f3(),
                )
            except TypeError:
                try:
                    janela.update_camera_preview(evidence_frame)
                except Exception:
                    pass
            except Exception:
                pass

        state = getattr(self, "_display_f3_operational_state", None)
        if janela is not None and isinstance(state, dict):
            try:
                janela.set_operational_reference_status(
                    str(state.get("text") or "IDENTIFICANDO..."),
                    str(state.get("color") or "#FDE68A"),
                )
            except Exception:
                pass

        self._display_f3_ng_evidence_snapshot = {
            "analysis": deepcopy(analysis) if isinstance(analysis, dict) else None,
            "context": deepcopy(context) if isinstance(context, dict) else None,
            "operational_state": deepcopy(state) if isinstance(state, dict) else None,
        }
        self._display_f3_ng_evidence_frozen = True
        self._display_f3_pending_ng_frame = None
        self._display_f3_pending_ng_analysis = None
        self._display_f3_pending_ng_context = None

        if janela is not None:
            freeze = getattr(janela, "freeze_ng_evidence", None)
            if callable(freeze):
                try:
                    freeze()
                except Exception:
                    pass

    def _liberar_evidencia_ng_display_f3(self) -> None:
        """Libera câmera/visor somente depois que EMPTY foi confirmado."""
        if not bool(getattr(self, "_display_f3_ng_evidence_frozen", False)):
            return

        self._display_f3_ng_evidence_frozen = False
        self._display_f3_ng_evidence_snapshot = None
        self._cancelar_resultado_display_f3()

        janela = self.display_f3_window
        if janela is None:
            return

        release = getattr(janela, "release_ng_evidence", None)
        if callable(release):
            try:
                release()
            except Exception:
                pass

        # EMPTY já foi confirmado: agora sim a interface pode pedir outra placa.
        show_waiting = getattr(janela, "show_waiting_new_plate", None)
        if callable(show_waiting):
            try:
                show_waiting(self.display_check_runtime.snapshot())
                return
            except Exception:
                pass
        self._renderizar_fluxo_checks_display_f3()

    def _cancelar_resultado_display_f3(self) -> None:
        if self.display_f3_result_after_id is None:
            return
        try:
            self.root.after_cancel(self.display_f3_result_after_id)
        except Exception:
            pass
        self.display_f3_result_after_id = None

    def _retornar_ao_check_atual_display_f3(self) -> None:
        self.display_f3_result_after_id = None
        if self.display_f3_ativo:
            self._renderizar_fluxo_checks_display_f3()

    def _agendar_retorno_ao_fluxo_display_f3(self) -> None:
        self._cancelar_resultado_display_f3()
        try:
            self.display_f3_result_after_id = self.root.after(
                self.DISPLAY_F3_RESULT_HOLD_MS,
                self._retornar_ao_check_atual_display_f3,
            )
        except Exception:
            self.display_f3_result_after_id = None

    def registrar_resultado_check_display_f3(self, aprovado: bool = True) -> dict:
        """Entrada oficial para a futura detecção automática do Display."""
        if not bool(aprovado):
            # Precisa ocorrer antes de registrar o evento: registrar NG reinicia o
            # runtime no H1, e perderíamos o CHECK/cores que realmente falharam.
            self._congelar_evidencia_ng_display_f3()

        evento = self.display_check_runtime.registrar_resultado_check(aprovado)
        janela = self.display_f3_window
        tipo = str(evento.get("event", ""))
        snapshot = evento.get("snapshot", self.display_check_runtime.snapshot())

        if janela is None:
            return evento

        if tipo == DisplayCheckSequenceRuntime.EVENT_PLATE_OK:
            try:
                janela.show_plate_result(True, snapshot)
            except Exception:
                pass
            self._agendar_retorno_ao_fluxo_display_f3()
        elif tipo == DisplayCheckSequenceRuntime.EVENT_PLATE_NG:
            try:
                janela.show_plate_result(False, snapshot, discarded=False)
            except Exception:
                pass
            self._agendar_retorno_ao_fluxo_display_f3()
        else:
            self._cancelar_resultado_display_f3()
            self._renderizar_fluxo_checks_display_f3()
        return evento

    def concluir_check_display_f3(self) -> dict:
        """Atalho semântico: conclui com sucesso o CHECK atualmente aguardado."""
        return self.registrar_resultado_check_display_f3(True)

    def descartar_placa_display_f3(self) -> dict | None:
        """Tecla/botão 1: soma TOTAL+NG e reinicia no primeiro CHECK."""
        if not self.display_f3_ativo:
            return None
        if (
            bool(getattr(self, "_display_f3_ng_evidence_frozen", False))
            or bool(getattr(self, "_display_f3_waiting_empty_rearm", False))
            or bool(getattr(self, "_display_f3_waiting_new_board_after_empty", False))
        ):
            # O ciclo já terminou. Impede TOTAL/NG duplicado pela tecla 1.
            return None
        snapshot_atual = self.display_check_runtime.snapshot()
        if not snapshot_atual.get("checks"):
            return None

        evento = self.display_check_runtime.descartar_placa()
        snapshot = evento.get("snapshot", self.display_check_runtime.snapshot())
        janela = self.display_f3_window
        if janela is not None:
            try:
                janela.show_plate_result(False, snapshot, discarded=True)
            except Exception:
                pass
        self._agendar_retorno_ao_fluxo_display_f3()
        return evento

    def _ativar_tela_producao_display_f3(self) -> bool:
        self.display_f3_ativo = True
        self._cancelar_resultado_display_f3()
        self._display_f3_ng_evidence_frozen = False
        self._display_f3_ng_evidence_snapshot = None
        janela_existente = self.display_f3_window
        release = getattr(janela_existente, "release_ng_evidence", None)
        if callable(release):
            try:
                release()
            except Exception:
                pass
        self._atualizar_resumo_projeto_display_f3()
        self.display_check_runtime.reiniciar_placa()
        janela = self.display_f3_window
        if janela is not None:
            try:
                janela.show_waiting_camera()
            except Exception:
                pass
            try:
                janela.set_check_sequence(self.display_check_runtime.snapshot())
            except Exception:
                pass
            try:
                janela.show()
            except Exception:
                pass
        self._agendar_preview_display_f3(0)
        return True

    def _abrir_f3_apos_escolha_camera(self, _indice: int) -> None:
        if self._f2_esta_aberto():
            return
        try:
            self.iniciar_tela_ao_vivo()
        except Exception:
            pass
        self._ativar_tela_producao_display_f3()

    def abrir_tela_producao_display_f3(self) -> bool:
        if self.display_f3_ativo:
            janela = self.display_f3_window
            if janela is not None:
                try:
                    janela.show()
                except Exception:
                    pass
            return True

        if self._f2_esta_aberto():
            try:
                self.view.atualizar_status(
                    "Feche a Produção F2 antes de abrir a Produção Display F3."
                )
            except Exception:
                pass
            return False

        if not bool(getattr(self, "camera_ativa", False)):
            abrir_seletor = getattr(self, "abrir_seletor_camera", None)
            if callable(abrir_seletor):
                abrir_seletor(
                    ao_selecionar=self._abrir_f3_apos_escolha_camera,
                )
                return True

            try:
                self.iniciar_tela_ao_vivo()
            except Exception:
                pass

        return self._ativar_tela_producao_display_f3()

    def fechar_tela_producao_display_f3(self) -> None:
        self.display_f3_ativo = False
        self.display_check_runtime.reiniciar_placa()
        self._cancelar_resultado_display_f3()
        self._display_f3_ng_evidence_frozen = False
        self._display_f3_ng_evidence_snapshot = None
        janela_atual = self.display_f3_window
        release = getattr(janela_atual, "release_ng_evidence", None)
        if callable(release):
            try:
                release()
            except Exception:
                pass

        if self.display_f3_after_id is not None:
            try:
                self.root.after_cancel(self.display_f3_after_id)
            except Exception:
                pass
            self.display_f3_after_id = None

        configuracao = self._display_project_config_window
        if configuracao is not None and configuracao.visible:
            try:
                configuracao.close()
            except Exception:
                pass
        self._display_project_config_window = None

        janela = self.display_f3_window
        if janela is not None:
            try:
                janela.hide()
            except Exception:
                pass

        try:
            self.root.after_idle(self.root.focus_force)
        except Exception:
            pass

    def _agendar_preview_display_f3(
        self,
        atraso_ms: int | None = None,
    ) -> None:
        if not self.display_f3_ativo or self.display_f3_after_id is not None:
            return
        atraso = (
            self.DISPLAY_F3_PREVIEW_INTERVAL_MS
            if atraso_ms is None
            else max(0, int(atraso_ms))
        )
        try:
            self.display_f3_after_id = self.root.after(
                atraso,
                self._atualizar_preview_display_f3,
            )
        except Exception:
            self.display_f3_after_id = None

    def _atualizar_preview_display_f3(self) -> None:
        self.display_f3_after_id = None
        if not self.display_f3_ativo:
            return

        janela = self.display_f3_window
        frame = getattr(self, "camera_frame_atual", None)
        freeze_visual = bool(
            getattr(self, "_display_f3_ng_evidence_frozen", False)
        )
        if janela is not None and not freeze_visual:
            try:
                janela.update_camera_preview(
                    frame,
                    visual_rotation=self._obter_rotacao_visual_display_f3(),
                )
            except TypeError:
                # Compatibilidade com a interface da Fase 1 e seus testes.
                try:
                    janela.update_camera_preview(frame)
                except Exception:
                    pass
            except Exception:
                pass

        self._agendar_preview_display_f3()

    @staticmethod
    def responsabilidades_f3() -> tuple[str, ...]:
        """Contrato imutável aprovado na Fase 1."""
        return (
            "janela_f3",
            "atalho_f3",
            "preview_camera_somente_leitura",
            "ciclo_abertura_fechamento_f3",
        )

    @staticmethod
    def responsabilidades_f3_fase2() -> tuple[str, ...]:
        return (
            "projeto_display_persistente",
            "resolucao_mestra_display",
            "mascaras_display_persistentes",
        )

    @staticmethod
    def responsabilidades_f3_fase3() -> tuple[str, ...]:
        return (
            "checks_display_persistentes",
            "ordem_checks_configuravel",
            "estado_mascara_por_check",
            "editor_visual_checks",
        )

    @staticmethod
    def responsabilidades_f3_fluxo_checks() -> tuple[str, ...]:
        return (
            "sequencia_checks_em_producao",
            "contador_total_ok_ng_f3",
            "descarte_placa_tecla_1",
            "reinicio_primeiro_check",
        )
