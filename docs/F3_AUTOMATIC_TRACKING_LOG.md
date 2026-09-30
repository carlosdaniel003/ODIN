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

