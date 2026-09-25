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
previews/configuração e DEBUG completo. `HIGH` permanece reservado para compute
operacional puro. A Etapa 5 consolidou os proprietários stateful; isso autoriza
offloads futuros somente quando o trabalho puder ser expresso como request/result
sem manipular Tkinter ou state machine no worker.

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

## D-014 — F3RuntimeCoordinator é o proprietário do scheduler F3

**Status:** Accepted

O `F3RuntimeCoordinator`, em
`src/platform/display_f3_runtime_coordinator.py`, é o proprietário canônico do
scheduler periódico da Produção Display F3.

No produto:

- somente o coordenador agenda o próximo tick do F3 via `root.after()`;
- chamadas históricas a `_agendar_preview_display_f3` delegam ao coordenador;
- frame repetido não percorre novamente o pipeline pesado;
- CONFIGURAR usa cadência de fundo;
- resultado/rearme e tracking pendente permanecem observáveis pelo coordenador;
- callbacks caros recebem uma janela de idle antes do próximo tick;
- a antiga cadência adaptativa e o wrapper final de responsividade não são
  instalados como autoridades concorrentes.

O fallback de scheduling no método base continua temporariamente para testes e
composições que não executam o bootstrap final; ele não é a autoridade do runtime
de produto.

O coordenador orquestra. Ele não implementa algoritmos de tracking, presença,
energia, análise de CHECK ou state machine.

---

## D-015 — F3RuntimeAuthorities é a composição canônica das autoridades F3

**Status:** Accepted

`F3RuntimeAuthorities`, em
`src/platform/display_f3_runtime_authorities.py`, registra os proprietários
canônicos de tracking, presença, energia, análise de CHECK e máquina de sequência.

Proprietários:

~~~text
tracking       F3TrackingAuthority
presença       F3PresenceAuthority
energia        F3PowerAuthority
check analyzer F3CheckAnalyzerAuthority
sequência      F3StateMachineAuthority
~~~

Consequências:

- consumidores não devem criar uma segunda memória/autoridade para essas
  responsabilidades;
- builders históricos de estado físico/operacional funcionam como adapters e
  recebem o mesmo snapshot canônico cacheado por frame/contexto;
- energia depende da resposta de presença e não pode promovê-la implicitamente;
- mutações de sequência passam pela facade canônica quando instalada;
- caches e latches canônicos são invalidados em abertura, fechamento e rearme;
- módulos históricos podem continuar fornecendo primitivas de visão e
  compatibilidade até a auditoria de resíduos da Etapa 7;
- consolidar autoridade não significa executar automaticamente todo o pipeline
  em worker. Compute pesado só pode ir ao executor quando estiver separado de
  Tkinter e das mutações stateful.

---

## D-016 — DesktopProductionApp é a composição canônica do produto

**Status:** Accepted

O produto Windows/Linux é iniciado por:

~~~text
main.py
  -> main_desktop.py
  -> DesktopProductionApp
~~~

A composição base é:

~~~text
DesktopProductionApp
  -> DesktopBaseODINApp
  -> DesktopODINApp
~~~

Consequências:

- `main_rpi.py` é somente launcher de compatibilidade;
- `RaspberryPi3ProductionApp` e `RaspberryPi3ODINApp` são aliases para as
  classes Desktop;
- a câmera é selecionada por `CAMERA_SERVICE_CLASS`, não por monkey patch de
  variável global em módulo Raspberry;
- o caminho canônico importa somente módulos Desktop/genéricos e não depende de
  GPIO;
- projetos, editor de máscaras e métricas que antes estavam acoplados à classe
  GPIO foram preservados em `DesktopBaseODINApp`;
- aliases Raspberry de câmera/thread permanecem temporariamente para consumidores
  históricos;
- remoção física dos shims/aliases e código GPIO legado pertence à Etapa 7.

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
