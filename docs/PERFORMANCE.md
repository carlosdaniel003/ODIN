# Regras de Desempenho e Runtime em Tempo Real

## 1. Princípio central

**Tkinter nunca deve esperar visão computacional pesada.**

Responsividade da interface é requisito funcional do ODIN.

Um algoritmo correto que bloqueia cliques, mouse, repaint ou fechamento da janela não está pronto para produção.

## 2. Thread principal do Tkinter

O main thread é reservado para:

- eventos;
- teclado/mouse;
- criação de widgets;
- atualização de widgets;
- criação/uso de objetos Tk como `PhotoImage`;
- apresentação de resultados já preparados.

Não executar diretamente no event loop:

- ORB/AKAZE pesado;
- loops por muitas referências;
- auditoria completa de todos os CHECKS;
- leituras repetidas de disco;
- processamento OpenCV Full HD repetitivo;
- cálculos que podem exceder o orçamento de interação.

## 3. Captura da câmera

A captura deve permanecer desacoplada da UI.

O serviço de câmera publica o último frame válido e metadados.

A UI e a análise consomem snapshots; não devem controlar o loop interno de captura frame a frame.

## 4. Latest-frame-wins

Para inspeção ao vivo não manter fila histórica de frames esperando processamento.

Exemplo:

~~~text
analisando frame 101

câmera produz 102
câmera produz 103
câmera produz 104
câmera produz 105

termina 101
próximo = 105
~~~

Invariantes desejadas:

~~~text
analysis_in_flight = 0 ou 1
pending_frame      = 0 ou 1
pending_frame      = sempre o mais recente
~~~

Frames intermediários descartados por backpressure são comportamento esperado, não erro.

## 5. Executor pesado

O F3 deve convergir para um proprietário central de trabalho pesado.

Regra desejada:

~~~text
heavy vision jobs ativos <= 1
~~~

Prioridades conceituais:

~~~text
ALTA    análise operacional
NORMAL  análise manual do CHECK atual
BAIXA   thumbnails, previews e debug completo
~~~

Trabalho de baixa prioridade não deve competir com inspeção produtiva.

### Estado implementado

O executor canônico atual é `F3HeavyVisionExecutor` e mantém:

~~~text
max_workers = 1
max_pending = 8
~~~

Uso atual:

~~~text
NORMAL  análise manual do CHECK atual
LOW     configuração / thumbnails / DEBUG completo
HIGH    reservado para análise operacional da Etapa 4
~~~

Quando a fila está cheia, um job de prioridade maior pode substituir trabalho
pendente de prioridade inferior. Previews com a mesma chave usam substituição
latest-wins em vez de acumular backlog.

## 6. Scheduler

O F3 deve convergir para exatamente um scheduler periódico proprietário.

O scheduler decide:

- render devido?
- tracking devido?
- análise de CHECK devida?
- existe análise em andamento?
- há frame novo?
- configuração está aberta?
- há resultado para publicar?
- runtime está em rearme/resultado?

Evite arquitetura:

~~~text
after original
 ↓
wrapper
 ↓
cancel
 ↓
reschedule
 ↓
wrapper
 ↓
cancel
 ↓
reschedule
~~~

O objetivo é um coordenador que agenda o próximo ciclo conscientemente.

## 7. Proibição de busy loop

Não usar:

~~~python
while True:
    ...
~~~

sem condição de parada e espera bloqueante/controlada.

Workers devem preferir:

- `Event`;
- `Condition`;
- fila limitada;
- waits;
- executor.

Polling rápido sem necessidade é proibido.

## 8. Não reprocessar o mesmo frame

Operações caras devem possuir token/frame ID quando aplicável.

Se o frame já foi processado para a mesma finalidade e nenhum estado relevante mudou, não repita a análise.

## 9. I/O e referências

No hot path:

- evitar `cv2.imread` repetido para a mesma referência;
- evitar reler JSON a cada frame;
- evitar recodificar PNG/base64 sem necessidade;
- evitar `deepcopy` de grandes estruturas quando basta snapshot mínimo;
- recortar ROI antes de reduzir/copiar Full HD quando possível.

Caches precisam seguir as regras de invalidação de `docs/ENGINEERING_RULES.md`.

## 10. Configuração e previews

Abrir **CONFIGURAR** deve tornar a janela visível antes de trabalho pesado.

Primeiro paint deve priorizar:

- shell da janela;
- header;
- layout;
- placeholders;
- botões.

Depois podem ser carregados:

- projeto;
- painéis secundários;
- referências;
- thumbnails.

Processamento OpenCV de preview deve ocorrer fora do Tk quando pesado.

O worker pode produzir um array/imagem preparada; a criação de `PhotoImage` e atualização do widget ocorre no thread Tk.

### Resize

Não ligar processamento pesado diretamente a cada evento `<Configure>`.

Resize deve preferir:

~~~text
novo tamanho
 ↓
debounce/coalescing
 ↓
reusar cache/thumbnail
 ↓
render necessário
~~~

Mover o mouse sobre a aplicação nunca deve iniciar trabalho de visão sem relação direta com a interação.

## 11. Analisar x Debug

A ação operacional **ANALISAR** deve ser barata em termos de preparação no Tk e trabalhar somente com o necessário para a análise solicitada.

Diagnóstico completo de engenharia deve ser executado sob demanda pelo fluxo de **DEBUG TÉCNICO**.

Debug não deve impor seu custo ao caminho produtivo quando está desligado.

## 12. Snapshots mínimos

Quando a UI envia trabalho para um worker, prefira envelope pequeno e explícito:

~~~text
AnalysisRequest
- frame / referência imutável apropriada
- frame_id
- timestamp
- project_id
- check_id
- rotation
- state_version
~~~

Não copie "todo o estado do F3" antes de cada operação apenas por precaução.

## 13. Metas de aceitação

As métricas abaixo são metas arquiteturais, não afirmação de desempenho medido atual.

| Métrica | Meta |
| --- | ---: |
| resposta normal a clique/hover durante F3 | < 50 ms |
| callback Tk steady-state p95 | 16–25 ms |
| callback Tk excepcional | preferencialmente < 100 ms |
| CONFIGURAR -> shell visível | < 150 ms |
| ANALISAR -> feedback visual/desabilitação | < 50 ms |
| análises pesadas simultâneas | máximo 1 |
| schedulers periódicos F3 | exatamente 1 |
| frames pendentes para análise | máximo 1 |
| fila histórica de frames | 0 |
| threads que manipulam widgets Tk | somente main thread |

O resultado final de uma análise pode levar mais que 50 ms. O que precisa responder imediatamente é a interface.

## 14. Métricas recomendadas

O runtime deve permitir medir quando necessário:

- FPS real da câmera;
- FPS/taxa de análise;
- frame ID capturado;
- frame ID analisado;
- frames descartados;
- duração de tracking;
- duração de presença;
- duração de energia;
- duração do check analyzer;
- duração total de análise;
- callback Tk p50/p95/max;
- quantidade de `after()` relevantes;
- heavy jobs ativos;
- threads vivas;
- tamanho de filas;
- tempo CONFIGURAR -> primeiro paint;
- tempo ANALISAR -> feedback;
- tempo do debug completo.

## 15. Otimização correta

Não otimizar apenas por intuição.

Fluxo:

~~~text
medir
 ↓
identificar hot path
 ↓
alterar uma causa
 ↓
medir novamente
 ↓
comparar
~~~

Não adicionar uma camada de "performance fix" se o gargalo pode ser removido no proprietário canônico.
