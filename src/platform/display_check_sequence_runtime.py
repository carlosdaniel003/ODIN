from __future__ import annotations

from copy import deepcopy


class DisplayCheckSequenceRuntime:
    """Máquina de sequência mínima e isolada para a Produção Display F3.

    Esta classe não conhece câmera, Tkinter, Produção F2 ou GPIO. Ela mantém
    apenas a ordem dos CHECKS, o progresso da placa atual e os contadores de
    sessão do F3. A futura análise do Display chamará
    ``registrar_resultado_check`` quando o CHECK atual for validado.
    """

    EVENT_WAITING = "waiting_check"
    EVENT_ADVANCED = "check_advanced"
    EVENT_PLATE_OK = "plate_ok"
    EVENT_PLATE_NG = "plate_ng"
    EVENT_PLATE_DISCARDED = "plate_discarded"
    EVENT_NO_CHECKS = "no_checks"

    def __init__(self) -> None:
        self._checks: list[dict] = []
        self._current_index = 0
        self._completed_ids: list[str] = []
        self.total = 0
        self.ok = 0
        self.ng = 0
        self.last_result: str | None = None

    @staticmethod
    def _normalizar_checks(checks) -> list[dict]:
        resultado: list[dict] = []
        ids_usados: set[str] = set()
        for indice, check in enumerate(checks or []):
            if not isinstance(check, dict):
                continue
            check_id = str(check.get("id") or f"CHECK_{indice + 1:03d}").strip().upper()
            nome = str(check.get("name") or check_id).strip() or check_id
            if not check_id or check_id in ids_usados:
                continue
            ids_usados.add(check_id)
            resultado.append(
                {
                    "id": check_id,
                    "name": nome,
                    "order": len(resultado),
                }
            )
        return resultado

    @staticmethod
    def _assinatura(checks: list[dict]) -> tuple[tuple[str, str], ...]:
        return tuple((str(item["id"]), str(item["name"])) for item in checks)

    def configurar_checks(self, checks, reiniciar: bool = False) -> bool:
        """Atualiza a sequência e reinicia a placa se a configuração mudou."""
        novos = self._normalizar_checks(checks)
        mudou = self._assinatura(novos) != self._assinatura(self._checks)
        self._checks = novos
        if mudou or reiniciar:
            self.reiniciar_placa()
        return mudou

    def reiniciar_placa(self) -> None:
        self._current_index = 0
        self._completed_ids = []

    def _check_atual(self) -> dict | None:
        if not self._checks:
            return None
        indice = min(max(0, self._current_index), len(self._checks) - 1)
        return self._checks[indice]

    def snapshot(self) -> dict:
        atual = self._check_atual()
        concluidos = set(self._completed_ids)
        etapas = []
        for indice, check in enumerate(self._checks):
            if check["id"] in concluidos:
                estado = "completed"
            elif atual is not None and check["id"] == atual["id"]:
                estado = "current"
            else:
                estado = "pending"
            etapas.append(
                {
                    "id": check["id"],
                    "name": check["name"],
                    "order": indice,
                    "state": estado,
                }
            )
        return {
            "checks": etapas,
            "current_index": self._current_index if atual is not None else None,
            "current_check": deepcopy(atual),
            "completed_ids": tuple(self._completed_ids),
            "total": int(self.total),
            "ok": int(self.ok),
            "ng": int(self.ng),
            "last_result": self.last_result,
        }

    def registrar_resultado_check(self, aprovado: bool = True) -> dict:
        """Registra o CHECK atual e retorna um evento para a interface F3."""
        atual = self._check_atual()
        if atual is None:
            return {
                "event": self.EVENT_NO_CHECKS,
                "snapshot": self.snapshot(),
            }

        if not bool(aprovado):
            falhou = deepcopy(atual)
            concluidos = tuple(self._completed_ids)
            self.total += 1
            self.ng += 1
            self.last_result = "NG"
            self.reiniciar_placa()
            return {
                "event": self.EVENT_PLATE_NG,
                "failed_check": falhou,
                "completed_ids": concluidos,
                "snapshot": self.snapshot(),
            }

        self._completed_ids.append(str(atual["id"]))
        concluido = deepcopy(atual)

        if self._current_index + 1 < len(self._checks):
            self._current_index += 1
            return {
                "event": self.EVENT_ADVANCED,
                "completed_check": concluido,
                "snapshot": self.snapshot(),
            }

        concluidos = tuple(self._completed_ids)
        self.total += 1
        self.ok += 1
        self.last_result = "OK"
        self.reiniciar_placa()
        return {
            "event": self.EVENT_PLATE_OK,
            "completed_check": concluido,
            "completed_ids": concluidos,
            "snapshot": self.snapshot(),
        }

    def descartar_placa(self) -> dict:
        """Descarta a placa atual, soma NG e volta imediatamente ao primeiro CHECK."""
        atual = deepcopy(self._check_atual())
        concluidos = tuple(self._completed_ids)
        self.total += 1
        self.ng += 1

        # O descarte continua sendo contabilizado como NG, mas não deve alimentar
        # a memória visual de "última placa analisada". O operador acabou de
        # descartar justamente a placa corrente; depois do card PLACA DESCARTADA
        # o F3 deve seguir direto para o rearmamento físico, sem exibir de novo
        # "PLACA JÁ ANALISADA / COLOQUE OUTRA PLACA".
        self.last_result = None
        self.reiniciar_placa()
        return {
            "event": self.EVENT_PLATE_DISCARDED,
            "discarded_at_check": atual,
            "completed_ids": concluidos,
            "snapshot": self.snapshot(),
        }


# Extensões instaladas somente no contexto Display/F3.
import src.platform.display_reference_learning  # noqa: E402,F401
import src.platform.display_reference_learning_guard  # noqa: E402,F401
import src.platform.display_live_roi_overlay  # noqa: E402,F401
import src.platform.display_manual_transition_guard  # noqa: E402,F401
import src.platform.display_editor_performance  # noqa: E402,F401
