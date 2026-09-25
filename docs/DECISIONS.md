# Decisões Arquiteturais do ODIN

Este arquivo registra decisões duradouras para impedir que agentes futuros reabram discussões já resolvidas sem nova evidência.

Uma decisão pode ser substituída, mas deve ser marcada como **Superseded** e apontar para a nova decisão.

---

## D-001 — Plataforma desktop Windows/Linux

**Status:** Accepted

O ODIN tem como plataformas alvo Windows e Linux desktop.

Raspberry Pi não é mais plataforma suportada. Nomes e classes Raspberry existentes são legado de implementação e serão migrados de forma incremental.

Consequência: novas funcionalidades não devem depender de GPIO/Raspberry salvo pedido explícito.

---

## D-002 — F2 e F3 são domínios operacionais isolados

**Status:** Accepted

F2 e F3 podem compartilhar infraestrutura e primitivas de visão, mas não devem compartilhar implicitamente state machine, contadores, resultado, debounce ou autoridade operacional.

---

## D-003 — Single Owner para responsabilidades críticas

**Status:** Accepted

Captura, scheduler, análise, tracking, presença, energia, state machine, persistência e apresentação devem convergir para proprietários canônicos claros.

Novas autoridades paralelas não são aceitas como solução permanente.

---

## D-004 — Tkinter é somente apresentação/interação

**Status:** Accepted

O main thread do Tkinter não deve executar processamento pesado de visão computacional.

Workers não podem manipular widgets Tk diretamente.

---

## D-005 — Latest-frame-wins

**Status:** Accepted

Pipelines de câmera ao vivo não devem criar backlog histórico de frames.

Quando análise está ocupada, somente o frame pendente mais recente é preservado.

---

## D-006 — Concorrência pesada limitada

**Status:** Accepted

O F3 possui como proprietário canônico de trabalho pesado o
`F3HeavyVisionExecutor`, em `src/platform/display_f3_heavy_executor.py`.

Contratos aceitos:

- um único worker por aplicação;
- máximo de um job pesado ativo;
- fila pendente limitada;
- prioridades `HIGH`, `NORMAL` e `LOW`;
- backpressure sem fila histórica ilimitada;
- cancelamento de jobs pendentes por proprietário;
- lifecycle ligado à aplicação;
- workers não manipulam Tkinter.

`NORMAL` é usado pela análise manual do CHECK atual. `LOW` é usado por
previews/configuração e DEBUG completo. `HIGH` é reservado para a análise
operacional e será conectado ao runtime pelo coordenador da Etapa 4.

Novos trabalhos pesados assíncronos do F3 não devem criar threads próprias fora
desse executor.

---

## D-007 — Patch sobre patch não é arquitetura final

**Status:** Accepted

Módulos `fix/v2/final/authority/compat/guard` existentes podem permanecer durante migração, mas uma nova correção deve preferir o proprietário canônico.

Soluções temporárias precisam de plano de consolidação e remoção do caminho substituído.

---

## D-008 — Debug é observador

**Status:** Accepted

Debug técnico, overlays informativos e telemetria não podem alterar OK/NG, sequência de CHECKS, debounce ou rearme.

O custo do debug deve ocorrer sob demanda sempre que possível.

---

## D-009 — Desenvolvimento por etapas com OK

**Status:** Accepted

Quando um plano estiver dividido em etapas, apenas a etapa atual é executada.

A próxima etapa depende de confirmação explícita do usuário com **OK**.

---

## D-010 — Performance é critério de aceitação

**Status:** Accepted

Responsividade não é melhoria opcional.

Mudanças em hot paths devem ser avaliadas por métricas e invariantes definidos em `docs/PERFORMANCE.md`.

---

## D-011 — Ambiente corporativo sem dependências administrativas por padrão

**Status:** Accepted

Novas soluções devem funcionar, por padrão, sem Docker, banco local como serviço ou instalação que exija privilégios de administrador.

Exceções exigem justificativa e aprovação explícita.

---

## D-012 — Modularidade por coesão, não por quantidade de arquivos

**Status:** Accepted

Arquivos e serviços devem agrupar responsabilidades coerentes.

O projeto não deve trocar classes gigantes por centenas de microarquivos sem fronteiras claras.

---

## D-013 — Composição preferida para novas responsabilidades

**Status:** Accepted

Novos serviços de runtime devem preferir composição e contratos explícitos.

Aumentar MRO, monkey patching e instalação dinâmica de wrappers só é aceitável como ponte de migração documentada.

---

## Como adicionar uma decisão

Use:

~~~text
## D-XXX — Título

Status: Proposed | Accepted | Superseded

Contexto:
Decisão:
Consequências:
Substitui/Substituída por:
~~~

Não remova silenciosamente decisões antigas.
