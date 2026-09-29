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

`HIGH` é usado pelo tracking ao vivo do F3 para ORB/AKAZE, fallback por
template e warp/alinhamento. `NORMAL` é usado pela análise manual do CHECK atual.
`LOW` é usado por previews/configuração e DEBUG completo.

O job de tracking não manipula widgets Tkinter. O resultado é versionado por
geração/ciclo, jobs pendentes usam latest-frame-wins e resultados obsoletos não
são aplicados ao ciclo seguinte.

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

- a câmera é selecionada por `CAMERA_SERVICE_CLASS`;
- o caminho canônico importa somente módulos Desktop/genéricos e não depende de
  GPIO;
- projetos, editor de máscaras e métricas foram preservados em
  `DesktopBaseODINApp`;
- os bridges temporários Raspberry utilizados durante a migração foram removidos
  conforme D-017.

---

## D-017 — Resíduos Raspberry/GPIO e patches órfãos são proibidos

**Status:** Accepted

A Etapa 7 encerra os bridges temporários da migração.

Decisão:

- o produto não mantém `main_rpi.py`, classes `Raspberry*` ou infraestrutura
  GPIO;
- `gpiozero` não é dependência do produto;
- o scheduler F3 substituído não permanece como módulo de compatibilidade;
- módulos patch-like só podem permanecer se tiverem consumidor produtivo
  verificável;
- testes e workflows devem usar exclusivamente a composição Desktop.

Contratos automatizados:

~~~text
tests/test_platform_legacy_residue.py
tests/test_orphan_patch_residue.py
tests/test_desktop_composition.py
~~~

Qualquer necessidade futura de Raspberry/GPIO exige uma nova decisão
arquitetural explícita; não deve ser reintroduzida como compatibilidade informal.

---

## D-018 — Preview F3 é latest-frame e CONFIGURAR não depende de idle

**Status:** Accepted

O frame usado por um worker pesado do F3 é uma cópia de análise, não uma fonte
visual futura.

Decisão:

- `camera_frame_atual` é a única autoridade da imagem ao vivo;
- quando um job de tracking termina, seu `raw_frame` não pode substituir o
  frame atual da preview;
- resultado de tracking muito antigo não alimenta decisão produtiva;
- `CONFIGURAR` deve ser enfileirado com `after(...)`, não `after_idle()`,
  porque câmera e scheduler periódicos podem manter o Tk continuamente ocupado;
- geometria de tracking pode permanecer temporariamente enquanto um novo job
  calcula, mas nunca congela a imagem visível.

Motivação: evitar preview com vários segundos de atraso e impedir que o clique em
CONFIGURAR seja postergado indefinidamente.

---

## D-019 — DEBUG TÉCNICO F3 apresenta evidência capturada; ANALISAR inicia o relatório

**Status:** Accepted

No fluxo manual do Display F3, o clique em `ANALISAR` é o único ponto que cria
a evidência diagnóstica daquela interação.

Decisão:

- antes de alterar o próprio botão, `ANALISAR` captura um print dos pixels
  visíveis da tela PRODUÇÃO DISPLAY F3;
- o frame bruto da câmera continua sendo congelado separadamente e permanece a
  única fonte para cálculo de visão;
- o CHECK atual é submetido ao `F3HeavyVisionExecutor` como `NORMAL`;
- o relatório técnico completo do mesmo frame é enfileirado no mesmo clique
  como `LOW`;
- `DEBUG TÉCNICO` não inicia análise, matching, reconstrução de overlay, visor
  ou status; ele apenas apresenta o print e as ações de cópia;
- `COPIAR DEBUG` só é liberado quando o relatório estático fica pronto;
- `COPIAR IMAGEM` publica o print como imagem nativa no clipboard do sistema.

Consequências:

- abrir DEBUG TÉCNICO tem custo visual pequeno e previsível;
- o operador vê exatamente a tela existente no instante de ANALISAR, em vez de
  uma reconstrução posterior;
- relatório e print permanecem vinculados ao mesmo clique;
- nenhum scheduler, thread ou autoridade produtiva adicional é criado;
- D-008 continua válida: todo esse fluxo é observador e não altera OK/NG,
  sequência, debounce ou rearme.

---

## D-020 — Segmentos luminosos refinam a geometria móvel do F3

**Status:** Accepted

No Display F3, câmera fixa não implica posição fixa da placa, do filtro preto ou
dos segmentos.

Decisão:

- o contorno configurado no F3 representa a região estrutural do filtro preto;
- a posição salva das 28 máscaras é um **modelo canônico**, não a coordenada
  produtiva obrigatória;
- quando existe emissão, o tracking usa somente os segmentos **ACESOS** do CHECK
  lógico atual como landmarks para refinar ou recuperar a pose;
- o filtro limita a região de busca; os segmentos luminosos determinam o
  alinhamento fino do display dentro dessa região;
- segmentos apagados não são procurados para obter pose;
- um ON esperado ausente ou uma emissão extra não invalida automaticamente o
  tracking se os demais landmarks sustentarem a geometria;
- quando já existe lock estrutural atual, o tracking executa um segundo estágio
  fino por segmento: os pixels luminosos são associados localmente aos IDs ON do
  modelo 88:88 e **3 landmarks identificados** já podem corrigir translação e,
  quando estiverem suficientemente espalhados, pequena rotação/escala;
- esse mínimo de 3 vale somente para geometria. Ele não reduz nenhum requisito de
  classificação, OK/NG ou CHECK; sem lock estrutural a reaquisição global mantém
  o quorum luminoso mais conservador;
- quando blooming/morfologia unem segmentos distintos em um único contorno, os
  pixels luminosos do filtro continuam podendo ser particionados localmente entre
  os centros ON esperados; OFF nunca é procurado para obter pose;
- quando a geometria da máscara projetada está disponível, um landmark local só
  participa do fit se a emissão realmente intersectar essa máscara e se o erro
  prévio permanecer dentro do limite de vizinhança; melhorar numericamente uma
  pose ruim não basta — erro residual alto veta a publicação do refinamento;
- OFF explicitamente confirmado pela autoridade física do mesmo
  projeto/CHECK veta o refinamento luminoso naquele instante; o tracking
  estrutural continua ativo e estado de energia INDETERMINADO não recebe esse
  veto, preservando a descoberta da transição para ligado;
- após o encaixe, as 28 ROIs são reprojetadas para o frame RAW e o analyzer
  canônico continua sendo a única autoridade para ON/OFF/POUCA LUZ e OK/NG;
- quando não há emissão, este refinamento luminoso simplesmente não executa
  classificação de segmentos apagados;
- a implementação pertence à autoridade de tracking existente e roda dentro do
  job HIGH do `F3HeavyVisionExecutor`; não cria scheduler, thread ou autoridade
  paralela.

Consequência: o operador ensina **o que procurar** por meio de foto, contorno,
máscaras e estados do CHECK; o runtime reencontra a geometria no frame atual em
vez de exigir que as máscaras permaneçam nas coordenadas em que foram
configuradas.

---

## D-021 — Lock atual do tracking pode confirmar presença física no F3

**Status:** Accepted

O filtro/display localizado pelo tracking é uma evidência física de que existe
placa no suporte, mesmo quando os scores globais das fotos de presença ficam
ambíguos por mudança de foco, posição ou enquadramento.

Decisão:

- `F3PresenceAuthority` continua sendo a única autoridade de presença;
- quando a presença visual não consegue confirmar placa, um tracking com
  `locked=true` e `evidence_current=true` pode confirmar
  `board_present=true`;
- a referência que obteve o lock (`H1`, `BLUE`, `USB`, `AUX`, board-off ou outra
  referência estrutural válida) não muda essa semântica: presença responde apenas
  se o objeto físico foi localizado;
- `empty_confirmed=true` possui precedência e nunca é sobrescrito pelo tracking;
- lock mantido por grace period ou qualquer resultado com
  `evidence_current=false` não confirma presença;
- presença confirmada exclusivamente pelo tracking não alimenta o latch visual de
  ambiguidade, evitando que um lock stale prolongue artificialmente a presença;
- o cache canônico inclui o estado relevante do tracking para que a chegada de um
  lock atual invalide imediatamente um snapshot anterior de presença no mesmo
  frame/contexto.

Consequência: presença deixa de bloquear energia quando o próprio tracker já
localizou fisicamente o filtro/display com evidência atual, sem criar nova
autoridade e sem permitir que geometria residual esconda suporte vazio.

---

## D-022 — Energia luminosa e autoridade espacial são estados distintos

**Status:** Accepted

O filtro preto pode estar corretamente localizado enquanto as 28 máscaras ainda
não estão finamente alinhadas com os segmentos reais. Nesse intervalo, declarar
a placa DESLIGADA apenas porque ROIs desalinhadas leem OFF cria um falso negativo.

Decisão:

- o refinamento por segmentos ACESOS usa preferencialmente a geometria desenhada
  na própria foto de referência do CHECK lógico atual;
- um lock estrutural obtido por AUX, USB, BOARD_OFF ou outra referência pode
  fornecer somente a pista grosseira do filtro; ele não fixa a identidade
  espacial das máscaras de H1;
- três ou mais componentes luminosos **validados contra a vizinhança das
  máscaras esperadas**, sem excesso incompatível de reflexos/componentes no
  filtro localizado, podem confirmar **energia física**, mesmo antes do encaixe
  fino; contagem bruta de hot spots não é prova suficiente;
- quando OFF já foi explicitamente confirmado pela autoridade de energia, essa
  mesma captura não pode ser promovida a ligada nem publicar pose luminosa por
  reflexos;
- energia confirmada sem alinhamento espacial resulta em
  `LIGADA • ALINHANDO <CHECK>`, com `allow_auto=false` e sem autoridade de
  OK/NG/avanço;
- somente após o encaixe luminoso publicar geometria atual o analyzer canônico
  volta a ter autoridade para comparar esperado × observado;
- no primeiro CHECK/H1, nenhuma leitura de máscara é apresentada como OK/NG
  antes de pelo menos um segmento que o CHECK espera ACESO ser reconhecido como
  ACESO com confiança válida; até lá a leitura bruta continua disponível no
  DEBUG, mas visor e overlay permanecem neutros;
- a telemetria do refinamento luminoso é incluída no DEBUG TÉCNICO para explicar
  componente detectado, espaço de fit, motivo de falha e estado de alinhamento;
- não é criado novo scheduler, worker ou autoridade paralela.

Consequência: presença, energia e geometria deixam de ser confundidas. O sistema
pode reconhecer que o display está claramente aceso sem julgar máscaras em
posições ainda não confiáveis.

---

## D-023 — F3 não usa banco angular 90°/180°/270°

**Status:** Accepted

Os três slots dedicados de rotação criavam fotografias, contornos e máscaras
paralelos ao modelo canônico do Projeto Display. Isso aumentava calibração,
persistência e caminhos de runtime para uma responsabilidade que já pode ser
resolvida pelo contorno canônico + refinamento luminoso.

Decisão:

- remover da configuração do F3 os slots 90°/180°/270° e suas ações de captura,
  carregamento, preview, edição e remoção;
- odin_display_tracking.json persiste somente a flag de tracking e o contorno
  canônico por projeto; payloads legados de orientations são migrados e removidos
  na primeira abertura do store com schema 2;
- a pasta gerenciada legada display_tracking_orientations é removida nessa mesma
  migração, eliminando as fotos 90°/180°/270° que deixaram de ter consumidores;
- nenhuma imagem angular entra no banco do F3DisplayObjectTracker, recebe bônus
  de score ou substitui temporariamente as máscaras do projeto;
- o contorno salvo em **Placa + Máscaras** permanece como região estrutural de busca;
- referências físicas/visuais normais do F3 podem continuar ajudando a obter a
  localização grosseira da placa, sem criar uma geometria angular alternativa;
- o alinhamento fino continua pertencendo ao tracking por segmentos que o CHECK
  atual espera ACESOS;
- esse refinamento luminoso é limitado pela pose estrutural do contorno: ele pode
  corrigir deslocamento fino, mas não pode impor salto grande de rotação, escala
  ou centro que deixe o conjunto de máscaras visualmente torto;
- a geometria ao vivo é sempre derivada das máscaras canônicas de **Placa +
  Máscaras**; geometria local de foto/CHECK não substitui o formato canônico;
- após a transformação, o formato canônico é reconstruído explicitamente:
  segmento continua segmento, círculo continua círculo e polígono preserva sua
  topologia;
- no preview produtivo com tracking, a apresentação é propositalmente simples:
  máscaras neutras e verde somente nos segmentos onde existe emissão identificada
  **e energia física confirmada**; com energia OFF/não confirmada, preview e visor
  88:88 permanecem neutros mesmo que exista classificação bruta ou telemetria
  luminosa residual. Vermelho/amarelo continuam
  disponíveis para decisão/diagnóstico, mas não deformam nem poluem a localização;
- após o encaixe, F3CheckAnalyzerAuthority continua responsável por classificar
  ON/OFF/POUCA LUZ e decidir conformidade; detectar luz para tracking não equivale
  a aprovar o CHECK.

Consequência: existe uma única geometria canônica de máscaras e contorno para o
Display F3. Movimento/rotação da placa é resolvido em runtime em vez de exigir
três bancos manuais de imagens angulares.

Esta decisão remove o caminho de referências angulares da implementação anterior
e preserva D-020, D-021 e D-022.

---

## D-024 — Um frame integralmente conforme aprova qualquer CHECK F3

**Status:** Accepted

A aprovação positiva do Display F3 não usa mais debounce de dois frames.

Decisão:

- todo CHECK produtivo usa exatamente **1 frame** para aprovação positiva;
- a regra vale para H1, BLUE/BT, USB, AUX e CHECKS futuros;
- o frame precisa ser uma análise canônica pronta e integralmente conforme:
  todas as máscaras ativas ACESO/APAGADO precisam estar corretas;
- no primeiro CHECK/H1, uma leitura completa 28/28 é evidência suficiente para
  registrar o CHECK como OK no próprio frame, mesmo que a identidade auxiliar
  por contorno ainda não tenha convergido;
- 27/28, análise incompleta, máscara incerta ou análise pertencente a outro
  CHECK não podem usar esse atalho;
- o contorno continua sendo fallback de localização/identidade enquanto a
  conformidade completa ainda não existe;
- CHECKS posteriores continuam sujeitos ao gate de transição física entre
  funções; esta decisão reduz somente o número de frames positivos necessários
  depois que o CHECK atual está autorizado;
- o debounce de NG permanece separado e não é reduzido por esta decisão;
- CHECK intermitente continua exigindo sua evidência temporal própria antes de
  poder ser considerado integralmente conforme.

Consequência: ao mostrar H1 com as 28 máscaras corretas no mesmo frame, o ODIN
registra imediatamente CHECK OK em vez de aguardar um segundo frame ou uma
segunda confirmação de identidade que contradiga a própria leitura 28/28.

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
