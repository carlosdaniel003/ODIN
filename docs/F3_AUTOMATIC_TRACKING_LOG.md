# F3 — Diário de engenharia do rastreamento automático

Este arquivo preserva o histórico técnico do **Rastreamento Automático de Objetos
do Display F3**: hipóteses, tentativas, regressões, correções, decisões que
funcionaram, caminhos abandonados e pendências.

O objetivo é impedir que uma conversa nova, um agente novo ou uma refatoração
futura volte a repetir uma estratégia já testada sem considerar o que aconteceu.

> Este documento é histórico e operacional. As decisões arquiteturais normativas
> continuam em docs/DECISIONS.md e têm precedência. Os resultados de testes
> físicos continuam em docs/F3_PHYSICAL_VALIDATION_LOG.md.

## 1. Estado de referência deste documento

- Branch: display.
- Snapshot inicial deste diário: commit
  e9376a93b097d50bbafadb37d42e124e08b58464.
- Data de consolidação: 30/09/2026.
- Plataformas alvo: Windows e Linux desktop.
- Raspberry Pi não é plataforma produtiva.
- O tracking continua sendo **opt-in**.
- Contexto de trabalho atual informado pelo usuário em 30/09/2026:
  **Rastreamento automático do Display F3 DESATIVADO**.
- Enquanto este contexto não for alterado explicitamente pelo usuário, novos
  testes físicos desta rodada devem ser interpretados como **tracking OFF**.
- Não reativar o tracking apenas para "ajudar" um teste do caminho sem tracking.
  Comparações ON/OFF devem ser intencionais e registradas.

Esse estado de trabalho não transforma OFF em default permanente do produto.
Quando o usuário mudar o modo, registrar a mudança neste diário.

---

## 2. Onde o rastreamento existe hoje

### 2.1 Configuração persistida

O sidecar do tracking é:

- arquivo: odin_display_tracking.json;
- schema atual: 2;
- flag: display_f3_object_tracking_enabled;
- store: F3TrackingConfigStore;
- dados por projeto: contorno canônico da placa/filtro.

A flag persistida é a autoridade final do toggle. O runtime mantém cache, mas
tracking_enabled() resincroniza o estado em memória quando o arquivo muda.

Alterar o toggle chama set_tracking_enabled(), persiste a flag e executa reset
completo do runtime de tracking.

### 2.2 UI atual

A configuração aparece em Projeto Display como:

- RASTREAMENTO AUTOMÁTICO DE OBJETOS • DISPLAY F3;
- Ativar rastreamento automático de objetos.

A descrição atual é baseada em:

~~~text
CONTORNO + SEGMENTOS LUMINOSOS
~~~

O contorno salvo em **Placa + Máscaras** limita a região de busca. Quando o
tracking está ligado, o runtime pode usar referências estruturais para localizar
a placa/filtro e os segmentos que o CHECK espera ACESOS para refinar a pose.

O nome do módulo display_f3_tracking_orientation_ui.py é histórico. O produto
não possui mais banco angular produtivo.

### 2.3 Proprietários canônicos envolvidos

~~~text
F3RuntimeCoordinator
  └─ F3HeavyVisionExecutor
       └─ job HIGH de tracking/análise

F3RuntimeAuthorities
  ├─ F3TrackingAuthority
  │    └─ F3DisplayObjectTracker
  ├─ F3PresenceAuthority
  ├─ F3PowerAuthority
  ├─ F3CheckAnalyzerAuthority
  │    └─ F3TrackedRawCheckAnalyzer
  │         └─ F3StrictMaskConformityAnalyzer
  └─ F3StateMachineAuthority
       └─ DisplayCheckSequenceRuntime
~~~

Responsabilidades:

- tracking: somente pose/geometria e evidência espacial;
- presença: decide se há placa/suporte vazio;
- energia: decide se o display possui energia e se há autoridade espacial;
- analyzer: decide conformidade das máscaras;
- state machine: avança CHECKS e contabiliza resultado;
- preview: apresenta o frame atual da câmera, não o frame antigo de um worker.

Tracking **não é** autoridade de OK/NG.

---

## 3. Contrato quando o tracking está DESATIVADO

Este é o modo em uso na rodada atual.

Quando tracking_enabled() retorna False:

- a camada opt-in do object tracking delega para a cadeia anterior do F3;
- não aplica alinhamento, warp ou reprojeção controlados pelo object tracking;
- não exige LOCK do object tracking para executar o caminho normal;
- align_frame_for_f3() devolve o frame original e nenhum resultado de tracking;
- o wrapper de preview não substitui o comportamento normal pelo preview
  rastreado;
- os guards específicos de tracking não devem bloquear a sequência;
- presença, energia, análise automática, sequência, rearme, DEBUG e câmera
  continuam existindo em seus proprietários normais;
- desde D-031, a conformidade semântica permanece estrita também com tracking
  desligado.

Regra crítica da rodada atual:

~~~text
TRACKING OFF
  ↓
sem autoridade geométrica do object tracking
  ↓
análise F3 normal
  ↓
F3StrictMaskConformityAnalyzer
  ↓
uma máscara ativa divergente impede OK
~~~

Portanto, desligar tracking não pode voltar a permitir aprovação de um CHECK
com um segmento esperado ACESO permanentemente apagado.

### Limitação física esperada com tracking OFF

Sem reprojeção dinâmica do object tracking, a geometria produtiva depende muito
mais de a placa/display permanecer próximo da posição ensinada/configurada.

Isso não é um bug por si só. É a diferença entre os dois modos.

Antes de "corrigir" deslocamentos observados com tracking OFF, confirmar se o
requisito é:

1. manter a peça fisicamente repetível no suporte; ou
2. voltar a usar tracking para tolerar variação de posição.

Não misturar os dois objetivos silenciosamente.

---

## 4. Contrato quando o tracking está ATIVADO

Resumo do caminho aceito atual:

~~~text
frame RAW latest-frame
  ↓
localização estrutural da placa/filtro
  ├─ referência do CHECK atual, quando útil
  ├─ BOARD_OFF como âncora estrutural
  ├─ ORB/template
  └─ AKAZE somente como fallback lazy
  ↓
LOCK estrutural
  ↓
buscar emissão somente dentro da região do filtro
  ↓
associar landmarks aos IDs que o CHECK espera ON
  ↓
refino/validação luminosa conservadora
  ↓
reprojetar geometria canônica das máscaras no frame RAW
  ↓
F3StrictMaskConformityAnalyzer
  ↓
F3PowerAuthority + gates de frescor/energia
  ↓
DisplayCheckSequenceRuntime
~~~

A imagem visível continua sendo camera_frame_atual. O frame usado por um worker
pesado não vira autoridade visual quando o worker termina.

---

## 5. Invariantes que NÃO devem ser quebrados

1. **Tracking localiza; analyzer julga.**
   Detectar luz para alinhar não equivale a aprovar o CHECK.

2. **Uma única máscara divergente bloqueia OK.**
   D-031 vale com tracking ON e OFF.

3. **OFF não é landmark de pose.**
   Segmentos apagados não são procurados para alinhar o grid.

4. **Reflexo não é segmento.**
   Emissão usada como landmark precisa de suporte geométrico do ID esperado.

5. **Resultado stale não decide.**
   Lock antigo, Future antigo ou resultado de outro CHECK/projeto não pode
   participar de decisão atual.

6. **EMPTY vence pose residual.**
   Suporte vazio confirmado invalida o ciclo mesmo que exista geometria antiga.

7. **Nova placa nunca herda pose da placa anterior.**
   Referências/calibração podem permanecer em cache; matriz/pose não.

8. **Preview é latest-frame-wins.**
   Não renderizar o frame antigo do worker como se fosse câmera ao vivo.

9. **Um executor pesado.**
   Não criar nova thread/scheduler/fila para "acelerar" tracking.

10. **Não existe banco angular 90°/180°/270°.**
    A geometria produtiva é canônica.

11. **Configuração aberta pausa o tracking pesado.**
    A câmera continua viva; o object tracking não deve disputar CPU com o editor.

12. **H1 não deve fabricar NG antes de existir referencial válido.**
    A regra de entrada do primeiro CHECK continua separada da correção D-031.

13. **Câmera + máscara + visor são um único espelho visual com tracking ON.**
    A cor visual não depende de gate de energia, presença, alinhamento produtivo,
    OK/NG ou avanço. Segmento físico detectado como emitindo no frame visível
    precisa ficar verde na máscara e no visor no mesmo repaint. A decisão
    produtiva continua separada. Esta regra é D-032 e não deve ser revertida
    para o comportamento antigo de "verde somente após power gate".

---

## 6. Linha do tempo das tentativas e aprendizados

### 18/09/2026 — Primeira engine isolada de object tracking

Principais commits:

- 13530ee59361 — Add isolated F3 object tracking engine;
- 670da136c6e4 — Add F3 orientation tracking configuration UI;
- d094e6824bf0 — Keep F3 tracking aligned through full auto-check cycle;
- 1ee51adb3664 — Apply F3 orientation mask corrections to aligned analysis;
- 501547c2c2bc — Cache ready F3 tracker between configuration changes;
- c92dc33f2286 — Cache F3 tracking configuration reads;
- 3f12881a3039 — Pause F3 tracking while configuration window is open;
- b503ab2f7970 — Keep F3 live camera raw while tracking analyzes aligned frame.

#### Estratégia tentada

- criar engine de tracking isolada do F2;
- manter a câmera visível RAW;
- usar frame alinhado apenas para análise;
- adicionar configuração de orientações/rotações;
- cachear configuração e tracker para reduzir custo.

#### O que ficou válido

- isolamento F2/F3;
- câmera ao vivo não deve ser substituída por frame alinhado;
- configuração aberta pausa tracking pesado;
- cache precisa ser invalidado somente quando configuração muda.

#### O que foi abandonado

O banco de orientações/rotações 90°/180°/270° foi posteriormente removido.
Não reconstruir essa abordagem sem nova decisão arquitetural explícita.

---

### 21/09/2026 — Banco estrutural, pose, fallback e autoridade final

Principais commits:

- c3ca73cf8078 — Estimate F3 reference pose from drawn board and masks;
- fdf294fd3609 — Build F3 tracking bank from mask, board-off and CHECK geometries;
- ea48935678fa — Use every calibrated F3 photo in ORB tracking bank;
- a026b741931d — Project F3 tracked board and masks onto live camera;
- b19348568cc7 — Use only explicitly drawn masks as F3 pose anchors;
- 6946f0aede1e — Analyze each F3 CHECK in its tracked reference geometry;
- de682d869781 — Disambiguate F3 board rotation with mask anchors;
- 11936d0b84e5 — Guard F3 tracking cycle until H1 is physically powered;
- 6c064f842829 — Install final F3 tracking authority on the live app instance;
- 89b71d0316f8 / 588e2efd27d2 / c36d014872d0 —
  edge-template fallback quando ORB é insuficiente;
- 92449bff5148 — sincronização do runtime com o checkbox persistido;
- b4b02e8d7769 — fresh same-CHECK power evidence;
- 04238bc5de0c / 6157f76b5eb3 — continuidade/histerese de lock.

#### Problemas encontrados

- ORB pode ficar pobre em superfícies escuras ou pouco texturizadas;
- a rotação podia ficar ambígua;
- checkbox persistido e cache em memória podiam divergir;
- um lock antigo podia sobreviver tempo demais;
- análise não podia avançar H1 sem evidência física compatível.

#### Soluções que permaneceram

- múltiplas referências estruturais podem ajudar a recuperar pose;
- template/edge e AKAZE são fallback, não segunda autoridade;
- estado persistido do toggle é final;
- evidência precisa ser atual e do CHECK correto;
- lock mantido/stale não possui mesma autoridade que lock atual.

---

### 21/09/2026 — Geometria canônica e visor

Principais commits:

- 2911a7945f90 — Keep canonical mask shapes across F3 checks and live overlays;
- 6dc6d956b96c — Preserve canonical mask shapes through F3 orientation tracking;
- e2a623857263 — Restore semantic mask ROIs in tracked F3 live preview;
- dd3d893415b8 / f7b382d954a5 — visor 88:88 guiado pelos estados das máscaras.

#### Aprendizado

Tracking não pode deformar o tipo da máscara:

- segmento continua segmento;
- círculo continua círculo;
- polígono preserva topologia.

A geometria transformada é derivada do modelo canônico.

---

### 24/09/2026 — Recuperação por CHECK atual e BOARD_OFF

Principais commits:

- 7a2480d8ffe8 — Recover F3 tracking from current check without LED content;
- 9ad93345a7a7 — Keep tracked F3 preview on effective mask authority;
- 176ae7acb3ef — Recover F3 tracking from board-off structural reference;
- 3710254893b7 — Make F3 tracking robust to motion and illumination.

#### Regra importante

A foto do CHECK atual ou BOARD_OFF pode ajudar a recuperar **pose estrutural**,
mas o conteúdo dos segmentos não pode ser usado como prova automática de
ON/OFF/OK/NG.

As ROIs luminosas são excluídas da parte estrutural usada para pose sempre que
necessário.

---

### 25/09/2026 — Tracking assíncrono e responsividade

Principais commits:

- 52d418eff135 — Offload live F3 tracking from Tk thread;
- 7f106ccf4a93 — Test asynchronous live F3 tracking;
- cc7491c90299 / 7827a9c06129 — ownership/lifecycle assíncrono;
- 942fb9608d28 — Keep F3 preview live during asynchronous tracking;
- 3c1657419d71 — Reject stale F3 tracking decisions safely;
- d98fcaa2c17c — Keep F3 preview responsive during semantic analysis.

#### Erro evitado

Executar ORB/AKAZE/reacquisition no Tk congela ou atrasa a interface.

#### Contrato consolidado

- trabalho pesado vai ao F3HeavyVisionExecutor;
- no máximo um trabalho pesado ativo;
- latest-frame-wins;
- resultados de geração/frame antigos são descartados;
- widgets Tk nunca são atualizados pelo worker;
- câmera continua atual mesmo se tracking estiver calculando frame anterior.

Não resolver lentidão criando threads paralelas adicionais.

---

### 28/09/2026 — Tracking guiado por segmentos luminosos

Principais commits:

- 65cedfc36b62 — Add luminous segment guided F3 tracking;
- a062592b4e28 — Restrict luminous tracking to filter ROI;
- adce29ea5f53 — Align F3 checks from luminous segment geometry;
- 71d5457beb50 — Bind luminous evidence to analyzed frame token;
- 5068f74e05b6 — Gate H1 mask judgment on first expected ON;
- a3a828aecf28 — Instrument luminous alignment failures;
- a3e1c270b0c8 — Recover H1 alignment from merged luminous segments;
- 0f05f54e5b73 — Keep semantic analysis on tracking snapshot.

#### Objetivo

O filtro preto é bom localizador grosseiro, mas o grid de segmentos pode se
deslocar dentro dele. Por isso os segmentos esperados ON passaram a participar do
alinhamento fino.

#### Problemas encontrados

- contornos luminosos podem se fundir por blooming;
- evidência de frame diferente do frame analisado cria incoerência;
- H1 não pode pintar/julgar máscaras antes de existir pelo menos um ON esperado
  realmente reconhecido;
- usar luz fora da ROI do filtro produz falsos landmarks.

#### Soluções aceitas

- restringir busca à ROI do filtro;
- preservar token de frame/geometria;
- particionar emissão localmente quando segmentos estão fundidos;
- somente IDs esperados ON podem fornecer landmarks;
- classificação semântica continua separada.

---

### 28/09/2026 — Remoção do banco angular

Principais commits:

- 6c2b40312cf4 — Simplify F3 tracking to contour and luminous segments;
- 437a1dd0c37a — Purge legacy F3 rotation assets.

Decisão: D-023.

#### O que foi removido

- slots 90°/180°/270°;
- fotos angulares gerenciadas;
- geometrias paralelas por orientação;
- prioridade especial de referências angulares.

O schema 2 migra payloads antigos e remove display_tracking_orientations.

#### Por que não voltar

Esse modelo multiplicava:

- calibração;
- fotos;
- máscaras;
- contornos;
- persistência;
- caminhos de decisão.

O problema é melhor representado por uma geometria canônica + pose em runtime.

---

### 28/09/2026 — Regressões visuais e saltos de pose

Principais commits:

- c26074cc9806 — Restore classic F3 mask presentation;
- 2747bc7ccd94 — Prevent abrupt 90 degree F3 tracking flips;
- c566580c70d1 — Make rotation guard compatible with tracking test doubles.

#### Aprendizado

Uma correção de pose que melhora score local não pode impor salto angular grande
no grid inteiro. O tracking precisa respeitar continuidade e limites físicos.

---

### 29/09/2026 — Refinamento fino por poucos segmentos: tentativa, regressão e hardening

Principais commits:

- f5e5f72038b0 — Refine F3 tracking with segment-centric alignment;
- 2699f908a381 — Harden three-segment F3 fine tracking;
- bf589e2600c7 — Restore stable F3 tracking after refinement regression;
- 57add1ed667f — Refine F3 tracking with ID-anchored luminous segments;
- 58c40ab9be1f — Harden luminous tracking against off-state reflections;
- dc22024e6acc — Fix luminous alignment power deadlock;
- 145b5f45cc33 — Harden fine segment alignment geometry;
- e0b588746446 — Reject inconsistent luminous anchor vectors;
- c605db2e11c2 — Report filtered luminous anchors accurately;
- ef3f80897a11 — Treat verified structural pose as aligned.

#### Falhas reais/observadas que motivaram a sequência

1. poucos segmentos concentrados podiam tentar girar ou deformar o grid;
2. reflexos com display desligado podiam parecer emissão;
3. landmarks diferentes podiam pedir vetores de correção incompatíveis;
4. uma pose visualmente correta podia ser rejeitada porque não produzia
   "ganho" geométrico adicional;
5. o próprio gate de energia podia impedir o refinamento necessário para provar
   que o display estava ligado.

#### Regras derivadas

- landmarks precisam ter ID e suporte espacial;
- anchors concentrados podem corrigir translação, mas não devem ganhar liberdade
  de rotação/escala sem distribuição suficiente;
- vetores inconsistentes são descartados;
- OFF confirmado com autoridade espacial veta promoção luminosa por reflexo;
- melhorar numericamente não basta se o residual final continua alto;
- uma matriz que já está correta pode ser confirmada sem movimento adicional.

---

### D-025 — Homografia do filtro + registro do H1 inteiro

Principais commits:

- 2247d3695ff7 — documentação inicial;
- c93831e224c0 — experimento isolado;
- b97ecab376e3 — visualização no DEBUG técnico;
- fd0637590952 — reutilização do lock estrutural;
- eed6f3bf31b4 — preservar homografia base quando ECC piora;
- c7d203940655 — diagnóstico de fallback.

**Status atual: Proposed / experimental. Não é autoridade produtiva.**

#### Hipótese

~~~text
filtro preto
→ homografia
→ ROI retificada
→ registro do H1 inteiro
→ máscaras fixas no espaço canônico
~~~

#### O que deu errado nas primeiras tentativas

- o detector independente do experimento chegou a retornar filter_not_found
  enquanto o tracking produtivo já possuía o filtro localizado;
- ECC podia piorar uma homografia base visualmente correta.

#### Correções no experimento

- reutilizar os quatro pontos do filtro já publicados pelo proprietário canônico;
- tratar ECC como candidato opcional;
- rejeitar refinamento que piore Dice, correlação, erro médio/P95 ou overlap das
  máscaras ON.

#### Regra de não repetição

Não conectar D-025 ao ciclo produtivo apenas porque funciona em uma foto.

Antes de promovê-lo, usar lote real de aproximadamente 20–30 frames H1 em
posições/ângulos permitidos e medir repetibilidade.

---

### D-026 — Pose já correta pode ser confirmada sem movimento

Principais commits:

- 5bd5f1325b58 — Confirm aligned H1 from exact luminous mask cores;
- 0a50398d4029 — regressão automatizada.

**Status: Accepted.**
**Validação física: PASS em 29/09/2026.**

#### Problema anterior

fine_gain_insufficient rejeitava pose já correta porque não existia movimento
adicional suficiente para justificar um novo fit.

#### Solução

Se a matriz base coloca emissão dentro do núcleo exato das máscaras ON do CHECK
atual em quorum suficiente, publicar:

~~~text
source_type = luminous_segment_grid
luminous_alignment_mode = base_core_verified
~~~

sem mover a matriz.

#### Lição

**Alinhamento e movimento não são sinônimos.**

Não reintroduzir regra que exija correção geométrica diferente de zero para
provar que a pose está correta.

---

### D-027 — CHECK intermitente e snapshot ON

Commit principal:

- 205037a78b15 — Preserve intermittent ON snapshots for F3 analysis.

**Status: Accepted.**
**Validação física BLUE: PASS.**

#### Problema

O BLUE podia acender no frame capturado pelo worker e apagar antes de o resultado
assíncrono chegar ao runtime.

#### Solução

Para intermittent=true, snapshot positivo coerente do mesmo projeto/CHECK pode
continuar elegível por até 2,5 s.

#### O que NÃO fazer

- não substituir camera_frame_atual pelo snapshot preservado;
- não somar segmentos de frames diferentes para fabricar conformidade;
- não aplicar a exceção a CHECK contínuo.

---

### D-028 — Tracking e energia em frames assíncronos próximos

Commit principal:

- 2fca6b695542 — Reconcile F3 USB luminous alignment across async frames.

**Status: Accepted.**
**Validação automatizada: PASS.**
**Validação física específica do USB: ainda registrada como pendente.**

#### Problema físico

USB chegou a:

- tracking luminoso atual e alinhado;
- energia confirmada;
- analyzer 28/28 approved=true;

mas a autoridade de energia de um frame posterior ainda carregava
spatial_alignment_ready=false, bloqueando o CHECK.

#### Solução

F3PowerAuthority pode reconciliar a geometria usando lock luminoso recente do
mesmo CHECK, desde que:

- locked=true;
- evidence_current=true;
- source_type=luminous_segment_grid;
- referência luminous:<CHECK atual>;
- IDs luminosos validados;
- idade e diferença de frames dentro dos limites operacionais;
- powered_confirmed=true no frame live.

#### Lição

Não exigir igualdade impossível entre clocks assíncronos diferentes, mas também
não relaxar frescor para aceitar lock velho.

---

### D-029 — Espelho visual latest-frame e primeira aquisição

Principais commits:

- ba627170e5da — Synchronize F3 live segments and speed initial lock;
- 979cb1fa0de5 — Tighten F3 live readout rendering;
- 52763e4677 — Fix F3 startup result drain deadlock;
- 05aaf3df55 — Test F3 completed worker result drain.

**Status: Accepted.**

#### Problema visual

Câmera mudava antes das máscaras verdes e do VISOR DO DISPLAY porque a UI usava
resultado atrasado do worker.

#### Solução

Criar uma amostra luminosa **somente visual** sobre o mesmo frame reduzido do
preview. Ela alimenta câmera/overlay/visor no mesmo repaint e não participa de
OK/NG.

#### Otimização que causou nova regressão

A tentativa de priorizar o primeiro lock criou um deadlock:

~~~text
Future terminou
→ executor deixou de estar busy
→ Future continuou armazenado
→ coordinator tratou como "ainda em voo"
→ render_only para sempre
→ resultado nunca era drenado
→ IDENTIFICANDO infinito
~~~

#### Correção

Future concluído força um full_cycle curto para publicação no thread Tk antes do
backpressure normal.

**Reteste físico do deadlock: PASS.**

#### Lição

"Future existe" e "Future ainda está executando" são estados diferentes.

---

### D-030 — Rearme entre placas e reacquisition

Principais commits:

- b84e3fe0e2e9 — Speed F3 reacquisition between boards;
- 7fe233edf1cf — Tighten F3 prioritized reacquisition.

**Status: Accepted.**
**Validação física: PASS.**

#### Problema

Reset completo entre placas descartava:

- pose antiga, corretamente;
- banco de referências/calibração, desnecessariamente.

Isso deixava a próxima aquisição lenta.

#### Solução

Separar:

~~~text
reset_tracking_runtime()
  = reset completo por mudança de projeto/configuração

reset_tracking_cycle()
  = nova placa
  = perde pose/matriz/resultados
  = preserva banco calibrado da sessão
~~~

Na aquisição sem pose, priorizar CHECK atual + BOARD_OFF e deixar restante como
fallback lazy.

#### Lição

Referência em cache não é pose.

Nunca reutilizar matriz/anchor da placa anterior para acelerar a próxima.

---

### D-031 — Tracking não pode rebaixar a conformidade estrita

Commit:

- e9376a93b097 — Restore F3 strict mask rejection and segregation.

**Status: Accepted.**
**Validação automatizada focada: PASS.**
**Reteste físico: pendente.**

#### Falha física

Segmento 24 deveria estar ACESO, estava fisicamente danificado e nunca acendeu,
mas o CHECK acabou sendo aprovado.

#### Causa

A camada estrita existia, porém F3TrackedRawCheckAnalyzer reconstruía
internamente um F3SameMaskReferenceAnalyzer mais permissivo e podia rebaixar a
autoridade semântica instalada anteriormente.

O mesmo wrapper final continuava publicado mesmo com tracking desligado.

#### Correção

F3TrackedRawCheckAnalyzer usa F3StrictMaskConformityAnalyzer internamente, e a
conformidade estrita aceita também as geometrias móveis do tracking.

Resultado esperado:

~~~text
MASK_024 esperado ON
+
MASK_024 observado OFF
+
display energizado / outro ON válido
=
CHECK não pode receber OK
→ NG após debounce normal
~~~

Essa regra vale com tracking ON e OFF.

---

### D-032 — Espelho visual independente dos gates

**Data:** 30/09/2026.  
**Modo:** tracking ON.  
**Estado:** correção implementada, pendente de reteste físico.

#### Sintoma observado

Mesmo com o segmento fisicamente aceso na câmera ao vivo, a máscara
correspondente e o segmento equivalente no VISOR DO DISPLAY podiam não ficar
verdes.

Isso viola o contrato visual: câmera real, overlay e visor precisam reagir como
uma única representação do mesmo frame.

#### Conflito encontrado

- D-029 já havia criado uma amostra latest-frame somente visual;
- o renderer clássico ainda possuía fallback condicionado a power gate;
- o visor ainda podia cair em classificação assíncrona/ready;
- D-023 continha a regra antiga de verde somente com energia física confirmada;
- o detector relativo podia perder CHECKS com maioria/todos os segmentos acesos
  porque o baseline global subia junto com o grupo ON.

#### Alteração

- D-032 torna explícito que gates produtivos não controlam cor visual;
- câmera/overlay e visor usam os mesmos `live_visual_mask_ids`;
- fallback de ambos é o mesmo `luminous_mask_ids`;
- classificação semântica não entra como fallback visual no tracking ON;
- detector ganhou separação pelo maior gap de scores e evidência absoluta forte
  para cobrir maioria/todos ON;
- nenhuma dessas evidências visuais participa de energia, OK/NG ou sequência.

#### Não repetir

Não voltar a neutralizar segmentos visualmente acesos porque:

- `power_confirmed=false`;
- `power_off_confirmed=true`;
- `spatial_alignment_ready=false`;
- H1 ainda não foi liberado;
- analyzer ainda não terminou.

Essas condições podem bloquear **decisão**, nunca o espelho visual D-032.

#### Próximo reteste

~~~text
tracking ON + LOCK
→ acender/apagar segmentos físicos
→ confirmar que máscara sobre câmera e visor mudam juntos
→ repetir enquanto power gate ainda está bloqueado
→ repetir em CHECK com maioria dos segmentos ON
→ confirmar que cor visual não altera decisão produtiva
~~~

---

## 7. Estratégias que já falharam ou foram abandonadas

| Estratégia | Problema observado | Estado |
| --- | --- | --- |
| Banco de fotos 90°/180°/270° | multiplica calibração, persistência e geometrias paralelas | REMOVIDO |
| ORB como única forma de reacquisition | superfície escura/pouco texturizada pode gerar poucos matches | NÃO USAR SOZINHO |
| Usar qualquer hot spot como landmark | reflexos e luz vizinha deslocam/tortam o grid | REJEITADO |
| Procurar segmentos OFF para pose | ausência de luz não fornece landmark confiável | REJEITADO |
| Deixar 3 anchors concentrados girarem/escalarem o grid | pose fica instável/torta | RESTRINGIDO |
| Exigir ganho fino diferente de zero | pose já correta falha em fine_gain_insufficient | CORRIGIDO D-026 |
| Renderizar resultado atrasado do worker | câmera, máscaras e visor ficam defasados | REJEITADO D-029 |
| Precalcular AKAZE do banco inteiro | custo grande no primeiro IDENTIFICANDO | REMOVIDO; AKAZE lazy |
| Reset completo a cada placa | reacquisition lento e recalibração desnecessária | CORRIGIDO D-030 |
| Tratar Future concluído como em voo | deadlock em IDENTIFICANDO | CORRIGIDO D-029 |
| ECC substituir homografia automaticamente | pode piorar base já boa | REJEITADO no experimento D-025 |
| Redetectar filtro no experimento ignorando lock estrutural | filter_not_found apesar de filtro já localizado | REJEITADO |
| Tracking escolher OK/NG | mistura geometria com semântica | PROIBIDO |
| Analyzer de tracking mais permissivo que o analyzer canônico | segmento defeituoso pode virar falso OK | CORRIGIDO D-031 |
| Reutilizar pose da placa anterior | nova placa pode entrar em outra posição | PROIBIDO D-030 |

---

## 8. Estratégias que funcionaram e devem ser preservadas

### Geometria

- um contorno canônico por projeto;
- ROIs preservam tipo/topologia;
- localização estrutural separada do alinhamento fino;
- CHECK atual e BOARD_OFF são referências prioritárias de reacquisition;
- landmarks luminosos são ligados a IDs ON esperados;
- núcleo exato da máscara pode validar pose já correta;
- continuidade/limites físicos vetam saltos absurdos.

### Concorrência/performance

- F3HeavyVisionExecutor como único executor pesado;
- jobs HIGH para tracking/analyzer;
- latest-frame-wins;
- Future concluído precisa ser drenado;
- AKAZE lazy;
- banco de referência lazy;
- reset de ciclo preserva calibração e apaga pose;
- preview não espera worker.

### Segurança da decisão

- tracking != conformidade;
- presença != energia;
- energia != alinhamento;
- alinhamento != OK;
- analyzer estrito é final;
- lock stale não decide;
- OFF confirmado com autoridade espacial veta falso landmark;
- H1 mantém gate de entrada próprio;
- CHECK intermitente preserva snapshot, mas não mistura frames.

---

## 9. D-025: o que está autorizado e o que NÃO está

D-025 continua **experimental**.

Pode ser usado para:

- DEBUG manual;
- comparar referência H1 x filtro retificado x H1 registrado;
- coletar métricas;
- testar homografia, correlação de fase e ECC;
- construir dataset real.

Não pode, sem nova validação/decisão:

- substituir o tracking produtivo atual;
- liberar energia;
- liberar máscaras;
- decidir OK/NG;
- avançar CHECK;
- alterar rearme;
- criar nova autoridade paralela.

Critério antes de promover:

- aproximadamente 20–30 frames H1 reais;
- variação de X/Y, pequena rotação e perspectiva permitida;
- medir erro, overlap, convergência e taxa de lock;
- confirmar repetibilidade;
- só então decidir se substitui o refinamento luminoso atual.

---

## 10. Situação física conhecida no fechamento deste snapshot

### Confirmado em equipamento

- D-026 / base_core_verified no H1: PASS;
- BLUE intermitente / D-027: PASS;
- deadlock de IDENTIFICANDO introduzido na D-029: corrigido e retestado PASS;
- D-030 / nova placa em outra posição sem herdar pose: PASS.

### Pendente de confirmação física

- D-028 / USB: reconciliação tracking luminoso + energia entre frames
  assíncronos;
- D-031 / segmento 24 defeituoso:
  - tracking ON;
  - tracking OFF;
- SEGREGAR PLACA após a correção mais recente.

### Baseline automatizado conhecido

No commit e9376a93b097:

- bloco focado de strict mask + segregation: 9/9 PASS;
- regressões luminosas focadas relevantes: PASS;
- suites de cycle rearm e fast H1/BLUE: PASS;
- a suíte ampla de object tracking ainda possui 7 failures + 1 error históricos,
  já presentes antes de D-031.

Não interpretar a suíte ampla como totalmente verde.

---

## 11. Foco atual: investigar F3 com tracking OFF

A partir de 30/09/2026, o foco de trabalho passou explicitamente para:

~~~text
RASTREAMENTO AUTOMÁTICO DO DISPLAY = DESATIVADO
~~~

Objetivo desta fase:

- validar o comportamento produtivo F3 sem depender de pose dinâmica;
- verificar que regras de negócio continuam corretas;
- separar defeitos do pipeline normal de defeitos introduzidos pelo tracking;
- não usar tracking como correção automática de falhas encontradas nesta fase.

Primeiros contratos a observar:

1. um CHECK integralmente conforme pode aprovar;
2. um segmento esperado ON que nunca acende deve reprovar em CHECK posterior ao
   H1 quando houver prova de display ligado;
3. um segmento esperado OFF que acende deve reprovar;
4. POUCA LUZ continua NG quando configurado/identificado;
5. BLUE intermitente mantém sua regra temporal;
6. NG congela o frame/evidência correta;
7. SEGREGAR funciona;
8. retirada da placa/rearme continua funcionando;
9. F2 continua isolado;
10. nenhuma flag residual de tracking deve bloquear o caminho OFF.

Se o problema só ocorre com tracking ON, registrar como tracking-specific.
Se também ocorre OFF, investigar primeiro o proprietário comum
(analyzer/power/presence/state machine) antes de tocar no tracker.

---

## 12. Como diagnosticar sem voltar a andar em círculos

Antes de mudar tracking novamente, responder:

### 12.1 O problema existe com tracking OFF?

- sim → provavelmente não é causa geométrica exclusiva do tracker;
- não → investigar pose, frescor, geometria móvel ou gates específicos de
  tracking.

### 12.2 Qual proprietário bloqueou?

Capturar no DEBUG:

- frame atual da câmera;
- frame/token do tracking;
- locked / evidence_current;
- reference / source_type;
- luminous IDs validados;
- presença;
- energia;
- spatial_alignment_ready;
- CHECK lógico;
- análise de máscaras;
- failed_mask_ids;
- decisão final;
- estado de rearme;
- Future/job pendente/concluído quando houver problema de IDENTIFICANDO.

### 12.3 Há duas verdades concorrentes?

Verificar se alguma camada:

- recalcula presença;
- recalcula energia;
- decide conformidade;
- move máscaras;
- registra resultado;

fora do proprietário canônico.

### 12.4 Já tentamos esta hipótese?

Consultar primeiro:

1. esta seção de histórico;
2. docs/DECISIONS.md;
3. docs/F3_PHYSICAL_VALIDATION_LOG.md;
4. histórico Git dos módulos afetados.

Se a hipótese for equivalente a uma estratégia da seção 7, não repeti-la sem
explicar qual nova evidência torna o resultado diferente.

---

## 13. Regras para futuros agentes/chats

Ao iniciar trabalho envolvendo o tracking F3:

1. ler AGENTS.md;
2. ler docs/DECISIONS.md;
3. ler docs/F3_PHYSICAL_VALIDATION_LOG.md;
4. ler este arquivo inteiro;
5. confirmar branch e HEAD;
6. confirmar se o usuário está testando tracking ON ou OFF;
7. não assumir que a última configuração lembrada ainda está ativa;
8. localizar o proprietário canônico antes de modificar código;
9. após duas tentativas malsucedidas para o mesmo defeito, parar de alterar
   algoritmo e instrumentar;
10. quando houver teste físico novo relacionado ao tracking:
    - registrar no F3_PHYSICAL_VALIDATION_LOG.md;
    - atualizar também este diário com a lição/estado;
    - nunca apagar a tentativa anterior.

---

## 14. Formato obrigatório para novas entradas deste diário

Usar este modelo:

~~~text
## YYYY-MM-DD — Título curto

Modo:
- tracking ON | OFF | comparação ON/OFF

Cenário:
- CHECK:
- placa/posição:
- condição de iluminação:
- comportamento esperado:

Sintoma/evidência:
- ...

Hipótese:
- ...

Tentativa:
- ...

Resultado:
- PASS | FAIL | REVERTIDO | PENDENTE DE RETESTE

Commit(s):
- ...

Decisão/ligação:
- D-XXX, se aplicável

Lição:
- ...

Não repetir:
- ...

Próximo reteste:
- ...
~~~

Quando uma tentativa falhar, ela permanece no arquivo. Quando uma tentativa
posterior resolver, acrescentar nova entrada em vez de reescrever a história.

---

## 30/09/2026 — Reteste D-032 falhou; ativada regra das duas tentativas

Modo:
- tracking ON

Cenário:
- câmera F3 ao vivo;
- máscara móvel sobre o display;
- VISOR DO DISPLAY;
- D-032 já aplicada.

Sintoma/evidência:
- segmentos físicos continuam sem produzir a reação visual esperada nas máscaras;
- o visor também não acompanha;
- os testes automatizados dos helpers haviam passado, portanto eles não provavam
  que o caminho real de runtime estava executando até o fim.

Hipótese atual:
- o defeito pode estar antes do detector visual ou em um fallback silencioso do
  `tracked_window_update`;
- o bloco de apresentação possuía um `except Exception` amplo que podia cair
  para geometria neutra sem deixar evidência da etapa que falhou;
- também é necessário separar objetivamente ausência de LOCK, contexto ausente,
  amostra visual vazia e falha do readout.

Tentativa:
- não alterar novamente threshold ou algoritmo visual;
- adicionar telemetria por estágio ao caminho real de repaint;
- anexar a telemetria ao DEBUG TÉCNICO capturado por ANALISAR.

Resultado:
- PENDENTE DE RETESTE / COLETA DE DEBUG

Decisão/ligação:
- D-032;
- regra das duas tentativas de AGENTS.md/ENGINEERING_RULES.md.

Lição:
- teste isolado de detector + inspeção de código não garante que o renderer final
  da instância chegou a consumir a amostra no equipamento;
- exceções silenciosas em apresentação impedem diagnóstico confiável;
- antes de nova correção, medir o caminho real.

Não repetir:
- não ajustar novamente thresholds do detector;
- não adicionar outro renderer/wrapper;
- não criar timer/thread paralelo para "forçar atualização";
- não presumir que `live_visual_mask_ids` chegou ao visor sem telemetria.

Próximo reteste:
- reproduzir a falha;
- clicar ANALISAR;
- copiar DEBUG;
- verificar o bloco
  `[ESPELHO VISUAL LIVE D-032 / CÂMERA + MÁSCARAS + VISOR]`.

---

## 30/09/2026 — Clarificação: falha visual era tracking OFF

Modo observado:
- tracking OFF

Clarificação do operador:
- o teste em que as máscaras continuavam cinzas e o VISOR DO DISPLAY não reagia
  foi executado com Rastreamento Automático desativado.

Causa confirmada no caminho de execução:
- `tracked_window_update` detectava tracking OFF e delegava imediatamente para
  o renderer anterior;
- a amostra D-032 estava conectada somente ao caminho tracking ON;
- o contexto fixo publicava `live_luminous_only=false`;
- o renderer fixo continuava dependente de análise/power gate para cor;
- o visor era atualizado antes da amostra latest-frame porque essa amostra nem
  existia nesse caminho;
- a geometria fixa continha somente máscaras ativas do CHECK, não todas as 28.

Correção D-033:
- tracking OFF passa a usar a mesma amostra visual latest-frame;
- muda somente a geometria: fixa em vez de rastreada;
- todas as máscaras do projeto podem participar do espelho visual;
- câmera e visor consomem a amostra depois de calculada e no mesmo repaint;
- decisão produtiva permanece separada.

Lição:
- não usar a flag de tracking para decidir se o espelho visual existe;
- tracking define **onde** estão as ROIs, não **se** o operador pode ver a
  emissão física representada.

Não repetir:
- não voltar a `live_luminous_only=false` apenas porque tracking está OFF;
- não limitar o espelho visual às máscaras ativas do CHECK;
- não atualizar o visor antes da amostra do frame atual.

---

## 30/09/2026 — Screenshot confirmou analyzer com 15 ON e espelho neutro

Modo:
- tracking OFF

Evidência:
- resumo visual: 19/28 conformes, 15 ACESOS, 13 APAGADOS;
- análise visual recente: CHECK AUX;
- estado operacional ainda mostrava ANALISANDO USB;
- máscaras da câmera e VISOR DO DISPLAY continuavam neutros.

Interpretação:
- o analyzer físico já conhecia os estados das máscaras;
- havia defasagem normal entre o CHECK lógico e a análise recente;
- o espelho dependia demais do detector visual leve e descartava a classificação
  física quando o CHECK não coincidia.

Tentativa D-034:
- usar somente o campo físico classified da análise recente do mesmo projeto;
- manter expected/matched estritamente presos ao CHECK correto;
- combinar o ON físico já conhecido com o ON do detector latest-frame;
- enviar um único mapa físico para câmera e visor.

Resultado:
- CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

Não repetir:
- não apagar cor física só porque o check_id mudou;
- não depender exclusivamente do detector leve quando o analyzer já possui
  estados físicos;
- não reutilizar matched/expected de outro CHECK como decisão.

---

## 30/09/2026 — DEBUG provou bypass final do espelho com tracking OFF

Modo:
- tracking OFF

Cenário:
- CHECK: AUX;
- placa presente e display ligado;
- comportamento esperado: ON verde vivo, OFF verde escuro, iguais na câmera e
  no VISOR DO DISPLAY.

Sintoma/evidência:
- câmera continuava com máscaras neutras;
- visor continuava neutro;
- DEBUG do caminho real publicou
  `stage=tracking_disabled` e
  `render_path=previous_window_update`;
- no mesmo bloco:
  `context_ready=NÃO`, `sample_ready=NÃO`, `visual_ids=0`,
  `readout_ready=NÃO`, `readout_visual_ids=0`;
- em paralelo a autoridade física já reportava 15 máscaras ON e 11 OFF
  confirmadas.

Causa:
- a autoridade final instalada diretamente na instância da janela ainda tinha
  um retorno antecipado quando tracking estava OFF;
- por isso as mudanças feitas no renderer/contexto inferior não eram alcançadas
  no caminho físico final.

Tentativa D-035:
- corrigir o proprietário final em vez de adicionar outro wrapper;
- tracking OFF agora passa pelo mesmo builder de espelho visual;
- OFF usa geometria fixa e ON usa geometria móvel;
- o mesmo contexto é enviado ao visor e ao renderer da câmera;
- sampler do frame atual é autoridade visual quando consegue medir a ROI;
- ON = verde vivo; OFF = verde escuro.

Resultado:
- CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

Decisão/ligação:
- D-035, substitui a parte operacional de D-034.

Lição:
- a telemetria `previous_window_update` provou que o problema era de roteamento
  do callback final, não de threshold;
- teste unitário do renderer inferior não prova que a instância final o consome.

Não repetir:
- não ajustar threshold para este defeito;
- não criar outro wrapper/timer;
- não permitir bypass do espelho apenas porque tracking está OFF;
- não usar cinza para OFF quando existe estado físico válido.

Próximo reteste:
- tracking OFF;
- confirmar câmera e visor juntos;
- ON deve ficar verde vivo;
- OFF deve ficar verde escuro;
- apagar/acender um segmento e verificar reação no frame atual.

---

## 30/09/2026 — D-036 separa máscara live fixa de máscara de referência

Modo:
- tracking OFF como foco atual;
- contrato também define a origem canônica do tracking ON.

Cenário:
- seção **Máscaras** do F3;
- geometrias locais existentes em CHECKS e referências visuais;
- operador pode mover, redimensionar ou trocar o formato da máscara.

Comportamento esperado:
- tracking OFF: câmera usa exatamente a geometria da seção **Máscaras**;
- CHECK/referência: geometria local serve somente para treinamento sobre a foto;
- mudar uma referência nunca desloca a ROI live;
- mudar **Máscaras** muda a ROI live.

Causa arquitetural encontrada:
- `mascaras_geometria_check_display()` era usado tanto para foto de referência
  quanto por alguns consumidores do frame ao vivo;
- isso misturava duas responsabilidades.

Tentativa:
- introduzir fonte explícita de geometria fixa do runtime;
- migrar preview, overlay, analyzer live e assinatura 4x7 para essa fonte;
- manter o helper de CHECK exclusivamente para referência/treinamento;
- preservar tracking ON como projeção da máscara canônica.

Resultado:
- IMPLEMENTADO — PENDENTE DE RETESTE FÍSICO.

Decisão/ligação:
- D-036.

Lição:
- identidade da máscara e pose da foto de treinamento não são a mesma coisa;
- CHECK pode ensinar o estado óptico da mesma MASK_xxx sem possuir autoridade
  para mover essa MASK_xxx na câmera ao vivo.

Não repetir:
- não usar `mask_overrides_reference` como geometria do frame atual com
  tracking OFF;
- não copiar geometria de referência para a seção **Máscaras** automaticamente;
- não criar uma segunda coleção de ROIs produtivas por CHECK.

Próximo reteste:
- tracking OFF;
- mover uma máscara somente em **Máscaras** e confirmar movimento na câmera;
- mover a mesma máscara somente na referência do CHECK e confirmar que a câmera
  NÃO muda;
- repetir trocando formato e tamanho;
- confirmar que o treinamento do CHECK continua usando sua geometria local.

---

## 30/09/2026 — Contorno canônico passa a integrar o preview live

Modo:
- tracking OFF como foco do teste;
- contrato também preservado no tracking ON.

Cenário:
- CHECK: H1 / fluxo normal;
- placa/posição: posição cadastrada no modo fixo;
- condição de iluminação: indiferente;
- comportamento esperado: o contorno desenhado em **Placa + Máscaras** deve
  aparecer na câmera ao vivo junto das máscaras.

Sintoma/evidência:
- o renderer final já possuía suporte a `board_points`;
- tracking ON publicava o contorno projetado quando havia LOCK;
- tracking OFF publicava `board_points=()`, eliminando o contorno do contexto.

Hipótese:
- defeito de composição do contexto visual fixo, não de tracking óptico.

Tentativa:
- consumir `canonical_board_points` do mesmo store canônico já usado pelo
  tracker;
- rotacionar os pontos para a orientação visual;
- incluir a assinatura do contorno na chave de cache;
- não usar contorno local de CHECK como geometria live.

Resultado:
- PENDENTE DE RETESTE FÍSICO

Commit(s):
- commit desta correção D-037.

Decisão/ligação:
- D-036 e D-037.

Lição:
- tracking OFF e ON devem divergir somente na transformação espacial; a
  identidade do contorno live nasce da mesma geometria canônica.

Não repetir:
- não deixar `board_points=()` no contexto live fixo quando existe contorno;
- não copiar `board_points_reference` de CHECK para a câmera;
- não criar segunda persistência de contorno.

Próximo reteste:
- confirmar contorno fixo com tracking OFF;
- confirmar contorno móvel com tracking ON + LOCK;
- editar o contorno canônico e confirmar invalidação visual do cache.



---

## 30/09/2026 — D-038/D-039: falso OFF de H1 e latch terminal com tracking OFF

Modo:
- tracking OFF;
- geometria live continua regida por D-036/D-037.

Evidência:
- H1 manual no mesmo frame: 28/28;
- strict runtime observado: 21/28, com as sete máscaras esperadas ON marcadas
  como OFF;
- energia/máscaras live confirmavam os sete ON;
- o runtime já estava em `waiting_empty_rearm=true`, TOTAL 1 / NG 1,
  `last_result=null`;
- a tela principal, porém, havia voltado para H1.

Interpretação:
- o primeiro defeito é semântico no aprendizado estrito, não no object tracking;
- o segundo é sincronização entre apresentação terminal e rearme físico, não
  captura de tecla nem geometria;
- o fato de a sequência interna voltar a H1 após evento terminal não significa
  que um novo ciclo esteja autorizado.

Correção D-038:
- preserva `F3StrictMaskConformityAnalyzer` como autoridade;
- preserva exclusão do CHECK atual dos pools globais;
- permite somente ON próprio validado no pool local da mesma máscara;
- OFF próprio nunca é reinjetado;
- margem física usa o limiar óptico já existente do F3;
- live ainda precisa cumprir todas as máscaras.

Correção D-039:
- resultado terminal, espera por EMPTY e espera por nova placa formam um único
  latch visual;
- SEGREGAR é desabilitado nesse latch e reabilitado somente com nova placa;
- tecla e botão continuam na mesma ação canônica;
- nenhuma autoridade de tracking, timer, thread, executor ou scheduler foi
  adicionada.

Não repetir:
- não corrigir falso OFF afrouxando a regra de 100% das máscaras;
- não voltar a aceitar OFF do próprio CHECK como auto-referência;
- não usar tracking para mascarar defeito de classificação com tracking OFF;
- não renderizar H1 como ativo enquanto `waiting_empty_rearm` ou
  `waiting_new_board_after_empty` estiverem ativos;
- não liberar SEGREGAR repetidamente para contornar o rearme.

Reteste obrigatório:
- H1 correto aprova com tracking OFF;
- segmento ON defeituoso continua bloqueando;
- SEGREGAR por botão, 1 e NumPad 1 contabiliza uma única vez;
- retirar e recolocar a placa faz a sequência visual
  TERMINAL -> EMPTY -> NOVA PLACA -> H1.

---

## 30/09/2026 — D-040: vermelho terminal de SEGREGAR é apresentação, não tracking

Modo:
- tracking OFF como foco atual;
- regra vale igualmente com tracking ON.

Cenário:
- CHECK: qualquer;
- placa/posição: placa ainda presente após SEGREGAR;
- condição de iluminação: indiferente;
- comportamento esperado: resultado permanece vermelho até EMPTY.

Sintoma/evidência:
- D-039 já preservava o latch terminal e bloqueava H1;
- cards/status/bordas ainda não comunicavam integralmente a segregação em
  vermelho;
- isso podia fazer botão/tecla parecerem sem efeito ou rápidos demais.

Hipótese:
- problema de apresentação do latch existente, não de captura de tecla, tracking,
  energia ou analyzer.

Tentativa:
- manter D-039 como autoridade de lifecycle;
- adicionar somente o tipo terminal `segregated` à janela;
- derivar dele cards/bordas/status vermelhos;
- propagar um flag de apresentação `terminal_segregated` para câmera e visor;
- renderizar contorno, máscaras e 28 segmentos em vermelho sem alterar a
  classificação física interna;
- limpar esse estado nos mesmos pontos de EMPTY/nova placa já existentes.

Resultado:
- PENDENTE DE RETESTE FÍSICO

Commit(s):
- commits da correção D-040.

Decisão/ligação:
- D-039 e D-040.

Lição:
- feedback terminal deve ser derivado do rearme físico já existente;
- vermelho de resultado pode sobrescrever a apresentação das ROIs/visor, mas
  nunca a classificação óptica ou a telemetria interna.

Não repetir:
- não adicionar outro binding para tecla 1;
- não criar timer para prolongar o vermelho;
- não alterar thresholds/tracking para um problema de feedback;
- não reescrever classificações ON/OFF como NG para obter o visual vermelho;
  use somente o override de apresentação terminal.

Próximo reteste:
- SEGREGAR por clique, 1 e NumPad 1;
- manter placa no suporte por vários segundos e confirmar vermelho persistente;
- confirmar câmera, contorno, máscaras e visor integralmente vermelhos;
- retirar a placa e confirmar transição para espera por nova placa;
- confirmar no debug/telemetria que ON/OFF físico continua preservado internamente.

---

## 30/09/2026 — D-041: referência visual é padrão segmentado dentro do contorno

Modo:
- tracking OFF como foco físico atual;
- contrato semântico vale também com tracking ON.

Cenário:
- CHECK: H1 como caso relatado, extensível aos demais CHECKS;
- referências: imagens dos CHECKS + Referências Visuais;
- cada imagem possui contorno local, máscaras alinhadas e estados ON/OFF;
- sintoma: segmentos ON esperados aparecem verdes, mas H1 pode continuar sem
  aprovação ou sem reconhecimento pela análise visual.

Regra confirmada:
- a fotografia inteira não é a memória semântica do CHECK;
- a memória útil é o padrão dos MASK_xxx dentro da região da placa;
- o contorno fornece a região/crop de normalização;
- a geometria local da referência localiza cada MASK_xxx naquela foto;
- o alinhamento relaciona esses IDs com o frame atual;
- a conformidade final continua sendo expected x observed por máscara.

Interação com tracking:
- tracking ON pode fornecer/projetar pose dinâmica antes da comparação;
- tracking OFF continua usando a geometria live canônica fixa definida por
  D-036, sem transformar geometrias locais de referência em ROIs produtivas;
- em ambos os modos, matching de cena inteira não pode virar um segundo veto
  semântico depois que o padrão de máscaras está 100% conforme.

Resultado:
- REGRA DOCUMENTADA — causa concreta do bloqueio de H1 ainda pendente de DEBUG.

Decisão/ligação:
- D-031, D-036, D-037 e D-041.

Lição:
- separar três papéis que historicamente se misturaram: localizar a placa,
  alinhar a geometria e julgar o padrão ON/OFF;
- reconhecimento visual de CHECK deve consumir a geometria/semântica ensinada,
  não pixels irrelevantes do fundo;
- uma análise visual global não deve contradizer uma conformidade semântica
  completa sem apontar qual regra produtiva real bloqueou o registro.

Não repetir:
- não comparar H1 inteiro com câmera inteira como autoridade final;
- não usar fundo/suporte/iluminação global para negar um padrão de segmentos
  integralmente conforme;
- não copiar a geometria local de CHECK para a câmera live com tracking OFF;
- não afrouxar D-031 para "fazer H1 passar"; primeiro identificar o bloqueio
  real quando todos os estados ON/OFF estiverem corretos.

Próximo reteste:
- reproduzir H1 com todos os ON esperados verdes;
- confirmar também todos os OFF esperados;
- capturar DEBUG no mesmo frame;
- localizar explicitamente o gate/autoridade que impede o registro do CHECK.

---

## 30/09/2026 — D-042: deadlock presença/energia confirmado com tracking OFF

Modo:
- tracking OFF.

Cenário:
- CHECK: H1;
- os sete ON esperados estavam verdes;
- analyzer estrito: 28/28 conforme;
- CHECK permaneceu em AGUARDANDO H1.

Sintoma/evidência:
- `board_present=false`;
- `energy=null` no status da autoridade canônica;
- motivo do gate: `placa_nao_confirmada_no_suporte`;
- análise H1 já aprovada semanticamente, mas marcada
  `blocked_by_power_gate=true`;
- diagnóstico de máscaras do mesmo frame confirmou os sete ON esperados.

Hipótese confirmada:
- não é defeito do object tracking;
- `F3RuntimeAuthorities.build_operational_state()` só calculava energia depois
  de a presença global já estar confirmada;
- com fotografia global ambígua, os segmentos nunca podiam fornecer a evidência
  que faltava para destravar a própria presença.

Tentativa:
- consolidar a solução no proprietário canônico, sem reativar o antigo
  `display_f3_runtime_contract_fix` como monkey patch produtivo;
- calcular a observação semântica das máscaras antes do gate final quando o frame
  não é EMPTY explícito;
- entregar essa evidência à `F3PresenceAuthority`;
- promover somente ocupação quando existe núcleo ON completo de um CHECK
  configurado e nenhuma contradição confiante;
- manter EMPTY soberano;
- manter o analyzer estrito como única autoridade de conformidade do CHECK.

Resultado:
- CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

Decisão/ligação:
- D-021, D-031, D-041 e D-042.

Lição:
- tracking OFF não significa que presença precise depender exclusivamente da
  fotografia global;
- estados semânticos das máscaras podem provar que há display/placa sem ganhar
  autoridade para aprovar o CHECK;
- a direção de dependência deve distinguir **calcular evidência** de **autorizar
  decisão**.

Não repetir:
- não voltar a pular a leitura semântica das máscaras apenas porque
  `board_present=false` na fotografia global;
- não baixar threshold global de presença para mascarar o problema;
- não instalar novamente um segundo wrapper que promova CHECK fora da
  `F3PresenceAuthority`;
- não permitir que evidência de segmentos sobrescreva EMPTY confirmado.

Próximo reteste:
- tracking OFF;
- iniciar diretamente em H1 com os sete ON corretos;
- confirmar presença/energia e avanço para BLUE;
- depois retirar a placa e confirmar que EMPTY continua vencendo.

---

## 30/09/2026 — D-042 PASS / D-043: BLUE 28/28 bloqueado fora do tracking

Modo:
- tracking OFF.

Validação anterior:
- D-042 PASS no equipamento real;
- H1 correto passou e a sequência avançou para BLUE.

Novo cenário:
- CHECK atual: BLUE / CHECK_002;
- H1 já concluído;
- 18 ON + 10 OFF esperados de BLUE estavam conformes;
- analyzer semântico: 28/28 aprovado;
- presença e energia confirmadas;
- gate produtivo liberado;
- UI dizia `DISPLAY EM BLUE` e `BLUE DETECTADO • 28/28 CONFORMES`;
- porém o resultado era bloqueado em
  `aguardando mudança física H1 → BLUE`.

Diagnóstico:
- este defeito não pertence ao object tracking; o snapshot registra tracking
  desativado;
- a autoridade `display_f3_physical_transition_authority` ainda usava
  identificação física independente/comparação de fotografias para confirmar
  H1 → BLUE;
- a comparação global das fotos estava ambígua e não consumia a evidência mais
  específica já disponível: o padrão BLUE completo das 28 máscaras;
- portanto o analyzer e a UI sabiam que BLUE estava presente, mas o guard final
  de transição ainda vetava o registro.

Correção D-043:
- preservar a autoridade física de transição existente;
- aceitar conformidade canônica 100% do CHECK atual como prova positiva da
  chegada ao destino somente quando o padrão ON/OFF realmente difere do CHECK
  anterior;
- exigir CHECK anterior concluído e análise do contexto atual;
- preservar o caminho físico independente para análise parcial, padrões iguais e
  para permitir NG somente depois que a função de destino realmente chegou;
- não alterar tracking, thresholds globais, scheduler ou geometria.

Resultado:
- D-042: PASS FÍSICO;
- D-043: CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

Decisão/ligação:
- D-024, D-031, D-041, D-042 e D-043.

Lição:
- com tracking OFF, um padrão ON/OFF integralmente diferente do estado anterior
  é evidência física da mudança de função mais específica que a similaridade da
  cena inteira;
- isso não elimina o gate de transição: redefine uma evidência positiva válida
  para o caso 100% conforme.

Não repetir:
- não deixar score global/foto inteira vetar indefinidamente um CHECK 28/28 cujo
  padrão difere do anterior;
- não remover o gate físico inteiro para resolver esse caso;
- não permitir 27/28 ou análise de outro CHECK como prova de transição;
- não usar a regra de conformidade total para gerar NG antes de confirmar que a
  função defeituosa realmente chegou.

Próximo reteste:
- tracking OFF;
- H1 → BLUE;
- quando BLUE chegar a 28/28, confirmar avanço imediato para USB;
- depois validar que uma divergência real em BLUE continua sem receber OK.

---

## 30/09/2026 — D-043 PASS físico com tracking OFF

Modo:
- tracking OFF.

Cenário:
- H1 já concluído;
- BLUE atual;
- padrão BLUE integralmente conforme;
- correção D-043 ativa.

Resultado:
- PASS FÍSICO;
- BLUE deixou de ficar preso no gate `H1 → BLUE`;
- a conformidade semântica completa confirmou a mudança de função;
- a sequência avançou para USB conforme esperado.

Decisão/ligação:
- D-024, D-031, D-041, D-042 e D-043.

Lição:
- o bloqueio não era causado pelo object tracking;
- com tracking OFF, o próprio padrão ON/OFF completo e diferente do CHECK
  anterior pode provar positivamente a transição sem depender de matching global
  da fotografia;
- isso preserva a separação entre geometria, presença, energia, conformidade e
  sequência, sem criar autoridade paralela.

Não repetir:
- não restaurar o veto por cena inteira sobre um CHECK 100% conforme;
- não remover as guardas de análise parcial ou de padrões semanticamente iguais;
- não atribuir ao tracking um defeito confirmado na autoridade de transição
  semântica.

Estado:
- D-043 VALIDADA FISICAMENTE NO CENÁRIO H1 → BLUE COM TRACKING OFF.

---

## 30/09/2026 — D-044: BLUE NG com MASK_024 apagada não é defeito de tracking

Modo:
- tracking OFF.

Cenário:
- H1 concluído;
- BLUE atual;
- 18 segmentos esperados ON;
- 17 confirmados como powered;
- MASK_024, esperada ON, permaneceu OFF;
- aprendizado semântico manual do mesmo frame: BLUE 27/28.

Sintoma:
- apesar da emissão evidente e do defeito corretamente observado, o runtime
  permaneceu em `IDENTIFICANDO PRESENÇA DA PLACA` e não chegou ao NG.

Diagnóstico:
- a falha não pertence ao object tracking;
- D-042 exigia padrão completo de algum CHECK para usar máscaras como presença,
  o que excluía por construção produtos NG;
- D-043 também exigia 100% para usar semântica como prova de handoff;
- a imagem global preferia placa desligada/ficava abaixo dos thresholds, portanto
  não oferecia a confirmação independente necessária.

Correção D-044:
- manter `F3PresenceAuthority` como único proprietário de presença, aceitando
  energia multi-máscara confirmada como prova apenas de ocupação quando o CHECK
  diverge;
- manter a autoridade existente de transição e acrescentar uma assinatura baseada
  somente nas máscaras que mudaram anterior → atual;
- exigir maioria estrita no padrão do destino e mais votos de destino que do
  estado anterior;
- a assinatura não decide OK/NG; o analyzer/debounce continuam responsáveis;
- não modificar tracking, geometria, thresholds globais ou scheduler.

Resultado:
- CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

Decisão/ligação:
- D-031, D-041, D-042, D-043 e D-044.

Não repetir:
- não exigir CHECK perfeito para confirmar que uma placa defeituosa está
  fisicamente presente;
- não liberar qualquer 27/28 como transição sem comparar o padrão das máscaras
  que realmente mudaram;
- não usar score de cena inteira como autoridade final de defeito;
- não atribuir ao tracking um bloqueio reproduzido com tracking OFF.

Próximo reteste:
- reproduzir BLUE com somente MASK_024 apagada;
- confirmar presença + energia + chegada BLUE;
- confirmar NG terminal sem avanço para USB;
- confirmar que H1 ainda presente não gera falso NG de BLUE.

---

## 01/10/2026 — D-044 PASS físico com tracking OFF

Modo:
- tracking OFF.

Cenário:
- H1 concluído;
- BLUE atual;
- MASK_024 esperada ON permaneceu fisicamente OFF;
- correção D-044 ativa.

Resultado:
- PASS FÍSICO;
- a placa permaneceu reconhecida como presente e energizada mesmo com o CHECK
  divergente;
- a assinatura semântica H1 → BLUE permitiu confirmar a chegada da função sem
  exigir BLUE perfeito;
- MASK_024 continuou divergente e o ODIN registrou NG corretamente;
- o defeito não depende do object tracking e foi validado com tracking desligado.

Decisão/ligação:
- D-031, D-041, D-042, D-043 e D-044.

Lição:
- presença, chegada ao CHECK e conformidade são autoridades distintas;
- um produto NG precisa poder entrar no fluxo de julgamento sem antes parecer
  um produto BOM;
- a assinatura de transição pode provar chegada, mas não substitui o analyzer
  que decide a divergência.

Não repetir:
- não exigir padrão 100% conforme para confirmar presença de placa energizada;
- não transformar 27/28 em OK;
- não atribuir ao tracking uma falha reproduzida e corrigida com tracking OFF.

Estado:
- D-044 VALIDADA FISICAMENTE NO CENÁRIO BLUE COM MASK_024 APAGADA.

