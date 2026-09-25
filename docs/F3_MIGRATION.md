# Plano de Modernização do F3

## Objetivo

Reduzir bloqueios do Tkinter, eliminar sobreposição de autoridades e transformar o F3 em um runtime previsível sem reescrita total.

Este documento define **ordem arquitetural**, não autoriza avançar etapas automaticamente.

O usuário continua sendo o gate: cada etapa deve ser concluída, testada e validada antes da próxima.

## Sequência

| Etapa | Objetivo |
| --- | --- |
| 1 | consolidar arquitetura de CONFIGURAR |
| 2 | separar ANALISAR de DEBUG COMPLETO |
| 3 | criar executor pesado único |
| 4 | criar F3RuntimeCoordinator + scheduler único |
| 5 | consolidar autoridades de tracking/presença/energia/análise |
| 6 | migrar composição Raspberry legada para Desktop Windows/Linux |
| 7 | remover resíduos, patches mortos e aliases comprovadamente substituídos |

O estado real de cada etapa deve ser confirmado na branch e na conversa atual. Não deduza status apenas deste documento.

## Etapa 1 — Configurar

Objetivo:

- primeiro paint rápido;
- UI incremental;
- previews pesadas fora do Tk;
- nenhuma renderização OpenCV pesada diretamente em `<Configure>`;
- cache/debounce explícitos;
- um fluxo canônico de construção da configuração.

Não criar outro `config_performance_fix` para compensar a arquitetura.

## Etapa 2 — Analisar x Debug

Separar responsabilidades:

~~~text
ANALISAR
  ↓
frame congelado
  ↓
CHECK atual
  ↓
resultado operacional/visual
~~~

~~~text
DEBUG TÉCNICO
  ↓
mesmo snapshot congelado
  ↓
diagnóstico completo sob demanda
  ↓
todos os CHECKS / referências / tracking / energia / presença / telemetria
~~~

O botão ANALISAR não deve pagar automaticamente o custo de uma auditoria forense completa.

## Etapa 3 — Executor pesado único

Criar um serviço canônico para trabalho pesado.

Características:

- concorrência limitada;
- prioridade;
- lifecycle;
- cancelamento;
- nenhum acesso direto a widgets;
- nenhuma fila ilimitada.

Nenhum módulo deve criar thread pesada arbitrariamente depois dessa consolidação sem passar pelo executor.

### Implementação consolidada da Etapa 3

O proprietário canônico é `F3HeavyVisionExecutor`.

Já passam pelo executor:

~~~text
NORMAL  ANALISAR / CHECK atual
LOW     DEBUG TÉCNICO completo
LOW     previews de configuração
LOW     previews das referências angulares de tracking
~~~

O executor mantém um único worker, fila limitada, prioridade, cancelamento por
proprietário e substituição de jobs pendentes de preview.

A análise operacional ao vivo ainda permanece no caminho histórico nesta etapa.
Ela não deve ser simplesmente movida para uma thread porque o callback atual
também altera estado produtivo e apresentação. A Etapa 4 passa a controlar
quando esse pipeline pode executar; a extração de compute puro para `HIGH`
depende da consolidação das autoridades stateful na Etapa 5.

## Etapa 4 — F3RuntimeCoordinator

Criar proprietário único do scheduling do F3.

Responsabilidades:

- cadence;
- frame novo;
- render;
- tracking;
- análise;
- estado de configuração;
- resultado;
- rearme;
- backpressure.

Meta estrutural:

~~~text
1 scheduler periódico F3
~~~

O coordinator não deve virar God Object: ele orquestra serviços, não implementa os algoritmos internos deles.

### Implementação consolidada da Etapa 4

O proprietário canônico é `F3RuntimeCoordinator`.

Fluxo atual:

~~~text
root.after
   ↓
F3RuntimeCoordinator
   ├── CONFIGURAR aberto → repaint leve / cadência de fundo
   ├── frame repetido → repaint leve
   ├── análise ainda não devida → repaint leve
   ├── tracking pendente → conclui a segunda metade do pipeline
   ├── rearme + frame novo → ciclo completo
   └── análise/tracking devido + frame novo → ciclo completo legado
~~~

Invariantes implementadas:

- um único timer periódico do F3 no runtime de produto;
- nenhum backlog histórico de frames;
- frame repetido não dispara novamente o pipeline completo;
- backpressure quando o executor pesado está ocupado;
- lifecycle start/stop/shutdown;
- métricas do scheduler disponíveis no runtime;
- cadência adaptativa histórica e wrapper final de responsividade deixam de ser
  autoridades de scheduling.

O pipeline completo ainda é chamado no thread Tk quando necessário porque hoje
ele contém, no mesmo encadeamento, compute de visão, autoridades stateful e
publicação de UI. Movê-lo inteiro para o executor violaria a regra de Tk e criaria
races de state machine. A Etapa 5 deve separar essas autoridades em serviços
antes de enviar compute operacional puro à prioridade `HIGH`.

## Etapa 5 — Consolidar autoridades

Migrar uma responsabilidade por vez:

1. tracking;
2. presença;
3. energia;
4. check analyzer;
5. state machine/apresentação derivada.

Para cada uma:

~~~text
capturar comportamento em testes
 ↓
criar/eleger autoridade canônica
 ↓
migrar consumidores
 ↓
validar
 ↓
desligar implementação histórica
 ↓
remover resíduo
~~~

Nunca manter permanentemente duas autoridades.

## Etapa 6 — Desktop Windows/Linux

Introduzir composição conceitual de desktop.

Direção:

~~~text
DesktopProductionApp
├── Windows adapters
└── Linux adapters
~~~

Classes Raspberry permanecem somente como compatibilidade temporária até seus consumidores serem migrados.

Não executar rename em massa antes da migração funcional.

## Etapa 7 — Limpeza de resíduos

Somente depois de testes comprovarem substituição:

- remover imports mortos;
- remover wrappers não usados;
- remover instaladores redundantes;
- remover aliases temporários;
- remover módulos fix/compat sem consumidores;
- remover timers antigos;
- remover estados duplicados;
- remover classes Raspberry não utilizadas.

## Critérios globais

Ao final da modernização:

~~~text
Tkinter
  ↓
ViewModel
  ↓
F3RuntimeCoordinator
  ├── LatestFrame
  ├── TrackingService
  ├── PresenceService
  ├── PowerService
  ├── CheckAnalyzer
  ├── StateMachine
  └── HeavyVisionExecutor
~~~

Invariantes:

- Tkinter nunca espera visão pesada;
- um scheduler F3;
- um heavy job ativo no máximo;
- um frame pendente no máximo;
- fila histórica de frames igual a zero;
- debug fora do caminho crítico;
- F2 e F3 isolados;
- nenhuma nova cadeia permanente de patches.
