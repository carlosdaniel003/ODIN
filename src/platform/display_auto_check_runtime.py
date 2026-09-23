from __future__ import annotations

from copy import deepcopy

from src.platform.display_auto_check_analyzer import DisplayAutomaticCheckAnalyzer
from src.platform.display_auto_check_policy import (
    DISPLAY_AUTO_DECISION_NG,
    DISPLAY_AUTO_DECISION_OK,
    DISPLAY_AUTO_DECISION_SEARCHING,
    DISPLAY_AUTO_MIN_CONFIDENCE,
    decidir_analise_display_f3,
)
from src.platform.display_project_repository import (
    DISPLAY_CHECK_STATE_OFF,
    DISPLAY_CHECK_STATE_ON,
)


class DisplayAutomaticCheckF3Mixin:
    """Liga a análise automática somente ao loop de preview da Produção Display."""

    # Sobrescreve apenas o intervalo do F3 automático pelo MRO. O F2 não usa
    # este mixin e mantém seu próprio ritmo de captura/renderização.
    DISPLAY_F3_PREVIEW_INTERVAL_MS = 45

    # H1 precisa ser rápido, mas ainda exige dois frames consecutivos. Bluetooth
    # é um evento transitório/piscante e é confirmado na primeira leitura OK.
    # NG continua deliberadamente mais conservador.
    DISPLAY_AUTO_OK_STABLE_FRAMES = 2
    DISPLAY_AUTO_NG_STABLE_FRAMES = 6
    DISPLAY_AUTO_TRANSITION_FRAMES = 1
    DISPLAY_AUTO_TRANSIENT_CHECK_NAMES = frozenset(
        {"BLUETOOTH", "BLUE", "BT"}
    )
    DISPLAY_AUTO_MANUAL_TRANSITION_SOURCE_NAMES = frozenset(
        {"BLUETOOTH", "BLUE", "BT", "USB"}
    )

    def __init__(self, *args, **kwargs) -> None:
        self._display_auto_analyzer = None
        self._display_auto_signature = None
        self._display_auto_last_decision = None
        self._display_auto_stable_frames = 0
        self._display_auto_transition_frames = self.DISPLAY_AUTO_TRANSITION_FRAMES
        self._display_auto_last_frame_token = None
        self._display_auto_last_analysis = None
        self._display_auto_manual_entry_signature = None
        self._display_auto_manual_entry_label = ""
        self._display_auto_intermittent_signature = None
        self._display_auto_intermittent_seen_on = set()
        self._display_f3_pending_ng_frame = None
        self._display_f3_pending_ng_frame_id = None
        self._display_f3_pending_ng_analysis = None
        self._display_f3_pending_ng_context = None
        self._display_f3_pending_ng_runtime = None
        super().__init__(*args, **kwargs)
        self._rebuild_display_auto_analyzer()

    def _rebuild_display_auto_analyzer(self) -> None:
        repository = getattr(self, "display_project_repository", None)
        self._display_auto_analyzer = (
            DisplayAutomaticCheckAnalyzer(repository)
            if repository is not None
            else None
        )
        self._reset_display_auto_stability()

    def _reset_display_auto_stability(self, transition: bool = True) -> None:
        self._display_auto_signature = None
        self._display_auto_last_decision = None
        self._display_auto_stable_frames = 0
        self._display_auto_last_frame_token = None
        self._display_auto_last_analysis = None
        self._display_auto_intermittent_signature = None
        self._display_auto_intermittent_seen_on = set()
        self._display_f3_pending_ng_frame = None
        self._display_f3_pending_ng_frame_id = None
        self._display_f3_pending_ng_analysis = None
        self._display_f3_pending_ng_context = None
        self._display_f3_pending_ng_runtime = None
        self._display_auto_transition_frames = (
            self.DISPLAY_AUTO_TRANSITION_FRAMES if transition else 0
        )

    def _display_auto_clear_manual_entry_gate(self) -> None:
        self._display_auto_manual_entry_signature = None
        self._display_auto_manual_entry_label = ""

    def _display_auto_frame_token(self, frame):
        camera_token = getattr(self, "camera_ultimo_frame_id", None)
        if isinstance(camera_token, int) and camera_token >= 0:
            return ("camera", int(camera_token))
        return ("object", id(frame))

    def _display_auto_set_preview_status(self, text: str, color: str) -> None:
        window = getattr(self, "display_f3_window", None)
        if window is None:
            return
        try:
            window.set_preview_status(str(text), str(color))
        except Exception:
            pass

    def _display_auto_configuration_open(self) -> bool:
        window = getattr(self, "_display_project_config_window", None)
        if window is None:
            return False
        try:
            return bool(window.visible)
        except Exception:
            return False

    @staticmethod
    def _display_auto_reason_text(reason: str) -> str:
        messages = {
            "camera_sem_frame": "Aguardando imagem da câmera",
            "camera_sem_frame_visual": "Aguardando imagem visual válida",
            "projeto_display_inexistente": "Selecione um Projeto Display",
            "check_display_inexistente": "CHECK atual não encontrado",
            "resolucao_mestra_ausente": "Defina a resolução mestre",
            "check_sem_mascaras_ativas": "CHECK sem máscaras ACESO/APAGADO",
            "aprendizado_incompleto": "Configure aprendizado ACESO e APAGADO",
            "mascara_visual_nao_encontrada": "Máscara do CHECK não encontrada",
            "mascara_invalida": "Máscara inválida para análise",
            "mascara_fora_do_frame": "Máscara fora da imagem",
        }
        return messages.get(str(reason), str(reason).replace("_", " "))

    @staticmethod
    def _display_auto_searching_text(reason: str) -> str:
        messages = {
            "aguardando_referencia_h1": "buscando referência H1 válida",
            "classificacao_incerta": "leitura incerta • continuando busca",
            "aguardando_evidencia_placa_ligada": (
                "buscando segmento aceso para confirmar placa ligada"
            ),
            "aguardando_estado_do_check": "buscando estado válido do CHECK",
            "sem_resultados_de_mascara": "aguardando segmentos identificáveis",
        }
        return messages.get(str(reason), "continuando busca")

    def _display_auto_current_context(self):
        runtime = getattr(self, "display_check_runtime", None)
        repository = getattr(self, "display_project_repository", None)
        if runtime is None or repository is None:
            return None

        snapshot = runtime.snapshot()
        current = snapshot.get("current_check")
        if not isinstance(current, dict):
            return None

        project_name = repository.obter_projeto_ativo()
        if not project_name:
            return None

        check_id = str(current.get("id") or "")
        if not check_id:
            return None

        try:
            current_index = int(snapshot.get("current_index", 0) or 0)
        except (TypeError, ValueError):
            current_index = 0

        return {
            "project_name": str(project_name),
            "check_id": check_id,
            "check_name": str(current.get("name") or check_id),
            "intermittent": bool(current.get("intermittent", False)),
            "current_index": current_index,
        }

    @staticmethod
    def _display_auto_is_reference_gate(context: dict) -> bool:
        # O primeiro CHECK é protegido mesmo se o operador renomear H1.
        if int(context.get("current_index", 0) or 0) == 0:
            return True
        return str(context.get("check_name") or "").strip().upper() == "H1"

    @classmethod
    def _display_auto_normalized_check_tokens(cls, check_name: str) -> set[str]:
        name = str(check_name or "").strip().upper()
        normalized = " ".join(name.replace("-", " ").replace("_", " ").split())
        return set(normalized.split())

    @classmethod
    def _display_auto_is_transient_check(cls, context: dict) -> bool:
        """CHECK intermitente usa confirmação rápida após evidência temporal."""
        if "intermittent" in context:
            return bool(context.get("intermittent"))
        name = str(context.get("check_name") or "").strip().upper()
        normalized = " ".join(name.replace("-", " ").replace("_", " ").split())
        if normalized in cls.DISPLAY_AUTO_TRANSIENT_CHECK_NAMES:
            return True
        tokens = set(normalized.split())
        return bool(tokens.intersection(cls.DISPLAY_AUTO_TRANSIENT_CHECK_NAMES))

    @classmethod
    def _display_auto_requires_manual_transition_after(cls, check_name: str) -> bool:
        """BLUE e USB só mudam de função após o botão físico do Display."""
        tokens = cls._display_auto_normalized_check_tokens(check_name)
        return bool(tokens.intersection(cls.DISPLAY_AUTO_MANUAL_TRANSITION_SOURCE_NAMES))

    @staticmethod
    def _display_auto_has_manual_entry_evidence(analysis: dict) -> bool:
        """Confirma visualmente que a próxima função começou antes de permitir NG.

        O gate exige pelo menos um segmento esperado ACESO reconhecido como ACESO.
        Quando o CHECK também possui segmentos esperados APAGADOS, exige ao menos
        um deles reconhecido como APAGADO. Assim um frame remanescente do modo
        anterior ou um pisca intermediário não libera a reprovação do novo CHECK.
        """
        if not isinstance(analysis, dict) or not bool(analysis.get("ready")):
            return False
        if analysis.get("approved") is True and not bool(
            analysis.get("intermittent", False)
        ):
            return True

        results = [
            item
            for item in (analysis.get("mask_results") or [])
            if isinstance(item, dict)
        ]
        if not results:
            return False

        confident = []
        for item in results:
            try:
                confidence = float(item.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            if confidence >= DISPLAY_AUTO_MIN_CONFIDENCE:
                confident.append(item)

        expected_on = [
            item
            for item in results
            if str(item.get("expected")) == DISPLAY_CHECK_STATE_ON
        ]
        expected_off = [
            item
            for item in results
            if str(item.get("expected")) == DISPLAY_CHECK_STATE_OFF
        ]
        on_evidence = any(
            str(item.get("expected")) == DISPLAY_CHECK_STATE_ON
            and str(item.get("classified")) == DISPLAY_CHECK_STATE_ON
            for item in confident
        )
        if not on_evidence:
            return False

        if not expected_off:
            return True

        return any(
            str(item.get("expected")) == DISPLAY_CHECK_STATE_OFF
            and str(item.get("classified")) == DISPLAY_CHECK_STATE_OFF
            for item in confident
        )

    @staticmethod
    def _display_auto_has_reference_power_evidence(analysis: dict) -> bool:
        """H1 só pode avançar quando existir segmento esperado ACESO realmente ACESO.

        Não confia apenas em analysis['approved'], porque uma placa desligada nunca
        pode validar o primeiro CHECK por coincidência/classificação equivocada.
        """
        if not isinstance(analysis, dict) or not bool(analysis.get("ready")):
            return False

        results = [
            item
            for item in (analysis.get("mask_results") or [])
            if isinstance(item, dict)
        ]
        if not results:
            return False

        expected_on = [
            item
            for item in results
            if str(item.get("expected") or "") == DISPLAY_CHECK_STATE_ON
        ]
        if not expected_on:
            return False

        for item in expected_on:
            try:
                confidence = float(item.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            if (
                confidence >= DISPLAY_AUTO_MIN_CONFIDENCE
                and str(item.get("classified") or "") == DISPLAY_CHECK_STATE_ON
                and item.get("matched") is not False
            ):
                return True
        return False

    def _display_auto_update_intermittent_evidence(
        self,
        context: dict,
        analysis: dict,
    ) -> tuple[bool, int, int]:
        """Exige uma fase ON completa do padrão intermitente.

        Não acumula segmentos isolados entre frames. Se MASK_027 nunca acender
        junto com os demais segmentos esperados ON, o CHECK nunca ganha
        autoridade para aprovar, mesmo que cada outro segmento tenha sido visto
        aceso em momentos diferentes.
        """
        if not bool(context.get("intermittent", False)):
            return True, 0, 0

        signature = (
            str(context.get("project_name") or ""),
            str(context.get("check_id") or ""),
        )
        if getattr(self, "_display_auto_intermittent_signature", None) != signature:
            self._display_auto_intermittent_signature = signature
            self._display_auto_intermittent_seen_on = set()

        results = [
            item
            for item in (analysis.get("mask_results") or ())
            if isinstance(item, dict)
        ]
        expected_on_ids = {
            str(item.get("mask_id") or "")
            for item in results
            if str(item.get("mask_id") or "")
            and str(item.get("expected") or "") == DISPLAY_CHECK_STATE_ON
        }
        total = len(expected_on_ids)
        if total == 0:
            return True, 0, 0

        current_on_ids = set()
        for item in results:
            mask_id = str(item.get("mask_id") or "")
            if not mask_id or mask_id not in expected_on_ids:
                continue
            try:
                confidence = float(item.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            if (
                confidence >= DISPLAY_AUTO_MIN_CONFIDENCE
                and str(item.get("classified") or "") == DISPLAY_CHECK_STATE_ON
                and item.get("raw_matched") is not False
            ):
                current_on_ids.add(mask_id)

        full_on_phase_now = expected_on_ids.issubset(current_on_ids)
        if full_on_phase_now:
            # A memória só nasce de UM frame íntegro; nunca da soma de frames.
            self._display_auto_intermittent_seen_on = set(expected_on_ids)

        full_on_seen = expected_on_ids.issubset(
            set(getattr(self, "_display_auto_intermittent_seen_on", set()) or set())
        )
        observed = total if full_on_seen else len(current_on_ids)
        return bool(full_on_seen), int(observed), int(total)

    def _display_auto_arm_manual_entry_gate(
        self,
        context: dict,
        event: dict,
    ) -> None:
        # O H1 também precisa aguardar a mudança física até o Bluetooth.
        # Para os demais passos, mantemos a regra já existente BLUE→USB e USB→AUX.
        requires_gate = (
            self._display_auto_is_reference_gate(context)
            or self._display_auto_requires_manual_transition_after(
                str(context.get("check_name") or "")
            )
        )
        if not requires_gate:
            self._display_auto_clear_manual_entry_gate()
            return

        snapshot = event.get("snapshot") if isinstance(event, dict) else None
        current = snapshot.get("current_check") if isinstance(snapshot, dict) else None
        if not isinstance(current, dict):
            self._display_auto_clear_manual_entry_gate()
            return

        next_check_id = str(current.get("id") or "")
        if not next_check_id:
            self._display_auto_clear_manual_entry_gate()
            return

        self._display_auto_manual_entry_signature = (
            str(context.get("project_name") or ""),
            next_check_id,
        )
        self._display_auto_manual_entry_label = str(
            current.get("name") or next_check_id
        )

    def _process_display_auto_check(self) -> None:
        if not bool(getattr(self, "display_f3_ativo", False)):
            return

        if getattr(self, "display_f3_result_after_id", None) is not None:
            self._reset_display_auto_stability()
            return

        if self._display_auto_configuration_open():
            self._reset_display_auto_stability(transition=False)
            self._display_auto_set_preview_status(
                "AUTO PAUSADO • configuração do Display aberta",
                "#FDE68A",
            )
            return

        frame = getattr(self, "camera_frame_atual", None)
        if frame is None or getattr(frame, "size", 0) == 0:
            self._reset_display_auto_stability()
            return

        frame_token = self._display_auto_frame_token(frame)
        if frame_token == self._display_auto_last_frame_token:
            return
        self._display_auto_last_frame_token = frame_token

        context = self._display_auto_current_context()
        if context is None:
            self._reset_display_auto_stability()
            return

        reference_gate = self._display_auto_is_reference_gate(context)
        transient_check = self._display_auto_is_transient_check(context)
        signature = (
            context["project_name"],
            context["check_id"],
        )
        manual_entry_waiting = self._display_auto_manual_entry_signature == signature
        if (
            self._display_auto_manual_entry_signature is not None
            and not manual_entry_waiting
        ):
            self._display_auto_clear_manual_entry_gate()

        if signature != self._display_auto_signature:
            self._display_auto_signature = signature
            self._display_auto_intermittent_signature = (
                signature if bool(context.get("intermittent", False)) else None
            )
            self._display_auto_intermittent_seen_on = set()
            self._display_auto_last_decision = None
            self._display_auto_stable_frames = 0
            # H1 e Bluetooth são transitórios. Um CHECK protegido pelo botão
            # físico também é observado imediatamente, porém sem permitir NG
            # até surgir evidência visual da nova função.
            self._display_auto_transition_frames = (
                0
                if reference_gate or transient_check or manual_entry_waiting
                else self.DISPLAY_AUTO_TRANSITION_FRAMES
            )

        if self._display_auto_transition_frames > 0:
            self._display_auto_transition_frames -= 1
            self._display_auto_set_preview_status(
                (
                    f"AUTO • {context['check_name']} • estabilizando "
                    f"{self.DISPLAY_AUTO_TRANSITION_FRAMES - self._display_auto_transition_frames}"
                    f"/{self.DISPLAY_AUTO_TRANSITION_FRAMES}"
                ),
                "#FDE68A",
            )
            return

        analyzer = self._display_auto_analyzer
        repository = getattr(self, "display_project_repository", None)
        if analyzer is None or getattr(analyzer, "repository", None) is not repository:
            self._rebuild_display_auto_analyzer()
            analyzer = self._display_auto_analyzer
        if analyzer is None:
            return

        analysis = analyzer.analyze(
            frame=frame,
            project_name=context["project_name"],
            check_id=context["check_id"],
            visual_rotation=self._obter_rotacao_visual_display_f3(),
        )
        self._display_auto_last_analysis = analysis

        if not bool(analysis.get("ready")):
            self._display_auto_last_decision = None
            self._display_auto_stable_frames = 0
            self._display_auto_set_preview_status(
                "AUTO INDISPONÍVEL • "
                + self._display_auto_reason_text(analysis.get("reason", "")),
                "#FCA5A5",
            )
            return

        # O primeiro CHECK/H1 é a trava física do ciclo. Sem pelo menos um
        # segmento que H1 espera ACESO efetivamente classificado como ACESO,
        # não existe OK, NG nem avanço para Bluetooth/BLUE.
        if (
            reference_gate
            and not self._display_auto_has_reference_power_evidence(analysis)
        ):
            self._display_auto_last_decision = None
            self._display_auto_stable_frames = 0
            self._display_auto_set_preview_status(
                "AUTO • H1 • aguardando placa ligada / segmento aceso confirmado",
                "#FDE68A",
            )
            return

        if manual_entry_waiting:
            if not self._display_auto_has_manual_entry_evidence(analysis):
                self._display_auto_last_decision = None
                self._display_auto_stable_frames = 0
                target = self._display_auto_manual_entry_label or context["check_name"]
                self._display_auto_set_preview_status(
                    f"AUTO • {target} • aguardando botão / mudança de função",
                    "#FDE68A",
                )
                return
            self._display_auto_clear_manual_entry_gate()

        intermittent_ready, intermittent_seen, intermittent_total = (
            self._display_auto_update_intermittent_evidence(
                context,
                analysis,
            )
        )

        policy = decidir_analise_display_f3(
            analysis,
            reference_gate=reference_gate,
        )
        decision = str(policy.get("decision") or DISPLAY_AUTO_DECISION_SEARCHING)

        if (
            bool(context.get("intermittent", False))
            and decision == DISPLAY_AUTO_DECISION_OK
            and not intermittent_ready
        ):
            self._display_auto_last_decision = None
            self._display_auto_stable_frames = 0
            self._display_auto_set_preview_status(
                (
                    f"AUTO • {context['check_name']} • INTERMITENTE • "
                    f"aguardando fase ON completa "
                    f"{intermittent_seen}/{intermittent_total}"
                ),
                "#FDE68A",
            )
            return

        if decision == DISPLAY_AUTO_DECISION_SEARCHING:
            self._display_auto_last_decision = None
            self._display_auto_stable_frames = 0
            self._display_auto_set_preview_status(
                (
                    f"AUTO • {context['check_name']} • "
                    + self._display_auto_searching_text(policy.get("reason", ""))
                ),
                "#FDE68A",
            )
            return

        approved = decision == DISPLAY_AUTO_DECISION_OK
        if decision not in (DISPLAY_AUTO_DECISION_OK, DISPLAY_AUTO_DECISION_NG):
            return

        if approved == self._display_auto_last_decision:
            self._display_auto_stable_frames += 1
        else:
            self._display_auto_last_decision = approved
            self._display_auto_stable_frames = 1

        required = (
            1
            if approved and transient_check
            else (
                self.DISPLAY_AUTO_OK_STABLE_FRAMES
                if approved
                else self.DISPLAY_AUTO_NG_STABLE_FRAMES
            )
        )
        matched = int(analysis.get("matched_mask_count", 0) or 0)
        total = int(analysis.get("active_mask_count", 0) or 0)
        decision_text = "conforme" if approved else "NG confirmado"
        self._display_auto_set_preview_status(
            (
                f"AUTO • {context['check_name']} • {matched}/{total} {decision_text} • "
                f"{self._display_auto_stable_frames}/{required}"
            ),
            "#86EFAC" if approved else "#FCA5A5",
        )

        if self._display_auto_stable_frames < required:
            return

        if not approved:
            self._display_f3_pending_ng_runtime = {
                "last_decision": False,
                "stable_frames": int(self._display_auto_stable_frames),
                "required_stable_frames": int(required),
                "transition_frames": int(self._display_auto_transition_frames),
                "physical_stable_key": getattr(
                    self,
                    "_display_f3_physical_stable_key",
                    None,
                ),
                "physical_pending_key": getattr(
                    self,
                    "_display_f3_physical_pending_key",
                    None,
                ),
                "physical_pending_frames": getattr(
                    self,
                    "_display_f3_physical_pending_frames",
                    None,
                ),
                "unknown_off_pending_frames": getattr(
                    self,
                    "_display_f3_unknown_off_pending_frames",
                    None,
                ),
                "manual_entry_signature": deepcopy(
                    getattr(
                        self,
                        "_display_auto_manual_entry_signature",
                        None,
                    )
                ),
                "manual_entry_label": getattr(
                    self,
                    "_display_auto_manual_entry_label",
                    None,
                ),
                "waiting_empty_rearm": getattr(
                    self,
                    "_display_auto_waiting_empty_rearm",
                    None,
                ),
            }

        self._display_auto_stable_frames = 0
        self._display_auto_last_decision = None

        if not approved:
            # Preserva exatamente a evidência que fechou o debounce. A captura
            # pode atualizar camera_frame_atual em outra thread antes de o método
            # de resultado montar a UI, portanto não releia "o frame mais novo".
            try:
                self._display_f3_pending_ng_frame = frame.copy()
            except Exception:
                self._display_f3_pending_ng_frame = frame
            self._display_f3_pending_ng_frame_id = getattr(
                self,
                "camera_ultimo_frame_id",
                None,
            )
            self._display_f3_pending_ng_analysis = deepcopy(analysis)
            self._display_f3_pending_ng_context = deepcopy(context)

        event = self.registrar_resultado_check_display_f3(approved)
        event_type = str(event.get("event", ""))
        if event_type == "check_advanced":
            self._display_auto_arm_manual_entry_gate(context, event)
            self._display_auto_signature = None
            self._display_auto_transition_frames = self.DISPLAY_AUTO_TRANSITION_FRAMES
        else:
            self._display_auto_clear_manual_entry_gate()
            self._reset_display_auto_stability()

    def _atualizar_preview_display_f3(self) -> None:
        super()._atualizar_preview_display_f3()
        self._process_display_auto_check()
