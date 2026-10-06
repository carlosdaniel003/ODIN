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
- OFF só veta o refinamento luminoso quando a evidência pertence à **mesma
  captura** e foi calculada sobre geometria com autoridade espacial já
  confirmada; OFF herdado de frame anterior nunca bloqueia a descoberta de uma
  transição física para ligado;
- OFF calculado com ROIs sustentadas apenas pelo lock estrutural é diagnóstico de
  energia, mas não pode vetar o refinamento que precisa corrigir essas próprias
  ROIs; isso evita o ciclo máscara desalinhada -> lê OFF -> bloqueia alinhamento;
- quando OFF da mesma captura e com geometria espacialmente autoritativa já foi
  explicitamente confirmado, essa captura não pode ser promovida a ligada nem
  publicar pose luminosa por reflexos;
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
- quando já existe lock estrutural, componentes luminosos globais sem identidade
  servem somente como telemetria/aquisição: a pose fina só pode ser publicada por
  landmarks associados aos IDs das máscaras ON esperadas;
- anchors concentrados em uma região podem corrigir **translação**, mas rotação e
  escala finas exigem distribuição espacial suficiente nos eixos X e Y do
  display; poucos segmentos de um mesmo dígito não podem girar as 28 máscaras;
- quando o ajuste fica restrito a translação, os vetores de deslocamento dos
  landmarks precisam formar um consenso espacial; anchors que pedem movimentos
  incompatíveis são descartados antes de calcular a correção do grid;
- o padding usado para procurar emissão perto de uma máscara não possui autoridade
  de alinhamento. Antes de publicar a pose, o runtime reprojeta as máscaras ON e
  exige emissão dentro do **núcleo geométrico exato**, sem dilatação, em quorum
  suficiente; luz presente apenas na vizinhança é rejeitada como segmento
  vizinho/reflexo;
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

**Nota de 30/09/2026:** a cláusula de apresentação que condicionava o verde à
energia física confirmada foi **substituída por D-032**. Gates de energia
continuam obrigatórios para decisão produtiva, mas não controlam o espelho visual
latest-frame da câmera/máscaras/visor.

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


## D-025 — Experimento de alinhamento F3 por homografia do filtro + registro visual do H1

**Status:** Proposed

### Contexto

O cenário físico do F3 é controlado:

- a câmera é fixa;
- a base/suporte é fixa;
- a placa pode entrar em posições diferentes no campo da câmera;
- o filtro preto do display se move com a placa e sempre contém os segmentos;
- o conjunto luminoso pode se deslocar dentro do próprio filtro, portanto o
  filtro não é uma referência fina suficiente para posicionar as 28 máscaras;
- depois que a placa entra no ciclo e H1 é exibido, a placa não se move
  fisicamente durante a sequência H1 -> BLUE -> USB -> AUX;
- máscaras fixas funcionaram de forma consistente quando a geometria da imagem
  coincidia com a referência; as tentativas recentes de fazer as máscaras
  perseguirem landmarks luminosos individualmente não atingiram consistência
  suficiente no equipamento real.

A estratégia deve explorar essas restrições físicas em vez de tratar o problema
como tracking genérico de 28 objetos independentes.

### Proposta

Separar localização grosseira e alinhamento fino em dois estágios distintos.

~~~text
FRAME RAW
   ↓
LOCALIZAR FILTRO PRETO
   ↓
H_filter = homografia do filtro
   ↓
FILTRO RETIFICADO / ROI CANÔNICA
   ↓
REGISTRO VISUAL DO H1 INTEIRO
   ↓
T_segments = pequeno ajuste interno dos segmentos
   ↓
IMAGEM CANÔNICA DOS SEGMENTOS
   ↓
28 MÁSCARAS FIXAS
~~~

Regras da proposta:

- o contorno do filtro preto é **localizador grosseiro**, não autoridade final
  da posição dos segmentos;
- os quatro cantos do filtro localizado devem permitir retificação por
  homografia para uma ROI canônica de tamanho conhecido;
- a fotografia H1 ensinada em CONFIGURAR, já associada ao contorno e às máscaras,
  torna-se a principal referência geométrica para o alinhamento fino do primeiro
  CHECK;
- após retificar o filtro, o runtime deve comparar a região inteira do H1 com a
  referência H1, preferencialmente em representação reduzida a emissão/contraste
  útil, em vez de estimar a pose pelas correspondências individuais de poucas
  máscaras;
- o alinhamento fino deve experimentar registro de imagem do H1 completo,
  priorizando tecnologias OpenCV como correlação de fase para deslocamento
  grosseiro e ECC para refinamento;
- após a homografia, o ajuste interno deve começar conservador: translação X/Y e
  pequena rotação. Escala livre só deve ser considerada se medições reais
  demonstrarem necessidade;
- o objetivo é transformar **a imagem móvel para o espaço das máscaras fixas**,
  e não continuar transformando as 28 máscaras para perseguir o frame bruto;
- as máscaras permanecem na geometria canônica ensinada. Classificação
  ON/OFF/POUCA LUZ continua pertencendo ao analyzer canônico e não ao tracking;
- o reconhecimento visual do CHECK pode comparar o crop retificado com as
  referências H1/BLUE/USB/AUX para telemetria, mas em produção o CHECK esperado
  deve ser a comparação principal; os demais scores são diagnóstico;
- a autoridade espacial passa conceitualmente por três estados:
  SEM_LOCK -> LOCK_FILTRO -> LOCK_SEGMENTOS;
- somente LOCK_SEGMENTOS autoriza as 28 máscaras a participarem da análise
  produtiva;
- quando H1 obtiver LOCK_SEGMENTOS, a transformação geométrica do ciclo deve
  ser congelada e reutilizada em BLUE, USB e AUX;
- durante o mesmo ciclo, o runtime não deve recalcular continuamente pose por
  CHECK. Pequena vibração pode ser tolerada; deslocamento significativo deve
  invalidar a geometria e bloquear a análise em vez de adaptar silenciosamente;
- retirada da placa ou rearme físico descarta a transformação congelada e obriga
  nova aquisição H1 para a próxima placa;
- todo compute pesado continua pertencendo ao F3TrackingAuthority /
  F3DisplayObjectTracker e ao F3HeavyVisionExecutor; esta proposta não cria
  novo scheduler, thread ou autoridade paralela.

### Implementação experimental — Etapa 1

A primeira etapa de D-025 foi implementada como compute isolado, sem participação
no runtime produtivo:

- `src/platform/display_f3_h1_registration.py` contém retificação por homografia,
  mapa de emissão, correlação de fase, refinamento ECC euclidiano, métricas de
  alinhamento e projeção experimental das máscaras fixas;
- `display_f3_object_tracking.experiment_h1_filter_registration()` reutiliza o
  detector estrutural de filtro já existente somente para produzir candidatos e
  escolhe o melhor registro H1 para telemetria;
- nenhuma chamada do scheduler, energia, analyzer, sequência ou UI produtiva usa
  esse caminho nesta etapa;
- testes sintéticos reproduzem explicitamente filtro movendo/perspectivando e o
  H1 deslocando/rotacionando internamente de forma independente;
- a próxima evidência necessária continua sendo o lote de imagens reais H1.

D-025 permanece **Proposed** até a validação física. Esta implementação não
autoriza substituir o alinhamento luminoso produtivo atual.

### Implementação experimental — Etapa 2

O caminho experimental foi conectado exclusivamente ao diagnóstico manual
acionado por **ANALISAR**, reutilizando o worker LOW já existente do relatório
técnico:

- quando o CHECK lógico congelado é H1, o diagnóstico carrega a foto H1 real
  salva em CONFIGURAR e a geometria do filtro/máscaras desenhada nessa foto;
- o mesmo frame bruto congelado pelo clique em ANALISAR é usado junto da
  geometria do filtro já publicada pelo LOCK estrutural do tracking canônico;
  essa geometria é capturada no mesmo seed do ANALISAR e entra diretamente na
  homografia, sem redetectar o filtro quando quatro pontos válidos existem;
- o detector escuro independente permanece somente como fallback diagnóstico
  quando o snapshot não contém geometria estrutural utilizável;
- o resultado gera um PNG diagnóstico precomputado com três painéis:
  REFERÊNCIA H1 | FILTRO RETIFICADO | H1 REGISTRADO, todos com as mesmas
  máscaras fixas do espaço retificado;
- DEBUG TÉCNICO apenas apresenta esse PNG e as métricas ECC/Dice/erro/overlap;
  abrir a janela não acessa câmera, não executa OpenCV e não cria novo job;
- BLUE/USB/AUX não executam este experimento nesta etapa;
- o resultado permanece sem autoridade produtiva e não altera tracking ao vivo,
  energia, analyzer, OK/NG, sequência ou rearme.

Esta etapa permite coletar evidência física real pressionando ANALISAR enquanto
H1 estiver visível. A substituição do alinhamento produtivo continua bloqueada
até a comparação em múltiplas posições demonstrar repetibilidade.

#### Guarda conservadora do refinamento ECC

O teste físico com iluminação ambiente reduzida demonstrou que a homografia
base/LOCK estrutural pode já estar geometricamente melhor que o candidato ECC.
Por isso, nesta etapa diagnóstica:

- o resultado ECC é tratado como **candidato**, nunca como substituição
  automática da homografia base;
- Dice e correlação não podem diminuir;
- erro médio e erro P95 não podem aumentar;
- quando máscaras ON fixas estiverem disponíveis, a sobreposição da emissão com
  essas máscaras também não pode piorar;
- qualquer regressão preserva a geometria da homografia base, com
  `refinement_applied=False` e motivo explícito no DEBUG;
- falha de convergência do ECC ou candidato fora dos limites de rotação/deslocamento
  também preservam a homografia base válida; o ECC é opcional e nunca pode
  transformar uma retificação válida em `SEM VISUAL`;
- o DEBUG separa o motivo do wrapper experimental do motivo interno do registro
  por meio de `registration_reason` / `refinement_reason`;
- as métricas do candidato rejeitado continuam registradas para diagnóstico;
- esta guarda continua sem autoridade produtiva e não altera energia, OK/NG,
  avanço de CHECK ou rearme.

### Registro de validação física — 29/09/2026

A investigação no equipamento real passou pelas seguintes tentativas e
observações. Este histórico deve ser preservado para evitar repetir soluções já
testadas sem considerar seus limites:

1. **Máscaras fixas**: funcionaram bem quando a placa coincidia com a posição
   ensinada, mas deixaram de servir quando a placa/filtro entrou deslocado ou
   rotacionado no campo da câmera.
2. **Tracking estrutural do filtro/placa**: recuperou uma pose grosseira, porém
   reflexos no filtro desligado chegaram a ser confundidos com landmarks
   luminosos. Foram adicionados veto por OFF confirmado, suporte dentro da máscara
   projetada, limite de erro local e rejeição de poses com residual alto.
3. **Refinamento luminoso por landmarks individuais**: conseguiu localizar
   emissão, mas em alguns frames tentava torcer/deslocar o grid ou recusava uma
   pose visualmente boa por ganho fino insuficiente.
4. **Homografia + registro H1 (D-025)**: foi criada como caminho experimental
   isolado. A primeira execução real parou em `filter_not_found`, embora o
   tracking produtivo já exibisse LOCK estrutural. O experimento passou então a
   reutilizar os quatro pontos do filtro já localizados pelo proprietário
   canônico de tracking.
5. **Ambiente com iluminação reduzida**: ao apagar a luz externa, os segmentos
   ficaram mais destacados e o alinhamento estrutural/luminoso ficou visualmente
   muito melhor, mesmo com a foto H1 de referência tendo sido capturada com a luz
   ambiente acesa. Isso mostrou que localização geométrica por emissão pode ser
   mais robusta à iluminação global do que matching da fotografia inteira.
6. **ECC piorando uma base boa**: em teste real, a base apresentava
   aproximadamente `Dice=0,597` e erro médio `4,37 px`, enquanto o candidato ECC
   caiu para `Dice=0,313` e erro médio `18,07 px`. A partir disso ECC virou apenas
   candidato: qualquer regressão preserva a homografia/base.
7. **ECC sem convergência**: outro teste retornou
   `h1_registration_not_converged`. Foi corrigido para que falha do ECC ou
   transformação fora do guard nunca apaguem uma homografia válida; o DEBUG
   passou a registrar `ecc_failed_base_preserved` ou motivo equivalente.
8. **Geometria adquirida em BLUE e reutilizada no H1**: no teste real mais
   recente, o clique ocorreu em H1 no frame 373, mas a geometria ainda vinha de
   `check:CHECK_002`/BLUE, obtida anteriormente. Visualmente as máscaras estavam
   sobre os segmentos, porém o refinamento H1 atual registrava seis landmarks
   locais e falhava em `fine_gain_insufficient`. Isso demonstrou que uma pose já
   correta pode ser rejeitada simplesmente porque não existe movimento adicional
   suficiente para justificar um refinamento.
9. **Conclusão desta rodada**: alinhamento e movimento não são sinônimos. Se a
   matriz atual já coloca emissão dentro do núcleo geométrico exato das máscaras
   ON identificadas, o runtime deve poder confirmar `LOCK_SEGMENTOS` mantendo a
   própria matriz, em vez de exigir uma nova transformação.

A integração produtiva da homografia D-025 continua bloqueada. A regra derivada
do item 9 é registrada separadamente em D-026 porque usa a autoridade produtiva
de tracking já existente e não transforma o experimento D-025 em autoridade.

### Validação antes de integrar ao ciclo produtivo

A primeira implementação deve ser um experimento isolado de geometria, sem
alterar energia, OK/NG, avanço de CHECK ou regras produtivas.

Usar um conjunto de aproximadamente 20 a 30 imagens reais de H1 com variações de:

- posição horizontal;
- posição vertical;
- pequena rotação;
- pequenas diferenças de perspectiva/enquadramento permitidas pela montagem.

Para cada imagem:

~~~text
detectar filtro
→ homografia
→ crop retificado
→ mapa de emissão / imagem de registro
→ registrar H1 contra a referência
→ aplicar as 28 máscaras fixas
→ medir alinhamento
~~~

Critérios devem incluir métricas objetivas, não somente inspeção visual:

- erro médio e máximo de alinhamento;
- sobreposição entre emissão real e máscaras ON;
- score/convergência do registro;
- taxa de sucesso do lock;
- estabilidade entre imagens diferentes da mesma montagem.

Somente depois de o experimento demonstrar consistência a nova geometria deve ser
conectada novamente a energia, analyzer, sequência e UI produtiva.

### Relação com decisões anteriores

Enquanto esta decisão estiver como **Proposed**, D-020, D-022 e D-023 continuam
descrevendo o comportamento aceito atual.

Se o experimento for validado e esta decisão for promovida a **Accepted**, ela
substituirá especificamente a parte dessas decisões que usa landmarks luminosos
individuais como mecanismo principal de alinhamento fino. As regras de
proprietário único, isolamento de energia/analyzer e ausência de banco angular
continuam válidas.

### Consequência esperada

O filtro responde apenas **onde está a região do display**. O H1 inteiro responde
**onde está o grid real dos segmentos dentro dessa região**. Depois da aquisição
H1, a inspeção recupera a estabilidade das máscaras fixas em um espaço canônico
e evita recalcular a pose durante os demais CHECKS do mesmo ciclo.

---
## D-026 — Pose já alinhada pode ser confirmada pelo núcleo luminoso sem novo movimento

**Status:** Accepted

### Contexto

O teste físico mostrou um caso em que as máscaras estavam visualmente
posicionadas sobre os segmentos do H1, mas o refinamento fino continuava
bloqueando a autoridade espacial por `fine_gain_insufficient`. A exigência de
ganho geométrico era inadequada nesse cenário: quando a pose de entrada já está
correta, a melhor correção pode ser exatamente zero.

Também foi observado que uma pose herdada de BLUE pode permanecer geometricamente
útil ao voltar para H1. Essa pose não deve ganhar autoridade para H1 apenas por
ter sido boa em BLUE; o H1 atual precisa reconfirmá-la com evidência luminosa dos
seus próprios IDs.

### Decisão

- com lock estrutural existente, antes/depois de tentar o refinamento fino, o
  tracking testa a matriz base contra o **núcleo geométrico exato**, sem padding,
  das máscaras que o CHECK atual espera ACESAS;
- se o quorum de núcleos identificados contiver emissão suficiente, a matriz base
  pode ser publicada novamente **sem qualquer movimento** como lock luminoso do
  CHECK atual;
- esse caminho recebe modo `base_core_verified` e continua usando
  `source_type=luminous_segment_grid`, tornando explícito que a autoridade atual
  veio da prova luminosa dos IDs, e não apenas da referência estrutural anterior;
- os IDs confirmados no núcleo são carregados no mesmo snapshot
  frame+geometria usado pelo worker semântico;
- para esses IDs, quando o estado esperado é ON, a evidência geométrica/luminosa
  atual pode reconciliar uma classificação aprendida OFF/ambígua para ON. Assim,
  um segmento realmente aceso dentro da sua própria máscara pode aparecer
  **verde** sem depender exclusivamente de semelhança fotométrica com imagens
  tiradas sob outra iluminação;
- essa reconciliação é permitida somente para `expected=ON`, no mesmo CHECK, com
  `spatial_alignment_ready=true`, `luminous_evidence_current=true` e geometria
  publicada por `luminous_segment_grid`;
- segmentos esperados OFF **nunca** são promovidos por essa regra. Eles continuam
  pertencendo ao analyzer canônico, preservando a detecção de segmento indevido;
- o CHECK só avança quando todas as máscaras ativas estiverem conformes. Portanto,
  confirmar os ON luminosos não cria atalho para 27/28, não ignora um OFF que
  acendeu e não altera D-024;
- CHECK intermitente mantém sua autoridade temporal própria e não usa essa
  reconciliação direta;
- uma geometria antiga de BLUE pode servir como matriz base, mas só se torna
  autoridade espacial de H1 depois que o próprio H1 atual valida emissão dentro
  dos seus núcleos identificados.

### Consequência

Quando as máscaras já estão corretamente em cima dos segmentos, o sistema deixa
de exigir uma transformação artificial para provar alinhamento. O H1 pode
confirmar a geometria no próprio frame, pintar em verde os ON cuja emissão foi
identificada dentro da máscara correta e, se os 28 estados estiverem conformes,
registrar H1 OK e liberar a transição para o próximo CHECK.

Esta decisão complementa D-022, D-023 e D-024. D-025 permanece experimental e
não se torna autoridade produtiva por causa desta mudança.


---
## D-027 — Snapshot ON de CHECK intermitente

**Status:** Accepted

### Contexto

No teste físico de BLUE, o tracking encontrou os 18 segmentos ON no frame 1215, mas o runtime já estava observando uma fase OFF quando o resultado assíncrono ficou disponível. O analyzer do snapshot rastreado confirmou os 18 IDs luminosos, porém o resultado permaneceu bloqueado pelo gate de energia.

### Decisão

- A câmera visível continua latest-frame-wins.
- Em CHECK com `intermittent=true`, um snapshot coerente de frame, geometria e CHECK com evidência positiva pode continuar elegível por até 2,5 s.
- A exceção vale somente para o mesmo projeto e CHECK.
- O snapshot precisa ter evidência positiva: geometria `luminous_segment_grid` com IDs validados ou análise explícita com pelo menos um ON positivo.
- A mesma regra vale na passagem tracking para analyzer e na entrega posterior do resultado semântico.
- Um único ON apenas preserva o frame candidato; não aprova o CHECK. As regras temporais atuais continuam exigindo a fase ON válida, conformidade do CHECK e tratamento de defeito persistente.
- CHECK contínuo, outro CHECK/projeto, snapshot sem emissão positiva ou com mais de 2,5 s continuam sujeitos à regra normal de frescor.
- O snapshot preservado nunca substitui `camera_frame_atual`.

### Consequência

O BLUE pode ter a fase acesa capturada e analisada mesmo que, quando o worker termine, a câmera já esteja mostrando a fase apagada. Segmentos de frames diferentes continuam não sendo somados para fabricar conformidade.

Esta decisão complementa D-024 e D-026.

---
## D-028 — Gate espacial aceita lock luminoso atual do mesmo CHECK entre frames assíncronos

**Status:** Accepted

### Contexto

No teste físico de USB de 29/09/2026, o display estava correto e a análise
semântica chegou a `approved=true` com 28/28 máscaras conformes. A energia física
também estava confirmada. Mesmo assim, o CHECK não avançou.

O DEBUG mostrou duas visões temporalmente próximas do mesmo estado:

- o tracker no frame 942 possuía `luminous:CHECK_004`,
  `source_type=luminous_segment_grid`, `evidence_current=true`, 15/15 IDs ON
  validados e `alignment_ready=true`;
- a autoridade de energia, em um frame live posterior, possuía
  `powered_confirmed=true`, porém ainda carregava
  `spatial_alignment_ready=false` / `structural_only`.

O resultado 28/28 correto ficou `blocked_by_power_gate=true`. A falha era de
coerência temporal entre proprietários assíncronos, não de energia, classificação
ou geometria luminosa.

### Decisão

- `F3PowerAuthority` continua sendo o proprietário do gate de energia.
- O proprietário canônico de tracking passa sua evidência explicitamente ao
  `F3PowerAuthority`.
- Quando a energia do frame live estiver realmente confirmada, a autoridade pode
  reconciliar `spatial_alignment_ready` a partir do lock luminoso atual do
  tracker, desde que:
  - `locked=true`;
  - `evidence_current=true`;
  - `source_type=luminous_segment_grid`;
  - a referência seja exatamente `luminous:<CHECK atual>`;
  - existam IDs luminosos validados;
  - a idade do lock esteja dentro de
    `F3_TRACKING_MAX_OPERATIONAL_RESULT_AGE_MS`;
  - a diferença de frame esteja dentro de
    `F3_TRACKING_MAX_OPERATIONAL_FRAME_GAP`.
- O tracking não substitui a prova de energia: sem
  `powered_confirmed=true`, essa reconciliação não libera decisão.
- Lock estrutural, lock mantido/stale, outro CHECK e evidência fora da janela de
  frescor continuam bloqueados.
- A regra estrita de mesmo snapshot dentro da autoridade bruta de energia não é
  relaxada. A reconciliação acontece na composição canônica das autoridades,
  onde tracking e energia já são proprietários distintos.
- O CHECK ainda precisa passar pelo analyzer canônico. A reconciliação apenas
  remove o falso bloqueio espacial; não transforma tracking em autoridade de
  OK/NG.

### Consequência

Um CHECK contínuo como USB pode ser aprovado quando:

~~~text
tracking recente prova a geometria luminosa do USB
+
frame live prova que o display continua energizado
+
analyzer prova 28/28 conforme
=
USB possui autoridade produtiva para avançar
~~~

A defasagem normal de poucos frames causada pelo executor pesado deixa de
bloquear um CHECK correto, sem aceitar geometria antiga ou pertencente a outro
CHECK.

O histórico físico detalhado desta ocorrência fica em
`docs/F3_PHYSICAL_VALIDATION_LOG.md`.

---
## D-029 — Espelho visual latest-frame-wins e aquisição inicial prioritária no F3

**Status:** Accepted

### Contexto

No teste físico de 29/09/2026, a câmera mostrava o display real mudando antes
das máscaras verdes e do `VISOR DO DISPLAY`. Isso era visualmente desconcertante,
especialmente no BLUE intermitente: a imagem física já estava em outra fase,
enquanto as duas representações da UI ainda refletiam o último resultado do
worker de tracking/análise.

O atraso era arquitetural. A câmera visível já seguia latest-frame-wins, porém a
cor das máscaras e o visor lógico consumiam `luminous_mask_ids` e classificações
produzidas por jobs HIGH assíncronos. Esses jobs precisam continuar assíncronos
para decisão produtiva, mas não são a fonte adequada para uma animação que deve
espelhar o frame que o operador está vendo.

Também foi observado que a abertura do F3 podia permanecer tempo demais em
`IDENTIFICANDO...`. O primeiro `configure()` do tracker calculava ORB e AKAZE
para todas as referências antes de o fallback AKAZE ser realmente necessário,
e o primeiro job HIGH de tracking podia ficar atrás de trabalho LOW já presente
no executor.

### Decisão

#### Espelho visual

- A câmera física continua sendo latest-frame-wins.
- Depois que existe geometria rastreada válida, o **mesmo frame já reduzido para
  o preview** recebe uma leitura luminosa leve sobre o núcleo das 28 ROIs.
- Essa leitura usa somente o canal V e estatísticas locais simples; não executa
  ORB, AKAZE, template matching, feature extractor ou acesso a disco.
- O resultado é calculado no máximo uma vez por `frame_token + CHECK + geometria`
  e é reutilizado em repaints repetidos.
- A mesma coleção `live_visual_mask_ids` alimenta, no mesmo repaint:
  - as máscaras verdes sobre a câmera;
  - os segmentos verdes do `VISOR DO DISPLAY`.
- Uma fase escura válida produz conjunto vazio e apaga as duas representações
  juntas.
- Essa leitura é **somente apresentação**. Ela não participa de energia,
  presença, ON/OFF/POUCA LUZ produtivo, OK/NG, debounce ou avanço de CHECK.
- A autoridade produtiva continua no tracking/analyzer/energy/state machine
  canônicos. Não existe segundo scheduler nem segunda thread.

#### Aquisição inicial

- As features AKAZE das referências salvas deixam de ser calculadas
  preventivamente para todas as imagens no primeiro `configure()`.
- ORB/template continuam disponíveis imediatamente.
- AKAZE de uma referência é materializado e cacheado somente quando o caminho de
  reacquisition realmente precisa desse fallback.
- Falha de materialização também é cacheada, evitando retry caro a cada frame.
- O primeiro job HIGH de tracking pode ser enfileirado mesmo quando o executor
  já possui trabalho de menor prioridade. Depois que esse future existe, o
  backpressure normal volta a valer.
- Nenhum worker adicional é criado e `F3HeavyVisionExecutor` continua com
  concorrência máxima de um job.

### Consequência

Visualmente, a intenção passa a ser:

~~~text
frame N chega da câmera
→ preview reduzido
→ amostra luminosa leve nas ROIs
→ câmera e VISOR recebem o mesmo estado visual do frame N
~~~

Enquanto isso, em paralelo e sem alterar a decisão:

~~~text
latest frame elegível
→ tracking/analyzer HIGH
→ energia + analyzer + state machine
→ OK/NG / avanço de CHECK
~~~

Assim, responsividade visual e segurança da decisão deixam de disputar a mesma
latência. A abertura também deixa de pagar antecipadamente pelo fallback AKAZE
de todas as referências.

A validação física desta mudança é registrada em
`docs/F3_PHYSICAL_VALIDATION_LOG.md`.

---

## D-030 — Rearme invalida pose e preserva banco de referências F3

**Status:** Accepted

### Contexto

Após validar a correção que destravou o `IDENTIFICANDO...`, o teste físico
confirmou que a câmera e o pipeline voltaram a avançar. Permaneceram dois custos
desnecessários no início de cada aquisição:

- `configure()` decodificava todas as fotografias estruturais Full HD e
  calculava ORB para todo o banco antes de saber qual referência seria necessária;
- o rearme após EMPTY chamava reset completo do tracker, apagando também esse
  banco já preparado, embora projeto, resolução e referências não tivessem mudado.

Além disso, a próxima placa pode entrar em outra posição. Portanto a geometria da
placa anterior nunca pode atravessar o rearme.

### Decisão

- configuração/calibração e pose efêmera do ciclo passam a ter lifecycles
  distintos;
- `reset_tracking_runtime()` continua sendo reset completo para mudança de
  configuração, projeto ou edição de referências;
- o rearme físico entre placas usa `reset_tracking_cycle()`, que:
  - cancela jobs pendentes e invalida geração;
  - limpa Future/resultado/geometria live;
  - limpa matriz, orientação, frame anterior e evidência do lock;
  - preserva o banco de referências já calibrado da mesma sessão;
- a próxima placa, mesmo entrando em outra posição, precisa obter um novo lock do
  zero; preservar referências não significa preservar pose;
- `configure()` indexa metadados das referências, mas imagem/ORB/template são
  materializados sob demanda e cacheados no primeiro uso;
- durante aquisição sem pose válida, o CHECK lógico atual e `board_off` têm
  prioridade sobre as demais vistas; o restante do banco continua disponível
  como fallback;
- AKAZE permanece fallback lazy;
- nenhum novo scheduler, thread, worker ou fila é criado.

### Consequência

O primeiro `IDENTIFICANDO...` deixa de pagar antecipadamente pelo banco inteiro
e, após a retirada da placa, o próximo ciclo reutiliza a calibração em memória
sem reutilizar a posição anterior.

O fluxo esperado é:

~~~text
resultado terminal
→ retirar placa
→ EMPTY confirmado
→ descartar pose/matriz/anchor da placa anterior
→ preservar banco de referências da sessão
→ nova placa entra em qualquer posição permitida
→ aquisição prioriza CHECK atual + board_off
→ novo LOCK
~~~

A segurança permanece conservadora: referência cacheada é somente calibração;
OK/NG, energia, presença e sequência continuam nas autoridades canônicas.

---

## D-031 — Tracking F3 não pode rebaixar a conformidade estrita das máscaras

**Status:** Accepted

### Contexto

No teste físico de 29/09/2026, uma placa com o segmento 24 fisicamente
danificado permaneceu sem emissão nesse segmento, embora o CHECK o esperasse
ACESO. Mesmo assim, depois de algum tempo o CHECK foi aprovado.

A árvore já possuía F3StrictMaskConformityAnalyzer, cuja regra é que uma única
máscara configurada divergente impede aprovação. Porém a composição final de
tracking instalava F3TrackedRawCheckAnalyzer e, internamente, reconstruía um
F3SameMaskReferenceAnalyzer simples. Isso rebaixava a autoridade semântica
depois que a camada estrita já havia sido instalada.

O desvio existia tanto com tracking ativo quanto no fallback sem tracking,
porque o wrapper final continuava sendo o analyzer publicado para a sessão.

### Decisão

- F3TrackedRawCheckAnalyzer continua proprietário da adaptação geométrica RAW
  + ROIs móveis, mas sua autoridade semântica interna passa a ser
  F3StrictMaskConformityAnalyzer;
- a conformidade estrita aceita explicitamente mask_geometry_override,
  resolução e fonte geométrica, preservando a leitura sobre ROIs rastreadas;
- tracking fornece geometria e evidência luminosa positiva; não substitui a regra
  de que todas as máscaras ativas do CHECK precisam permanecer conformes;
- um segmento esperado ACESO que seja classificado APAGADO, enquanto o display
  possui evidência de energia/segmentos ON, continua para a política de NG e não
  pode ser convertido em OK pela composição final;
- com tracking desligado, o caminho legado/alinhado usa a mesma autoridade
  semântica estrita;
- H1 mantém a política já aceita de referencial: divergência no primeiro CHECK
  não cria NG automático antes de H1 ser confirmado. Esta decisão corrige o
  falso OK; não remove esse gate de entrada.

### Consequência

A composição passa a obedecer:

~~~text
tracking ON
frame RAW + geometria móvel
→ conformidade estrita
→ política SEARCHING / OK / NG

tracking OFF
frame do pipeline normal
→ mesma conformidade estrita
→ mesma política SEARCHING / OK / NG
~~~

Uma máscara ausente não pode ser escondida pela troca de analyzer feita pelo
tracking. Em particular, se MASK_024 deveria estar ON e permanece OFF em um
CHECK posterior com display energizado, a decisão esperada é NG após o debounce
normal.

---

## D-032 — Câmera, máscaras e visor F3 formam um espelho visual único e independente dos gates

**Status:** Accepted

### Contexto

O requisito operacional do modo **Rastreamento Automático do Display F3** é que o
operador veja a mesma realidade em três representações simultâneas:

1. segmento físico presente na câmera ao vivo;
2. máscara/ROI desenhada sobre esse segmento;
3. segmento correspondente no VISOR DO DISPLAY.

Em 30/09/2026 foi observado novamente que um segmento fisicamente aceso podia
permanecer sem verde na máscara/visor. O histórico continha duas intenções
concorrentes: D-029 criou uma amostra visual latest-frame, mas D-023 e fallbacks
do renderer ainda permitiam condicionar cor ao gate de energia ou a
classificações assíncronas.

Gate produtivo e espelho visual são responsabilidades diferentes.

### Decisão

Com tracking ativo e geometria válida:

- o frame visível da câmera é a fonte temporal do espelho;
- uma única amostra luminosa leve do **mesmo frame de preview** produz
  `live_visual_mask_ids`;
- câmera/overlay e VISOR DO DISPLAY consomem exatamente esses mesmos IDs no mesmo
  repaint;
- se a amostra latest-frame ainda não estiver disponível, ambos usam o mesmo
  snapshot `luminous_mask_ids`; não é permitido que um use classificação
  semântica e o outro use tracking;
- presença, energia, power gate, spatial gate, gate de H1, debounce, OK/NG e
  avanço de CHECK **não podem apagar, atrasar ou neutralizar a cor do espelho
  visual**;
- se um segmento está fisicamente emitindo e a ROI visual o detecta, a máscara
  sobre a câmera fica verde e o mesmo segmento do visor fica verde;
- se a emissão desaparece no frame atual, ambos deixam o verde juntos;
- classificações assíncronas de ON/OFF/POUCA LUZ não são fallback do espelho
  visual com tracking ativo;
- essa cor não possui autoridade de produção. Um verde visual não prova energia,
  conformidade, OK nem autorização para avançar;
- a única pré-condição geométrica é existir uma ROI/pose válida para saber onde
  amostrar e desenhar. Isso não é um gate de decisão;
- o detector visual permanece leve, sem ORB, AKAZE, template matching, acesso a
  disco, novo scheduler, thread ou worker.

### Robustez da amostra visual

O detector latest-frame não pode depender somente de um percentil global das
máscaras, porque CHECKS com maioria ou todos os segmentos acesos elevam o
baseline e podem esconder emissão real.

Por isso a apresentação pode combinar, sem participar da decisão produtiva:

- separação relativa de brilho;
- maior gap entre grupos de scores das ROIs;
- evidência absoluta forte dentro do núcleo da própria ROI.

### Consequência

A regra visual obrigatória é:

~~~text
SEGMENTO FÍSICO ACENDE NO FRAME N
        ↓
amostra visual do frame N
        ↓
MASK_xxx entra nos IDs visuais
        ├── máscara sobre a câmera = VERDE
        └── segmento do visor      = VERDE
        ↓
NO MESMO REPAINT
~~~

e, independentemente disso:

~~~text
presença / energia / alinhamento produtivo / analyzer / state machine
        ↓
decidem se existe autoridade para OK/NG/avanço
~~~

D-032 **refina D-029** e **substitui somente a antiga restrição visual de D-023**
que exigia energia confirmada para apresentar verde. As proteções produtivas de
D-020 a D-031 permanecem válidas.

---

## D-033 — Espelho visual F3 vale com tracking ligado e desligado

**Status:** Accepted

### Contexto

Após D-032, o reteste físico foi inicialmente interpretado como sendo do modo
Rastreamento Automático. O operador esclareceu em 30/09/2026 que o problema
observado naquele momento ocorria com **Rastreamento Automático desativado**:

- as máscaras da câmera permaneciam cinzas;
- o VISOR DO DISPLAY não mostrava os segmentos acesos.

A implementação D-032 estava conectada ao caminho final da instância de
tracking. Com tracking OFF, esse wrapper delegava para o renderer fixo anterior.
Esse caminho ainda:

- não executava a amostra visual latest-frame;
- deixava `live_luminous_only=false`;
- atualizava o visor antes de existir a amostra do frame;
- usava somente máscaras ativas do CHECK para o overlay;
- podia neutralizar a apresentação conforme power gate/classificação.

Portanto a regra visual estava correta, mas incompleta no caminho de execução.

### Decisão

O espelho visual D-032 é uma regra do **Display F3**, não uma característica
exclusiva do tracking.

~~~text
TRACKING ON
→ ROIs móveis
→ amostra visual latest-frame
→ câmera/máscaras + visor

TRACKING OFF
→ ROIs fixas do Projeto Display
→ a MESMA amostra visual latest-frame
→ câmera/máscaras + visor
~~~

Regras obrigatórias:

- as 28 máscaras configuradas permanecem disponíveis para o espelho visual,
  inclusive quando uma máscara está `ignore` no CHECK atual;
- `ignore` controla decisão do CHECK, não a existência visual da máscara;
- tracking OFF usa geometria fixa; tracking ON usa geometria móvel;
- a diferença de geometria não pode alterar a semântica visual;
- se um segmento físico está emitindo, sua máscara e seu segmento no visor ficam
  verdes no mesmo repaint;
- o visor é atualizado somente depois da amostra visual do frame atual;
- power gate, presença, H1, debounce, OK/NG e state machine não controlam essa
  cor visual;
- a amostra continua sem autoridade produtiva;
- não criar segundo scheduler, thread, worker ou fila para essa apresentação.

### Consequência

D-033 **estende D-032 para tracking OFF**. D-032 continua válida para o caminho
com tracking; esta decisão elimina a diferença visual entre os dois modos.


---

## D-034 — Estado físico visual não depende do CHECK lógico

**Status:** Superseded by D-035

### Contexto

No reteste de 30/09/2026 com tracking OFF, a interface mostrou ao mesmo tempo
`15 ACESOS` e `13 APAGADOS`, enquanto as máscaras da câmera e o VISOR DO
DISPLAY permaneciam neutros.

Também havia defasagem assíncrona entre o CHECK lógico exibido e o CHECK da
análise visual recente. Isso mostrou que o analyzer já possuía estados físicos
das máscaras, mas a apresentação os descartava por exigir o CHECK lógico atual
e por depender exclusivamente dos IDs produzidos pelo detector visual leve.

### Decisão

O espelho visual F3 passa a manter um mapa compartilhado
`live_visual_classifications` com estados físicos `on`, `off` e
`low_light`.

- o mapa pode consumir `mask_results[].classified` da análise recente do mesmo
  projeto, mesmo se o CHECK lógico já tiver avançado;
- `expected`, `matched`, aprovação e sequência continuam vinculados ao CHECK
  correto e não são reaproveitados;
- ON detectado no frame atual também pode promover a máscara para ON;
- um detector visual vazio não pode neutralizar um ON físico que o analyzer já
  publicou;
- câmera e VISOR DO DISPLAY recebem o mesmo mapa;
- ON = verde, OFF = azul/cinza, LOW_LIGHT = amarelo;
- gates produtivos não controlam essa apresentação.

### Consequência

Se o analyzer informa 15 máscaras ON e 13 OFF, a interface não pode mostrar os
28 segmentos como neutros. D-034 complementa D-032 e D-033 sem alterar a decisão
produtiva.



---

## D-035 — Espelho visual final do F3 também é autoridade com tracking OFF

**Status:** Accepted

### Contexto

O reteste físico de 30/09/2026 trouxe a evidência que faltava. Com tracking OFF,
o DEBUG do próprio runtime publicou:

~~~text
stage=tracking_disabled
render_path=previous_window_update
context_ready=NÃO
sample_ready=NÃO
visual_ids=0
readout_ready=NÃO
readout_visual_ids=0
~~~

Ao mesmo tempo, a autoridade física já possuía máscaras ON/OFF. Logo, D-033 e
D-034 estavam corretas como intenção, porém o proprietário final da janela
continuava retornando antes de executar o espelho visual quando o tracking estava
desativado.

### Decisão

O callback final `tracked_window_update`, já instalado diretamente na instância
real da janela F3, é o proprietário final do repaint câmera + máscaras + visor nos
dois modos.

~~~text
tracking ON
→ geometria móvel
→ amostra visual do frame atual
→ mapa ON/OFF/LOW_LIGHT
→ câmera + visor

tracking OFF
→ geometria fixa
→ a MESMA amostra visual do frame atual
→ o MESMO mapa ON/OFF/LOW_LIGHT
→ câmera + visor
~~~

É proibido um `return previous_window_update` antes da construção do espelho
visual apenas porque tracking está OFF.

### Semântica visual obrigatória

No ao vivo:

- segmento fisicamente ON → **verde vivo** (`#22C55E`);
- segmento fisicamente OFF → **verde escuro** (`#14532D`);
- POUCA LUZ/validação → amarelo;
- sem evidência válida → neutro/cinza;
- câmera e VISOR DO DISPLAY consomem o mesmo mapa no mesmo repaint.

A cor ON/OFF acima é apresentação física e independe de power gate, presença,
expected, matched, aprovação, reprovação ou avanço de CHECK.

### Frescor

Quando o sampler do frame atual consegue medir uma ROI, esse resultado é a
autoridade visual daquele repaint:

- ROI no conjunto luminoso → ON;
- ROI amostrada fora do conjunto luminoso → OFF.

Classificações físicas assíncronas do analyzer/autoridade de energia são fallback
somente quando uma ROI não pôde ser amostrada. Assim um ON antigo não pode
permanecer verde depois que o segmento apagou no frame atual.

### Consequência

D-035 substitui a parte operacional de D-034 e consolida D-032/D-033 no
proprietário final já existente. Nenhum novo timer, thread, worker, fila ou
scheduler é criado. Tracking continua definindo geometria, não a existência do
espelho visual.



---

## D-036 — Máscaras do projeto são a única geometria live com tracking OFF

**Status:** Accepted

### Contexto

No F3 existem duas geometrias com finalidades diferentes:

1. a seção **Máscaras** do Projeto Display;
2. geometrias locais desenhadas dentro de CHECKS/referências visuais.

Historicamente, `mascaras_geometria_check_display()` combinava a máscara
canônica com `mask_overrides_reference` do CHECK e alguns consumidores de
runtime usavam esse resultado também sobre a câmera ao vivo. Isso permitia que
uma máscara desenhada apenas para recortar uma foto de treinamento deslocasse ou
redimensionasse a ROI produtiva quando o Rastreamento Automático estava
desativado.

### Decisão

Com **Rastreamento Automático desativado**, a única autoridade geométrica sobre o
frame atual é:

~~~text
Projeto Display
→ Máscaras
→ posição + tamanho + formato
→ câmera ao vivo
→ análise produtiva
→ overlay/visor
~~~

Logo:

- mover uma máscara em **Máscaras** move a ROI fixa da câmera;
- redimensionar uma máscara em **Máscaras** redimensiona a ROI fixa da câmera;
- trocar círculo/segmento/polígono ponto-a-ponto em **Máscaras** troca o formato
  usado no frame ao vivo;
- `mask_overrides_reference`, `masks_reference` e geometrias salvas dentro de
  CHECK/referência visual pertencem somente à respectiva foto de
  referência/treinamento;
- uma geometria local de CHECK nunca substitui a geometria live fixa;
- IDs continuam ligando a máscara canônica aos exemplos de treinamento;
- `mask_states` continua dizendo ON/OFF/IGNORE por CHECK e não altera posição.

Com **Rastreamento Automático ativado**, a identidade geométrica ainda nasce da
mesma seção **Máscaras**, mas o tracker projeta essa geometria canônica para a
pose atual da placa. Referências de CHECK podem auxiliar a localizar/calibrar a
pose, mas não viram uma segunda máscara produtiva.

### Contrato de implementação

- `mascaras_geometria_runtime_fixa_display(project)` é a fonte canônica para
  consumidores live sem tracking;
- `mascaras_geometria_check_display(project, check)` fica restrita à geometria
  local de foto/referência;
- apresentação, análise semântica e assinatura 4x7 no modo fixo usam a primeira;
- construção de dataset/foto de CHECK continua autorizada a usar a segunda.

### Consequência

Editar uma referência visual pode melhorar o treinamento sem deslocar a câmera.
Editar **Máscaras** muda imediatamente a geometria produtiva fixa no próximo
contexto/configuração recarregado.


---

## D-037 — Contorno canônico da placa permanece visível na câmera F3

**Status:** Accepted

### Contexto

No modo com Rastreamento Automático desativado, D-036 já tornava a seção
**Máscaras** a autoridade das ROIs live, mas o preview fixo ainda publicava
`board_points=()`. Assim o contorno da placa desenhado em **Placa + Máscaras**
não aparecia na câmera ao vivo, apesar de estar persistido no sidecar canônico de
tracking.

### Decisão

- o contorno salvo em **Placa + Máscaras** é parte da geometria live do projeto;
- tracking OFF usa o contorno canônico fixo no mesmo espaço mestre das máscaras;
- tracking ON usa esse mesmo contorno canônico projetado pela pose do tracker;
- contornos locais de CHECK/referência continuam pertencendo somente à foto de
  treinamento;
- o cache do preview fixo inclui a assinatura dos pontos do contorno para que uma
  edição seja refletida sem reutilizar geometria antiga;
- o contorno é apresentação/geometria e não cria autoridade de presença,
  energia, OK/NG ou sequência.

### Consequência

Câmera ao vivo, máscaras e contorno passam a representar a mesma geometria
canônica quando tracking está OFF, enquanto o modo tracking ON preserva a
projeção móvel já existente.

---

## D-038 — ON próprio validado pode calibrar a mesma máscara sem enfraquecer D-031

**Status:** Accepted

### Contexto

No reteste físico de 30/09/2026 com tracking OFF, H1 estava visualmente aceso,
mas a conformidade estrita publicou 21/28: exatamente as sete máscaras que H1
esperava ON foram tratadas como OFF. No mesmo frame congelado, o aprendizado por
mesma máscara classificou H1 como 28/28 conforme.

A causa arquitetural é a exclusão absoluta da foto do CHECK atual introduzida
para impedir autoaprendizado de defeito. A proteção é correta para impedir que
um segmento salvo defeituoso ensine o próprio erro, porém ficou excessivamente
forte quando o mesmo segmento possui distribuição óptica diferente entre H1,
BLUE, USB e AUX.

### Decisão

D-031 permanece válida e não é relaxada: uma única máscara divergente ainda
bloqueia OK. A política de referência passa a ser assimétrica:

- a foto do CHECK atual continua excluída dos pools globais;
- OFF do próprio CHECK continua sempre excluído;
- ON do próprio CHECK pode voltar somente ao pool **local da mesma MASK_xxx**;
- essa reinjeção só é válida quando a energia óptica da amostra ON fica acima de
  todas as referências OFF externas da mesma máscara por pelo menos
  `F3_LOW_LIGHT_MIN_ENERGY_SPAN`;
- a referência reinjetada é marcada explicitamente como
  `validated_self_on`;
- `mask_states` continua sendo o gabarito funcional;
- a leitura live continua precisando classificar cada máscara e cumprir 100% do
  CHECK para receber OK.

### Consequência

Um H1 realmente aceso deixa de ser reprovado apenas porque outras funções
produzem outra intensidade/cor no mesmo segmento. Ao mesmo tempo, uma foto em
que o segmento esperado ON esteja realmente apagado não possui separação física
contra OFF suficiente e não pode ensinar o defeito como correto.

---

## D-039 — Resultado terminal e SEGREGAR compartilham o latch do rearme físico

**Status:** Accepted

### Contexto

No mesmo reteste, a interface mostrava `AGUARDANDO H1` enquanto o runtime
estava em `waiting_empty_rearm=true` e o status operacional dizia para retirar
a placa anterior. Os contadores já estavam em TOTAL 1 / NG 1 e
`last_result=null`, assinatura do fluxo de SEGREGAR, mas depois do hold visual
o snapshot da máquina de CHECKS voltou a renderizar H1.

Isso fazia duas proteções corretas parecerem defeitos:

1. H1 não podia aprovar porque o ciclo anterior ainda estava terminal;
2. botão/tecla 1 pareciam não funcionar porque novas segregações eram
   corretamente bloqueadas contra dupla contabilização.

### Decisão

O estado visual terminal passa a usar o mesmo latch do rearme físico:

- APROVADA, NG e SEGREGADA permanecem na apresentação enquanto
  `waiting_empty_rearm` estiver ativo;
- ao confirmar EMPTY, a tela muda explicitamente para
  `AGUARDANDO NOVA PLACA`, sem fingir que H1 já está ativo;
- o botão SEGREGAR fica desabilitado durante espera por EMPTY e durante espera
  pela nova placa;
- botão, tecla `1` e NumPad `1` continuam chamando a mesma ação canônica;
- somente depois de a nova placa ser confirmada o latch visual é liberado, H1 é
  renderizado novamente e SEGREGAR volta a ser habilitado;
- as guardas existentes contra dupla contabilização permanecem intactas;
- nenhum novo timer/thread/worker é criado.

### Consequência

A UI passa a refletir o estado real da máquina física. Um operador não vê H1
ativo durante um ciclo já encerrado e não interpreta uma ação corretamente
bloqueada como botão/atalho quebrado.

---

## D-040 — SEGREGAR usa vermelho terminal persistente até EMPTY

**Status:** Accepted

### Contexto

D-039 corrigiu a divergência em que a máquina já estava aguardando retirada,
mas a tela voltava a H1. O requisito operacional foi refinado: depois de
**SEGREGAR PLACA**, não basta impedir o retorno a H1; o estado terminal precisa
permanecer visualmente vermelho enquanto a mesma placa continua no suporte.

### Decisão

D-040 complementa D-039 somente na apresentação:

- uma segregação válida registra o tipo terminal como `segregated`;
- enquanto `waiting_empty_rearm` estiver ativo, painel de resultado e cards de
  CHECK permanecem vermelhos;
- cards usam o texto `SEGREGADO`;
- bordas do preview, do VISOR DO DISPLAY e do painel de projeto permanecem
  vermelhas;
- o status operacional e o status inferior mostram
  `PLACA SEGREGADA • RETIRE A PLACA DO SUPORTE` em vermelho;
- repaints e o timer histórico de resultado não podem remover esse vermelho;
- EMPTY encerra o vermelho terminal e muda para espera por nova placa;
- a nova placa confirmada libera H1 e reabilita SEGREGAR;
- câmera ao vivo, contorno da placa, todas as máscaras e os 28 segmentos do
  visor recebem override visual vermelho enquanto a segregação estiver terminal;
- esse override é somente de apresentação: classificações, telemetria e decisões
  continuam preservando o estado físico ON/OFF/POUCA LUZ de D-032/D-035;
- nenhuma nova autoridade, thread, scheduler, fila ou timer é criada.

### Consequência

Clique, tecla `1` e NumPad `1` passam a ter feedback visual inequívoco e
durável: se a placa foi segregada e ainda não saiu do suporte, a tela continua
vermelha.

---

## D-041 — Referências visuais F3 são memória alinhada do padrão de segmentos, não classificador de cena inteira

**Status:** Accepted

### Contexto

Em 30/09/2026 o operador relatou um defeito recorrente no H1: os segmentos que
H1 deveria manter acesos podiam aparecer corretamente verdes no ao vivo e,
ainda assim, o CHECK não era aprovado ou a análise visual não reconhecia H1.

O requisito operacional foi esclarecido: as imagens cadastradas dentro dos
CHECKS e as imagens cadastradas em **Referências Visuais** já possuem a
informação relevante para identificar o estado do display — contorno da placa,
máscaras alinhadas aos segmentos e padrão de segmentos ACESOS/APAGADOS. A
fotografia inteira contém fundo, suporte e variações globais que não devem
competir com essa memória semântica.

### Decisão

A unidade de comparação visual do F3 passa a ser conceitualmente a **região da
placa + padrão alinhado de segmentos**, e não a cena inteira.

```text
REFERÊNCIA APRENDIDA
contorno local da placa
+ máscaras locais por MASK_xxx
+ estados ON/OFF do CHECK
        ↓
recortar/normalizar a região da placa
        ↓
alinhar os mesmos IDs de segmento
        ↓
comparar padrão ON/OFF
        ↓
identificar o CHECK
```

Regras obrigatórias:

- toda foto de CHECK ou Referência Visual pode manter seu próprio contorno local
  e suas máscaras locais alinhadas aos segmentos visíveis naquela foto;
- essas geometrias locais ensinam **onde está o mesmo MASK_xxx na referência**;
  elas não substituem a geometria live canônica da seção **Máscaras**, conforme
  D-036;
- a análise deve priorizar o crop delimitado pelo contorno da placa/filtro e o
  alinhamento do padrão de segmentos dentro dessa região;
- comparação global da fotografia, fundo, suporte ou iluminação geral pode ser
  usada para presença, localização grosseira, aquisição ou diagnóstico, mas não
  pode ser uma segunda autoridade semântica de H1/BLUE/USB/AUX;
- após alinhamento válido, um CHECK está semanticamente conforme quando todas as
  máscaras ativas cumprem `mask_states`: esperadas `on` estão ON e esperadas
  `off` estão OFF; `ignore` não participa;
- portanto D-031 permanece intacta: uma única máscara ativa divergente continua
  bloqueando OK;
- quando o padrão estiver 100% conforme, um score de imagem inteira ou diferença
  visual de fundo não pode negar a identidade do CHECK;
- em H1, se o padrão aprendido estiver integralmente presente, H1 está
  reconhecido semanticamente; o registro produtivo ainda respeita somente os
  gates físicos/frescor/rearme já existentes para impedir decisão sobre frame
  stale, placa ausente ou ciclo encerrado;
- se todos os segmentos esperados ON estão visivelmente verdes, mas o CHECK não
  é registrado, o runtime/debug precisa indicar objetivamente qual condição
  restante bloqueou a decisão, em vez de resumir o caso como falha genérica de
  "análise visual";
- o aprendizado de NG só deve ser usado depois que a identificação positiva dos
  estados corretos estiver estável. Falso negativo causado por desalinhamento ou
  comparação global não deve virar memória de defeito.

### Consequência

A memória visual do F3 passa a representar **o desenho funcional do display**.
O ODIN procura a placa, trabalha na sua região útil, alinha os segmentos e decide
pela conformidade das máscaras. Isso evita que uma fotografia correta de H1 seja
negada por diferenças irrelevantes fora do display e torna explícito que o
sistema precisa aprender primeiro os estados corretos antes de usar exemplos NG.


---

## D-042 — Padrão semântico energizado pode confirmar presença quando a cena global é ambígua

**Status:** Accepted

### Contexto

Em 30/09/2026 um novo reteste físico reproduziu o defeito recorrente de H1:
visualmente os sete segmentos esperados estavam acesos e verdes, e o analyzer
estrito já classificava o próprio H1 como **28/28 conforme**, porém o CHECK não
avançava.

O DEBUG mostrou uma dependência circular no runtime canônico:

```text
foto global não confirma presença
→ F3RuntimeAuthorities não calcula a energia semântica das máscaras
→ gate publica placa_nao_confirmada_no_suporte
→ análise 28/28 fica raw_diagnostic_only
→ H1 nunca ganha autoridade
```

A cena global estava ambígua por diferença de enquadramento/foco/iluminação, mas
a informação funcional do display já era muito mais específica que o score da
fotografia inteira.

### Decisão

A separação **presença / energia / CHECK** permanece, mas observação e autoridade
passam a ser explicitamente diferentes:

1. a leitura semântica live das máscaras pode ser calculada antes do gate final
   de presença como **observação do mesmo frame**;
2. somente a `F3PresenceAuthority` pode transformar essa observação em
   `board_present=true`;
3. para isso, a energia precisa estar confirmada, o padrão precisa conter **todos
   os segmentos esperados ON** de pelo menos um CHECK configurado e nenhuma
   observação confiante pode contradizer os estados ON/OFF desse padrão;
4. essa correspondência serve exclusivamente para provar **OCUPAÇÃO física**;
   ela não aprova nem seleciona o CHECK produtivo;
5. depois da presença, a energia produtiva volta ao fluxo normal e o
   `F3StrictMaskConformityAnalyzer` continua exigindo a conformidade completa do
   CHECK lógico atual conforme D-031/D-041;
6. `EMPTY` confirmado possui precedência absoluta e nunca pode ser sobrescrito
   por emissão residual, reflexo ou evidência semântica;
7. tracking atual continua podendo confirmar presença conforme D-021; D-042 é o
   equivalente semântico necessário principalmente no caminho tracking OFF;
8. a implementação reutiliza o mesmo classificador/cache de energia por máscara;
   não cria timer, thread, worker, scheduler ou segunda autoridade.

### Consequência

A fotografia global deixa de ser um pré-requisito circular para que os próprios
segmentos provem que existe uma placa energizada. Um H1 real pode sair de
`IDENTIFICANDO PRESENÇA` quando o padrão aprendido está fisicamente presente,
mas somente o analyzer estrito pode concluir H1.

D-042 **refina a direção presença → energia descrita em D-015/D-022**: a
autorização produtiva de energia continua depois da presença, porém sua leitura
óptica pode existir antes como evidência entregue ao proprietário de presença.


---

## D-043 — Conformidade 100% do CHECK atual pode provar a transição física quando o padrão mudou

**Status:** Accepted

### Contexto

No reteste físico de 30/09/2026, D-042 foi validada: H1 passou corretamente e
a sequência avançou para BLUE. Em BLUE surgiu um bloqueio diferente.

O DEBUG do mesmo frame mostrava simultaneamente:

- presença confirmada;
- energia confirmada;
- gate produtivo liberado;
- BLUE configurado com 18 ON + 10 OFF;
- leitura semântica BLUE integralmente conforme, 28/28;
- ausência de máscaras divergentes na apresentação;
- porém o resultado final era vetado por
  `physical_transition_not_confirmed`, com a mensagem
  `BLUE BLOQUEADO • aguardando mudança física H1 → BLUE`.

A causa estava em `display_f3_physical_transition_authority.py`: para CHECKS
posteriores ao primeiro, a autoridade aceitava somente identificação visual
independente por contorno/estado físico ou comparação de fotos entre o CHECK
anterior e o atual. Mesmo quando o analyzer canônico provava que **todas** as
máscaras do padrão de destino estavam fisicamente no estado esperado, essa prova
não participava da confirmação da transição.

Isso contradizia D-041 no caso em que a fotografia inteira ficava ambígua: uma
comparação global/relativa de cena acabava funcionando como veto sobre um padrão
funcional já completamente identificado.

### Decisão

A autoridade física de transição continua existindo, mas passa a aceitar uma
segunda forma de prova positiva para CHECKS posteriores:

1. o CHECK anterior precisa estar concluído na máquina de estados;
2. a análise canônica precisa pertencer exatamente ao CHECK lógico atual;
3. a análise precisa estar `ready=true`, `approved=true` e com todas as máscaras
   ativas conformes (`matched == active`);
4. os `mask_states` do CHECK atual precisam diferir semanticamente do CHECK
   anterior em pelo menos uma máscara ON/OFF;
5. cumpridas essas condições, a conformidade 100% do destino é prova física de
   que a função mudou e a transição é confirmada;
6. 27/28, análise incompleta, análise de outro CHECK ou dois CHECKS com o mesmo
   padrão ON/OFF **não** usam essa confirmação e continuam dependentes da
   comparação física independente;
7. a regra confirma somente a chegada ao CHECK. Um CHECK defeituoso continua
   precisando de identificação física independente antes que um NG possa ser
   aplicado, evitando reprovar uma função anterior durante uma transição;
8. EMPTY, presença, energia, frescor, alinhamento e rearme continuam com suas
   autoridades e precedências atuais;
9. nenhuma nova thread, worker, scheduler, timer ou autoridade paralela é criada.

### Consequência

A sequência H1 → BLUE → USB → AUX não fica presa quando o padrão funcional do
CHECK de destino já está inequivocamente presente, mesmo que a fotografia global
ou a comparação entre cenas não prefira o destino.

Ao mesmo tempo, a proteção histórica contra avanço prematuro continua válida
para leituras parciais/defeituosas: somente conformidade total de um padrão que
realmente difere do anterior pode confirmar a transição por semântica.

D-043 refina a cláusula de D-024 que mantinha CHECKS posteriores sujeitos ao
gate de transição física: **o gate permanece; a conformidade estrita 100% passa
a ser uma evidência física válida do próprio handoff quando existe mudança real
de padrão**.

### Validação física — 30/09/2026

**PASS.** Com Rastreamento Automático desativado, H1 foi concluído, BLUE atingiu
conformidade completa e deixou de permanecer bloqueado em `H1 → BLUE`. A
sequência avançou para USB, confirmando no equipamento real o comportamento
previsto por D-043.


---

## D-044 — Produto NG pode provar presença e chegada ao CHECK sem precisar parecer um CHECK BOM

**Status:** Accepted

### Contexto

Depois da validação física de D-043, foi apresentado um BLUE realmente
**defeituoso**: o segmento/máscara 24 deveria estar ACESO, mas permaneceu
APAGADO. A câmera e a leitura por mesma máscara reconheciam a anomalia.

O DEBUG do frame congelado mostrou:

- CHECK lógico BLUE;
- configuração BLUE com 18 máscaras ON + 10 OFF;
- energia física do CHECK: 17 votos `powered`, 1 voto `off`, zero empate;
- `MASK_024`: esperada ON, classificada OFF com confiança alta;
- análise pelas fotos/máscaras: BLUE 27/28, exatamente com `MASK_024` divergente;
- mesmo assim a autoridade de presença publicou placa não confirmada porque
  D-042 exigia algum CHECK configurado integralmente conforme para usar a
  evidência semântica de presença.

Isso cria um deadlock lógico para NG: se a presença exige um CHECK perfeito, um
produto defeituoso não consegue chegar à etapa que deveria justamente detectar o
defeito.

Além disso, D-043 só permitia que conformidade 100% provasse a transição entre
CHECKS. Um BLUE 27/28 precisava de uma identificação física independente por
foto/contorno, que pode ficar ambígua exatamente nos casos em que a memória
funcional das máscaras já mostra que a função mudou.

### Decisão

D-044 separa definitivamente três perguntas:

1. **Há placa energizada?**
2. **A função física já mudou do CHECK anterior para o CHECK atual?**
3. **O CHECK atual está conforme?**

#### Presença

Quando a cena global estiver ambígua, `F3PresenceAuthority` pode confirmar
somente **OCUPAÇÃO** se a autoridade canônica de energia já publicou
`powered_confirmed=true` por votação multi-máscara discriminante, mesmo quando
nenhum CHECK configurado está 100% conforme.

Nesse modo:

- a origem continua sendo a própria `F3PresenceAuthority`;
- `matched_check_ids` permanece vazio;
- nenhuma identidade H1/BLUE/USB/AUX é inventada;
- nenhuma decisão OK/NG é concedida;
- EMPTY confirmado continua tendo precedência absoluta.

#### Chegada ao CHECK defeituoso

Para CHECKS posteriores, a autoridade existente de transição também pode usar a
assinatura das máscaras cujo estado ON/OFF **realmente mudou** entre o CHECK
anterior e o atual.

O procedimento é:

```text
CHECK anterior concluído
→ listar somente MASK_xxx cujo estado mudou anterior → atual
→ ler ON/OFF físico dessas máscaras pela autoridade de energia
→ contar votos que seguem o padrão atual e o padrão anterior
→ maioria estrita no padrão atual + atual > anterior
→ chegada ao CHECK atual confirmada
```

Essa regra não é um novo classificador de resultado. Ela apenas responde que a
função física já saiu do estado anterior e chegou predominantemente ao destino.
Uma máscara que ainda conserva o estado anterior pode então ser julgada como
falha pelo analyzer canônico.

#### Resultado

Depois de presença + energia + chegada válidas:

- o analyzer estrito continua sendo a única autoridade semântica das máscaras;
- uma máscara ativa divergente continua impedindo OK conforme D-031;
- o debounce NG já existente continua obrigatório, inclusive para CHECK
  intermitente como BLUE;
- D-044 não cria timer, worker, scheduler, thread ou autoridade paralela;
- análise parcial/stale de outro CHECK não ganha autoridade;
- se a assinatura ainda prefere o CHECK anterior, NG permanece bloqueado para
  não reprovar prematuramente durante uma transição.

### Consequência

Um produto defeituoso deixa de precisar imitar um produto BOM para entrar no
fluxo de julgamento. No caso físico que originou D-044, 17 segmentos esperados
ON de BLUE confirmam energia e a assinatura H1 → BLUE confirma que a função
mudou, enquanto `MASK_024=OFF` permanece livre para ser detectada pelo analyzer
como NG.

D-044 refina D-042 e D-043 sem enfraquecer D-031:

- D-042 continua válido para padrão completo e presença;
- D-043 continua válido para transição de CHECK 100% conforme;
- D-044 cobre especificamente **presença energizada com CHECK divergente** e
  **chegada semântica forte de um CHECK defeituoso**.

### Validação física — 01/10/2026

**PASS.** Com Rastreamento Automático desativado, o cenário BLUE defeituoso foi
reproduzido com `MASK_024` esperada ON permanecendo fisicamente OFF. O runtime
manteve presença e energia válidas, confirmou a chegada à função BLUE sem exigir
um BLUE perfeito e o analyzer registrou corretamente o defeito como NG.

Isso valida no equipamento real a separação introduzida por D-044 entre
**presença**, **chegada ao CHECK** e **conformidade/NG**.


---

## D-045 — NG congelado destaca somente a falha efetivamente confirmada

**Status:** Accepted

### Contexto

Após D-044 ser validada fisicamente, o BLUE defeituoso passou a gerar NG
corretamente. No estado terminal, porém, a câmera congelada e o VISOR DO DISPLAY
continuavam mostrando os segmentos apenas pelas cores físicas ON/OFF, sem apontar
visualmente qual segmento havia fechado o defeito.

O DEBUG do mesmo caso mostrou duas camadas distintas de divergência:

- `effective_failed_mask_ids` bruto podia conter múltiplos IDs transitórios;
- `effective_confirmed_failed_mask_ids` continha somente a falha persistente que
  efetivamente sobreviveu ao debounce/intermitência e fechou o NG.

No cenário físico, `MASK_024` era a falha confirmada. Usar a lista bruta para o
vermelho faria a UI marcar também divergências temporárias como defeitos finais.

### Decisão

1. O **SEGREGAR manual** preserva D-040: câmera, contorno, máscaras e visor podem
   ficar integralmente vermelhos durante o latch terminal.
2. O **NG automático/congelado** usa outra regra: somente IDs presentes em
   `effective_confirmed_failed_mask_ids` recebem vermelho.
3. A câmera congelada e o VISOR DO DISPLAY consomem a mesma lista confirmada do
   mesmo contexto/frame que fechou o NG.
4. `effective_failed_mask_ids` bruto e `effective_validating_mask_ids` não são
   fonte do vermelho terminal de NG.
5. Máscaras não confirmadas como falha continuam exibindo a semântica física
   normal: verde para ON, verde escuro para OFF e amarelo quando aplicável.
6. No VISOR DO DISPLAY, a falha confirmada tem prioridade visual sobre o caminho
   `live_luminous_only`; portanto um segmento fisicamente OFF mas confirmado NG
   aparece vermelho, não verde escuro.
7. Na câmera, a máscara confirmada recebe preenchimento/contorno vermelho com
   prioridade sobre o espelho luminoso ON/OFF.
8. A regra é somente de apresentação. Não altera analyzer, debounce, presença,
   energia, sequência, rearme, tracking ou classificação óptica.
9. Nenhum novo timer, worker, scheduler, thread ou autoridade é criado.

### Consequência

O frame congelado passa a explicar visualmente o NG: o operador vê exatamente a
máscara/segmento que fechou a reprovação, enquanto o restante do display continua
representando o estado físico real.

Para o caso que originou D-045, o resultado esperado é:

```text
BLUE terminal NG
→ MASK_024 confirmada como falha
→ máscara 24 vermelha na câmera congelada
→ segmento 24 vermelho no VISOR DO DISPLAY
→ demais segmentos permanecem ON/OFF normais
```

### Reteste físico visual — 01/10/2026

A primeira implementação de D-045 **não passou** no equipamento. O resultado NG
foi correto, mas `MASK_024` continuou verde escuro tanto na câmera congelada
quanto no VISOR DO DISPLAY.

O novo DEBUG confirmou que a decisão semântica estava correta e que
`effective_confirmed_failed_mask_ids` continha somente `MASK_024`. O problema
era de lifecycle visual: a lógica de cor estava correta quando chamada
isoladamente, porém o freeze podia preservar o último repaint live anterior à
confirmação final do debounce.

A implementação foi então consolidada no próprio caminho de congelamento:

1. o runtime preserva o frame/análise exatos que fecharam o NG;
2. a janela levanta o latch e sincroniza o readout congelado explicitamente com
   `effective_confirmed_failed_mask_ids`;
3. depois do latch, a câmera é repintada diretamente a partir do mesmo frame
   congelado e do mesmo contexto, sem nova captura e sem nova análise;
4. segmentos do visor recebem tags de diagnóstico por `MASK_xxx` e estado para
   permitir verificar a cor que realmente chegou ao canvas;
5. o snapshot de DEBUG preserva o estado visual runtime anterior a qualquer
   reconstrução manual, evitando que o diagnóstico recalcule o contexto e
   esconda uma falha de apresentação;
6. nenhum timer, worker, scheduler ou classificador adicional foi criado.

**Validação física — 01/10/2026: PASS.** O reteste no equipamento confirmou
a segunda correção de D-045. No BLUE NG com `MASK_024` fisicamente apagada, a
máscara 24 ficou vermelha na câmera congelada e o segmento 24 ficou vermelho no
VISOR DO DISPLAY, enquanto os demais segmentos mantiveram suas cores físicas
normais. O comportamento terminal permaneceu congelado até a retirada da placa.


---

## D-046 — Resultado APROVADO mantém espelho visual live e same-mask vence falso ON visual

**Status:** Accepted

### Contexto

Após D-045 ser validada, foi observado um novo caso no resultado terminal
**PLACA APROVADA**. O AUX estava fisicamente correto e havia sido aprovado pelo
analyzer, porém o VISOR DO DISPLAY mostrava o segmento 10 em verde como se
estivesse ACESO, embora AUX configure `MASK_010=off`.

O DEBUG confirmou que a decisão produtiva estava correta:

- AUX foi reconhecido por aprendizado same-mask como **28/28 conforme**;
- `MASK_010` em AUX estava `expected=off`, `classified=off` e
  `matched=true`;
- a presença semântica identificava a placa como AUX;
- portanto o verde da `MASK_010` era apenas erro de apresentação, sem
  participação no OK.

Ao mesmo tempo, a telemetria do espelho visual mostrava dois problemas:

1. o sampler leve de brilho do preview listava `MASK_010` entre as máscaras
   luminosas, mesmo com a autoridade física same-mask classificando-a OFF;
2. o hook visual estava caindo em
   `fixed_render_exception` porque `_render_check_cards_f3_fixed()` não aceitava
   o parâmetro `force_terminal_segregated`, fazendo fallback para o render
   anterior e permitindo que as máscaras ficassem cinzas ao encerrar o ciclo.

### Decisão

1. A decisão produtiva continua integralmente separada do espelho visual.
2. Quando a autoridade física same-mask e o sampler leve observarem o **mesmo
   frame**, a classificação física same-mask prevalece para ON/OFF visual.
3. O sampler latest-frame continua sendo usado para:
   - máscaras sem classificação física disponível;
   - substituir classificação física pertencente a frame anterior/stale.
4. O espelho visual de câmera + VISOR DO DISPLAY continua ativo após
   **PLACA APROVADA**, enquanto a placa permanecer no suporte aguardando EMPTY.
5. Resultado OK não congela câmera nem visor. O freeze continua exclusivo do NG
   conforme D-045; SEGREGAR mantém o override terminal definido por D-040.
6. Wrappers que substituem `_render_check_cards` precisam preservar a assinatura
   atual, inclusive `force_terminal_segregated`, para não interromper o pipeline
   visual.
7. A telemetria do espelho passa a registrar se o frame físico same-mask é o
   mesmo frame do preview, permitindo distinguir:
   - sampler visual usado como fallback;
   - classificação física same-mask usada como autoridade de apresentação.
8. Nenhum timer, worker, scheduler ou classificador produtivo adicional é criado.

### Consequência

No caso AUX que originou D-046:

```text
AUX correto
→ analyzer same-mask = 28/28
→ MASK_010 expected OFF / classified OFF
→ resultado da placa = OK
→ VISOR mantém MASK_010 verde escuro
→ demais máscaras continuam reagindo ao estado físico live
→ câmera e visor permanecem atualizando até a placa sair do suporte
```

A correção não altera o resultado do CHECK; ela torna a apresentação consistente
com a mesma evidência física que já estava correta no runtime.

**Validação física:** pendente de reteste no resultado APROVADO com AUX ainda no
suporte.

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

---

## D-047 — Zoom do F3 pertence ao Projeto Display e usa uma única visão derivada do frame

**Status:** Accepted

### Contexto

O Display F3 usa atualmente uma Logitech BRIO 4K e precisa permitir aproximação
da placa sem exigir reposicionamento físico imediato da câmera.

Existem duas formas diferentes de aproximação:

1. o zoom exposto pelo próprio dispositivo/driver através de
   `CAP_PROP_ZOOM` no DirectShow;
2. um zoom por software do ODIN, feito sobre o frame já capturado.

Aplicar somente um zoom visual no canvas criaria uma inconsistência grave:
o operador enxergaria a placa ampliada, mas presença, tracking, máscaras,
CHECKS e decisão OK/NG continuariam trabalhando sobre outro frame.

### Decisão

1. Os dois zooms são configuração **por Projeto Display**, persistida no
   repositório exclusivo do F3.
2. O zoom da câmera é representado por:
   - `camera_zoom.enabled`;
   - `camera_zoom.value`, no intervalo 100–500, equivalente a 1×–5× para o
     perfil BRIO/DirectShow.
3. O serviço canônico de câmera continua sendo o único proprietário do hardware.
   O F3 apenas envia `zoom_enabled` e `zoom`; suporte real é confirmado por
   escrita + readback, como nos demais controles manuais.
4. Ao fechar o F3, o zoom de hardware é desabilitado pelo mesmo serviço e o
   baseline capturado antes do ajuste é restaurado, preservando o isolamento F2/F3.
5. O zoom ODIN é persistido como `software_zoom`, de 1× a 5×.
6. O zoom ODIN usa crop central e redimensiona de volta para a mesma largura e
   altura do frame original. Assim a resolução mestre e o sistema de coordenadas
   do F3 permanecem estáveis.
7. `F3RuntimeCoordinator` é o ponto único que entrega essa visão derivada aos
   callbacks do F3. Preview, tracking, presença, energia, analyzer e freeze NG
   observam o mesmo frame ampliado durante o ciclo.
8. O frame bruto global da câmera não é substituído permanentemente; ele é
   restaurado ao terminar cada callback do F3.
9. O zoom por software possui cache por frame/projeto/fator para evitar repetir
   crop + resize quando o mesmo frame é apenas repintado.
10. Alterar qualquer zoom muda o enquadramento físico aparente. Portanto o
    operador deve revisar ou recapturar foto de referência, contorno e máscaras
    antes de liberar produção.
11. Nenhum novo timer, worker, scheduler ou autoridade paralela é criado.

### Consequência

O F3 passa a oferecer dois níveis de aproximação sem misturar estado com F2 e
sem permitir que UI e decisão produtiva enxerguem imagens diferentes.

O comportamento físico da BRIO ainda depende do suporte real que o driver
DirectShow expõe para `CAP_PROP_ZOOM`; quando o driver não confirmar o valor,
o controle permanece diagnosticável como não aplicado/ignorado.

---

## D-048 — Enquadramento do zoom ODIN é uma janela persistente do Projeto Display

**Status:** Accepted

### Contexto

Depois da validação física do zoom de câmera e do zoom ODIN, surgiu a necessidade
de não limitar o zoom por software a um crop central fixo.

O operador precisa enxergar a imagem da câmera ao vivo, aproximar a região de
interesse e decidir visualmente: **"é aqui; é isto que será exibido na câmera do
F3 Display"**.

### Decisão

1. O zoom ODIN continua sendo uma transformação única do frame F3, mas passa a
   possuir um centro configurável `x/y` normalizado por Projeto Display.
2. O Projeto Display persiste:
   - `software_zoom`;
   - `software_zoom_center.x`;
   - `software_zoom_center.y`.
3. A configuração do F3 apresenta duas visualizações:
   - **ENQUADRAMENTO • ARRASTE A JANELA**: mostra o frame-fonte e a janela que
     será recortada;
   - **VISUALIZAÇÃO AO VIVO • SAÍDA FINAL DO F3**: mostra o resultado efetivo
     após zoom/enquadramento e rotação visual.
4. Clique ou arraste sobre a visualização-fonte reposiciona o centro da janela.
   A janela é limitada geometricamente para nunca sair do frame.
5. O mesmo recorte salvo é consumido pelo runtime produtivo. Preview, tracking,
   presença, energia, máscaras, análise OK/NG e freeze terminal continuam
   observando a mesma visão derivada.
6. O frame bruto permanece disponível somente como fonte do seletor de
   enquadramento; ele não vira uma segunda autoridade de decisão.
7. A atualização ao vivo da configuração reutiliza o `F3RuntimeCoordinator`.
   Não é criado novo timer, worker, fila ou scheduler.
8. Durante a configuração, mudanças do zoom físico podem ser aplicadas para
   preview. Ao fechar sem salvar, o runtime reaplica a configuração persistida
   do Projeto Display ativo.
9. Alterar enquadramento invalida visualmente referências anteriores; antes da
   produção o operador deve revisar/recapturar foto, contorno e máscaras.

### Consequência

O F3 passa a possuir uma "câmera virtual" configurável sobre a imagem ampliada,
sem alterar a resolução mestre nem duplicar o pipeline de visão.

---

## D-049 — Mapa único de enquadramento representa o campo de visão efetivo do F3

**Status:** Accepted

### Contexto

A primeira UI de zoom mostrava duas visualizações grandes e aplicava rotação
visual na prévia final. Isso tornou difícil entender qual imagem era a referência
espacial e qual região efetivamente seria usada pelo F3.

Também havia um desacoplamento conceitual: o viewport arrastável movia apenas o
crop do Zoom ODIN, enquanto o zoom digital da câmera permanecia central.

### Decisão

1. A configuração de zoom do F3 possui uma **imagem principal de referência em
   1× e orientação natural da câmera**.
2. Sobre essa imagem existe um único **quadro azul**, que representa o campo de
   visão final usado pelo F3.
3. O tamanho do quadro azul representa o zoom efetivo combinado:

       zoom efetivo = zoom digital da câmera × Zoom ODIN

4. O mapa principal não aplica a rotação visual configurada do F3. Rotação
   continua pertencendo ao pipeline de produção, não à navegação espacial do
   operador.
5. A prévia secundária passa a ser apenas **RECORTE ATUAL DO F3 • SEM ROTAÇÃO**.
6. Quando o zoom físico da câmera está acima de 1×, arrastar o quadro azul move
   o centro do zoom através dos controles UVC/DirectShow `PAN` e `TILT`.
7. Quando o zoom físico está desativado, o mesmo gesto move
   `software_zoom_center.x/y`.
8. O centro do zoom físico é persistido por Projeto Display como
   `camera_zoom_center.x/y`.
9. Para permitir navegação enquanto a câmera física já está ampliada, o ODIN
   preserva em memória um snapshot 1× da sessão imediatamente antes de aplicar
   o zoom físico. Esse snapshot é somente referência visual; decisões de visão
   continuam usando frames atuais.
10. Fechar o F3 restaura zoom/pan/tilt da câmera por meio do mesmo serviço
    canônico de controles ao vivo; F2 não herda esses ajustes.
11. Nenhum timer, worker, fila ou scheduler adicional é criado.

### Consequência

O operador passa a trabalhar com uma única metáfora visual:

    imagem completa 1×
    + quadro azul = área que o F3 usará
    + arrastar quadro = mover enquadramento

A UI deixa de misturar navegação de enquadramento com rotação visual de produção.

---

## D-050 — Visualizações de configuração do F3 seguem a rotação visual do desenvolvimento

**Status:** Accepted

### Contexto

A D-049 definiu o mapa de zoom em orientação natural/sem rotação para simplificar
o enquadramento. No uso físico, isso criou uma inconsistência com a tela principal
de desenvolvimento: quando o operador define, por exemplo, **180°**, a câmera do
F3 é visualizada em 180°, mas o mapa do zoom e a janela de captura de máscaras
continuavam aparecendo na orientação original.

### Decisão

A regra mais recente é:

1. a rotação visual definida na tela de desenvolvimento é a autoridade de
   apresentação para todas as visualizações operacionais do F3;
2. o **MAPA DA CÂMERA** do zoom usa essa rotação;
3. o **RECORTE ATUAL DO F3** usa a mesma rotação;
4. o quadro azul é desenhado na orientação visual e o gesto de drag é convertido
   de volta para coordenadas canônicas antes de alterar centro de zoom,
   `pan/tilt` ou `software_zoom_center`;
5. **Máscaras → Capturar foto com a câmera** também mostra o frame ao vivo com a
   mesma rotação visual;
6. a captura salva o frame mestre na orientação canônica, sem gravar a rotação
   visual nos pixels; isso evita rotação dupla quando a foto é carregada pelo
   editor de máscaras;
7. geometria persistida continua na resolução/orientação mestre e é transformada
   apenas para apresentação/edição visual;
8. a rotação continua sendo 0/90/180/270 conforme o contrato existente da tela
   principal;
9. nenhum novo timer, worker, scheduler ou autoridade de câmera é criado.

### Relação com D-049

D-050 **substitui especificamente** os itens da D-049 que exigiam mapa e recorte
"sem rotação". Permanecem válidos os demais contratos da D-049 sobre quadro azul,
zoom combinado, pan/tilt, persistência por projeto e snapshot 1×.

### Consequência

Se o operador definiu 180° na tela de desenvolvimento, ele deve enxergar 180° em:

    câmera F3
    mapa de zoom
    recorte atual do zoom
    captura ao vivo de referência das máscaras
    editores/referências que já seguem a rotação visual

A persistência interna permanece canônica.

## D-051 — CHECK intermitente reconcilia falso OFF ambiguo somente com prova fisica ON da mesma mascara

**Status:** Accepted

### Contexto

No teste fisico de 02/10/2026, H1 foi concluido e a sequencia chegou ao BLUE
com a placa presente e energizada. O padrao BLUE correto permaneceu, porem, em
25/28 mascaras conformes. A autoridade estrita classificou
`MASK_021`, `MASK_023` e `MASK_024` como OFF com confiancas proximas do
empate, apesar de as tres regioes estarem visualmente luminosas.

O DEBUG do mesmo caso mostrou duas evidencias adicionais:

- o gabarito fotografico do proprio BLUE reconhecia as tres mascaras como ON;
- a comparacao fisica da mesma mascara entre BLUE, LIVE e PLACA DESLIGADA
  publicou 18/18 votos de energia para as mascaras esperadas ON.

O runtime de CHECK intermitente ja possuia veto para falso OFF confirmado por
template exato, mas a autoridade estrita nao publica esse metadado de template
porque D-038 impede que a foto do proprio CHECK se torne a autoridade semantica
que o aprova. Assim, o BLUE podia ficar indefinidamente em busca mesmo quando a
leitura produtiva estava apenas ambigua e a mesma mascara possuia prova fisica
de emissao.

### Decisao

A autoridade semantica estrita permanece inalterada. A reconciliacao passa a
usar uma evidencia fisica auxiliar, com as seguintes restricoes:

1. somente divergencias `expected=ON` e `classified=OFF` podem receber esse
   suporte;
2. a classificacao estrita precisa estar na faixa ambigua ja existente
   (`confidence < F3_CHECK_PHOTO_MIN_CONFIDENCE`); uma falha OFF confiante nao
   pode ser rebaixada por esta regra;
3. o suporte usa exclusivamente features ja extraidas/cached da **mesma
   MASK_xxx**:
   - LIVE do frame em julgamento;
   - ON da foto do CHECK logico atual;
   - OFF da referencia PLACA DESLIGADA;
4. a referencia ON do CHECK atual so pode ajudar quando ON e OFF sao
   fisicamente discriminantes segundo o classificador relativo de energia ja
   existente. Referencia ON escura ou praticamente igual ao OFF produz empate e
   nao possui autoridade;
5. o analyzer estrito apenas anota a evidencia. Ele nao altera seu
   `classified`, `matched` ou `approved`;
6. somente o runtime de CHECK **intermitente**, durante uma fase ON valida, pode
   consumir a anotacao e reconciliar aquele falso OFF na copia efetiva do mesmo
   frame;
7. OFF ou empate na evidencia fisica mantem a divergencia. O contador
   persistente e o NG continuam funcionando normalmente;
8. a fase ON completa continua tendo que existir em **um unico frame**. Nao ha
   soma de segmentos vistos em frames diferentes;
9. nao foi reduzido threshold global, nao existe aprovacao 25/28 e nenhuma
   mascara OFF esperada e transformada em ON por esta regra;
10. nenhum timer, worker, scheduler ou segunda autoridade produtiva foi criado.

### Consequencia

Um BLUE correto deixa de ficar preso porque o classificador aprendido ficou
praticamente empatado em uma mascara que a evidencia fisica da propria ROI
confirma como energizada. Ao mesmo tempo, um segmento realmente defeituoso
continua OFF: se LIVE permanecer proximo de PLACA DESLIGADA, nao existe suporte
positivo e a divergencia segue para a persistencia/NG ja definida em D-031 e
D-044.

A regra preserva D-038: a foto do CHECK atual nao se autoaprova. Ela participa
somente como extremo ON de uma comparacao fisica discriminante contra uma
referencia OFF independente da mesma mascara.

### Validacao

- regressao automatica cobre falso OFF ambiguo com suporte fisico positivo;
- regressao automatica cobre segmento realmente apagado sem suporte;
- regressao automatica cobre referencia ON escura, que permanece sem autoridade;
- reteste fisico do BLUE correto e do BLUE com `MASK_024` realmente apagada
  permanece pendente.

---

## D-052 — H1 desempata falso OFF ambíguo somente com prova física same-mask independente

**Status:** Accepted

### Contexto

No reteste físico de 02/10/2026, a placa estava corretamente no H1 e o gate
produtivo já estava liberado, mas o primeiro CHECK permaneceu em **26/28**.

O DEBUG do mesmo frame mostrou uma contradição objetiva entre duas leituras da
mesma região:

- o gabarito exato da foto de H1 reconheceu **28/28**;
- `MASK_012` e `MASK_020`, ambas esperadas ON, estavam visualmente saturadas e
  muito próximas da própria referência H1;
- o classificador semântico estrito, porém, decidiu OFF nas duas com confiança
  praticamente empatada;
- a comparação física direta da mesma máscara
  `BOARD_OFF ↔ LIVE ↔ H1` confirmou **7/7 máscaras esperadas ON como powered**.

D-051 não resolvia esse cenário porque foi deliberadamente limitada a CHECK
intermitente. H1 é não intermitente. Além disso, o suporte de D-051 utiliza as
features do aprendizado semântico; para `MASK_012` e `MASK_020`, as amostras
aprendidas ON/OFF ficaram próximas demais para serem discriminantes, embora a
comparação direta das imagens físicas H1 e PLACA DESLIGADA separasse corretamente
o estado live.

### Decisão

O primeiro CHECK/reference gate recebe um **desempate físico restrito**, sem
transformar a foto do próprio H1 em autoridade semântica isolada.

A regra é:

1. só é avaliada no primeiro CHECK/reference gate e fora do modo intermitente;
2. só é chamada quando existe uma divergência
   `expected=ON → classified=OFF`;
3. a divergência precisa estar na faixa semântica já considerada ambígua
   (`confidence < 0.58`);
4. a evidência vem da `F3PowerAuthority`, reutilizando a comparação física já
   existente da **mesma MASK_xxx** no mesmo frame:
   - LIVE atual;
   - foto do CHECK atual como extremo ON;
   - referência independente **PLACA DESLIGADA** como extremo OFF;
5. ON e OFF precisam ser fisicamente discriminantes;
6. somente `winner=powered` pode desempatar a máscara para ON;
7. `winner=off`, empate, referência não discriminante ou evidência ausente
   preservam a falha original;
8. uma decisão semântica OFF confiante não pode ser sobrescrita;
9. máscaras `expected=OFF` nunca participam desse resgate;
10. depois do desempate, a conformidade completa é recalculada. O H1 só recebe
    OK se todas as máscaras ativas ficarem conformes;
11. o gabarito exato de pixels continua diagnóstico. Ele sozinho não aprova H1;
12. não há redução de threshold global, aprovação parcial, soma entre frames,
    timer, worker, scheduler ou segunda máquina de decisão.

### Proteção contra autoaprendizado de defeito

D-038 permanece válida.

A foto do H1 funciona apenas como o extremo ON de uma comparação contra uma
referência OFF independente. Se a própria foto H1 tiver o segmento apagado, ON
e OFF não serão discriminantes e o desempate não terá autoridade. Se o produto
live estiver realmente com o segmento apagado, LIVE ficará do lado OFF e a
divergência permanece.

Portanto:

```text
H1 bom + classificador semântico empatado + LIVE fisicamente ON
→ desempate físico same-mask
→ 28/28
→ fluxo normal de OK

H1 com segmento realmente apagado
→ LIVE próximo de BOARD_OFF
→ nenhum desempate
→ H1 continua não conforme
```

### Implementação

- `F3PowerAuthority` expõe a primitiva existente de comparação relativa do
  CHECK atual, sem ganhar autoridade de OK/NG;
- `DisplayAutomaticCheckF3Mixin` solicita essa evidência somente quando o H1
  possui falso OFF ambíguo;
- a correção é aplicada sobre a cópia da análise do mesmo frame e preserva a
  classificação semântica anterior em telemetria;
- os contadores e IDs de falha são recalculados antes da política produtiva e da
  publicação para a UI.

### Validação

Regressões automatizadas cobrem:

- H1 26/28 com falsos OFF ambíguos em `MASK_012` e `MASK_020`, ambos
  fisicamente powered, fechando 28/28;
- segmento realmente apagado, que permanece OFF;
- OFF semântico confiante, que não pode ser relaxado;
- máscara esperada OFF, que nunca pode ser promovida por esta regra;
- integração do runtime: H1 ambíguo + prova física válida avança pelo fluxo
  produtivo existente.

**Reteste físico:** pendente.

---

## D-053 — H1 reconcilia falso OFF pela prova física, sem corte de confiança semântica

**Status:** Accepted

### Contexto

O reteste físico posterior à D-052 manteve o H1 correto preso em **27/28**.
A única divergência foi `MASK_013`, configurada ON e fisicamente acesa, mas
classificada OFF pelo aprendizado semântico com `confidence=0.5944`.

No mesmo frame:

- o gabarito exato da foto H1 reconheceu `MASK_013` como ON e fechou 28/28;
- a comparação física direta `BOARD_OFF ↔ LIVE ↔ H1` classificou
  `MASK_013` como `powered`;
- a votação direta do CHECK publicou 7/7 máscaras ON como `powered`;
- a autoridade global de energia publicou 6 ON + 1 OFF porque responde outra
  pergunta: se existe energia física suficiente no display, usando o pool
  aprendido de todas as máscaras discriminantes.

A D-052 condicionava a consulta/reconciliação física a
`confidence < 0.58`. Esse corte não representa uma fronteira física. A
confiança do classificador same-mask é derivada da distância dentro do pool de
referências aprendidas; ela pode ficar acima de 0.58 e ainda contradizer uma
comparação física direta, independente e mais específica da mesma ROI.

### Decisão

O primeiro CHECK/reference gate mantém a conformidade estrita, mas o falso OFF
`expected=ON → classified=OFF` passa a ser reconciliado pela evidência física
same-mask sem usar um threshold de confiança semântica como gate.

A regra é:

1. somente o primeiro CHECK/reference gate, não intermitente, usa esta
   reconciliação;
2. qualquer divergência `expected=ON → classified=OFF` solicita a comparação
   física direta pela `F3PowerAuthority`;
3. a evidência precisa declarar explicitamente comparação da **mesma máscara**;
4. a referência OFF continua sendo a cena independente
   **PLACA DESLIGADA** e a referência ON é a foto do CHECK atual;
5. OFF e ON precisam ser fisicamente discriminantes;
6. somente `winner=powered` reconcilia a máscara para ON;
7. `winner=off`, `tie`, evidência ausente ou referência não discriminante
   preservam integralmente a falha semântica;
8. a confiança semântica anterior continua registrada em telemetria, mas não
   pode vetar uma prova física direta que cumpra os itens anteriores;
9. máscaras esperadas OFF continuam fora dessa regra;
10. depois da reconciliação o H1 ainda exige **100% das máscaras ativas
    conformes no mesmo frame** para receber OK;
11. o gabarito exato da foto do CHECK continua diagnóstico e não aprova sozinho;
12. a autoridade global de energia continua responsável por
    **PRESENÇA/ENERGIA**, não por arbitrar a conformidade individual do H1;
13. nenhum timer, worker, scheduler, fila ou segunda autoridade produtiva é
    criado.

### Segurança do defeito real

A retirada do corte `0.58` não transforma uma classificação semântica
confiante em OK automaticamente.

O fluxo continua sendo:

```text
expected ON + semantic OFF
→ comparar BOARD_OFF x LIVE x ON do mesmo MASK_xxx

LIVE = powered + referências discriminantes
→ reconciliar falso OFF

LIVE = off/tie OU referências não discriminantes
→ manter OFF
→ H1 não avança
```

Assim, um segmento realmente apagado continua protegido mesmo quando a
classificação semântica possui confiança alta.

### Relação com D-052

D-053 substitui especificamente os itens da D-052 que usavam
`confidence < 0.58` como condição para consultar/aplicar o desempate físico.
Os demais contratos da D-052 permanecem válidos.

### Validação automatizada

As regressões cobrem:

- reprodução de `MASK_013` com `confidence=0.5944` e prova física
  `powered`, que passa a reconciliar;
- integração do runtime H1 no mesmo cenário, avançando pelo fluxo oficial;
- segmento realmente apagado com confiança semântica alta e prova física
  `off`, que permanece falha;
- máscaras esperadas OFF continuam impossíveis de promover por essa regra;
- o gate rápido H1/BLUE permanece verde.

**Validação física:** pendente de reteste.

---

## D-054 — Zoom físico do F3 valida readback real e se recupera de reset do driver

**Status:** Accepted

### Contexto

Em 02/10/2026, após as correções de enquadramento/rotação já validadas,
o operador relatou que o zoom físico da câmera do F3 **se desfez durante o uso**.

A configuração lógica do Projeto Display continuava indicando zoom aplicado,
mas a câmera podia retornar fisicamente a outro valor — por exemplo, voltar
para 1× após renegociação/reinicialização do backend UVC/DirectShow.

O runtime mantinha uma assinatura em memória com o último comando enviado:

```text
(enabled, zoom_value, center_x, center_y)
```

Se essa assinatura não mudasse, o F3 concluía que o zoom ainda estava aplicado
e evitava reenviar o comando. Esse cache lógico não detectava quando o hardware
perdia o zoom sem alterar a configuração persistida.

### Decisão

O cache lógico do zoom deixa de ser suficiente para considerar o zoom físico
válido.

Quando existe zoom físico configurado acima de 1×:

1. o F3 consulta, quando disponível, o último **readback real** publicado pelo
   serviço canônico de controles da câmera;
2. se o readback ainda coincide com o zoom configurado, a assinatura lógica
   continua válida e nenhum comando redundante é enviado;
3. se o readback mostra que a câmera voltou a outro valor, a assinatura em
   memória deixa de impedir a reaplicação;
4. o zoom salvo do Projeto Display é reaplicado pelo mesmo caminho canônico de
   controles de câmera;
5. se existe alteração de câmera ainda pendente, o runtime não dispara uma
   segunda aplicação concorrente;
6. enquanto **CONFIGURAR** está aberto, a recuperação automática não sobrescreve
   um valor que o operador ainda está testando e não salvou;
7. backends que não expõem readback continuam compatíveis: ausência de leitura
   não é tratada automaticamente como reset;
8. a recuperação reutiliza o scheduler/repaint canônico do F3; nenhum novo
   `after()`, timer, worker, thread ou serviço de câmera é criado.

### Consequência

A verdade do zoom físico passa a ser:

```text
configuração persistida
+ assinatura do último comando
+ readback real do hardware quando disponível
```

Assim, uma reinicialização silenciosa do zoom pelo driver não deixa o F3 preso
na falsa condição "zoom já aplicado".

### Complemento de implementação — 05/10/2026

O reteste físico mostrou que o zoom da câmera ainda podia se desfazer. A revisão
do caminho real encontrou uma lacuna na primeira implementação da D-054:
`obter_valores_controles_camera_ao_vivo()` expunha o último readback armazenado
durante a aplicação do controle, mas esse valor **não era atualizado novamente**
se o driver alterasse `CAP_PROP_ZOOM` sozinho depois disso.

Portanto, um estado como:

```text
comando enviado = 250
cache de readback = 250
hardware reseta silenciosamente para 100
cache continua = 250
```

fazia a assinatura lógica parecer válida e impedia a recuperação prevista pela
própria D-054.

O contrato é complementado sem criar nova autoridade:

1. enquanto o zoom manual está habilitado, o serviço canônico de câmera atualiza
   periodicamente o readback de `CAP_PROP_ZOOM`;
2. essa leitura ocorre na **mesma thread canônica de captura**, preservando a
   afinidade do `VideoCapture`;
3. a leitura é limitada em cadência e não cria `after()`, timer, worker,
   scheduler ou segunda câmera;
4. valores fora da faixa configurada, como `0` retornado por backend sem
   suporte, não substituem um readback válido nem provocam loop de reaplicação;
5. o F3 continua sendo apenas consumidor desse readback: se o valor real diverge
   do Projeto Display, reutiliza o mesmo caminho canônico já existente para
   reaplicar zoom/pan/tilt.

Assim, a D-054 passa a depender de **readback fresco do hardware**, e não apenas
do último valor lido durante uma escrita anterior.

### Regressões automatizadas

Foram adicionados testes para:

- readback igual ao zoom solicitado → não reaplicar;
- hardware resetado de 2.5× para 1× → invalidar assinatura e reaplicar;
- comando ainda pendente → não duplicar aplicação;
- preservar contratos existentes de zoom/enquadramento e preview ao vivo.

Os workflows específicos de câmera/zoom utilizados na correção passaram.

**Validação física:** pendente de reteste explícito após esta correção.

---

## D-055 — Reconciliação física do H1 usa primitiva estável, fora do monkey patch da energia unificada

**Status:** Accepted

### Contexto

O reteste físico posterior à D-053 ainda deixou o H1 correto em **27/28**, com
`MASK_013` como único falso OFF.

O DEBUG do runtime mostrou:

```text
reference_gate_physical_tie_breaker_ids=[]
reference_gate_physical_tie_breaker_source=f3_unified_live_mask_power_authority
effective_failed_mask_ids=[MASK_013]
```

No mesmo frame, o diagnóstico direto `CHECK x PLACA DESLIGADA` publicou:

```text
expected_on=7
powered_votes=7
off_votes=0
MASK_013=powered
```

Portanto D-053 estava correta no critério de reconciliação, mas o runtime não
estava recebendo a evidência física que a decisão pressupunha.

A causa foi a camada histórica de compatibilidade da autoridade de energia v2.
Na instalação final ela substituía em runtime:

```python
power_module.avaliar_evidencia_energia_relativa_display_f3
    = avaliar_evidencia_energia_unificada_display_f3
```

`F3PowerAuthority.evaluate_current_check_relative()` chamava exatamente esse
símbolo substituível. Assim, a reconciliação individual do H1 recebia a
autoridade global de energia — que marcou `MASK_013` OFF — em vez do
comparador direto BOARD_OFF/LIVE/ON do CHECK atual.

### Decisão

A comparação física individual do CHECK atual passa a possuir uma primitiva
estável e explicitamente separada da compatibilidade histórica:

```text
avaliar_evidencia_energia_check_relativa_display_f3
```

Regras:

1. a primitiva estável continua pertencendo ao mesmo módulo/autoridade física;
   não é criada uma segunda autoridade;
2. ela compara exclusivamente a mesma máscara em
   **BOARD_OFF ↔ LIVE ↔ foto ON do CHECK atual**;
3. `F3PowerAuthority.evaluate_current_check_relative()` deve chamar essa
   primitiva estável;
4. o nome legado `avaliar_evidencia_energia_relativa_display_f3` permanece
   disponível para os wrappers históricos e pode continuar sendo substituído
   pela autoridade unificada v2;
5. a fonte publicada pela primitiva estável também é fixa:
   `f3_same_mask_relative_power_authority`;
6. a autoridade unificada continua sendo a única verdade global de
   presença/energia e não perde nenhum consumidor histórico;
7. a reconciliação do H1 continua obedecendo D-053 e só altera um falso OFF
   quando a comparação direta mesma-máscara retorna
   `reference_discriminative=True` e `winner=powered`;
8. nenhuma aprovação parcial, threshold novo, timer, worker, scheduler ou fila
   é criado.

### Consequência

O monkey patch de compatibilidade da energia global não pode mais trocar,
silenciosamente, a pergunta feita pela reconciliação do H1.

A separação passa a ser explícita:

```text
energia global do display
→ f3_unified_live_mask_power_authority

reconciliação física de uma máscara do CHECK atual
→ f3_same_mask_relative_power_authority
```

### Regressão obrigatória

Os testes devem simular simultaneamente:

- símbolo legado apontando para a autoridade unificada;
- primitiva estável retornando `MASK_013=powered`.

`F3PowerAuthority.evaluate_current_check_relative()` deve consumir somente a
segunda.

**Validação física:** pendente de reteste do H1 correto.

---

## D-056 — CHECK intermitente não usa confiança semântica como veto da prova física same-mask

**Status:** Accepted

### Contexto

Após a D-055, o H1 correto foi validado fisicamente e avançou para BLUE.

No BLUE correto, o frame congelado mostrou os segmentos `MASK_022` e
`MASK_026` fisicamente acesos. O diagnóstico direto do próprio CHECK contra
BOARD_OFF confirmou os **18 segmentos esperados ON como powered**, incluindo
`MASK_022` e `MASK_026`.

Mesmo assim o analyzer estrito classificou `MASK_022` como OFF com
`confidence=0.6605`, acumulou a divergência por três fases ON e confirmou NG.
A função de suporte físico intermitente só consultava a prova same-mask quando a
confiança semântica era menor que `F3_CHECK_PHOTO_MIN_CONFIDENCE`.

Esse é o mesmo erro conceitual já eliminado do primeiro CHECK pela D-053:
confiança do classificador aprendido e evidência física same-mask são grandezas
diferentes.

### Decisão

Para CHECK intermitente:

```text
expected=ON
+ semantic classified=OFF
→ sempre pode consultar a prova física same-mask disponível
```

A confiança semântica deixa de ser condição para executar essa comparação.

A reconciliação continua restrita a:

```text
referência ON e BOARD_OFF disponíveis
+ par ON/OFF fisicamente discriminante
+ LIVE winner=powered
→ suporte físico confirmado
```

Se a evidência retornar `off`, `tie`, referência não discriminante ou estiver
indisponível, a divergência permanece e o debounce de NG continua normal.

### Segurança

- a foto do próprio CHECK não aprova sozinha;
- BOARD_OFF independente continua obrigatório;
- D-031 continua exigindo conformidade de todas as máscaras;
- um segmento realmente apagado continua sem suporte físico;
- o suporte apenas impede falso OFF semântico; não promove máscara esperada OFF;
- o debounce de CHECK intermitente permanece inalterado;
- não são criados novos thresholds, timers, workers, schedulers ou autoridades.

### Apresentação terminal

O visor/câmera congelados continuam usando a análise efetiva do mesmo frame que
fecha o NG. Ao eliminar o falso OFF antes do debounce, máscaras fisicamente ON
como `MASK_026` não devem mais chegar ao snapshot terminal como OFF por esse
mesmo erro semântico.

### Regressões

Cobertura obrigatória:

```text
BLUE expected ON
semantic OFF confidence=0.6605
same-mask physical=powered
→ suporte físico confirmado
```

e o oposto:

```text
BLUE expected ON
semantic OFF confidence=0.95
same-mask physical=off
→ continua OFF
→ nenhum suporte físico
```

**Validação física:** pendente de reteste do BLUE correto.

---

## D-057 — BLUE intermitente usa F3PowerAuthority como única fonte física de suporte

**Status:** Accepted

### Contexto

O reteste físico posterior à D-056 ainda produziu falso NG no BLUE.
A falha persistente migrou para `MASK_024`, embora o frame congelado e a
comparação direta `CHECK BLUE x PLACA DESLIGADA` confirmassem os 18 segmentos
esperados ON como `powered`.

O problema remanescente não era mais o corte de confiança removido pela D-056.
Existiam duas fontes diferentes de "suporte físico" no mesmo ciclo:

```text
F3StrictMaskConformityAnalyzer
→ rederiva suporte a partir das features do aprendizado

F3PowerAuthority.evaluate_current_check_relative
→ compara diretamente BOARD_OFF ↔ LIVE ↔ foto ON do CHECK
```

O debounce intermitente consumia o primeiro caminho. O DEBUG manual mostrava o
segundo. Quando esses dois caminhos discordavam, o runtime podia acumular falso
OFF mesmo com a autoridade física direta indicando `powered`.

### Decisão

A partir de D-057, a única fonte física com autoridade para impedir um falso
OFF no debounce intermitente é:

```text
F3PowerAuthority.evaluate_current_check_relative()
source=f3_same_mask_relative_power_authority
```

Regras:

1. em CHECK intermitente, o runtime consulta essa autoridade no mesmo frame
   antes de contar falhas da fase ON;
2. a evidência precisa declarar `same_mask_comparison=True`;
3. a fonte precisa ser exatamente `f3_same_mask_relative_power_authority`;
4. para uma máscara `expected=ON` e semanticamente OFF, somente
   `reference_discriminative=True` + `winner=powered` confirma suporte;
5. `winner=off`, `tie`, evidência ausente ou fonte diferente preservam a
   divergência e o debounce normal;
6. a estimativa local produzida pelo analyzer estrito permanece apenas como
   telemetria/diagnóstico e é preservada em campos `intermittent_learning_*`;
7. antes do debounce, qualquer `intermittent_power_confirmation` legado é
   substituído pelo resultado da F3PowerAuthority;
8. o runtime existente continua responsável por zerar o contador da máscara
   confirmada fisicamente e reconciliá-la para ON na fase válida;
9. não é criada nova autoridade, thread, timer, scheduler, fila ou threshold.

### Segurança

A mudança não transforma brilho alto em aprovação direta. A máscara só recebe
suporte se a comparação física independente entre BOARD_OFF, LIVE e ON do mesmo
ID for discriminante e escolher `powered`.

Um segmento realmente apagado continua seguindo:

```text
semantic OFF
+ F3PowerAuthority same-mask = off/tie
→ intermittent_power_confirmation=False
→ contador de falha continua
→ NG após debounce
```

A autoridade global `f3_unified_live_mask_power_authority` também não pode
substituir essa evidência individual, mesmo que publique `same_mask_comparison`.

### Relação com D-056

D-056 permanece correta ao retirar o veto por confiança semântica. D-057 corrige
a fonte efetivamente usada pelo debounce. O suporte local do analyzer deixa de
ser autoridade produtiva.

### Regressões obrigatórias

- `MASK_024 semantic OFF confidence=0.6414` + fonte direta `powered` deve receber
  suporte e não acumular falha;
- fonte global/unificada não pode confirmar suporte intermitente;
- `MASK_022`, `MASK_024` e `MASK_026` falsos OFF no mesmo BLUE devem ser
  reconciliados no frame e permitir avanço quando o restante estiver conforme;
- segmento realmente apagado com fonte direta `off` continua sem suporte.

**Validação física:** pendente de reteste do BLUE correto.

---

---

## D-058 — CHECK intermitente consome a lista canônica de suporte físico

**Status:** Accepted

### Contexto

No reteste físico posterior à D-057, o BLUE correto permaneceu em 26/28 sem
fechar NG. A D-057 já havia produzido corretamente:

```text
intermittent_power_support_confirmed_mask_ids:
MASK_019
MASK_021
MASK_022
MASK_024

source=f3_same_mask_relative_power_authority
authority=f3_power_authority_current_check_relative
authoritative=true
```

Mesmo assim o observador da fase intermitente publicou somente:

```text
intermittent_physical_support_veto_ids:
MASK_021
MASK_024
```

e `MASK_019`/`MASK_022` continuaram em
`effective_failed_mask_ids`.

A autoridade física estava correta; o consumidor voltou a reinterpretar a
evidência por campos individuais de cada máscara. Isso recriou uma segunda
leitura da mesma decisão já fechada pela F3PowerAuthority.

### Decisão

A lista:

```text
intermittent_power_support_confirmed_mask_ids
```

é o contrato canônico entre o produtor D-057 e o observador da fase
intermitente, desde que simultaneamente:

```text
intermittent_power_support_authoritative=True
intermittent_power_support_source=f3_same_mask_relative_power_authority
intermittent_power_support_authority=f3_power_authority_current_check_relative
```

Regras:

1. o observador não rederiva suporte físico a partir de
   `intermittent_power_confirmation` por máscara;
2. um ID canonicamente confirmado, `expected=ON` e semanticamente `OFF`,
   zera seu contador e entra em `physical_support_veto_ids`;
3. essa aplicação ocorre antes do filtro de confiança semântica, preservando
   D-056: confiança do classificador aprendido não pode vetar prova física
   same-mask independente;
4. campos `intermittent_power_confirmation` e
   `intermittent_power_support` por máscara continuam disponíveis para DEBUG,
   mas não são uma segunda autoridade produtiva;
5. fonte incorreta, autoridade incorreta ou
   `intermittent_power_support_authoritative=False` não concede veto;
6. `winner=off/tie` continua fora da lista confirmada e segue o debounce de
   falha normal;
7. nenhuma regra de threshold, timer, worker, scheduler, fila ou autoridade é
   adicionada.

### Regressões obrigatórias

```text
canonical confirmed=[019,021,022,024]
+ campos locais de 019/022 stale ou confidence baixa
→ physical_support_veto_ids=[019,021,022,024]
→ nenhum falso OFF efetivo remanescente
```

e:

```text
intermittent_power_confirmation=True apenas no item
+ ausência do contrato canônico autorizado
→ não pode vetar falha
→ defeito segue para debounce
```

O teste do observador cobre inclusive campo local stale com confiança semântica
abaixo do piso, provando que esse valor não filtra a lista canônica. O teste
integrado do BLUE reproduz a confiança baixa observada fisicamente
(`MASK_022=0.538`) junto da prova same-mask canônica `powered`.

### Escopo

A diferença observada entre o frame manual 550 e o snapshot produtivo 533
permanece registrada para reteste, mas não é alterada por esta decisão. A causa
objetiva desta etapa é a quebra do contrato entre a lista canônica já correta e
o consumidor que produzia somente dois vetos.

**Validação física:** pendente de reteste do BLUE correto.

---
## D-059 — Display F3 migra a autoridade visual para Edge AI neural por segmentos

**Status:** Accepted

### Contexto

Após a D-058, o caminho convencional do Display F3 chegou a um estado em que
um CHECK fisicamente correto podia publicar simultaneamente:

```text
last_auto_analysis.ready=true
last_auto_analysis.approved=true
effective_matched_mask_count=28
gate produtivo liberado
```

e ainda assim permanecer sem avanço. Em outras situações já observadas, a
cadeia convencional também apresentou falsos ON por reflexo, falsos OK com
segmento apagado, falha em transformar segmento apagado em NG, sensibilidade a
pequenos deslocamentos da placa e perda de robustez com variação de iluminação.

A continuidade por novos thresholds, vetos, probes, debounces e wrappers deixa
de ser a direção do produto para a **decisão visual do F3**.

### Decisão

A autoridade visual do Display F3 será migrada, por etapas, para uma solução
**Edge AI local**, CPU-first e sem dependência de nuvem/API paga.

A unidade semântica da rede não será "foto inteira = OK/NG". O contrato alvo é:

```text
frame da câmera
  ↓
contorno/geometria configurados
  ↓
normalização/alinhamento do display
  ↓
detector neural de segmentos
  ↓
28 estados observados ON/OFF + confiança
  ↓
comparação determinística com mask_states do CHECK atual
  ↓
OK / NG / INCERTO
  ↓
F3StateMachineAuthority / DisplayCheckSequenceRuntime
```

A rede responde **o estado visual dos segmentos**. A sequência produtiva continua
determinística.

### Fonte de verdade já existente na configuração F3

A migração deve reaproveitar o que o usuário já configura no Projeto Display:

- imagem de referência de cada CHECK;
- contorno local da placa/display;
- geometria local das 28 máscaras/segmentos;
- IDs estáveis `MASK_xxx`;
- estado esperado `on/off/ignore` de cada máscara;
- geometria live canônica de **Placa + Máscaras**;
- ordem dos CHECKS, por exemplo H1 → BLUE → USB → AUX.

Esses dados são a anotação inicial do problema. Não será introduzida exigência
de o operador classificar produção manualmente para alimentar a IA.

### Primeira etapa obrigatória

A migração começa **somente pelo H1**.

Critério funcional da primeira etapa:

```text
H1 esperado
+ frame live normalizado
→ modelo publica os 28 estados observados

observado == esperado
→ H1 OK
→ registra uma única vez
→ avança para o próximo CHECK

qualquer segmento ativo divergente
→ H1 NG

confiança insuficiente
→ INCERTO
→ não aprova nem reprova até obter evidência suficiente
```

BLUE, USB e AUX não serão migrados na mesma etapa. O próximo CHECK só recebe a
autoridade neural depois de o estágio anterior ser validado fisicamente e o
usuário autorizar a progressão.

### Regra de autoridade durante a migração

Quando um CHECK estiver marcado como **neural**:

1. a conformidade visual produtiva pertence a uma única cadeia:
   `NeuralSegmentDetector → F3CheckEvaluator`;
2. o classificador visual convencional não pode aprovar, reprovar ou vetar esse
   CHECK em paralelo;
3. presença, captura, configuração, sequência, resultado terminal, rearme e UI
   continuam com seus proprietários canônicos;
4. tracking/alinhamento geométrico pode continuar como infraestrutura de pose,
   mas não é autoridade de ON/OFF nem de OK/NG;
5. o caminho convencional pode permanecer temporariamente apenas para CHECKS
   ainda não migrados, sem receber novas correções algorítmicas como direção de
   produto;
6. após a migração física dos CHECKS, o código convencional substituído deve ser
   auditado e removido quando ficar sem consumidores.

### Treinamento e inferência

Direção técnica inicial:

- treinamento local/offline com ferramenta gratuita;
- exportação do modelo para ONNX;
- inferência produtiva com OpenCV DNN carregando artefato ONNX, reutilizando a dependência OpenCV já presente no ODIN;
- CPU-first;
- sem LLM;
- sem serviço cloud;
- sem custo por inferência;
- sem conexão obrigatória com internet;
- modelo pequeno, com prioridade para baixa latência;
- augmentation a partir das referências configuradas para brilho, contraste,
  pequenos deslocamentos, rotação, escala, blur e outras variações realistas.

A seleção exata da arquitetura neural será validada na etapa de protótipo. A
documentação não fixa antecipadamente um backbone específico sem benchmark no
hardware real.

### Estado da implementação N1

A base neural foi dividida em duas entregas antes da validação física:

- **N1.1 — dataset/treino:** concluída. As fotos já cadastradas nos CHECKS,
  geometrias locais e `mask_states` formam automaticamente amostras ON/OFF por
  `MASK_xxx`. O treinamento é offline e exporta ONNX no caminho associado ao
  próprio `DisplayProjectRepository`.
- **N1.2 — runtime H1:** implementada. O primeiro CHECK da ordem do projeto usa
  `F3H1NeuralAnalyzer` + `F3NeuralSegmentDetector`; as máscaras ativas são
  inferidas em um único batch pelo OpenCV DNN. BLUE/USB/AUX continuam no
  analisador convencional.
- **N1.3 — treino real controlado:** executada no Projeto Display real
  `CM_500_L`. O primeiro CHECK permaneceu integralmente fora do treino como
  validação independente; o artefato `cm_500_l_segments.onnx` foi aceito pelo
  gate offline e promovido ao runtime produtivo somente após cumprir o contrato
  de validação/compatibilidade do pipeline N1.3.
- O artefato neural é **fail-closed**: modelo/metadados ausentes ou incompatíveis
  deixam o H1 indisponível e não reativam o classificador convencional como
  fallback. O runtime também exige schema de metadados N1.3, SHA-256 do ONNX e
  evidência explícita de validação independente do primeiro CHECK antes de
  carregar o modelo.
- Tracking permanece somente como fonte de geometria/pose para o H1 neural. O
  desempate óptico e a reconciliação luminosa convencionais não podem alterar
  ON/OFF publicados pela CNN.
- A sonda exata/bridge histórico do primeiro CHECK é somente observador enquanto
  a autoridade neural H1 estiver instalada, impedindo dupla autoridade de
  aprovação.
- `INCERTO` nunca aprova nem reprova. Divergência neural certa pode produzir
  NG no H1 somente quando o próprio frame também contém evidência positiva de
  display ligado; uma leitura totalmente escura continua aguardando evidência
  de energia em vez de virar falso NG.

### Marco de migração real — 05/10/2026

O primeiro reteste físico com o artefato promovido confirmou que a migração não
é apenas arquitetura planejada: o **H1 já está executando com autoridade neural
real no runtime**.

O snapshot produtivo registrou:

```text
reference_authority=f3_h1_neural_segment_detector
neural_visual_authority=true
conventional_visual_authority_used=false
neural_batch_size=28
neural_model.ready=true
```

Consequência arquitetural consolidada:

- **H1:** a decisão visual ON/OFF pertence à CNN/ONNX; o classificador
  convencional não aprova, reprova nem veta em paralelo;
- **BLUE / USB / AUX:** permanecem temporariamente no caminho convencional até
  a migração individual de cada CHECK ser autorizada;
- presença, energia, geometria/pose, sequência, resultado terminal e rearme
  continuam fora da rede e preservam seus proprietários canônicos;
- o caminho convencional do H1 passa a ser legado sem autoridade produtiva e
  deverá ser removido quando não houver mais consumidor necessário.

O primeiro H1 físico correto não foi aprovado ainda porque as 28 saídas ficaram
na faixa `INCERTO` com os limiares conservadores `OFF<=0.20` e `ON>=0.80`.
Isso é um problema de calibração/robustez neural, **não um retorno ao
classificador convencional**.

**Validação física N1:** EM ANDAMENTO. A migração de autoridade do H1 foi
confirmada; a aceitação produtiva ainda depende de calibrar/validar o modelo
contra H1 correto, segmento apagado, reflexo, deslocamento e variação de
iluminação antes de migrar BLUE.

### Objetivos de robustez

A nova autoridade deve ser validada contra, no mínimo:

1. H1 correto com todos os segmentos esperados;
2. H1 com um único segmento esperado ON fisicamente apagado;
3. reflexo em região de segmento esperado OFF;
4. pequeno deslocamento da placa/display;
5. pequena rotação/variação de escala dentro da tolerância definida;
6. mudança moderada de iluminação externa;
7. repetição da mesma condição em frames consecutivos;
8. latência compatível com o ciclo produtivo, sem travar o Tkinter.

### Não fazer

- não criar CNN como mais um voto dentro da cadeia convencional atual;
- não deixar convencional + neural decidirem simultaneamente o mesmo CHECK;
- não treinar um simples classificador "H1 foto = OK" que esconda qual segmento
  falhou;
- não usar foto inteira/fundo como autoridade semântica do CHECK;
- não adicionar API paga ou inferência remota;
- não migrar todos os CHECKS de uma vez;
- não continuar investindo em novos thresholds/probes/vetos convencionais para
  o H1 enquanto a etapa neural estiver em andamento.

### Relação com decisões anteriores

D-031 a D-058 permanecem como histórico válido do caminho convencional e como
fonte de requisitos de segurança/regressão. Elas não obrigam a nova autoridade
neural a reproduzir a implementação convencional.

A partir desta decisão, a direção canônica para **novas correções da percepção
visual do Display F3** é a migração neural por segmentos.

**Validação física N1:** EM ANDAMENTO. O H1 já executou com autoridade neural
real em produção; os retestes #1 e #2 identificaram a calibração fixa
`0.20/0.80` como bloqueio de certeza. A correção de calibração passa a seguir
D-060 e permanece pendente de novo reteste físico antes de migrar BLUE.



---

## D-060 — Certeza neural do H1 é calibrada no CHECK reservado; INCERTO não é CONFORME

**Status:** Accepted

### Contexto

Nos dois primeiros retestes físicos do H1 neural, o ONNX estava carregado e era
a única autoridade visual, mas a decisão permaneceu em `INCERTO`. O segundo
snapshot mostrou separação útil entre as classes no frame real:

```text
maior P(ON) esperado OFF = 0.496080
menor P(ON) esperado ON  = 0.684468
gap live                 = +0.188388
```

Apesar disso, o metadata N1.3 exigia `OFF<=0.20` e `ON>=0.80`, valores
fixados pelo pipeline e não derivados da distribuição do modelo. O mesmo
snapshot revelou uma inconsistência apenas de apresentação: 27 resultados
`uncertain` tinham `matched=None`, mas a UI os contabilizava como conformes
porque descontava somente `matched is False`.

### Decisão

A certeza neural do H1 passa a fazer parte do próprio contrato do artefato.

1. O primeiro CHECK continua integralmente fora da **otimização** da CNN.
2. Depois de selecionar o melhor modelo, as amostras H1 reservadas são usadas
   para calibração junto de variações determinísticas do augmentation existente.
3. O mesmo batch de calibração precisa produzir logits equivalentes no PyTorch
   e no OpenCV DNN produtivo.
4. A promoção exige separação empírica estrita:
   `max P(ON) dos OFF < min P(ON) dos ON`.
5. O maior OFF e o menor ON delimitam a faixa produtiva `INCERTO`; não existe
   fallback para thresholds manuais `0.20/0.80` nem uso produtivo do midpoint
   observado em um frame.
6. Se as distribuições de calibração se sobrepõem, o artefato não é promovido.
7. O metadata neural passa para `schema_version=3` e registra origem da
   calibração, contagens, extremos, gap e thresholds.
8. O runtime aceita somente schema 3 com calibração íntegra e coerente. Artefato
   antigo/schema 2 falha fechado e precisa ser regenerado pelo pipeline.
9. `uncertain` continua sem gerar OK ou NG. Na UI, porém, ele também não pode
   ser contado como CONFORME: a tela deve expor estado `INDETERMINADO` e a
   contagem real de máscaras certas/incertas.

### Limite desta calibração

Augmentation melhora o gate offline, mas não substitui evidência física. A
liberação produtiva N1 ainda exige os retestes reais de:

- H1 correto nominal;
- H1 correto com pequeno deslocamento;
- pequena variação de iluminação;
- segmento esperado ON fisicamente apagado;
- reflexo em segmento esperado OFF.

Só depois desses cenários e de autorização explícita do usuário a migração pode
avançar para BLUE.

### Implementação

- pipeline: `scripts/treinar_f3_segmentos_neural.py`;
- contrato compartilhado: `display_f3_neural_dataset.py`;
- gate/runtime: `display_f3_neural_runtime.py`;
- verdade visual efetiva: `display_auto_check_runtime.py`;
- apresentação: `display_f3_mask_status.py`.

Commits da implementação:

```text
1d3ca06bd52f427e297ab27b5a745d7b2eface50
08d1cb7c59e373f82e4349eaf14b64d645d27579
```

Os testes dedicados **Display F3 neural dataset tests** e
**Display F3 fast H1 BLUE tests** passaram no HEAD da correção.

**Validação física:** PENDENTE DE RETESTE COM ARTEFATO SCHEMA 3.

---

## D-061 — BOARD_OFF entra no treino neural como OFF físico da mesma máscara

**Status:** Accepted

### Contexto

A auditoria de cobertura por máscara física executada no projeto real
`CM_500_L` mostrou:

```text
28 máscaras totais
18 com ON+OFF no treino
5 com somente uma classe, mas compatível com H1
5 com estado exigido pelo H1 nunca visto no treino
```

As cinco lacunas eram:

```text
MASK_015 → H1 OFF; BLUE/USB/AUX ON
MASK_021 → H1 OFF; BLUE/USB/AUX ON
MASK_022 → H1 OFF; BLUE/USB/AUX ON
MASK_023 → H1 OFF; BLUE/USB/AUX ON
MASK_025 → H1 OFF; BLUE/USB/AUX ON
```

A mesma análise mostrou que o F3 já possui uma referência física dedicada
`PLACA DESLIGADA NO SUPORTE`, com foto real e possibilidade de geometria local
das mesmas máscaras. Essa referência já era usada no caminho convencional como
OFF local por máscara e pode fornecer a classe ausente sem usar a foto H1.

### Decisão

O dataset neural passa a reaproveitar `PLACA DESLIGADA NO SUPORTE` como fonte
auxiliar de treino.

Contrato:

1. BOARD_OFF gera somente rótulo `off`;
2. cada amostra mantém o mesmo `MASK_xxx` físico;
3. somente foto válida + geometria explicitamente salva sobre essa foto podem
   entrar no dataset;
4. ausência de geometria explícita não autoriza projetar máscaras canônicas por
   suposição;
5. BOARD_OFF nunca entra no conjunto reservado de H1;
6. H1 continua integralmente fora da otimização da CNN;
7. o preflight deve expor `board_off_sample_count`, fonte auxiliar usada e a
   nova matriz de cobertura;
8. BLUE/USB/AUX continuam sendo as referências funcionais de CHECK do treino;
9. nenhuma mudança em arquitetura CNN, augmentation, thresholds ou authority é
   feita nesta etapa.

### Efeito esperado

Com as 28 máscaras BOARD_OFF corretamente configuradas, o conjunto real
`CM_500_L` deve passar de:

```text
18 máscaras com ON+OFF
5 somente uma classe compatível
5 com estado H1 inédito
```

para aproximadamente:

```text
26 máscaras com ON+OFF
2 somente OFF (MASK_002, MASK_003)
0 estados H1 inéditos
```

Esse resultado precisa ser confirmado pelo preflight real; não é considerado
validado apenas pela expectativa arquitetural.

### Limite

BOARD_OFF ensina como cada segmento fisicamente apagado aparece sem emissão
própria. Ele não garante sozinho cobertura de todos os casos de halo/reflexo
proveniente de segmentos vizinhos acesos. Se a calibração continuar com overlap
depois de fechar a cobertura, a próxima evidência deve apontar para contexto
espacial/capacidade do modelo, e não para nova tentativa de balanceamento
arbitrário.

**Validação:** testes de software passam; preflight real ainda pendente.

---

## D-062 — Augmentation fotométrico neural não pode empilhar transformações que mudem a classe física

**Status:** Accepted

### Contexto

Após D-061, o preflight real de `CM_500_L` confirmou a cobertura esperada:

```text
sample_count=140
train_count=112
validation_count=28
BOARD_OFF=28
26 máscaras com ON+OFF no treino
2 máscaras somente OFF (MASK_002, MASK_003)
0 estados H1 inéditos
```

O novo treino manteve H1 integralmente fora da otimização e atingiu 100% na
foto H1 original, mas a calibração com 16 variações determinísticas por
referência ainda apresentou sobreposição:

```text
max OFF P(ON)=0.736686  → MASK_010 / aug06
min ON  P(ON)=0.611381  → MASK_012 / aug07
gap=-0.125305
```

A inspeção dos parâmetros mostrou um padrão sistemático. O pior OFF recebeu
simultaneamente ganho > 1, offset positivo e gamma < 1, além de reflexo; o pior
ON recebeu simultaneamente ganho < 1, offset negativo e gamma > 1. Outros
extremos repetiram o mesmo comportamento mesmo sem reflexo.

O augmentation anterior sorteava `alpha`, `beta` e `gamma`
independentemente. Três mecanismos fotométricos podiam, portanto, empilhar
clareamento ou escurecimento sobre a mesma amostra até alterar semanticamente a
aparência ON/OFF.

### Decisão

Nesta etapa a arquitetura CNN, o tensor `4x48x48`, o contexto espacial, o
split, BOARD_OFF, thresholds, reflection hard-negative e a autoridade produtiva
permanecem inalterados.

A política fotométrica passa a usar **um único operador principal por amostra**:

```text
gain   → alpha 0.85 .. 1.15 | beta=0 | gamma=1
offset → beta -0.06 .. +0.06 | alpha=1 | gamma=1
gamma  → gamma 0.85 .. 1.18 | alpha=1 | beta=0
```

O operador é escolhido de forma determinística a partir do RNG já usado pelo
pipeline. O mesmo contrato vale para ON e OFF; não existe ajuste dependente do
rótulo.

O diagnóstico passa a registrar também:

- `photometric_mode`;
- `photometric_draw`;
- os valores finais de `brightness_alpha`, `brightness_beta` e `gamma`.

Blur, ruído, pequena rotação/escala/translação e o reflexo sintético de OFF
continuam ativos. As 16 variações por referência H1 continuam obrigatórias.

### Critério

O objetivo não é facilitar artificialmente o gate, mas impedir que o próprio
augmentation produza exemplos cuja transformação fotométrica acumulada troque a
semântica física.

Depois desta mudança o mesmo modelo deve ser retreinado. A promoção continua
exigindo:

```text
H1 original = 100%
max_OFF_P(ON) < min_ON_P(ON)
```

Se a sobreposição persistir com esta política fotométrica conservadora, a
próxima hipótese permitida é capacidade/contexto espacial da CNN, sem voltar ao
classificador convencional e sem relaxar o threshold.

---

## D-063 — Calibração neural H1 incorpora múltiplos frames físicos sem entrar no treino

**Status:** Accepted

### Contexto

Após D-062, o mesmo modelo manteve o H1 integralmente fora da otimização e
passou pelo gate offline:

```text
H1 original: 28/28 = 100%
max OFF P(ON)=0.584876
min ON  P(ON)=0.827438
gap=+0.242561
```

O reteste nominal físico, porém, mostrou que a distribuição live da
`MASK_017` fica repetidamente abaixo do limite ON derivado apenas da foto H1
reservada + augmentation. Em cinco frames congelados independentes da mesma
condição H1 correta:

```text
MASK_017 P(ON)
0.828465 → ON / PASS
0.821631 → INCERTO
0.820450 → INCERTO
0.809613 → INCERTO
0.809678 → INCERTO
```

Resultado operacional: 1/5 aprovações e 4/5 leituras `27/28`, sempre com
`MASK_017` INCERTA.

Nos mesmos cinco frames, os extremos físicos permaneceram separáveis:

```text
max OFF físico P(ON)=0.534034  → MASK_010
min ON físico  P(ON)=0.809613  → MASK_017
gap físico=+0.275579
```

Portanto não existe evidência de overlap físico ON/OFF. O problema é que o
limite ON da calibração sintética não cobria a variação física nominal
recorrente da `MASK_017`.

### Decisão

A calibração de certeza do H1 passa a poder incorporar **múltiplos frames
físicos H1 congelados**, sem alterar os pesos da CNN.

Contrato:

1. H1 continua integralmente fora da **otimização** da rede;
2. a calibração física exige no mínimo 5 frames congelados H1 únicos;
3. os rótulos ON/OFF vêm exclusivamente do `mask_states` configurado do H1;
4. a classificação produzida pela própria CNN nunca vira rótulo de treino;
5. os frames são ingeridos offline a partir do DEBUG TÉCNICO já existente,
   usando o bloco `last_auto_analysis` e as probabilidades neurais por máscara;
6. cada snapshot precisa declarar a autoridade
   `f3_h1_neural_segment_detector`, projeto/check compatíveis e a mesma
   assinatura de calibração do artefato;
7. frames duplicados são eliminados por `frame_sha256_24`;
8. o conjunto físico também precisa ser estritamente separável:
   `max OFF físico < min ON físico`;
9. a calibração final combina os extremos de forma conservadora:

```text
max_OFF_final = max(max_OFF_augmented, max_OFF_físico)
min_ON_final  = min(min_ON_augmented, min_ON_físico)
```

10. o gap combinado também precisa permanecer positivo;
11. não existe midpoint, threshold manual ou exceção específica para
    `MASK_017`;
12. o ONNX e seus pesos permanecem inalterados; somente o metadata schema 3 é
    atualizado atomicamente com a nova evidência e os thresholds derivados;
13. o runtime aceita a origem anterior para compatibilidade e valida
    fail-closed o novo contrato físico quando presente;
14. DEBUGs futuros passam a expor o SHA-256 do ONNX, reforçando a identidade do
    artefato usado na coleta física;
15. depois de incorporados, esses frames deixam de ser validação independente:
    o reteste físico posterior precisa usar frames novos.

### Resultado esperado no lote físico atual

Com os cinco frames já coletados:

```text
base augmented:
  max OFF=0.584876
  min ON =0.827438

physical:
  max OFF=0.534034
  min ON =0.809613

combined:
  max OFF=0.584876
  min ON =0.809613
  gap≈0.224737
```

A faixa continua derivada de evidência empírica e mantém uma região INCERTO
real entre OFF e ON.

### Implementação

- contrato compartilhado:
  `src/platform/display_f3_neural_dataset.py`;
- ingestão/validação/calibração física offline:
  `src/platform/display_f3_neural_physical_calibration.py`;
- CLI:
  `scripts/treinar_f3_segmentos_neural.py`;
- validação fail-closed no runtime:
  `src/platform/display_f3_neural_runtime.py`.

A recalibração física é um caminho offline de engenharia. Não cria scheduler,
thread, worker, autoridade produtiva paralela ou novo processamento por frame.

### Limite da decisão

Esta calibração não conclui a validação produtiva do H1. Depois da atualização,
é obrigatório usar **novos frames físicos** para validar novamente:

- H1 nominal repetido;
- pequeno deslocamento;
- variação moderada de iluminação;
- segmento esperado ON realmente apagado;
- reflexo em segmento esperado OFF.

BLUE não recebe autoridade neural antes desses cenários e de autorização
explícita do usuário.

---

## D-064 — BLUE migra para autoridade neural com debounce por fase ON

**Status:** Accepted

### Contexto

Após o PASS físico N1.7 do H1 neural, o usuário autorizou explicitamente a
progressão para a Etapa N2. No mesmo lote foi apresentado um caso produtivo em
que o BLUE estava fisicamente defeituoso: `MASK_024` deveria estar ACESA no
CHECK BLUE, mas permanecia apagada. Apesar disso, a telemetria do ciclo anterior
registrou BLUE como `28/28`, `policy_decision=ok` e
`registration_event=check_advanced`.

Esse caso torna inadequado continuar ampliando reconciliações convencionais do
BLUE. Em especial, gabarito exato e suporte físico usados historicamente para
corrigir falsos OFF não podem transformar um OFF neural real em ON esperado.

### Decisão

A Etapa N2 fica definida assim:

1. H1 e BLUE usam `F3NeuralCheckAnalyzer` +
   `F3NeuralSegmentDetector` como única autoridade semântica ON/OFF;
2. USB e AUX permanecem convencionais nesta etapa;
3. o mesmo ONNX já promovido é reutilizado; esta mudança não retreina a CNN e
   não relaxa thresholds;
4. BLUE continua intermitente e a intermitência permanece responsabilidade do
   runtime temporal, não da CNN;
5. fase OFF e fase de transição do pisca não geram OK nem NG;
6. somente uma fase ON pode validar conformidade ou acumular divergência;
7. divergência neural **certa** precisa aparecer em 3 amostras de fase ON para
   fechar NG persistente;
8. `INCERTO` neural não aprova, não reprova, não incrementa e não zera o
   contador persistente;
9. a antiga reconciliação por gabarito exato e o veto por
   BOARD_OFF/LIVE/ON ficam desabilitados quando
   `neural_visual_authority=true`;
10. energia continua sendo autoridade de energia/presença operacional, mas não
    pode reescrever o estado ON/OFF produzido pela CNN;
11. a aprovação do BLUE ainda exige uma fase ON completa, no mesmo frame, com
    todos os segmentos esperados ON efetivamente reconhecidos ON;
12. modelo/metadados ausentes ou incompatíveis permanecem fail-closed, sem
    fallback convencional no BLUE;
13. o identificador histórico
    `f3_h1_neural_segment_detector` é mantido por compatibilidade com os
    DEBUGs e com a calibração física H1 já coletada; o escopo N2 é exposto por
    `neural_check_scope=first_two_checks_n2` e `neural_stage`.

### Implementação

- autoridade neural incremental:
  `src/platform/display_f3_neural_runtime.py`;
- policy OK/NG/INCERTO:
  `src/platform/display_auto_check_policy.py`;
- fase ON/OFF/transição e debounce:
  `src/platform/display_auto_check_runtime.py`;
- composição canônica:
  `src/platform/display_f3_runtime_authorities.py`;
- sonda exata somente observadora:
  `src/platform/display_f3_live_diagnostic_trace.py`;
- bootstrap:
  `src/platform/desktop_production_app.py`.

### Critério do próximo reteste físico

O N2 ainda não é considerado validado fisicamente. Antes de qualquer migração
de USB, testar pelo menos:

- BLUE correto piscando normalmente;
- BLUE com `MASK_024` fisicamente apagada enquanto as demais esperadas ON
  acendem;
- fase totalmente apagada do pisca sem falso NG;
- repetição de várias fases ON/OFF;
- `INCERTO` em uma máscara sem aprovação indevida;
- reflexo e pequena variação de posição/iluminação;
- confirmação de que USB continua convencional.

**USB/AUX neural continuam fora do escopo desta decisão.**

---

## D-065 — Autoridade híbrida universal por máscara substitui a migração CHECK a CHECK

**Status:** Accepted

### Contexto

Durante o reteste posterior à N2, cinco capturas consecutivas de uma placa H1
fisicamente correta mostraram uma assimetria clara entre as duas fontes já
existentes no ODIN:

- o aprendizado físico da **mesma máscara** classificou o H1 corretamente em
  `28/28` nas cinco capturas;
- a CNN permaneceu presa em `27/28` em quatro capturas e chegou a `25/28`
  em uma captura;
- `MASK_017`, fisicamente ACESA, oscilou em P(ON) aproximadamente entre
  `0.721` e `0.801`, abaixo do limiar ON global `0.809613`;
- em uma das capturas, `MASK_008`, `MASK_017` e `MASK_020` ficaram
  simultaneamente INCERTAS para a CNN, embora a leitura física por máscara
  continuasse coerente com o H1 correto.

Isso mostrou que continuar acumulando frames OK para recalibrar um único limiar
global a cada nova incerteza não é uma estratégia produtiva escalável.

Também não é necessário aguardar vários defeitos reais para "ensinar NG". O
modelo semântico do F3 é por estado de segmento: **ON/OFF**, enquanto NG é a
regra determinística `observado != esperado`. Uma mesma `MASK_xxx` já pode
possuir exemplos físicos ON em alguns CHECKS e OFF em outros CHECKS/BOARD_OFF.

### Decisão

O julgamento semântico do Display F3 passa a usar uma **única autoridade
híbrida por máscara**, válida para todos os CHECKS configurados e para CHECKS
criados futuramente.

Fluxo:

```text
frame + geometria MASK_xxx
        │
        ├── CNN/ONNX → ON / OFF / INCERTO
        │
        └── aprendizado físico da MESMA máscara
             → ON / OFF / POUCA LUZ + confiança/separação
        │
        ▼
F3HybridCheckAnalyzer
        │
        ├── consenso forte                  → estado confirmado
        ├── CNN INCERTA + físico local forte→ físico resolve
        ├── discordância forte              → INCERTO
        ├── POUCA LUZ física confiável      → POUCA LUZ
        └── sem evidência física local forte→ CNN mantém seu estado
        │
        ▼
estado semântico final por máscara
        │
        ▼
expected x observed
        │
        ▼
OK / NG / BUSCANDO
```

Regras obrigatórias:

1. **Não existe votação majoritária para liberar OK.** Duas fontes fortes em
   desacordo produzem `INCERTO`.
2. A evidência física capaz de resolver a CNN precisa vir do par ON/OFF local da
   **mesma máscara física** (`f3_check_photos_same_mask`) e satisfazer o
   contrato de confiança já existente do classificador físico. Não foi criado
   novo threshold arbitrário.
3. Fallback por pool de máscaras diferentes continua podendo existir como
   diagnóstico/compatibilidade do analisador físico, mas não recebe poder para
   resolver uma incerteza neural dentro da fusão.
4. A CNN continua necessária. Modelo/metadados ausentes ou inválidos permanecem
   fail-closed; a mudança não transforma o sistema em fallback convencional.
5. `neural_certain` preserva a verdade bruta da CNN. A decisão produtiva usa
   `semantic_certain`, que representa a certeza **depois da fusão**.
6. O resultado guarda telemetria separada de CNN, evidência física e resolução
   híbrida para permitir auditoria.
7. `conventional_visual_authority_used=false` continua verdadeiro: o
   aprendizado same-mask não é uma segunda autoridade paralela; ele é uma
   entrada da única autoridade híbrida.
8. H1, BLUE, AUX, USB e qualquer CHECK futuro entram automaticamente pelo ID e
   ordem configurados no projeto. Não existe limite `first_two_checks` nem
   lista hardcoded de nomes.
9. CHECK intermitente continua sendo responsabilidade do runtime temporal.
   OFF/transição não é defeito. Na fase ON, o debounce consome o
   `semantic_certain` final, inclusive quando a evidência física resolveu uma
   CNN incerta.
10. Gabarito exato, sonda positiva e reconciliações históricas permanecem
    observadores/guards onde ainda forem necessários, mas não podem reescrever o
    estado final de uma máscara sob autoridade híbrida.
11. Treinamento/recalibração continuam offline. O runtime não se auto-treina com
    decisões próprias.
12. Coleta automática futura de exemplos físicos confirmados é permitida como
    dataset de engenharia, mas não faz parte desta decisão e não pode promover
    pesos/thresholds automaticamente em produção.

### Compatibilidade

O identificador histórico `f3_h1_neural_segment_detector` permanece publicado
em `reference_authority` para não quebrar o pipeline de calibração H1 e DEBUGs
já coletados. A autoridade produtiva atual é publicada separadamente como:

```text
semantic_authority = f3_hybrid_same_mask_neural_authority
hybrid_check_scope = all_configured_checks_hybrid_v1
```

Os aliases `F3NeuralCheckAnalyzer`,
`instalar_autoridade_neural_h1_blue_display_f3()` e
`instalar_autoridade_neural_h1_display_f3()` permanecem somente por
compatibilidade. O proprietário canônico passa a ser
`F3HybridCheckAnalyzer` + `instalar_autoridade_hibrida_display_f3()`.

### Decisões anteriores afetadas

D-059 a D-064 continuam preservadas como histórico da evolução neural, mas a
restrição de escopo "H1 primeiro, depois BLUE, depois USB/AUX" fica
**superseded** por D-065 após autorização explícita do usuário para aplicar a
nova autoridade a todos os CHECKS.

A recomendação de N2.1 de continuar recalibrando o H1 com os cinco novos frames
também fica superseded neste ponto. Esses frames serviram como evidência para a
mudança arquitetural, não como autorização para baixar/expandir o threshold
global novamente.

### Validação exigida

A mudança só será considerada fisicamente validada depois de testar no JIG:

- H1 correto repetidamente, incluindo o caso antes preso em `MASK_017`;
- BLUE correto em múltiplas fases ON/OFF;
- BLUE NG com `MASK_024` apagada;
- USB correto e um caso divergente quando disponível;
- AUX correto e um caso divergente quando disponível;
- um CHECK adicional criado pelo projeto, provando que entra no mesmo contrato
  sem alteração de código;
- ausência de falso OK quando CNN e físico forte discordarem;
- ausência de falso NG durante a fase OFF do BLUE.

Até essa validação, o estado é **IMPLEMENTADO / PENDENTE DE RETESTE FÍSICO**.



---

## D-066 — Tracking F3 ativo é autoridade de geometria, não de decisão semântica

**Status:** Accepted

### Contexto

A autoridade híbrida D-065 foi validada fisicamente no H1 com o Rastreamento
Automático desativado. Nesse modo, a decisão ON/OFF/POUCA LUZ/INCERTO por
`MASK_xxx` e a decisão CHECK OK/NG/BUSCANDO pertencem ao
`F3HybridCheckAnalyzer` e à state machine canônica.

Ao reativar o Rastreamento Automático, o requisito de produto é preservar essa
mesma decisão já validada. O tracking deve resolver apenas a variação espacial:
onde está a placa/display e onde cada máscara canônica deve ser aplicada no frame
atual.

O código histórico ainda possuía guards específicos do tracking capazes de
interferir no registro do H1/ciclo e uma reconciliação luminosa capaz de alterar
classificação semântica em caminhos legados. Essas regras não podem formar uma
segunda autoridade quando D-065 está ativa.

### Decisão

Com a autoridade híbrida instalada, o contrato é:

```text
TRACKING OFF
frame
→ geometria fixa do Projeto Display
→ F3HybridCheckAnalyzer
→ F3StateMachineAuthority

TRACKING ON
frame
→ F3TrackingAuthority
→ localizar placa/filtro
→ estimar pose/frescor
→ reprojetar máscaras canônicas
→ F3HybridCheckAnalyzer
→ F3StateMachineAuthority
```

Regras obrigatórias:

1. Tracking pode localizar placa/filtro, estimar pose, publicar LOCK/frescor e
   reprojetar contorno + máscaras canônicas.
2. Segmentos luminosos podem continuar sendo usados como **landmarks de
   geometria**, sem transformar essa emissão em estado semântico.
3. Tracking não pode escrever/reconciliar ON/OFF/POUCA LUZ/INCERTO quando
   `hybrid_visual_authority=true`.
4. Evidência `luminous_core_*` do tracking não pode alterar a classificação
   final produzida pela autoridade híbrida.
5. Tracking não pode instalar uma segunda regra de H1, OK, NG ou avanço de
   CHECK quando a autoridade híbrida estiver ativa.
6. Os guards históricos `tracking_h1_power_guard` e
   `tracking_h1_cycle_guard` permanecem apenas como compatibilidade para um
   eventual caminho legado sem autoridade híbrida; eles são bypassados no
   runtime híbrido.
7. A ausência de LOCK ou evidência geométrica atual pode bloquear a **execução
   da análise**, porque as ROIs ainda não possuem posição confiável. Esse
   bloqueio é geométrico e não constitui decisão semântica.
8. O mesmo `F3HybridCheckAnalyzer` deve receber:
   - máscaras fixas quando tracking está OFF;
   - as mesmas máscaras canônicas reprojetadas quando tracking está ON.
9. A mesma `F3StateMachineAuthority` registra o resultado nos dois modos.
10. Nenhum novo threshold, classificador, timer, worker, scheduler ou autoridade
    de decisão é criado por esta separação.

### Implementação

- `display_f3_object_tracking.py` identifica quando a autoridade híbrida está
  ativa e delega o registro diretamente à mesma state machine do caminho OFF;
- `F3TrackedRawCheckAnalyzer` continua adaptando frame RAW + geometria móvel,
  mas não aplica reconciliação luminosa quando a semântica é híbrida;
- regressões garantem que a geometria móvel é entregue ao analyzer e que a
  evidência luminosa do tracker não é chamada para reclassificar segmentos.

### Consequência

A diferença funcional entre os modos fica limitada a **onde estão as ROIs**:

```text
OFF = geometria fixa
ON  = geometria rastreada

ON/OFF do segmento = mesma autoridade híbrida
CHECK OK/NG        = mesma policy/state machine
```

Assim, ativar o Rastreamento Automático não cria outro modelo de inspeção nem
muda o critério que já funcionou com tracking desativado.

**Validação física:** PENDENTE DE RETESTE COM TRACKING ON.


---

## D-067 — Aquisição neural de pose para LOCK rápido do tracking F3

**Status:** Accepted / Implemented / Physical validation pending

### Contexto

No primeiro reteste de tracking ON após D-066, o frame ao vivo estava em
`camera_frame_id=1489`, enquanto o último resultado do object tracking ainda
pertencia ao frame `1330`. A câmera operava em aproximadamente 15 FPS. Portanto
o caminho pesado de aquisição podia ficar vários segundos atrás do vídeo atual.

O mesmo snapshot mostrou:

- `object_not_locked`;
- ORB/rescue sem candidato;
- filtro preto detectado com sucesso;
- D-025 encontrou uma pose plausível e melhorou o alinhamento;
- o encaixe luminoso global encontrou componentes, mas nenhuma hipótese válida;
- quando o tracking finalmente encontra a pose em outros frames, as máscaras
  acompanham corretamente os segmentos.

A falha principal desta etapa é, portanto, **aquisição lenta/ambígua da pose**,
não a decisão semântica D-065.

### Decisão

Adicionar um prior neural separado, treinado offline somente para GEOMETRIA.

```text
referências configuradas do F3
+ contorno/pose salvos
        |
        v
Tiny CNN de pose
        |
        v
quatro âncoras canônicas aproximadas no frame
        |
        +--- detector do filtro preto
        |
        v
selecionar correspondência geométrica correta
        |
        v
CURRENT -> CANÔNICO
        |
        v
refino luminoso
        |
        v
F3HybridCheckAnalyzer
```

### Restrições obrigatórias

1. A CNN de pose não recebe nem produz OK/NG.
2. A CNN de pose não decide ON/OFF/POUCA LUZ/INCERTO.
3. O estado esperado do CHECK não é função de perda do alinhamento; isso evita
   deslocar ROIs para fazer um produto defeituoso parecer conforme.
4. A saída neural sozinha não é aceita como LOCK produtivo.
5. O detector estrutural do filtro/contorno precisa fornecer o quadrilátero
   observado; a rede serve para desambiguar a correspondência/orientação.
6. A pose final continua sujeita aos limites de escala, translação, continuidade
   e frescor do tracking.
7. Após LOCK, fluxo óptico temporal é tentado antes de ORB Full HD.
8. ORB/AKAZE/template continuam como fallback integral se o ONNX estiver
   ausente, inválido ou rejeitado.
9. O modelo é treinado offline e produção usa apenas OpenCV DNN/ONNX.
10. Nenhum novo thread, timer ou executor é criado.
11. D-066 permanece soberana: o tracking fornece geometria; a IA Híbrida decide
    a semântica.

### Dataset

As amostras vêm do próprio Projeto Display:

- foto de Máscaras;
- placa desligada no suporte;
- fotos H1/BLUE/USB/AUX;
- futuras fotos de CHECK;
- `reference_to_canonical` já calculado pelo tracker;
- contorno canônico salvo.

O primeiro CHECK configurado fica fora do treino como validação independente.
Augmentations simulam pequena rotação, escala, deslocamento, blur e variação de
exposição sem alterar a identidade geométrica.

### Runtime

A ordem nominal passa a ser:

```text
COM LOCK ANTERIOR
  fluxo óptico -> neural reacquire -> ORB -> AKAZE -> template

SEM LOCK
  neural + filtro -> ORB -> AKAZE -> template
```

A CNN opera em 192x108; ORB/AKAZE Full HD só são pagos quando os caminhos
rápidos falham.

### Artefatos

- `src/platform/display_f3_neural_tracking.py`;
- `scripts/treinar_f3_tracking_neural.py`;
- modelo local `data/models/f3_tracking/<projeto>_pose.onnx`;
- metadados JSON com hash, geometria e métricas de validação.

### Validação exigida

O primeiro treino real do projeto `CM_500_L` mostrou que o regressor aprendeu
a pose, mas não atingiu os thresholds antigos de regressão absoluta:

- H1 original: mean = 49.19 px;
- H1 aumentado: mean = 62.02 px;
- H1 aumentado: p95 = 133.99 px.

Esses thresholds eram incompatíveis com o papel definido nesta própria decisão:
a CNN **não fornece a pose final**. O filtro estrutural fornece o quadrilátero
real e a CNN escolhe somente sua correspondência/orientação.

Portanto, o gate de promoção foi corrigido sem simplesmente relaxar erro de
pixels:

1. o H1 original, mantido totalmente fora do treino, precisa selecionar a
   correspondência correta;
2. 100% das augmentations de H1 precisam selecionar a correspondência correta;
3. o p05 da margem entre a hipótese vencedora e a segunda melhor precisa ser no
   mínimo 3% da diagonal da resolução mestre;
4. erro absoluto mean/p95 permanece como telemetria;
5. a pose neural continua sem poder virar LOCK sem quadrilátero estrutural
   detectado no frame.

Antes de considerar D-067 fisicamente validada:

- executar `--preflight`;
- treinar e promover o ONNX somente se o gate de
  correspondência/orientação passar;
- medir `worker_elapsed_ms` e `worker_age_ms`;
- confirmar LOCK inicial rápido em H1;
- deslocar/rotacionar levemente a placa e confirmar reacquisition;
- confirmar que as 28 máscaras continuam coincidindo com os segmentos;
- confirmar que H1/BLUE/USB/AUX mantêm exatamente a decisão D-065/D-066;
- confirmar que modelo ausente continua usando o tracking legado.

**Estado físico:** PENDENTE.
