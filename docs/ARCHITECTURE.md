# Arquitetura do ODIN

## 1. Propósito

O ODIN é um sistema desktop de inspeção industrial por visão computacional para placas eletrônicas.

A aplicação combina:

- captura de câmera;
- OpenCV e análise óptica;
- configuração de projetos e referências;
- edição de ROIs/máscaras;
- inspeção produtiva;
- estado de ciclo;
- apresentação em Tkinter;
- diagnóstico técnico.

O requisito central é executar inspeção de forma previsível e responsiva sem transformar crescimento funcional em acoplamento entre módulos.

## 2. Plataformas

Plataformas suportadas:

- Windows;
- Linux desktop.

Raspberry Pi não é plataforma suportada. A composição canônica é desktop
Windows/Linux e os shims/classes Raspberry e GPIO já foram removidos após
auditoria de consumidores e CI.

A árvore produtiva deve permanecer orientada a Desktop/Windows/Linux.

## 3. Domínios do produto

### Engenharia e parametrização

Responsável por:

- seleção/configuração de câmera;
- projetos;
- resolução mestre;
- referências;
- máscaras/ROIs;
- ferramentas de edição;
- debug e visualizações técnicas.

### Produção F2

Responsável pelo ciclo produtivo de LEDs/segmentos do F2.

Seu estado operacional e regras de decisão são próprios.

### Produção Display F3

Responsável pela sequência configurável de CHECKS de display.

Seu projeto, persistência, state machine, contadores, referências e regras de decisão são próprios.

### Regra de isolamento

F2 e F3 podem compartilhar:

- câmera;
- estruturas geométricas;
- primitivas de visão;
- utilitários;
- infraestrutura genérica.

Não devem compartilhar implicitamente:

- progresso do ciclo;
- CHECK atual;
- resultado;
- contadores;
- debounce;
- autoridade de presença;
- autoridade de energia;
- estado de rearme.

## 4. Arquitetura atual e direção alvo

A branch `display` cresceu historicamente usando mixins e funções `instalar_*` para preservar compatibilidade durante muitas correções.

Essa composição continua sendo parte do runtime atual, mas **não é o padrão desejado para novas responsabilidades**.

A direção arquitetural é:

~~~text
Tkinter UI
   │
   │ eventos e renderização
   ▼
ViewModel / Controller de apresentação
   │
   ▼
Runtime Coordinator
   │
   ├── Camera / Latest Frame
   ├── Tracking
   ├── Presence
   ├── Power
   ├── Check Analyzer
   ├── State Machine
   ├── Persistence
   └── Heavy Work Executor
~~~

O objetivo não é reescrever o sistema de uma vez. A migração substitui uma autoridade por vez.

### Composição canônica Desktop

O runtime de produto é composto por:

~~~text
main.py
  └── main_desktop.py
      └── DesktopProductionApp
          └── DesktopBaseODINApp
              └── DesktopODINApp
~~~

Responsabilidades de plataforma:

- `DesktopProductionApp` é a composição final de F2, F3 e parametrização;
- `DesktopBaseODINApp` agrega projetos, editor de máscaras e métricas sem GPIO;
- `DesktopODINApp` possui o lifecycle base e seleciona câmera por
  `CAMERA_SERVICE_CLASS`;
- `LiveFixedFullHdCameraService` é injetado pela composição final;
- `DesktopCameraService` e `ThreadedDesktopCameraService` são os nomes
  canônicos da infraestrutura de captura;
- Windows e Linux continuam diferenciados por adapters/backends internos.

A classe da câmera é uma dependência explícita da composição por
`CAMERA_SERVICE_CLASS`.

Não existem aliases `Raspberry*`, launcher `main_rpi.py` nem infraestrutura
GPIO no runtime canônico.

### Executor pesado canônico do F3

A execução pesada assíncrona do F3 possui atualmente um proprietário explícito:

~~~text
src/platform/display_f3_heavy_executor.py
  └── F3HeavyVisionExecutor
~~~

Contratos atuais:

- exatamente um worker por aplicação;
- no máximo um job pesado ativo;
- fila pendente limitada;
- prioridade `HIGH / NORMAL / LOW`;
- substituição de job pendente por chave para previews latest-wins;
- cancelamento de jobs pendentes por proprietário;
- lifecycle encerrado junto da janela raiz;
- nenhum acesso a widgets Tkinter pelo executor.

Consumidores já migrados:

- tracking ao vivo ORB/AKAZE/template/warp — `HIGH`;
- classificação semântica automática do CHECK F3 — `HIGH`;
- previews da configuração — `LOW`;
- análise manual do CHECK atual — `NORMAL`;
- relatório técnico completo iniciado pelo clique em ANALISAR — `LOW`.

A janela `DEBUG TÉCNICO` é somente apresentação: mostra o print da tela F3
capturado no mesmo clique e não submete trabalho de visão ao executor.

O callback produtivo completo não é enviado a background. Tracking e
classificação semântica pesada usam o executor, enquanto aplicação de resultado,
presença, energia, sequência e apresentação permanecem nos proprietários
corretos. O frame analisado nunca substitui `camera_frame_atual`: a câmera
visível continua latest-frame-wins.

### Autoridades canônicas do runtime F3

A composição produtiva do F3 possui um registro explícito de proprietários:

~~~text
src/platform/display_f3_runtime_authorities.py
  └── F3RuntimeAuthorities
      ├── F3TrackingAuthority
      │     └── F3DisplayObjectTracker
      ├── F3PresenceAuthority
      ├── F3PowerAuthority
      ├── F3CheckAnalyzerAuthority
      │     └── F3TrackedRawCheckAnalyzer
      └── F3StateMachineAuthority
            └── DisplayCheckSequenceRuntime
~~~

Contratos atuais:

- cada responsabilidade possui um proprietário explícito;
- tracking reutiliza uma única instância stateful do tracker;
- presença possui uma única memória de estabilidade curta;
- `F3PresenceAuthority` pode aceitar um lock de tracking como evidência positiva
  de placa somente quando `locked=true` e `evidence_current=true`; EMPTY
  confirmado continua tendo precedência e lock mantido/stale não promove presença;
- energia produtiva recebe presença como gate e não pode ignorá-la; D-042/D-044
  permitem calcular a observação semântica das máscaras antes do gate somente
  para entregá-la à `F3PresenceAuthority`, que continua sendo a única autoridade
  capaz de confirmar ocupação; um padrão completo pode identificar o estado,
  enquanto emissão multi-máscara `powered` sem padrão completo confirma apenas
  que existe placa energizada; EMPTY confirmado tem precedência;
- tracking estrutural localiza o filtro, mas o refinamento luminoso do CHECK
  atual prefere o espaço da própria referência daquele CHECK antes de compor
  novamente para o espaço canônico;
- emissão luminosa detectada dentro do filtro pode provar **energia física** sem
  provar conformidade; enquanto o encaixe fino dos segmentos não estiver pronto,
  a autoridade de energia mantém OK/NG e avanço de CHECK bloqueados;
- analyzer produtivo possui uma única instância/cache por sessão;
- a autoridade de transição física entre CHECKS aceita identificação física
  independente do destino; D-043 acrescenta conformidade canônica 100% quando o
  padrão ON/OFF difere do anterior; D-044 acrescenta, para um destino defeituoso,
  uma assinatura de chegada baseada somente nas máscaras que mudaram entre os
  dois CHECKS, exigindo maioria estrita no padrão do destino. Essa assinatura
  confirma chegada, não conformidade nem NG; padrões idênticos e assinaturas que
  ainda preferem o CHECK anterior permanecem bloqueados;
- mutações de sequência passam pela facade da state machine;
- estado físico + presença + energia são calculados uma vez por
  `frame/projeto/CHECK/rearme` e reutilizados pelos adapters históricos;
- caches/latches são invalidados em abertura, fechamento e rearme físico;
- o coordinator publica as métricas dessas autoridades junto do scheduling.

Módulos históricos `fix/v2/final/guard/compat` que permanecem na árvore foram
auditados e possuem consumidores produtivos. Módulos órfãos comprovadamente
substituídos foram removidos na Etapa 7. Nenhum novo patch paralelo deve ser
criado quando existir um proprietário canônico.


### Direção experimental — filtro como localizador e H1 como referência geométrica fina

> Estado: **proposta de experimento**, ainda não descreve o runtime produtivo
> atual. A decisão correspondente está em D-025.

O problema geométrico do Display F3 possui duas referências físicas diferentes:

1. o **filtro preto**, que acompanha aproximadamente a placa e delimita a região
   onde os segmentos sempre aparecem;
2. o **grid luminoso dos segmentos**, que pode se deslocar dentro do próprio
   filtro e por isso não deve herdar automaticamente a pose fina do contorno.

A direção experimental separa essas responsabilidades:

~~~text
Frame RAW
   ↓
Tracking estrutural do filtro
   ↓
Homografia H_filter
   ↓
Filtro retificado em ROI canônica
   ↓
Registro visual do H1 completo
   ↓
Ajuste interno T_segments
   ↓
Imagem normalizada para a geometria de referência
   ↓
Máscaras canônicas fixas
~~~

Contratos propostos:

- F3TrackingAuthority permanece o único proprietário de tracking;
- localizar o filtro produz LOCK_FILTRO, suficiente para presença/região, mas
  insuficiente para analisar máscaras;
- o primeiro CHECK/H1 é usado para obter LOCK_SEGMENTOS por registro da imagem
  inteira do padrão luminoso contra a referência ensinada;
- o alinhamento deve normalizar a imagem para o espaço canônico das máscaras,
  em vez de recalcular 28 geometrias independentes no frame RAW;
- o registro fino deve começar com transformação conservadora após a homografia:
  translação e pequena rotação; escala só entra se experimentos reais provarem
  necessidade;
- reconhecimento visual de H1/BLUE/USB/AUX na ROI retificada é permitido como
  evidência/telemetria de identidade, mas não cria uma segunda autoridade de
  OK/NG;
- após LOCK_SEGMENTOS no H1, a transformação do ciclo é congelada para os
  CHECKS seguintes, pois a placa não deve mover fisicamente durante
  H1 -> BLUE -> USB -> AUX;
- movimento significativo depois do lock invalida a geometria; não deve disparar
  adaptação silenciosa contínua;
- retirada/rearme da placa encerra o lock geométrico do ciclo;
- qualquer implementação pesada continua no executor HIGH existente, sem novo
  scheduler, fila ou thread.

A validação inicial deve ocorrer fora da lógica produtiva de energia/OK/NG:
um lote de imagens reais de H1 em posições diferentes deve provar que a
retificação + registro coloca consistentemente as máscaras fixas sobre os
segmentos antes de o mecanismo substituir o alinhamento luminoso atual.
### Coordenador canônico do runtime F3

O scheduling periódico do F3 possui um proprietário explícito:

~~~text
src/platform/display_f3_runtime_coordinator.py
  └── F3RuntimeCoordinator
~~~

No runtime de produto, instalado por último em `main_desktop.py`, ele:

- possui o único `root.after()` periódico do ciclo F3;
- coalesça frame repetido em repaint leve;
- executa ciclo completo apenas em frame novo quando análise/tracking exigem;
- preserva a segunda metade pendente do pipeline cooperativo de tracking;
- mantém o rearme ativo em frames novos;
- reduz a cadência quando CONFIGURAR está aberto;
- aplica idle real após callbacks caros;
- observa o `F3HeavyVisionExecutor` e evita concorrência pesada paralela;
- publica métricas de ticks, ciclos completos, repaints, frames repetidos e idle.

O antigo wrapper de responsividade/cadência substituído foi removido da árvore;
o coordinator permanece como única autoridade periódica do F3.


No caminho visual do F3, tracking e câmera têm autoridades diferentes:
tracking fornece pose/geometria; a preview recebe sempre o frame atual publicado
pela câmera. O frame usado por ORB/AKAZE não volta a ser autoridade visual quando
o worker termina.

A abertura de `CONFIGURAR` entra na fila normal do Tk com `after(1)`; não usa
`after_idle()`, porque câmera e scheduler periódicos podem manter o mainloop
continuamente ocupado.

## 5. Direção de dependências

A dependência preferida é:

~~~text
UI
 ↓
Application / Runtime
 ↓
Domain services
 ↓
Core vision
 ↓
Infrastructure adapters
~~~

Regras:

- `core` não deve depender de Tkinter;
- persistência não deve decidir regra de produção;
- UI não deve duplicar decisão de domínio;
- debug não deve controlar produção;
- adapters Windows/Linux devem esconder detalhes de plataforma;
- serviços de domínio não devem depender de nomes legados Raspberry.

## 6. Proprietário único

O princípio mais importante da arquitetura é **Single Owner**.

| Responsabilidade | Proprietário desejado |
| --- | --- |
| captura da câmera | Camera Service |
| último frame | Latest Frame Buffer |
| scheduling F3 | F3 Runtime Coordinator |
| execução pesada F3 | Heavy Vision Executor |
| tracking | `F3TrackingAuthority` |
| presença | `F3PresenceAuthority` |
| energia | `F3PowerAuthority` |
| análise de CHECK | `F3CheckAnalyzerAuthority` |
| sequência | `F3StateMachineAuthority` / `DisplayCheckSequenceRuntime` |
| decisão de resultado | regra canônica do domínio |
| persistência | Repository |
| apresentação | ViewModel + UI |
| debug | Debug Service observador |

Um componente pode consumir estado de outro, mas não deve recriar sua regra.

## 7. Modularidade saudável

Um módulo deve representar responsabilidade coesa.

Bom exemplo:

~~~text
f3/
├── runtime/
│   ├── coordinator.py
│   └── state_machine.py
├── vision/
│   ├── tracking.py
│   ├── presence.py
│   ├── power.py
│   └── check_analyzer.py
├── config/
├── debug/
├── ui/
└── repository.py
~~~

Essa estrutura é direção, não ordem para mover arquivos imediatamente.

Evite arquitetura permanente do tipo:

~~~text
tracking.py
tracking_fix.py
tracking_fix_v2.py
tracking_final_fix.py
tracking_compat.py
tracking_authority.py
~~~

A história de bugs pertence ao Git e aos testes, não à árvore produtiva.

## 8. Composição em vez de herança crescente

Para novas responsabilidades, prefira objetos colaborativos injetados explicitamente:

~~~text
F3RuntimeCoordinator
    uses TrackingService
    uses PresenceService
    uses PowerService
    uses CheckAnalyzer
~~~

em vez de adicionar mais um mixin que sobrescreve métodos de uma classe com MRO já extensa.

Mixins existentes podem permanecer durante a migração. Novos mixins precisam de justificativa arquitetural real.

## 9. Estado e contratos

Estado compartilhado precisa de:

- proprietário;
- formato conhecido;
- lifecycle;
- regra de atualização;
- regra de invalidação;
- consumidores identificáveis.

Evite flags globais espalhadas com semânticas parcialmente sobrepostas.

Quando estado cruza módulos, prefira estruturas explícitas, por exemplo:

~~~text
FrameSnapshot
AnalysisRequest
AnalysisResult
RuntimeState
CheckContext
~~~

Estruturas imutáveis ou tratadas como snapshots são preferíveis quando trafegam entre threads.

## 10. UI e visão computacional

Tkinter é a camada de apresentação.

O thread do Tk deve:

- receber eventos;
- atualizar estado visual;
- criar/atualizar widgets;
- apresentar imagem/resultados já preparados.

O thread do Tk não deve ser o executor de ORB, AKAZE, matching pesado, loops por referência ou auditorias completas.

Processamento OpenCV pesado deve ocorrer fora do event loop e retornar somente dados/imagens prontos para apresentação.

Objetos Tk, incluindo `PhotoImage`, permanecem no thread principal.

## 11. Persistência

Repositórios devem encapsular:

- leitura;
- escrita;
- schema;
- migração;
- cache;
- invalidação.

Não fazer leitura de JSON/JPEG repetida dentro de hot loops quando os dados não mudaram.

Caches precisam de invalidação explícita e limite quando puderem crescer.

## 12. Compatibilidade de plataforma

A arquitetura alvo deve expor abstrações como:

~~~text
CameraService
├── Windows backend
└── Linux backend
~~~

Detalhes V4L2, DirectShow, Media Foundation e outros backends ficam em adapters.

A lógica F2/F3 não deve precisar saber qual backend abriu a câmera.

## 13. Segurança de migração

Ao substituir uma autoridade histórica:

1. capture o comportamento atual em testes;
2. introduza o componente canônico;
3. direcione consumidores para ele;
4. valide equivalência;
5. desligue o caminho histórico;
6. remova resíduos comprovadamente sem consumidores.

Não mantenha indefinidamente as duas autoridades ativas.


### Refinamento luminoso da pose F3

Dentro da autoridade canônica de tracking, o contorno configurado pode representar
o filtro preto móvel do display. Esse contorno fornece uma região grosseira de
busca; ele não fixa as 28 ROIs na câmera.

Não existe banco angular produtivo 90°/180°/270°. A geometria persistida pelo
tracking é o contorno canônico do projeto; referências estruturais normais do F3
podem ajudar na localização grosseira, e os segmentos luminosos do CHECK atual
fazem o alinhamento fino.

Quando o CHECK atual possui segmentos esperados ACESOS, o job de tracking pode
usar somente os componentes luminosos encontrados dentro do filtro para refinar
ou recuperar a transformação do frame atual para o espaço canônico:

~~~text
frame RAW
  -> localizar/projetar filtro preto
  -> recortar somente a ROI do filtro
  -> detectar emissão luminosa
  -> encaixar landmarks ON esperados
  -> atualizar pose corrente
  -> reprojetar as 28 máscaras
  -> F3CheckAnalyzerAuthority classifica ON/OFF/POUCA LUZ
~~~

Segmentos apagados não participam da aquisição da pose. Um segmento ON ausente
ou uma emissão extra pode permanecer como outlier durante o encaixe; a
conformidade continua pertencendo ao analyzer, não ao tracker. O refinamento
não cria nova autoridade, scheduler ou worker.
## 14. Direção canônica do Display F3 — Neural Vision / Edge AI

A partir da D-059, a arquitetura alvo do julgamento visual do Display F3 deixa
de crescer por regras ópticas convencionais e passa a migrar, CHECK por CHECK,
para uma autoridade neural local.

O objetivo não é adicionar uma CNN à cadeia existente. O objetivo é substituir
a autoridade visual do CHECK migrado.

### Fluxo alvo

```text
Camera Service / Latest Frame
  ↓
configuração do Projeto Display
  ├─ CHECK atual
  ├─ imagem de referência
  ├─ contorno
  ├─ geometrias MASK_xxx
  └─ mask_states esperados
  ↓
normalização/alinhamento
  ↓
F3NeuralSegmentDetector
  ↓
NeuralSegmentObservation[28]
  ├─ mask_id
  ├─ state = on/off/uncertain
  └─ confidence
  ↓
F3CheckEvaluator
  ↓
CheckDecision = OK / NG / UNCERTAIN
  ↓
F3StateMachineAuthority
  ↓
DisplayCheckSequenceRuntime
```

### Responsabilidades

| Responsabilidade | Proprietário alvo |
| --- | --- |
| captura/frame atual | serviços já canônicos de câmera/latest-frame |
| configuração de referência | Display Project Repository |
| geometria/pose | infraestrutura canônica de geometria/tracking |
| estado visual ON/OFF | `F3NeuralSegmentDetector` |
| comparação esperado x observado | `F3CheckEvaluator` |
| sequência de CHECKS | `F3StateMachineAuthority` / `DisplayCheckSequenceRuntime` |
| apresentação | UI/ViewModel, sem segunda decisão |
| debug | observador, sem poder produtivo |

O detector neural não controla a sequência. A state machine não reclassifica
pixels. O evaluator não executa tracking.

### Configuração como anotação inicial

As imagens e geometrias já salvas no F3 são ativos de treinamento e contexto,
não resíduos do classificador antigo:

- a imagem do CHECK representa uma condição visual de referência;
- o contorno delimita a região útil e auxilia normalização/alinhamento;
- as geometrias locais identificam onde cada `MASK_xxx` aparece naquela foto;
- `mask_states` fornece o rótulo esperado de cada segmento;
- a geometria canônica de **Placa + Máscaras** continua representando o espaço
  produtivo live.

Não há requisito arquitetural de classificação manual pelo operador durante a
produção para a primeira versão neural.

### Migração incremental

A ordem de implementação é deliberadamente estreita:

```text
ETAPA N1: H1 neural
  ↓ validação física + OK do usuário
ETAPA N2: BLUE neural
  ↓ validação física + OK do usuário
ETAPA N3: USB neural
  ↓ validação física + OK do usuário
ETAPA N4: AUX neural
```

Durante N1, os CHECKS ainda não migrados podem continuar usando o caminho atual
somente como compatibilidade temporária. Não se deve criar uma segunda
autoridade neural/convencional para o H1.

### Performance e implantação

O alvo operacional é inferência local, gratuita e CPU-first. O caminho
preferencial é treinamento offline e artefato ONNX em produção.

O hot path precisa preservar:

- UI Tkinter não bloqueada;
- latest-frame-wins;
- nenhuma fila ilimitada;
- nenhum novo scheduler periódico concorrente;
- reutilização do executor pesado/coordenador F3 existentes quando apropriado;
- modelo carregado uma vez e reutilizado;
- preprocessamento e buffers reutilizáveis sempre que possível;
- benchmark de latência no hardware real antes de ampliar para outros CHECKS.

A escolha final do backbone neural é consequência de benchmark, não decisão
arquitetural antecipada.

### Implementação incremental atual — N1.2

No primeiro CHECK da ordem do Projeto Display, o proprietário semântico é
`F3H1NeuralAnalyzer`, que usa `F3NeuralSegmentDetector`. O detector carrega
um artefato ONNX por projeto com `cv2.dnn.readNetFromONNX`, mantém a rede em
cache e executa todas as máscaras ativas em um único batch NCHW. Nenhuma
dependência de treinamento entra no hot path produtivo.

Quando tracking está ligado, `F3TrackedRawCheckAnalyzer` continua entregando
frame RAW + máscaras projetadas do mesmo snapshot, porém a reconciliação
luminosa convencional não pode alterar a classificação do H1 neural. Para os
CHECKS ainda não migrados, o mesmo wrapper delega ao analisador convencional.

Modelo ou metadados ausentes/incompatíveis deixam o H1 indisponível. Não existe
fallback convencional para a semântica ON/OFF do primeiro CHECK enquanto N1
estiver ativo.



### Treino, calibração e promoção do artefato — N1.3/N1.4

O treino permanece completamente fora do runtime produtivo. O fluxo canônico é:

```text
configuração/fotos locais dos CHECKS
  ↓
preflight sem PyTorch
  ↓
primeiro CHECK reservado integralmente para validação
  ↓
demais CHECKS alimentam treino ON/OFF por segmento
  ↓
TinyF3SegmentCNN
  ↓
exportação ONNX candidata
  ↓
validação 100% do primeiro CHECK original
  ↓
H1 reservado + variações determinísticas de calibração
  ↓
inferência PyTorch + OpenCV DNN nas mesmas amostras
  ↓
exigir max P(ON) dos OFF < min P(ON) dos ON
  ↓
extremos validados delimitam OFF / INCERTO / ON
  ↓
SHA-256 + metadados schema 3
  ↓
promoção atômica do artefato
```

A separação por CHECK evita vazamento de validação entre recortes provenientes
da mesma fotografia. No N1, o primeiro CHECK da ordem configurada continua
**fora da otimização do modelo**. Ele é usado como validação independente e,
depois, como conjunto de calibração junto de variações determinísticas do mesmo
preprocessamento/augmentation já conhecido pelo pipeline. Essas variações não
ensinam H1 ao otimizador; servem para verificar se a saída probabilística ainda
separa ON de OFF sob pequenas mudanças de brilho, contraste, deslocamento,
blur/ruído e reflexo sintético em OFF.

Os thresholds produtivos não são mais números fixos `0.20/0.80`. O artefato só
é promovido quando existe um gap empírico positivo entre as duas classes de
calibração. O maior `P(ON)` observado entre OFF e o menor `P(ON)` observado
entre ON formam as bordas da faixa `INCERTO`. Se as distribuições se sobrepõem,
o treino falha antes da promoção e o artefato produtivo anterior permanece
intacto.

O runtime aceita somente artefato que declare:

- `schema_version=3`;
- projeto exatamente correspondente ao projeto ativo;
- mapa de classes `off=0`, `on=1`;
- `split.strategy=hold_out_first_check_for_n1`;
- `validation_check_id` igual ao primeiro CHECK atual do projeto;
- `validation.accepted_for_physical_h1_retest=true`;
- `threshold_calibration.source=held_out_h1_augmented_probability_gap`;
- calibração separável, com exemplos ON/OFF, contagens coerentes e gap positivo;
- thresholds gravados coerentes com os extremos efetivamente calibrados;
- `onnx_sha256` correspondente ao arquivo ONNX local.

Artefato schema 2, metadata sem calibração ou calibração inconsistente falham
fechado. Não há fallback para `0.20/0.80` e não se corrige o JSON manualmente:
o modelo precisa ser regenerado pelo pipeline de treino. O modelo rejeitado
nunca é promovido ao caminho produtivo.

Na apresentação neural, `matched=None` / `uncertain` também não pode ser
contado como máscara conforme. INCERTO permanece neutro para NG, mas reduz a
contagem de conformidade e deve aparecer explicitamente como
`INDETERMINADO`.
