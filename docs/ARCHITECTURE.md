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

Raspberry Pi é legado arquitetural. O código atual ainda possui nomes e classes herdados dessa fase, mas a direção oficial é desktop Windows/Linux.

A migração deve ser incremental e protegida por testes. Não realizar rename/removal em massa apenas para eliminar nomes antigos.

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

- previews da configuração;
- previews das referências angulares de tracking;
- análise manual do CHECK atual;
- auditoria do DEBUG TÉCNICO.

A prioridade `HIGH` está reservada para a análise operacional. A conexão do hot
path produtivo ao executor pertence à Etapa 4, junto do `F3RuntimeCoordinator`,
para não mover callbacks stateful do runtime para background de forma insegura.

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
| tracking | Tracking Service |
| presença | Presence Service |
| energia | Power Service |
| análise de CHECK | Check Analyzer |
| sequência | State Machine |
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
