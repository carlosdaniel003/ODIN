# F3 — Registro de validação física

Este arquivo é o diário cronológico dos testes físicos do **Display F3**.

## Regra de manutenção

- Não apagar nem reescrever silenciosamente um resultado antigo.
- Registrar tanto **PASS** quanto **FAIL**.
- Registrar o comportamento observado no equipamento, a evidência do DEBUG,
  a causa identificada, a alteração realizada e o que ainda depende de reteste.
- Quando uma correção ainda não foi validada fisicamente, marcar explicitamente
  como **PENDENTE DE RETESTE**.
- Decisões arquiteturais continuam em `docs/DECISIONS.md`; este arquivo preserva
  a sequência factual dos testes.
- O log começa em 29/09/2026. Investigações anteriores continuam preservadas em
  `docs/DECISIONS.md`.

---

## 29/09/2026 — H1 / alinhamento por núcleo luminoso

**Resultado físico:** PASS observado no fluxo subsequente.

### Contexto

A rodada anterior mostrou que uma pose já visualmente correta podia ser rejeitada
por `fine_gain_insufficient`. A D-026 passou a permitir que o próprio núcleo
luminoso dos segmentos ON confirme uma pose já correta sem exigir movimento
geométrico artificial.

### Evidência operacional

Na execução que posteriormente chegou a USB, o H1 aparece como **CONCLUÍDO**.
O fluxo conseguiu avançar H1 -> BLUE -> USB.

### Estado

**PASS** para a progressão observada nesta montagem.

---

## 29/09/2026 — BLUE intermitente / snapshot ON

**Mudança relacionada:** D-027.

**Resultado físico:** PASS.

### Problema anterior

BLUE fica aproximadamente um intervalo aceso e outro apagado. O worker podia
capturar a fase ON, mas terminar quando a câmera já estava na fase OFF; o
resultado correto era descartado por frescor de frame.

### Alteração aplicada

Foi criada uma janela curta para preservar um snapshot positivo do mesmo
`project_name + check_id` quando `intermittent=true`. A câmera visível continua
latest-frame-wins; somente a evidência temporal do CHECK é preservada.

### Validação

Após a alteração, BLUE foi concluído automaticamente e a sequência avançou para
USB.

### Estado

**PASS**.

---

## 29/09/2026 — USB aceso corretamente, mas gate permaneceu bloqueado

**Resultado físico antes da correção:** FAIL.

### Sintoma

- H1: CONCLUÍDO.
- BLUE: CONCLUÍDO.
- USB: fisicamente aceso com o padrão esperado.
- UI permaneceu em `AGUARDANDO USB`.
- status superior: `PLACA NO SUPORTE • LIGADA • ALINHANDO USB`.
- máscaras visuais já mostravam segmentos luminosos identificados.

### Evidência do DEBUG

No mesmo cenário:

- CHECK lógico: `CHECK_004 / USB`;
- USB não é intermitente;
- energia física: **CONFIRMADA**;
- máscaras live: **15 ON / 11 OFF**;
- análise bruta do USB: **28/28**, `approved=true`;
- tracking luminoso:
  - frame 942;
  - `source_type=luminous_segment_grid`;
  - `evidence_current=true`;
  - 15/15 IDs ON encontrados;
  - `alignment_ready=true`;
  - modo `base_core_verified`;
- autoridade de energia em frame posterior:
  - frame 949;
  - `powered_confirmed=true`;
  - `spatial_alignment_ready=false`;
  - `spatial_alignment_source=structural_only`;
  - gate bloqueado por
    `energia_confirmada_aguardando_alinhamento_segmentos`;
- a análise semântica correta ficou
  `blocked_by_power_gate=true`.

### Causa

Existe latência normal entre os jobs HIGH de tracking e o frame live usado pela
autoridade de energia. O tracker canônico já possuía um lock luminoso atual e
válido do USB, mas o gate de energia exigia que o estado espacial do frame de
energia também já tivesse sido publicado como luminoso. Assim, duas evidências
válidas e próximas no tempo não eram reconciliadas:

~~~text
tracking frame 942
USB 15/15 alinhado
        +
energia frame 949
display ligado
        ↓
gate ainda usava spatial_alignment_ready=false
        ↓
28/28 correto ficava sem autoridade
~~~

### Correção D-028

O `F3PowerAuthority` passa a receber explicitamente a evidência do proprietário
canônico de tracking e pode reconciliar o gate espacial quando TODAS as condições
abaixo forem verdadeiras:

1. placa presente;
2. energia do frame live realmente confirmada;
3. alinhamento é requerido e a evidência de energia ainda o marca como não pronto;
4. tracking está `locked=true`;
5. `evidence_current=true`;
6. `source_type=luminous_segment_grid`;
7. referência é exatamente `luminous:<CHECK atual>`;
8. existem IDs luminosos validados;
9. idade do lock não excede o limite operacional do tracking;
10. diferença de frames não excede o limite operacional do tracking.

Não existe liberação por lock estrutural, lock mantido/stale, outro CHECK,
outro projeto ou evidência luminosa antiga.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

Implementação principal: commit `2fca6b695542b325eb67d6bfb3d7b6d10feefa31`.

### Validação automatizada desta correção

- compilação dos módulos F3: PASS;
- regressões luminosas focadas: **30 testes PASS**;
- novos testes D-028:
  - `test_usb_power_gate_aceita_lock_luminoso_atual_do_mesmo_check`: PASS;
  - `test_lock_luminoso_stale_ou_de_outro_check_nao_libera_gate`: PASS;
- workflow `Display F3 fast H1 BLUE tests`: PASS;
- workflow `Display F3 cycle rearm tests`: PASS;
- a suíte ampla de object tracking continua com **8 failures + 1 error** nos
  mesmos testes históricos já presentes antes desta alteração. A etapa focada
  da D-028 passa antes desse bloco agregado.

O reteste esperado é:

~~~text
H1 conclui
→ BLUE conclui
→ USB acende corretamente
→ tracking confirma USB luminoso
→ energia confirma display ligado
→ gate fica liberado
→ analyzer 28/28 possui autoridade
→ USB conclui e avança para AUX
~~~

---

## 29/09/2026 — Sincronia visual câmera x máscaras x visor e demora no IDENTIFICANDO

**Resultado físico antes da correção:** FAIL de experiência operacional.

### Sintoma observado

- os segmentos reais do display mudavam primeiro na câmera ao vivo;
- as máscaras verdes sobre a câmera reagiam depois;
- o `VISOR DO DISPLAY` também reagia depois;
- no BLUE intermitente, a defasagem entre a fase física e as representações da
  interface deixava a tela visualmente desconcertante;
- ao abrir o F3, a aquisição inicial permanecia tempo demais em
  `IDENTIFICANDO...`.

### Causa identificada no código

As duas representações visuais usavam resultados assíncronos do
tracking/analyzer, enquanto a imagem da câmera já era latest-frame-wins. Portanto
não existia garantia de que câmera, máscara verde e visor representassem o mesmo
frame.

Na inicialização, o banco de referências também calculava AKAZE
preventivamente para todas as fotos, apesar de AKAZE ser fallback de
reacquisition. Além disso, o coordinator podia deixar o primeiro tracking HIGH
esperando um executor ocupado por trabalho já existente.

### Correção D-029

- uma amostra luminosa **somente visual** é calculada sobre o mesmo frame reduzido
  que será desenhado na câmera;
- a amostra é compartilhada entre overlay e visor no mesmo repaint;
- repaints do mesmo frame reutilizam cache;
- nenhum timer, thread ou worker novo foi criado;
- a amostra não participa de OK/NG ou de qualquer autoridade produtiva;
- AKAZE das referências passou a ser lazy e cacheado somente quando necessário;
- o primeiro tracking HIGH recebe prioridade de enfileiramento para reduzir o
  tempo de `IDENTIFICANDO...`.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

Implementação principal: commit `ba627170e5da3629f27ec564ebd675547fdd035e`.

Ajuste final de renderização: commit
`979cb1fa0de5f78df9171ff0d2ae23ea6edbd5ef`, que evita reconstruir o conjunto
de IDs luminosos dentro de cada um dos 28 segmentos do visor e reforça o teste
de contrato do espelho visual.

### Validação automatizada desta correção

- compilação dos módulos F3: PASS;
- regressões luminosas focadas anteriores: **30 testes PASS**;
- novo bloco `live visual sync and startup performance regressions`:
  **8/8 testes PASS**;
- contratos validados:
  - frame ON detecta somente as ROIs luminosas;
  - frame totalmente escuro limpa imediatamente o espelho visual;
  - repaint do mesmo frame reutiliza cache;
  - câmera e visor consomem a mesma amostra latest-frame;
  - AKAZE das referências é lazy;
  - primeiro tracking HIGH pode entrar antes de trabalho de menor prioridade;
  - backpressure volta a valer após o primeiro future;
- `Display F3 fast H1 BLUE tests`: PASS;
- `Display F3 cycle rearm tests`: PASS;
- a suíte ampla de object tracking continua com **7 failures + 1 error** em
  regressões históricas já existentes fora desta alteração. O antigo teste que
  exigia AKAZE eager foi atualizado para o contrato lazy e agora passa.

### Reteste esperado

~~~text
abrir F3
→ aquisição inicial/LOCK ocorre mais cedo

BLUE acende
→ no mesmo repaint:
   câmera física mostra ON
   máscaras correspondentes ficam verdes
   VISOR mostra os mesmos segmentos verdes

BLUE apaga
→ no mesmo repaint:
   câmera física mostra OFF
   máscaras verdes apagam
   VISOR apaga os mesmos segmentos

sem backlog visual
sem queda perceptível de responsividade
sem alterar a regra produtiva de OK/NG
~~~

---

## 29/09/2026 — Reteste D-029 / runtime preso em IDENTIFICANDO

**Resultado físico:** FAIL.

### Sintoma observado

Após a correção de sincronia visual D-029, o Display F3 abriu normalmente, mas
permaneceu indefinidamente em `IDENTIFICANDO...` no H1. A câmera continuava ao
vivo e o operador conseguia acionar ANALISAR, porém o runtime produtivo não
publicava um novo lock de tracking nem liberava a sequência.

### Evidência objetiva do DEBUG

No clique analisado:

- câmera ao vivo: frame 811, com fluxo ativo em aproximadamente 15 FPS;
- último estado publicado de object tracking: frame 36;
- tracking: `locked=false`, `reason=object_not_locked`,
  `evidence_current=false`;
- energia produtiva: indisponível por `object_not_locked`;
- `last_auto_analysis=null`;
- CHECK atual permaneceu H1 e nenhum CHECK foi concluído.

A diferença extrema entre o frame atual da câmera e o frame ainda publicado pelo
tracking confirmou que o problema não era falta de atualização da câmera.

### Causa identificada

A otimização de aquisição inicial de D-029 introduziu um deadlock de publicação
no `F3RuntimeCoordinator`:

~~~text
primeiro full_cycle
  -> submete tracking HIGH
  -> _display_f3_tracking_future != None
  -> worker termina
  -> executor deixa de estar busy
  -> Future continua armazenado até o full_cycle consumi-lo

_choose_path()
  -> initial_lock_needed = True
  -> Future existe
  -> executor não está busy
  -> tracking_initial_lock_in_flight
  -> render_only
  -> nunca chama o consumidor do Future
  -> _display_f3_tracking_result continua None
  -> IDENTIFICANDO para sempre
~~~

O coordinator distinguia apenas `Future is None` de `Future existe`; não
distinguia um Future ainda em execução de um Future já concluído.

### Correção aplicada

O coordinator passa a verificar resultados assíncronos concluídos antes de:

- coalescer frame repetido;
- aplicar backpressure do executor;
- tratar o primeiro lock como ainda em voo.

Um Future concluído de tracking ou classificação semântica força exatamente um
`full_cycle` para que o consumidor canônico publique o resultado no thread Tk.
Nenhum novo scheduler, thread, worker ou fila foi criado.

A política de desempenho permanece:

~~~text
worker em voo -> render_only / backpressure
worker concluído -> full_cycle curto para drenar/publicar
próximo trabalho pesado -> continua no executor único
~~~

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Validação automatizada adicionada

- Future de tracking inicial concluído precisa ser drenado antes do backpressure;
- Future semântico concluído precisa ser drenado mesmo quando o frame visual se
  repete;
- o teste existente de tracking ainda em voo continua exigindo
  `render_only`/backpressure.

### Reteste esperado

~~~text
abrir F3
-> primeiro tracking HIGH é submetido
-> worker termina
-> coordinator drena o resultado concluído
-> tracking passa a acompanhar frames atuais
-> IDENTIFICANDO deixa de ficar preso

com LOCK válido:
-> câmera, máscaras verdes e VISOR usam a mesma amostra visual latest-frame
-> sem backlog visual
-> sem alterar OK/NG, energia ou sequência
~~~

---

## 29/09/2026 — Reteste do deadlock de publicação D-029

**Resultado físico:** PASS.

### Cenário

Foi repetida a abertura do Display F3 após a correção que passou a drenar
`Future` de tracking/semântica concluído antes do backpressure do coordinator.

### Resultado observado

O runtime deixou de permanecer indefinidamente em `IDENTIFICANDO...`.
O fluxo voltou a avançar normalmente.

### Estado

**PASS.**

A falha anterior permanece registrada acima como histórico; este reteste confirma
a correção do deadlock de publicação.

---

## 29/09/2026 — Troca de placa em nova posição e latência de aquisição

**Resultado físico antes desta alteração:** FAIL de desempenho / requisito de
reaquisição confirmado.

### Cenário

Depois de a placa terminar a inspeção e receber o resultado, ela é retirada do
suporte. A placa seguinte pode entrar em outra posição física.

O comportamento requerido é:

~~~text
placa A termina
→ placa A sai
→ suporte vazio confirmado
→ placa B entra em outra posição
→ ODIN procura novamente a placa
→ nenhuma pose da placa A é reutilizada
~~~

Também foi observado que o início de uma aquisição ainda permanece tempo demais
em `IDENTIFICANDO...`.

### Causa identificada no código

O rearme canônico já invalidava tracking, porém usava o mesmo reset completo
destinado a mudanças de configuração. Isso apagava simultaneamente:

- pose/matriz da placa anterior, o que é correto;
- banco de referências estruturais já preparado, o que é desnecessário.

Na aquisição seguinte, `configure()` precisava novamente decodificar todas as
fotografias estruturais e calcular ORB do banco inteiro.

No primeiro ciclo da sessão ocorria custo semelhante: o banco inteiro era
materializado antes de o tracker saber se H1 atual ou `board_off` já eram
suficientes para localizar a placa.

### Alteração aplicada

- foi separado reset completo de reset de ciclo;
- EMPTY agora invalida a pose corrente sem descartar a calibração/referências da
  sessão;
- a nova placa continua obrigatoriamente sem `last_matrix`, sem anchor angular,
  sem `last_result` e sem geometria live da placa anterior;
- referências passaram a ser materializadas sob demanda;
- aquisição inicial prioriza a referência do CHECK atual e `board_off`;
- as demais vistas continuam disponíveis como fallback;
- nenhum scheduler, thread ou worker adicional foi criado.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

~~~text
abrir F3
→ IDENTIFICANDO reduzido
→ novo LOCK

terminar placa A
→ retirar placa A
→ confirmar EMPTY
→ inserir placa B deslocada/rotacionada dentro da faixa permitida
→ pose antiga não aparece
→ ODIN procura novamente
→ obtém novo LOCK na posição da placa B
→ H1 segue normalmente
~~~

Além do tempo percebido, observar no DEBUG se o frame do tracking acompanha o
frame atual logo após a entrada da nova placa.

---

## 29/09/2026 — Reteste D-030 / nova placa em outra posição

**Resultado físico:** PASS.

### Cenário

Após concluir a placa anterior, ela foi retirada e uma nova placa entrou em outra
posição física. Também foi retestado o tempo de aquisição após a separação entre
pose efêmera e banco de referências da sessão.

### Resultado observado

- a placa seguinte foi procurada novamente;
- a pose da placa anterior não foi herdada;
- a nova posição foi adquirida corretamente;
- o fluxo voltou a funcionar após a otimização de IDENTIFICANDO....

### Estado

**PASS.**

---

## 29/09/2026 — SEGREGAR PLACA sem ação em transição de rearme

**Resultado físico antes da correção:** FAIL.

### Sintoma observado

O botão **SEGREGAR PLACA** podia não produzir ação.

### Causa identificada no código

A ação manual era bloqueada não apenas enquanto a placa anterior ainda aguardava
EMPTY, mas também durante waiting_new_board_after_empty. Nesse segundo estado,
a autoridade canônica de presença já podia ter confirmado fisicamente a nova
placa enquanto o debounce de rearme ainda não havia limpado a flag. O clique
virava um retorno silencioso.

Também foi confirmado que a extensão de nomenclatura SEGREGAR existia, mas não
era instalada explicitamente pela composição desktop canônica.

### Alteração aplicada

- waiting_empty continua bloqueando SEGREGAR para impedir dupla contagem;
- durante waiting_new_board, SEGREGAR é liberado somente quando
  board_presence_evidence confirma placa presente e não EMPTY;
- a composição desktop passa a instalar explicitamente a apresentação
  **SEGREGAR PLACA** antes de construir a janela F3;
- nenhuma regra ou contador do F2 é alterado.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

---

## 29/09/2026 — Segmento 24 fisicamente danificado foi aprovado

**Resultado físico antes da correção:** FAIL crítico de decisão.

### Cenário

O CHECK esperava o segmento 24 ACESO. O segmento estava fisicamente danificado e
não acendeu durante o teste. Mesmo assim, depois de algum tempo o CHECK foi
aprovado.

### Causa identificada no código

A conformidade estrita já existia e bloqueava OK quando qualquer máscara ativa
divergia. Entretanto, a composição final de tracking substituía o analyzer da
sessão por F3TrackedRawCheckAnalyzer, que internamente reconstruía
F3SameMaskReferenceAnalyzer simples.

Assim, a camada geométrica final podia rebaixar a autoridade semântica que deveria
continuar estrita. O mesmo wrapper permanecia publicado mesmo quando tracking
estava desligado.

### Correção D-031

- o analyzer final de tracking passa a usar F3StrictMaskConformityAnalyzer;
- a conformidade estrita agora aceita as ROIs móveis do tracking;
- tracking ligado e desligado passam pela mesma regra de conformidade;
- uma única máscara divergente impede OK;
- regressão explícita usa MASK_024 esperado ON, classificado OFF, com outro
  segmento ON: a política precisa retornar NG para MASK_024.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

~~~text
CHECK posterior energizado
→ demais segmentos esperados ON acendem
→ MASK_024 deveria estar ON, mas permanece fisicamente apagada
→ análise mantém MASK_024 como divergente
→ CHECK nunca recebe OK
→ após debounce normal de NG
→ placa é reprovada por MASK_024
→ frame/evidência NG permanece congelado até retirada
~~~

Repetir o mesmo teste com tracking habilitado e desabilitado para confirmar que a
autoridade semântica não muda com o modo de tracking.

---

## 30/09/2026 — Tracking ON / câmera, máscaras e visor não espelharam a mesma emissão

**Resultado físico antes da correção:** FAIL visual.

### Cenário

Modo **Rastreamento Automático do Display F3** ativo. Segmentos fisicamente
acesos eram visíveis na própria imagem da câmera, porém a máscara correspondente
e/ou o segmento equivalente do VISOR DO DISPLAY não reagiam em verde junto com
a emissão real.

### Requisito confirmado

A apresentação visual é independente dos gates produtivos:

~~~text
segmento físico aceso
→ máscara correspondente verde
→ segmento correspondente do visor verde
→ mesma atualização visual
~~~

Power gate, presença, spatial gate, H1, debounce e decisão OK/NG podem continuar
bloqueando a produção, mas não podem neutralizar esse espelho visual.

### Causa encontrada no código

D-029 já possuía amostra visual latest-frame, porém ainda existiam fallbacks
históricos que:

- condicionavam a apresentação ao estado de energia;
- permitiam ao visor usar classificação assíncrona;
- entravam em conflito com a intenção de fonte visual única;
- podiam perder maioria/todos os segmentos ON porque o threshold relativo subia
  junto com o baseline das máscaras.

### Correção D-032

- câmera/overlay e visor passam a consumir a mesma fonte visual;
- gate produtivo deixa de participar da cor do modo tracking;
- classificação semântica deixa de ser fallback do espelho visual;
- detector latest-frame cobre também maioria/todos ON por cluster gap + evidência
  absoluta forte;
- nenhum novo worker, thread, scheduler ou I/O foi adicionado.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

~~~text
tracking ON + LOCK
→ segmento acende fisicamente
→ máscara fica verde no mesmo repaint
→ visor fica verde no mesmo repaint

segmento apaga
→ máscara perde verde
→ visor perde verde

repetir com power gate bloqueado
→ a cor visual continua reagindo
→ OK/NG permanece bloqueado normalmente
~~~

---

## 30/09/2026 — Reteste D-032 / máscaras e visor continuam sem reagir

**Resultado físico:** FAIL.

### Sintoma observado

Após o commit D-032, o operador continua sem ver:

- as máscaras da câmera ao vivo reagirem/colorirem conforme os segmentos físicos;
- o VISOR DO DISPLAY acompanhar os segmentos físicos.

Portanto a alteração anterior não resolveu o caminho real de apresentação no
equipamento.

### Interpretação

Este é o segundo ciclo de correção do mesmo defeito visual sem validação física
positiva. Conforme a regra das duas tentativas do projeto, não será feita nova
mudança de algoritmo/threshold por hipótese.

A etapa atual passa a ser **diagnóstico instrumentado do caminho real**.

### Instrumentação adicionada

Foi adicionada telemetria leve, somente em memória, para identificar em qual
ponto o espelho visual D-032 deixa de funcionar:

- hook visual final ativo;
- tracking realmente habilitado;
- geometria presente/LOCK;
- quantidade de máscaras na geometria;
- contexto visual construído;
- quantidade de máscaras no contexto;
- amostra latest-frame pronta ou não;
- motivo da amostra;
- IDs visualmente luminosos;
- contexto do visor atualizado ou não;
- 28 slots do visor disponíveis ou não;
- IDs recebidos pelo visor;
- resultado do repaint;
- exceção e estágio exatos quando houver fallback silencioso.

Nenhum novo timer, thread, worker, scheduler, I/O ou processamento pesado foi
adicionado.

### Próximo teste

Com o defeito visível:

1. clicar em **ANALISAR**;
2. abrir **DEBUG TÉCNICO**;
3. usar **COPIAR DEBUG**;
4. enviar o bloco inteiro.

O relatório passa a conter:

~~~text
[ESPELHO VISUAL LIVE D-032 / CÂMERA + MÁSCARAS + VISOR]
~~~

Esse bloco permitirá distinguir objetivamente:

~~~text
tracking não está ativo
vs
não existe LOCK/geometria
vs
contexto visual não foi construído
vs
amostra não está lendo as 28 máscaras
vs
amostra produz 0 IDs
vs
visor não recebeu contexto
vs
renderer caiu no fallback por exceção
~~~

### Estado

**FAIL CONFIRMADO — DIAGNÓSTICO INSTRUMENTADO, AGUARDANDO EVIDÊNCIA DO EQUIPAMENTO.**

---

## 30/09/2026 — Clarificação do reteste D-032: tracking estava OFF

**Resultado físico observado:** FAIL visual.

### Clarificação

O operador informou que o cenário anterior em que:

- as máscaras da câmera estavam cinzas;
- o VISOR DO DISPLAY não mostrava os segmentos;

estava sendo executado com **Rastreamento Automático desativado**.

Portanto o diagnóstico anterior tratou o modo errado. A instrumentação colocada
no wrapper de tracking não poderia explicar esse cenário porque, com tracking
OFF, o runtime delegava para o renderer fixo.

### Causa confirmada no código

No caminho tracking OFF:

~~~text
tracked_window_update
→ tracking_enabled = false
→ previous_window_update
→ contexto fixo
→ live_luminous_only = false
→ sem amostra visual latest-frame
→ cor dependente de análise/power gate
→ máscaras cinzas / visor sem emissão
~~~

Além disso, o contexto fixo usava somente máscaras ativas do CHECK.

### Correção D-033

~~~text
tracking OFF
→ geometria fixa das máscaras
→ TODAS as máscaras disponíveis
→ amostra luminosa no frame atual
→ mesmos live_visual_mask_ids
   ├── overlay da câmera
   └── VISOR DO DISPLAY
→ mesmo repaint
~~~

A mudança não altera energia, OK/NG, debounce, sequência ou conformidade.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

Com tracking OFF:

1. abrir o F3;
2. manter a placa na posição cadastrada;
3. acender segmentos físicos;
4. confirmar que as máscaras correspondentes ficam verdes;
5. confirmar que o VISOR mostra exatamente os mesmos segmentos verdes;
6. apagar segmentos e confirmar que ambos perdem o verde juntos;
7. repetir mesmo enquanto power gate ainda não confirmou energia.

---

## 30/09/2026 — Screenshot: 15 ACESOS no analyzer e visor neutro

**Resultado físico:** FAIL visual confirmado.

### Evidência

No mesmo estado de tela:

~~~text
PLACA NO SUPORTE • LIGADA • ANALISANDO USB
19/28 CONFORMES • 15 ACESOS • 13 APAGADOS
ANÁLISE VISUAL: CHECK AUX • 93%
~~~

Apesar disso:

- as máscaras desenhadas sobre o display estavam neutras;
- o VISOR DO DISPLAY também estava totalmente neutro.

### Diagnóstico

A análise automática já havia identificado estados físicos para as máscaras.
Logo, o defeito estava na ligação entre essa evidência e a apresentação.

A diferença entre o CHECK lógico e o CHECK da análise recente confirma que o
pipeline pode publicar essas informações em momentos diferentes. Para cor
visual, o estado físico classified continua utilizável; expected/matched
continuam presos ao CHECK correto.

### Correção D-034

- o espelho visual aceita classified da análise recente do mesmo projeto;
- detector latest-frame e classificação física são combinados para ON visual;
- câmera e visor consomem o mesmo mapa físico;
- ON = verde, OFF = azul/cinza, LOW_LIGHT = amarelo;
- gates e decisão produtiva permanecem inalterados.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

---

## 30/09/2026 — Reteste D-034: DEBUG confirmou bypass do tracking OFF

**Resultado físico:** FAIL visual, causa confirmada por telemetria.

### Cenário

- Rastreamento Automático: DESATIVADO;
- CHECK lógico: AUX;
- placa presente;
- energia confirmada;
- objetivo visual:
  - ON = verde vivo;
  - OFF = verde escuro;
  - câmera e visor iguais.

### Evidência objetiva

O snapshot registrou 15 máscaras live ON e 11 live OFF confirmadas, mas o bloco
do espelho visual informou:

~~~text
tracking_enabled=NÃO
stage=tracking_disabled
render_path=previous_window_update
context_ready=NÃO
sample_ready=NÃO
visual_ids=0
readout_ready=NÃO
readout_visual_ids=0
preview_rendered=SIM
~~~

Portanto o frame era renderizado, porém o callback final abandonava o espelho
visual antes de construir contexto, amostrar ROIs e atualizar o visor.

### Causa confirmada

O `tracked_window_update` instalado diretamente na instância real possuía um
retorno antecipado para `previous_window_update` quando tracking estava OFF.
Essa camada era mais externa que as correções D-033/D-034 e anulava o caminho
pretendido.

### Correção D-035

- removido o bypass visual antecipado no proprietário final;
- tracking OFF usa geometria fixa e continua pelo espelho latest-frame;
- tracking ON usa geometria móvel pelo mesmo builder;
- sampler do frame atual publica ON e OFF por ROI;
- ON usa verde vivo `#22C55E`;
- OFF usa verde escuro `#14532D`;
- câmera e VISOR DO DISPLAY consomem o mesmo contexto;
- análise/power físico permanece somente fallback visual quando o sampler não
  possui amostra de uma ROI;
- nenhuma regra de OK/NG, energia, presença, debounce ou sequência foi alterada;
- nenhum timer/thread/worker/scheduler novo foi criado.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

~~~text
tracking OFF
→ display aceso
→ ROIs ON: verde vivo na câmera + visor
→ ROIs OFF: verde escuro na câmera + visor

segmento muda ON -> OFF
→ os dois perdem verde vivo no mesmo repaint
→ passam para verde escuro

segmento muda OFF -> ON
→ os dois passam para verde vivo
~~~

---

## 30/09/2026 — Tecla 1 não acionava SEGREGAR após mudança de foco

**Resultado físico antes da correção:** FAIL.

### Sintoma observado

Na Produção Display F3, pressionar **1** não executava **SEGREGAR PLACA**.

### Causa identificada

O atalho estava associado somente a `self.container`, que é um `tk.Frame`.
Ao abrir o F3 o Frame recebe foco, porém clicar em um widget filho — por exemplo
ANALISAR, CONFIGURAR, DEBUG ou outro controle — transfere o foco. Eventos de
teclado do widget filho não percorrem o binding particular do Frame pai.

A ação `descartar_placa_display_f3()` e o botão continuavam conectados; o
defeito estava na captura do atalho de teclado.

### Correção

- mantém os bindings existentes no container;
- adiciona `1` e `KP_1` ao toplevel/root com `add="+"`, sem substituir
  atalhos existentes;
- o handler global só consome a tecla quando a janela F3 está visível;
- a ação continua passando pela autoridade canônica de SEGREGAR e pelas guardas
  contra dupla contabilização;
- nenhuma regra de TOTAL/NG, rearme, tracking, câmera ou F2 foi alterada.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

~~~text
abrir F3
→ clicar em ANALISAR (ou outro controle)
→ pressionar 1
→ SEGREGAR PLACA
→ TOTAL +1
→ NG +1
→ resultado PLACA SEGREGADA
→ aguardar retirada/rearme normalmente

repetir com NumPad 1
→ mesmo comportamento
~~~

---

## 30/09/2026 — Contorno desenhado da placa não aparecia na câmera ao vivo

**Resultado físico antes da correção:** FAIL visual.

### Cenário

- Produção Display F3;
- foco atual em Rastreamento Automático desativado;
- contorno da placa já desenhado e salvo em **Placa + Máscaras**;
- máscaras live já usam a geometria canônica da seção **Máscaras**.

### Sintoma observado

O operador solicitou que o contorno da placa desenhado durante a configuração
também apareça sobre a câmera ao vivo. O preview fixo mostrava as máscaras, mas
não publicava os pontos do contorno canônico.

### Causa identificada

No caminho final de preview com tracking OFF,
`_project_preview_context()` preenchia explicitamente `board_points=()`.
O renderer já sabia desenhar `board_points`, portanto a falha era de contexto,
não de desenho OpenCV.

### Correção D-037

- carregar o contorno por `canonical_board_points(...)` usando o store canônico;
- aplicar a mesma rotação visual usada pelas máscaras;
- publicar `board_points` no contexto live;
- incluir os pontos na chave de cache do preview fixo;
- manter contornos locais de CHECK/referência fora da câmera live.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

~~~text
tracking OFF
→ abrir F3
→ confirmar máscaras fixas + contorno da placa desenhado na câmera ao vivo
→ editar somente o contorno em Placa + Máscaras
→ reabrir/atualizar F3
→ confirmar novo contorno sem mover as máscaras

tracking ON + LOCK
→ confirmar que o mesmo contorno acompanha a pose rastreada
~~~



---

## 30/09/2026 — H1 correto não aprovava e SEGREGAR parecia inoperante

**Resultado físico antes da correção:** FAIL de decisão/apresentação.

### Cenário

- Rastreamento Automático: DESATIVADO;
- CHECK lógico exibido: H1;
- sete segmentos esperados ON visivelmente acesos;
- operador tentou SEGREGAR pelo botão e pela tecla 1.

### Evidência objetiva do DEBUG

No frame congelado da auditoria manual:

- H1 possui 7 máscaras esperadas ON e 21 OFF;
- o aprendizado por mesma máscara classificou o CHECK como
  `approved=True`, 28/28;
- a autoridade de energia encontrou as sete máscaras ON esperadas como
  energizadas;
- a análise estrita observada pelo runtime tinha 21/28 e marcava justamente as
  sete máscaras ON de H1 como faltantes;
- simultaneamente o ciclo já estava terminal:
  `waiting_empty_rearm=true`, TOTAL 1, NG 1, `last_result=null`;
- a UI principal havia voltado para `AGUARDANDO H1`, apesar do status
  operacional informar `RETIRE A PLACA DO SUPORTE`.

### Causas

1. **D-038 / falso OFF do CHECK correto:** a proteção D-031 removia
   absolutamente a foto do CHECK atual do aprendizado. Em segmentos cuja
   assinatura óptica muda entre funções, H1 podia ficar mais próximo de OFF de
   outra função mesmo estando fisicamente aceso.
2. **D-039 / SEGREGAR aparentemente morto:** a segregação já havia sido
   contabilizada. O runtime resetou internamente a sequência para H1 e o hold
   visual terminou, mas o rearme físico ainda bloqueava qualquer novo ciclo e
   qualquer nova segregação. A apresentação não espelhava esse latch.

### Correções implementadas

- ON do próprio CHECK só pode ser referência local da mesma máscara quando prova
  emissão contra OFF externo com a margem óptica mínima já existente;
- OFF próprio continua proibido;
- uma máscara live divergente continua bloqueando OK;
- tela terminal não pode ser sobrescrita por H1 enquanto aguarda retirada;
- após EMPTY, a tela mostra explicitamente espera por nova placa;
- SEGREGAR fica visualmente desabilitado durante todo o rearme e volta somente
  após nova placa confirmada;
- botão, `1` e NumPad `1` permanecem na mesma ação oficial;
- regressões automatizadas cobrem o ON próprio válido, o ON escuro inválido,
  o latch terminal e o handoff visual do rearme.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

~~~text
1) nova placa confirmada
→ H1 realmente aceso
→ 28/28
→ H1 aprova com um frame conforme

2) segmento esperado ON fisicamente apagado
→ continua divergente
→ nunca recebe OK por auto-referência

3) pressionar 1 ou clicar SEGREGAR uma vez
→ TOTAL +1 / NG +1
→ PLACA SEGREGADA permanece visível
→ botão SEGREGAR desabilitado
→ repetir 1 não duplica contagem

4) retirar placa
→ suporte vazio confirmado
→ AGUARDANDO NOVA PLACA

5) colocar nova placa
→ H1 volta a ficar ativo
→ SEGREGAR volta a ficar habilitado
~~~

---

## 30/09/2026 — Refinamento do SEGREGAR: estado deve permanecer vermelho

**Resultado físico informado:** FAIL/AMBÍGUO de feedback visual antes do
refinamento.

### Relato do operador

O operador informou que tanto a tecla **1** quanto o clique em
**SEGREGAR PLACA** pareciam não funcionar, ou o resultado vermelho podia estar
rápido demais. O requisito explícito é que, depois da segregação, o estado
terminal permaneça vermelho enquanto a placa continuar no suporte.

### Diagnóstico sobre o estado atual

D-039 já impede que snapshots posteriores voltem o status principal para H1 e
mantém SEGREGAR bloqueado durante o rearme. Porém:

- os cards ainda podiam renderizar os estados normais H1/PRÓXIMO;
- o status inferior do guard terminal era amarelo;
- as bordas da coluna de câmera/visor permaneciam neutras;
- portanto o latch existia, mas o feedback visual não era integralmente vermelho.

### Correção D-040

- registrar o tipo terminal `segregated` na própria janela;
- cards de CHECK ficam vermelhos e mostram `SEGREGADO`;
- painel principal continua em `COLOR_NG`;
- bordas de preview/visor/projeto ficam vermelhas;
- status operacional e status inferior ficam vermelhos e pedem retirada;
- repaint durante `waiting_empty_rearm` preserva esse estado;
- EMPTY remove o chrome vermelho e entra em espera por nova placa;
- câmera, contorno, máscaras e VISOR DO DISPLAY recebem vermelho terminal
  integral enquanto a placa segregada permanece no suporte;
- o vermelho é apenas apresentação; a classificação física interna permanece
  intacta para diagnóstico e telemetria.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

~~~text
placa no suporte
→ clicar SEGREGAR
→ TOTAL +1 / NG +1
→ PLACA SEGREGADA
→ cards SEGREGADO em vermelho
→ câmera, contorno, máscaras e visor ficam vermelhos
→ bordas/status permanecem vermelhos
→ aguardar vários segundos
→ NÃO voltar a H1 e NÃO perder o vermelho

repetir com tecla 1 e NumPad 1 em nova placa
→ mesmo resultado

retirar placa
→ EMPTY confirmado
→ sai do terminal vermelho
→ COLOQUE OUTRA PLACA

colocar nova placa
→ H1 liberado
→ SEGREGAR reabilitado
~~~

---

## 30/09/2026 — H1 com segmentos esperados verdes, mas CHECK/análise visual não reconhece

**Resultado físico:** FAIL recorrente informado pelo operador.

### Sintoma observado

No Display F3 ocorre repetidamente o cenário em que os segmentos que H1 deve
manter acesos aparecem corretamente verdes no ao vivo, mas:

- o CHECK H1 não recebe aprovação; ou
- a análise visual não consegue reconhecer o estado como H1.

Não foi fornecido nesta entrada um novo bloco de DEBUG que identifique qual gate
específico vetou o registro. Portanto a causa técnica exata ainda não deve ser
inventada.

### Regra funcional confirmada pelo operador

As imagens cadastradas nos CHECKS e em **Referências Visuais** já contêm:

- contorno desenhado da placa/filtro;
- máscaras locais alinhadas aos segmentos;
- segmentos ACESOS e APAGADOS que compõem o estado ensinado.

O ODIN não deve usar a fotografia inteira de H1 como classificador final contra
a câmera inteira. A referência deve ser tratada como memória do padrão do
display:

```text
contorno da placa
→ recorte da região útil
→ alinhamento dos segmentos/máscaras
→ comparação dos mesmos MASK_xxx
→ padrão ON/OFF conforme
→ CHECK reconhecido
```

D-031 continua válida: além de todos os segmentos esperados ON estarem ON, os
segmentos esperados OFF também precisam permanecer OFF; `ignore` não participa.
Se o padrão estiver 100% conforme, diferença de fundo ou score de cena inteira
não pode rejeitar o CHECK.

### Providência desta etapa

- regra registrada como D-041;
- AGENTS.md e README.md atualizados para impedir que futuras correções voltem a
  usar matching de cena inteira como segunda autoridade semântica;
- nenhuma mudança de algoritmo foi aplicada nesta etapa, porque o relato atual
  define o contrato, mas ainda não contém a evidência de qual proprietário está
  bloqueando o H1 no runtime real.

### Próximo diagnóstico esperado

Reproduzir exatamente o caso em que todos os ON esperados de H1 aparecem verdes
e capturar o DEBUG no mesmo instante. O diagnóstico precisa responder, no mínimo:

- máscaras esperadas ON realmente classificadas ON;
- máscaras esperadas OFF realmente classificadas OFF;
- total de conformes e `failed_mask_ids`;
- alinhamento/contorno considerado válido;
- gate físico/frescor/rearme que eventualmente permaneceu bloqueado;
- qual componente publicou a mensagem de análise visual.

### Estado

**FAIL REGISTRADO — CONTRATO D-041 DOCUMENTADO — CAUSA DE RUNTIME PENDENTE DE EVIDÊNCIA.**

---

## 30/09/2026 — H1 28/28 ficou bloqueado por presença global ambígua

**Resultado físico antes da correção:** FAIL recorrente.

### Cenário

- Rastreamento Automático: DESATIVADO;
- CHECK lógico: H1;
- os sete segmentos que H1 espera ON estavam fisicamente acesos e verdes na
  câmera/visor;
- estados OFF restantes também foram reconhecidos pela análise semântica.

### Evidência objetiva do DEBUG

No mesmo snapshot:

- gate produtivo: **BLOQUEADO**;
- motivo: `placa_nao_confirmada_no_suporte`;
- autoridade de presença: `board_present=false` e energia operacional `null`;
- análise estrita H1 já estava `ready=true`, `approved=true` e
  `check_conforme_mascaras_configuradas`;
- `failed_mask_ids=[]`;
- H1 tinha 7 ON + 21 OFF e o analyzer publicou 7 ON + 21 OFF;
- a evidência diagnóstica das máscaras do próprio H1 mostrou 7/7 votos de
  energia e zero votos OFF;
- as referências globais de cena ficaram todas abaixo do threshold absoluto,
  apesar de a placa e o padrão H1 estarem visíveis.

### Causa confirmada

O runtime canônico continha um deadlock de dependência:

```text
F3PresenceAuthority não confirma placa pela foto global
→ F3RuntimeAuthorities não chama F3PowerAuthority.evaluate()
→ energia das máscaras não existe no snapshot operacional
→ gate mantém decisão bloqueada
→ analyzer 28/28 fica apenas diagnóstico
```

Portanto o defeito não estava no H1 nem na classificação dos segmentos. O
sistema já sabia exatamente quais máscaras estavam ON/OFF, mas a informação era
impedida de chegar à autoridade de presença.

### Correção D-042

- a observação semântica das máscaras é calculada no mesmo frame mesmo quando a
  presença global ainda está ambígua;
- `F3PresenceAuthority` continua sendo a única autoridade de presença;
- ela pode confirmar ocupação quando um padrão configurado possui todo o núcleo
  ON confirmado e nenhuma observação confiante contradiz seus estados ON/OFF;
- essa confirmação não aprova CHECK;
- depois da presença, a energia produtiva e o analyzer estrito seguem o fluxo
  normal;
- EMPTY confirmado continua tendo precedência absoluta;
- não foi reativado o antigo monkey patch de confirmação por máscaras e não foi
  criada autoridade paralela, timer, thread ou worker.

### Proteção contra recorrência

Foram adicionadas regressões para:

1. cena global ambígua + padrão H1 conhecido → presença confirmada;
2. EMPTY confirmado + emissão candidata → EMPTY continua soberano;
3. padrão incompleto/contraditório → não promove presença;
4. builder canônico rompe o deadlock presença/energia e libera o gate;
5. `F3PowerAuthority.apply` continua incapaz de ignorar ausência de presença por
   conta própria.

### Estado

**CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

```text
tracking OFF
→ placa H1 no suporte
→ 7 segmentos esperados ON ficam verdes
→ padrão semântico confirma presença
→ status deixa IDENTIFICANDO PRESENÇA
→ energia fica CONFIRMADA
→ strict analyzer confirma 7 ON + 21 OFF / 28 de 28
→ H1 aprova
→ sequência avança para BLUE
```

Teste de segurança adicional:

```text
retirar a placa
→ EMPTY confirmado
→ nenhuma emissão/reflexo residual promove presença
→ fluxo permanece aguardando nova placa
```

---

## 30/09/2026 — Reteste D-042 PASS e BLUE 28/28 bloqueado na transição H1 → BLUE

### Parte 1 — validação física de D-042

**Resultado:** PASS.

O operador confirmou que, com Rastreamento Automático desativado, o H1 passou a
ser reconhecido corretamente depois da correção D-042 e a sequência avançou para
BLUE.

Isso valida no equipamento real o contrato:

```text
H1 correto
→ padrão semântico confirma presença
→ energia confirmada
→ conformidade estrita H1
→ H1 concluído
→ BLUE atual
```

A entrada anterior de D-042 permanece preservada como histórico da falha e da
correção; este registro é a confirmação física posterior.

### Parte 2 — novo FAIL em BLUE

**Resultado antes da correção:** FAIL.

Cenário:

- Rastreamento Automático: DESATIVADO;
- H1 já concluído;
- CHECK lógico atual: BLUE / CHECK_002;
- BLUE configurado com 18 máscaras ON + 10 OFF;
- câmera e visor mostravam o padrão BLUE esperado.

Evidência do mesmo snapshot:

- presença: confirmada;
- energia: confirmada;
- gate produtivo: liberado;
- aprendizado semântico de BLUE: `ready=true`, `approved=true`, 28/28;
- UI: `BLUE DETECTADO • 28/28 CONFORMES • 18 ACESOS • 10 APAGADOS`;
- mesmo assim o status inferior permaneceu
  `BLUE BLOQUEADO • aguardando mudança física H1 → BLUE`;
- sequência: H1 completed / BLUE current;
- tracking: desativado.

### Causa confirmada

A falha não estava em presença, energia, máscaras ou no analyzer de BLUE.

O bloqueio vinha da camada mais externa de entrada física entre CHECKS,
`display_f3_physical_transition_authority.py`. Para CHECKS posteriores ao H1,
essa autoridade ainda exigia identificação independente por contorno/estado
físico ou preferência entre as fotos do CHECK anterior e do CHECK atual.

Como as fotografias globais permaneciam ambíguas, a comparação H1 → BLUE podia
falhar mesmo quando o padrão funcional BLUE já estava integralmente identificado
pelas 28 máscaras. O resultado era uma contradição interna:

```text
BLUE semanticamente 28/28
+ presença confirmada
+ energia confirmada
+ gate produtivo liberado

mas

transição física H1 → BLUE = não confirmada
→ registro do CHECK vetado
```

### Correção D-043

A autoridade existente de transição foi corrigida; não foi criada uma segunda
autoridade.

Agora, para CHECKS posteriores, a transição também pode ser confirmada quando:

1. o CHECK anterior já está concluído;
2. a análise canônica pertence ao CHECK atual;
3. a análise está pronta e 100% conforme;
4. `matched_mask_count == active_mask_count`;
5. o padrão ON/OFF do CHECK atual difere do CHECK anterior em pelo menos uma
   máscara ativa.

A conformidade 100% prova somente que a função de destino já chegou fisicamente.
Ela não enfraquece D-031 e não transforma análise parcial em autorização.

Proteções mantidas:

- 27/28 não libera a transição;
- análise de outro CHECK não libera;
- CHECK anterior não concluído não libera;
- dois CHECKS com o mesmo padrão ON/OFF não podem provar transição um ao outro;
- um CHECK defeituoso continua precisando da identificação física independente
  da chegada antes que NG seja permitido;
- EMPTY, presença, energia, frescor, alinhamento e rearme mantêm precedência;
- nenhum timer, worker, scheduler ou thread foi adicionado.

### Estado

**D-042 VALIDADA FISICAMENTE. D-043 IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Próximo reteste esperado

```text
tracking OFF
→ H1 correto 28/28
→ H1 CONCLUÍDO
→ mudar fisicamente para BLUE
→ BLUE mostra 18 ON + 10 OFF / 28 de 28
→ transição H1 → BLUE é confirmada pelo padrão semântico completo
→ BLUE CONCLUÍDO
→ sequência avança para USB
```

Teste negativo de segurança:

```text
BLUE com qualquer máscara divergente (ex.: 27/28)
→ NÃO usar D-043
→ NÃO concluir BLUE por conformidade parcial
```

---

## 30/09/2026 — D-043 validada fisicamente: BLUE 28/28 avançou para USB

**Resultado físico:** PASS.

### Cenário validado

- Rastreamento Automático: DESATIVADO;
- H1 já havia sido concluído corretamente;
- CHECK atual: BLUE / CHECK_002;
- BLUE atingiu conformidade semântica completa das máscaras;
- o operador confirmou que, após a correção D-043, o CHECK não permaneceu mais
  preso em `BLUE BLOQUEADO • aguardando mudança física H1 → BLUE`.

### Resultado observado

O fluxo esperado foi confirmado no equipamento real:

```text
H1 28/28
→ H1 CONCLUÍDO
→ BLUE
→ padrão BLUE 100% conforme
→ transição H1 → BLUE confirmada
→ BLUE CONCLUÍDO
→ sequência segue para USB
```

### Conclusão

D-043 está **VALIDADA FISICAMENTE** para o caso que originou a correção.

A validação confirma que a conformidade canônica 100% de um CHECK de destino,
quando seu padrão ON/OFF difere do CHECK anterior já concluído, é evidência
suficiente da chegada física à nova função e não deve ser vetada por matching de
cena inteira ambíguo.

As proteções permanecem obrigatórias e não foram alteradas pela validação:

- leitura parcial continua sem usar D-043;
- padrão semanticamente igual ao anterior continua sem provar transição;
- análise de outro CHECK não libera o gate;
- NG continua dependendo de confirmação de chegada da função defeituosa;
- EMPTY, presença, energia, frescor e rearme continuam soberanos.

### Estado

**PASS — D-043 VALIDADA FISICAMENTE.**

---

## 30/09/2026 — BLUE NG real: MASK_024 esperada ON permaneceu OFF

**Resultado físico antes da correção:** FAIL de captura de NG.

### Cenário

- Rastreamento Automático: DESATIVADO;
- H1 já concluído;
- CHECK lógico atual: BLUE / CHECK_002;
- BLUE configurado com 18 máscaras ON + 10 OFF;
- defeito físico intencional/real observado: segmento 24 não acendeu junto com
  os demais segmentos esperados de BLUE.

### Evidência objetiva do DEBUG

No frame congelado do mesmo clique:

- gate produtivo: BLOQUEADO;
- motivo: placa não confirmada no suporte;
- análise bruta produtiva ficou sem autoridade enquanto o gate permaneceu
  fechado;
- a evidência física de energia do próprio BLUE estava disponível e dizia:
  `powered_confirmed=true`, 18 ON esperados, **17 votos powered + 1 voto off**;
- `MASK_024` estava configurada como ON em BLUE;
- `MASK_024` foi classificada fisicamente como OFF, `matched=false`, confiança
  aproximada de 0,845 e `winner_semantic=off`;
- a análise por aprendizado ON/OFF das fotos dos CHECKS fechou BLUE em **27/28**;
- nessa análise, a divergência observada era exatamente `MASK_024 expected=on /
  classified=off`.

### Causa confirmada

A primeira trava era consequência direta do contrato anterior de presença:
D-042 só promovia presença sem cena global quando algum CHECK configurado
formava um padrão semântico completo.

Isso funciona para produto BOM, mas é circular para NG:

```text
BLUE defeituoso
→ 17 ON corretos + MASK_024 OFF
→ energia física está confirmada
→ nenhum CHECK fica 100% conforme
→ presença semântica não confirma placa
→ energia perde autoridade produtiva
→ analyzer não pode registrar NG
```

Mesmo depois de destravar presença, havia uma segunda proteção a preservar:
D-043 permitia provar H1 → BLUE semanticamente somente com BLUE 100% conforme.
Não seria seguro simplesmente transformar qualquer 27/28 em chegada, pois um
frame ainda em H1 poderia ser reprovado como BLUE antes da mudança física.

### Correção D-044

A correção foi aplicada nos proprietários existentes:

1. `F3PresenceAuthority` agora aceita a votação multi-máscara
   `powered_confirmed` como prova de **ocupação física** quando nenhum CHECK está
   completo. Nesse modo ela não inventa identidade de CHECK.
2. A autoridade de transição H1 → BLUE agora possui uma assinatura semântica
   adicional para CHECK defeituoso: considera somente máscaras cujo ON/OFF muda
   entre H1 e BLUE e exige maioria estrita dessas diferenças no padrão BLUE.
3. A assinatura confirma somente que BLUE chegou; ela não concede OK e não cria
   NG.
4. O analyzer estrito e o debounce NG existente continuam decidindo o defeito.
5. Se a assinatura ainda preferir H1, o NG permanece bloqueado.
6. EMPTY confirmado continua soberano.
7. Nenhum timer, worker, scheduler, thread ou autoridade paralela foi criado.

### Proteção contra regressão

Foram adicionados testes para:

- placa energizada com CHECK divergente ainda confirmar presença;
- emissão insuficiente não promover presença;
- BLUE 27/28 com assinatura H1 → BLUE predominantemente no destino confirmar a
  chegada física;
- assinatura ainda em H1 continuar bloqueando;
- o guard final permitir registrar `False/NG` somente depois da chegada
  semântica confirmada.

### Estado

**CORREÇÃO D-044 IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

```text
tracking OFF
→ H1 correto conclui
→ entrar em BLUE
→ manter MASK_024 fisicamente apagada
→ presença permanece confirmada
→ energia permanece confirmada
→ assinatura H1 → BLUE confirma chegada
→ analyzer identifica MASK_024 esperada ON / observada OFF
→ debounce NG existente confirma falha
→ placa recebe NG terminal
→ NÃO avançar para USB
→ TOTAL +1 e NG +1 exatamente uma vez
→ aguardar retirada/rearme conforme contrato terminal
```

---

## 01/10/2026 — D-044 validada fisicamente: BLUE com MASK_024 apagada gerou NG

**Resultado físico:** PASS.

### Cenário validado

- Rastreamento Automático: DESATIVADO;
- H1 concluído corretamente;
- CHECK atual: BLUE / CHECK_002;
- BLUE com defeito real reproduzido;
- segmento 24 / `MASK_024`, configurado como ON em BLUE, permaneceu fisicamente
  APAGADO enquanto os demais segmentos esperados acenderam.

### Resultado observado

O operador confirmou no equipamento real que, após a correção D-044, o ODIN
passou a capturar corretamente esse caso como **NG**.

Fluxo físico validado:

```text
H1 correto
→ H1 CONCLUÍDO
→ BLUE chega fisicamente
→ energia permanece confirmada apesar da MASK_024 OFF
→ presença permanece confirmada
→ assinatura H1 → BLUE confirma a chegada da função
→ analyzer mantém MASK_024 como divergente
→ BLUE não recebe OK
→ defeito é confirmado como NG
```

### Conclusão

D-044 está **VALIDADA FISICAMENTE** no cenário que originou a correção.

A validação confirma que:

- uma placa energizada com defeito não precisa formar um CHECK 100% conforme
  para continuar sendo reconhecida como presente;
- a chegada a BLUE pode ser provada pela assinatura das máscaras que mudaram em
  relação a H1, sem transformar conformidade parcial em OK;
- a `MASK_024` apagada permanece disponível para a autoridade semântica de NG;
- o produto defeituoso não avança como BLUE aprovado;
- a correção não depende de Rastreamento Automático.

### Estado

**PASS — D-044 VALIDADA FISICAMENTE.**

---

## 01/10/2026 — D-045: NG correto, mas segmento defeituoso ainda sem destaque vermelho

**Resultado físico antes da correção visual:** FAIL de apresentação / PASS de decisão NG.

### Cenário

- CHECK lógico: BLUE / CHECK_002;
- placa já havia sido corretamente classificada como NG por D-044;
- frame e visor estavam congelados aguardando retirada da placa;
- `MASK_024` era o segmento defeituoso confirmado: deveria estar ON e permaneceu
  OFF;
- requisito do operador: o segmento 24 deve ficar vermelho tanto na máscara da
  câmera congelada quanto no VISOR DO DISPLAY.

### Evidência do DEBUG

O snapshot congelado mostrou:

- placa presente e energia confirmada;
- CHECK lógico BLUE;
- fluxo já em rearme terminal aguardando retirada;
- análise BLUE bruta com múltiplas divergências visuais no frame congelado;
- porém a autoridade efetiva publicou uma lista específica de falha persistente
  confirmada, distinta das divergências ainda transitórias;
- o visor/overlay continuavam priorizando o caminho luminoso ON/OFF e, por isso,
  uma máscara confirmada NG podia permanecer verde escuro em vez de vermelho.

### Causa

O contexto já carregava `effective_confirmed_failed_mask_ids`, mas os dois
renderers finais tinham uma precedência incorreta:

1. a câmera entrava em `live_luminous_only` e retornava pelo renderer clássico
   antes de aplicar o destaque de falha confirmada;
2. o VISOR DO DISPLAY também entrava primeiro no ramo `live_luminous_only`,
   ignorando o conjunto `failed_mask_ids` já filtrado para falhas confirmadas.

A decisão NG estava correta; faltava somente refletir a mesma autoridade na
apresentação congelada.

### Correção D-045

- câmera: `effective_confirmed_failed_mask_ids` agora tem prioridade sobre
  verde/verde escuro no renderer clássico;
- visor: `failed_mask_ids` confirmado recebe estado visual `ng` antes do ramo
  `live_luminous_only`;
- a fonte do vermelho final continua sendo somente a lista confirmada;
- `effective_failed_mask_ids` bruto e `effective_validating_mask_ids` não viram
  vermelho terminal;
- SEGREGAR continua com sua regra própria de vermelho total;
- nenhuma regra de decisão, debounce, energia, tracking ou rearme foi alterada.

### Proteção contra regressão

Foram adicionados testes para confirmar que:

1. câmera live/frozen pinta a máscara confirmada em vermelho enquanto mantém as
   demais máscaras ON/OFF em verde/verde escuro;
2. VISOR DO DISPLAY dá prioridade a vermelho para a falha confirmada mesmo no
   modo `live_luminous_only`;
3. o contexto do visor prefere `effective_confirmed_failed_mask_ids` à lista
   bruta de falhas.

### Estado

**D-045 IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO VISUAL.**

### Reteste esperado

```text
tracking OFF ou ON
→ reproduzir BLUE NG com MASK_024 apagada
→ NG terminal congelado
→ somente MASK_024 fica vermelha na máscara da câmera
→ somente segmento 24 fica vermelho no VISOR DO DISPLAY
→ demais segmentos mantêm verde/verde escuro conforme ON/OFF físico
→ retirar placa
→ rearme continua normal
```

---

## 01/10/2026 — Reteste D-045 FAIL: MASK_024 continuou verde após o NG

**Resultado físico:** FAIL de apresentação. A decisão NG permaneceu correta.

### Evidência visual

No estado terminal mostrado na Produção Display F3:

- a tela principal estava em `PLACA NG / RETIRE A PLACA`;
- H1 permanecia concluído e BLUE era o CHECK que falhou;
- TOTAL=1, OK=0, NG=1;
- a câmera estava congelada no padrão BLUE;
- a máscara/segmento 24 continuava em verde escuro;
- o segmento 24 do VISOR DO DISPLAY também continuava em verde escuro.

Portanto, a primeira implementação de D-045 funcionava nos testes isolados do
renderer, mas não atingia a apresentação realmente congelada no fluxo completo.

### Evidência do DEBUG do mesmo caso

O relatório confirmou:

- CHECK lógico BLUE;
- NG/rearme já aguardando retirada da placa;
- análise semântica do BLUE em 27/28;
- `effective_confirmed_failed_mask_ids=['MASK_024']`;
- `effective_validating_mask_ids=[]`;
- no contexto reconstruído para o visor, `MASK_024` aparecia classificada como
  `off`, esperada `on` e listada como falha.

Isso descartou erro de classificação/autoridade. O ID correto existia; o
problema estava entre a confirmação final do NG e o repaint que ficou preservado
pelo latch visual.

### Causa de integração confirmada

O freeze ocorria depois de um último `update_camera_preview`, mas esse último
repaint ainda dependia do contexto live existente naquele instante. Em um CHECK
intermitente, a confirmação persistente pode ser publicada no fechamento do
debounce depois que o contexto visual usado pelo último repaint já havia sido
montado.

Assim, os testes unitários provavam corretamente que o renderer sabe pintar
`MASK_024` de vermelho quando recebe a lista confirmada, mas o canvas real podia
ser congelado com a versão imediatamente anterior do contexto.

Foi encontrado ainda um problema de observabilidade: a auditoria manual
reconstruía `visual_state.readout_context` sobre o frame congelado e substituía o
snapshot visual capturado da janela. Isso podia fazer o DEBUG mostrar a falha
corretamente mesmo quando o canvas real não a havia pintado.

### Segunda correção D-045

A apresentação terminal passou a ser determinística:

1. `freeze_ng_evidence(...)` recebe os IDs confirmados da análise exata que
   fechou o NG;
2. após levantar o latch, o readout congelado é sincronizado explicitamente e
   redesenhado;
3. o frame exato do NG é repintado diretamente após o freeze usando a geometria
   já congelada e `effective_confirmed_failed_mask_ids` da análise terminal;
4. esse repaint não captura novo frame e não roda nova análise;
5. os segmentos do canvas agora possuem tags por máscara/estado para diagnóstico
   do fill realmente desenhado;
6. o DEBUG preserva `runtime_visual_state_before_manual_recompute`, mantendo a
   evidência da janela antes de qualquer reconstrução manual;
7. nenhuma autoridade, thread, worker, timer ou scheduler novo foi criado.

### Testes adicionados

Foram adicionadas regressões que verificam:

- o freeze reaplica `MASK_024` no conjunto de falha do visor congelado;
- o repaint pós-freeze do frame terminal pinta `MASK_024` em vermelho e mantém
  os demais segmentos nas cores ON/OFF;
- o contexto diagnóstico preserva separadamente falhas brutas, confirmadas e em
  validação;
- o DEBUG salva o estado visual runtime antes de recalculá-lo.

### Estado

**SEGUNDA CORREÇÃO D-045 IMPLEMENTADA — PENDENTE DE NOVO RETESTE FÍSICO.**

### Reteste esperado

```text
reproduzir BLUE com MASK_024 fisicamente OFF
→ BLUE gera NG
→ PLACA NG / RETIRE A PLACA
→ câmera congela
→ SOMENTE a máscara 24 fica VERMELHA
→ no VISOR DO DISPLAY, SOMENTE o segmento 24 fica VERMELHO
→ demais ON permanecem verdes
→ demais OFF permanecem verde escuro
→ retirar placa
→ EMPTY/rearme segue normal
```

---

## 01/10/2026 — Reteste D-045 PASS: MASK_024 vermelha na câmera e no visor

**Resultado físico:** PASS.

### Cenário validado

- Rastreamento Automático: desativado;
- H1 concluído corretamente;
- CHECK atual: BLUE / CHECK_002;
- `MASK_024` configurada como ON em BLUE e mantida fisicamente OFF;
- o ODIN confirmou o BLUE como NG e congelou a evidência terminal.

### Resultado observado

O operador confirmou no equipamento real que a segunda correção D-045 passou:

```text
BLUE com MASK_024 apagada
→ NG confirmado
→ PLACA NG / RETIRE A PLACA
→ câmera congela a evidência
→ máscara 24 fica VERMELHA na câmera
→ segmento 24 fica VERMELHO no VISOR DO DISPLAY
→ demais segmentos continuam com cores ON/OFF normais
```

### Conclusão

A falha visual de integração entre confirmação final do debounce e freeze foi
resolvida. O repaint terminal agora usa o mesmo frame/análise que fechou o NG e
reafirma `effective_confirmed_failed_mask_ids` depois do latch visual.

Com isso, D-045 está **VALIDADA FISICAMENTE** para o caso que originou a
correção: `MASK_024` apagada em BLUE é destacada em vermelho tanto na máscara da
câmera congelada quanto no VISOR DO DISPLAY.

### Estado

**PASS — D-045 VALIDADA FISICAMENTE.**

---

## 01/10/2026 — D-046: AUX aprovado correto, mas espelho visual mostrou falso ON e perdeu cores ao encerrar

**Resultado físico antes da correção:** PASS de decisão / FAIL de apresentação.

### Cenário

- sequência completa concluída com PLACA APROVADA;
- último estado físico da placa: AUX;
- AUX estava correto no equipamento;
- `MASK_010` em AUX deveria permanecer OFF;
- o VISOR DO DISPLAY mostrou o segmento 10 verde como se estivesse ON;
- após encerrar as análises, as máscaras da câmera também podiam voltar a cinza
  em vez de continuar reagindo ao estado luminoso enquanto a placa permanecia
  no suporte.

### Evidência do DEBUG

O relatório confirmou que o resultado produtivo não estava errado:

- aprendizado same-mask de AUX: `approved=True`, `matched=28/28`;
- `MASK_010` de AUX: `expected=off`, `classified=off`, `matched=true`;
- presença semântica: CHECK_003 / AUX;
- portanto o verde da MASK_010 no visor era somente erro do espelho visual.

A telemetria visual mostrou ao mesmo tempo:

- `live_visual_mask_ids` incluía `MASK_010`, gerado pelo sampler leve de brilho;
- o hook caiu em `fixed_render_exception`;
- erro: `_render_check_cards_f3_fixed() got an unexpected keyword argument
  'force_terminal_segregated'`;
- caminho de render virou `previous_window_update`.

### Causa

Foram confirmadas duas causas de apresentação:

1. o sampler visual latest-frame tinha prioridade absoluta e podia transformar
   brilho/glare dentro da ROI em falso ON mesmo quando a autoridade física
   same-mask do mesmo frame dizia OFF;
2. o wrapper de cards do layout fixo estava com assinatura antiga, quebrando o
   hook visual quando o estado terminal tentava usar `force_terminal_segregated`.

### Correção D-046

- se a autoridade física same-mask e o sampler observam o mesmo frame, a leitura
  same-mask prevalece visualmente;
- o sampler continua preenchendo máscaras sem classificação física e substituindo
  estado stale de frame anterior;
- o renderer fixo de cards passou a aceitar `force_terminal_segregated` e
  preservar o comportamento terminal;
- PLACA APROVADA não congela câmera/visor: o espelho visual continua live até
  EMPTY/rearme;
- NG congelado continua seguindo D-045 e SEGREGAR continua seguindo D-040;
- telemetria agora publica `live_visual_same_physical_frame` e os dois tokens de
  frame para diagnóstico.

### Estado

**D-046 IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.**

### Reteste esperado

```text
AUX correto com MASK_010 fisicamente OFF
→ AUX conclui 28/28
→ PLACA APROVADA
→ segmento 10 permanece verde escuro no VISOR
→ máscaras da câmera continuam verdes/verde-escuro conforme o estado físico
→ alterar visualmente algum segmento ainda no suporte atualiza câmera + visor
→ nenhuma máscara volta a cinza apenas porque o ciclo terminou
→ retirar placa
→ EMPTY/rearme normal
```

---

## 01/10/2026 — FAIL: NG permaneceu congelado após retirada da placa do suporte

**Resultado físico:** FAIL de rearme/apresentação após retirada da placa.

### Cenário observado

- Display F3 em ciclo produtivo normal;
- uma placa concluiu o ciclo com resultado **NG**;
- durante o estado terminal, a apresentação ficou corretamente congelada em NG;
- o operador retirou fisicamente a placa do suporte;
- após a retirada, a tela permaneceu congelada no NG em vez de retornar ao estado normal de espera/rearme.

### Comportamento esperado

A retirada física da placa deve encerrar imediatamente a apresentação terminal da
placa anterior e liberar o F3 para o estado normal de espera/rearme.

O resultado anterior deve continuar identificável visualmente, porém em sua
variante escura/inativa:

- após **OK**, o verde terminal deve voltar para **verde escuro**;
- após **NG**, o vermelho terminal deve voltar para **vermelho escuro**;
- câmera/visor não podem permanecer congelados no frame terminal depois que a
  placa já saiu do suporte;
- a retirada da placa deve encerrar qualquer latch/freeze pertencente ao ciclo
  anterior e preparar a interface para a próxima placa.

### Sintoma observado

    placa gera NG
    → F3 congela corretamente no resultado NG
    → operador retira a placa do suporte
    → apresentação continua congelada no NG
    → F3 não volta ao estado visual normal de rearme/espera

### Evidência objetiva disponível

Neste relato não foi anexado DEBUG técnico. A evidência disponível é a observação
física direta do equipamento: a placa foi retirada do suporte, mas o estado visual
terminal de NG permaneceu congelado.

### Causa

**Ainda não diagnosticada.**

O próximo diagnóstico deve verificar o caminho que transforma a confirmação de
EMPTY/retirada física em limpeza do freeze/latch terminal e atualização da
apresentação pós-ciclo, sem alterar as regras já validadas de congelamento do NG
enquanto a placa ainda permanece no suporte.

### Alteração aplicada

Nenhuma. Este registro documenta somente o FAIL físico relatado.

### Próximo reteste esperado

    placa conclui OK ou NG
    → resultado terminal é mostrado normalmente enquanto a placa permanece no suporte
    → retirar fisicamente a placa
    → EMPTY/rearme é reconhecido
    → qualquer freeze/latch da placa anterior é encerrado
    → OK anterior passa para verde escuro
    → NG anterior passa para vermelho escuro
    → câmera/visor deixam de permanecer congelados no frame da placa retirada
    → F3 fica pronto para receber a próxima placa

### Estado

**FAIL REGISTRADO — PENDENTE DE DIAGNÓSTICO E CORREÇÃO.**

---

## 01/10/2026 — Correção do freeze NG após EMPTY confirmado

**Estado:** CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

### Causa confirmada no código

O rearme físico já reconhecia corretamente a transição
`RESULTADO TERMINAL → EMPTY → AGUARDANDO NOVA PLACA`, porém o guard final
publicava a tela de espera chamando diretamente `show_waiting_new_plate()`.

No NG automático existem dois latches visuais coordenados:

- `_display_f3_ng_evidence_frozen` no runtime, que impede o repaint live;
- `_display_ng_evidence_frozen` na janela, que preserva câmera/visor congelados.

O método canônico `_liberar_evidencia_ng_display_f3()` já desmontava os dois
latches e só deveria ser executado depois que EMPTY estivesse confirmado, mas o
handoff final não o chamava. Assim, o estado físico avançava para suporte vazio
enquanto o preview continuava bloqueado pelo flag da placa NG anterior.

### Alteração aplicada

- o guard terminal passa pelo `_liberar_evidencia_ng_display_f3()` quando a
  transição de `waiting_empty` para `waiting_new_board` ocorre com evidência
  NG congelada;
- o caminho existente continua sendo usado para OK/SEGREGAR, sem criar timer,
  worker, scheduler ou autoridade paralela;
- `show_waiting_new_plate()` passa a escolher a cor escura pela memória
  `last_result`: OK usa verde escuro e NG usa vermelho escuro;
- o tema completo da janela recebe a mesma escolha imediatamente após EMPTY,
  em vez de assumir `ng_waiting` para qualquer resultado;
- D-045 permanece intacta: enquanto a placa NG ainda estiver no suporte, câmera
  e visor continuam congelados no frame exato que fechou o NG.

### Regressões adicionadas

- transição NG congelado → EMPTY confirma que o liberador canônico é chamado,
  o flag de freeze do runtime é removido e a UI entra uma única vez na espera
  por nova placa;
- seleção do tema pós-EMPTY confirma `ok_waiting` para último resultado OK e
  `ng_waiting` para último resultado NG.

### Reteste físico esperado

    placa gera NG
    → NG permanece congelado enquanto a placa está no suporte
    → retirar a placa
    → EMPTY é confirmado pelo rearme físico
    → freeze do runtime e da janela é liberado
    → câmera deixa imediatamente o frame congelado
    → tela entra em espera com identidade VERMELHO ESCURO
    → nova placa confirmada libera H1

Teste complementar:

    placa gera OK
    → retirar a placa
    → EMPTY confirmado
    → tela entra em espera com identidade VERDE ESCURO
    → nova placa confirmada libera H1

---

## 01/10/2026 — Reteste pós-correção: NG continuou congelado após retirada

**Resultado físico:** FAIL.

### Cenário

- placa entrou em NG normalmente;
- congelamento terminal do NG funcionou como esperado enquanto a placa permaneceu no suporte;
- a placa foi retirada fisicamente;
- visualmente, a câmera/visor continuaram presos no NG anterior;
- comportamento esperado: ao confirmar suporte vazio, o freeze deve ser encerrado e a interface deve voltar ao estado de espera normal da próxima placa.

### Evidência disponível

Neste reteste foi reportada evidência visual do equipamento. Não foi fornecido novo DEBUG textual.

A primeira correção havia passado nos testes unitários de `final_rearm_guard`, porém isso não representava a composição final do produto.

### Causa encontrada no caminho real

`DesktopProductionApp.__init__()` instala o rearme dedicado e o guard terminal,
mas, no final do bootstrap de `main_desktop.py`,
`instalar_autoridades_runtime_display_f3(app)` substitui
`operational_module._build_operational_state` pelo `canonical_builder`.

O builder canônico chamava apenas `aplicar_gate_rearme_ciclo_f3()`.
Esse gate libera o ciclo somente quando o classificador geral já devolve
`kind="empty"`.

O detector dedicado de rearme — criado justamente para o caso em que a cena
vazia ainda pode ser confundida com H1/um CHECK antigo e para usar a comparação
relativa EMPTY x placa — ficava fora do caminho final. Assim:

    placa NG retirada
    → builder canônico continua vendo estado geral não-EMPTY
    → waiting_empty_rearm permanece ativo
    → _liberar_evidencia_ng_display_f3() não é alcançado
    → câmera/visor continuam congelados corretamente pelo latch NG

### Correção aplicada

A responsabilidade foi consolidada dentro de `F3RuntimeAuthorities`, que é a
autoridade final do runtime:

- quando não existe rearme pendente, o fluxo normal permanece inalterado;
- quando `waiting_empty_rearm` ou `waiting_new_board_after_empty` está ativo,
  o builder canônico chama `aplicar_rearme_fisico_dedicado_f3()`;
- o detector dedicado mantém debounce de EMPTY, comparação específica de suporte
  vazio e a fase explícita de nova placa;
- ao confirmar EMPTY, o caminho existente chama
  `_liberar_evidencia_ng_display_f3()`, desmontando os latches de runtime e
  janela;
- nenhuma nova thread, timer, fila, scheduler ou segunda autoridade foi criada.

### Regressão adicionada

O teste do próprio `F3RuntimeAuthorities.build_operational_state()` agora exige
que, durante `waiting_empty_rearm`, o builder canônico use o rearme dedicado e
não o gate simples.

### Próximo reteste esperado

    gerar NG
    → manter placa no suporte
    → confirmar que NG continua congelado
    → retirar a placa
    → EMPTY dedicado confirma a retirada
    → freeze NG é liberado
    → câmera volta ao live mostrando o suporte vazio
    → tela entra em espera vermelho-escuro por ter vindo de NG
    → inserir nova placa
    → após confirmação física, H1 volta a ficar ativo

**Estado:** CORREÇÃO IMPLEMENTADA — PENDENTE DE NOVO RETESTE FÍSICO.

---

## 01/10/2026 — PASS físico: NG libera freeze após retirada da placa

**Resultado físico:** PASS.

### Cenário validado

- o F3 concluiu uma placa em NG;
- enquanto a placa permaneceu fisicamente no suporte, câmera e VISOR DO DISPLAY permaneceram congelados no frame terminal do NG conforme D-045;
- o operador retirou a placa do suporte;
- o rearme dedicado confirmou o suporte vazio;
- o freeze terminal foi encerrado;
- câmera/visor voltaram ao estado normal de espera;
- a interface deixou de permanecer presa visualmente no NG anterior.

### Resultado observado

O comportamento esperado foi confirmado no equipamento real:

    placa gera NG
    → NG permanece congelado enquanto a placa está no suporte
    → operador retira a placa
    → EMPTY é confirmado
    → freeze NG é liberado
    → câmera/visor deixam o frame congelado
    → F3 volta ao estado normal de espera/rearme

### Correção validada

Commit validado fisicamente:

`a4966084efca890490291192d343ee017c0d6c02`
— `fix(f3): integrar rearme dedicado na autoridade canônica`.

A validação confirma que o rearme dedicado precisa permanecer integrado em
`F3RuntimeAuthorities`, pois essa é a autoridade final instalada no runtime.
Não é suficiente depender apenas de wrappers anteriores de
`_build_operational_state`, porque eles podem ser substituídos pela composição
canônica posterior.

### Estado

**PASS FÍSICO — CORREÇÃO VALIDADA.**

---

## 01/10/2026 — Zoom de câmera e zoom ODIN no Projeto Display

**Estado:** IMPLEMENTADO — PENDENTE DE RETESTE FÍSICO.

### Requisito

Adicionar dentro de **CONFIGURAR** do F3 dois controles independentes:

- zoom digital da Logitech BRIO/driver;
- zoom por software do próprio ODIN.

### Implementação

O Projeto Display passou a persistir:

- `camera_zoom.enabled`;
- `camera_zoom.value` entre 100 e 500;
- `software_zoom` entre 1.0× e 5.0×.

A janela **Projeto Display** possui agora a seção
`ZOOM DA CÂMERA / ODIN`, com:

- checkbox para habilitar o zoom da câmera;
- slider de 1× a 5× para o zoom da câmera;
- slider de 1× a 5× para o zoom ODIN;
- ação `Salvar e aplicar zoom`;
- aviso para revisar referências, contorno e máscaras depois de alterar o
  enquadramento.

### Zoom da câmera

O serviço canônico de câmera recebeu suporte a `CAP_PROP_ZOOM`.

No perfil BRIO/DirectShow:

    100 → 1×
    ...
    500 → 5×

O mesmo mecanismo usado para foco/ganho/exposição confirma o ajuste por
readback e aceita passos discretos do driver. Ao sair do F3, o controle é
desabilitado e o baseline anterior é restaurado.

### Zoom ODIN

O zoom por software:

    frame bruto
    → crop central conforme fator de zoom
    → resize para a resolução original
    → frame F3 derivado

O `F3RuntimeCoordinator` publica temporariamente essa mesma visão derivada para
todo o ciclo F3, de modo que câmera ao vivo, tracking, presença, energia,
máscaras, CHECKS, análise OK/NG e congelamento terminal trabalhem sobre o mesmo
frame.

O frame bruto global da câmera permanece preservado para não alterar o F2.

### Performance

O frame ampliado por software é armazenado em cache por:

- frame da câmera;
- Projeto Display;
- fator de zoom;
- resolução.

Repintar o mesmo frame não refaz o `crop + resize`.

Nenhum novo timer, worker, scheduler ou loop foi criado.

### Reteste físico esperado

1. abrir F3 → CONFIGURAR;
2. habilitar **zoom digital da câmera**;
3. testar aproximadamente 1×, 2× e 3× e confirmar se a BRIO/DirectShow aceita;
4. salvar e confirmar que o enquadramento permanece no projeto;
5. testar **zoom ODIN** em 1×, 1.5×, 2× e 3×;
6. confirmar que preview e máscaras observam exatamente a mesma imagem ampliada;
7. fechar e reabrir o F3 e confirmar persistência do Projeto Display;
8. fechar o F3 e confirmar que o zoom de hardware não permanece contaminando o F2;
9. após escolher o zoom definitivo, recapturar/revisar referência, contorno e
   máscaras antes de validar produção.

**Validação física:** pendente.

---

## 01/10/2026 — PASS físico: zoom de câmera e zoom ODIN

**Resultado físico:** PASS.

### Cenário validado

Após a implementação da D-047, o operador testou no F3 os controles de zoom
adicionados ao Projeto Display e confirmou que o comportamento funcionou no
equipamento real.

Foram validados no fluxo real de configuração:

- controle de zoom digital da câmera exposto ao F3;
- controle de zoom por software do ODIN;
- aplicação do zoom no fluxo do Display F3.

Não foi fornecido novo DEBUG textual neste reteste; a validação reportada foi
visual/operacional.

### Estado

**PASS FÍSICO — CONTROLES DE ZOOM VALIDADOS.**

A próxima evolução solicitada é tornar o enquadramento configurável visualmente:
preview ao vivo + janela de captura arrastável para escolher qual região da
imagem ampliada será efetivamente entregue à câmera do Display F3.

---

## 01/10/2026 — Enquadramento arrastável e preview ao vivo do zoom

**Estado:** IMPLEMENTADO — PENDENTE DE RETESTE FÍSICO.

### Requisito

Após o PASS físico dos controles de zoom, foi solicitado:

- uma visualização ao vivo da câmera dentro das configurações do F3;
- uma segunda visualização que funcione como a "câmera virtual" do ODIN;
- possibilidade de clicar/arrastar a janela de enquadramento para escolher
  exatamente qual região ampliada será exibida e analisada pelo F3 Display.

### Implementação

A seção de zoom da configuração passou a exibir:

1. **ENQUADRAMENTO • ARRASTE A JANELA**
   - mostra o frame-fonte ao vivo;
   - desenha um retângulo sobre a região que o zoom ODIN recortará;
   - clique ou arraste reposiciona o centro do recorte;
   - o retângulo é limitado para não sair da imagem.

2. **VISUALIZAÇÃO AO VIVO • SAÍDA FINAL DO F3**
   - mostra o frame após zoom ODIN;
   - usa o mesmo centro X/Y;
   - mantém a resolução de saída;
   - aplica também a rotação visual usada pela câmera do F3.

O centro do recorte é persistido por Projeto Display como coordenadas
normalizadas `software_zoom_center.x/y`.

### Runtime e performance

- o `F3RuntimeCoordinator` continua sendo o único scheduler periódico;
- durante cada callback ele mantém disponível o frame bruto apenas para o
  seletor visual e entrega a visão transformada ao runtime F3;
- não foi criado novo `after()`, worker, fila ou thread para o preview;
- durante CONFIGURAR a cadência de repaint foi ajustada para aproximadamente
  10 FPS, sem executar o pipeline pesado de análise;
- o frame global bruto é restaurado ao final do callback.

### Reteste físico esperado

    abrir F3 → CONFIGURAR
    → ajustar zoom da câmera e/ou zoom ODIN
    → confirmar imagem ao vivo no quadro de enquadramento
    → arrastar a janela para a região desejada
    → confirmar que SAÍDA FINAL DO F3 acompanha imediatamente
    → Salvar e aplicar zoom
    → fechar CONFIGURAR
    → confirmar que a câmera produtiva do F3 mostra exatamente o enquadramento salvo
    → fechar/reabrir F3
    → confirmar persistência do mesmo enquadramento

Depois de definir o enquadramento definitivo, revisar/recapturar referências,
contorno e máscaras antes de validar inspeção produtiva.

**Validação física:** pendente.

---

## 01/10/2026 — FAIL físico: CONFIGURAR deixou de abrir após preview/enquadramento de zoom

**Resultado físico:** FAIL.

### Cenário

Após a implementação do preview ao vivo e do enquadramento arrastável do zoom,
o operador abriu o F3 e tentou acessar **CONFIGURAR**.

### Sintoma observado

- a janela **CONFIGURAR** não abriu;
- o sistema apresentou erro durante a tentativa de construção da janela;
- o problema surgiu após a inclusão dos novos widgets de preview/enquadramento.

Não foi fornecido traceback textual deste teste físico.

### Diagnóstico

O smoke em Linux/Xvfb abria a janela, portanto o problema foi tratado como
incompatibilidade/ordem de construção do Tk no ambiente Windows real.

Foram identificados dois riscos introduzidos pela nova UI:

1. os `Scale` de zoom possuem callbacks e alguns builds do Tk podem dispará-los
   durante a construção do widget, antes de `zoom_source_canvas` e
   `zoom_final_canvas` existirem;
2. o cursor `"fleur"` usado no canvas de arraste depende do backend Tk e não é
   necessário para a regra funcional.

### Correção aplicada

- `zoom_source_canvas` e `zoom_final_canvas` agora nascem explicitamente como
  `None` antes da criação dos sliders;
- `_rerender_zoom_preview()`, `update_live_zoom_preview()` e o desenho do
  viewport retornam com segurança enquanto os canvases ainda não existem;
- o cursor do viewport passou de `"fleur"` para `"hand2"`, já usado no ODIN
  e mais seguro entre Windows/Linux;
- nenhum novo timer, worker, scheduler ou autoridade foi criado;
- o runtime de inspeção e as regras de zoom/enquadramento não foram alterados.

### Regressão

Foi adicionado teste que chama o caminho de rerender antes da existência dos
canvases e exige que a operação não gere exceção. O contrato também proíbe o
retorno do cursor `"fleur"` nessa janela.

### Próximo reteste esperado

    abrir F3
    → clicar CONFIGURAR
    → janela deve abrir normalmente
    → seção de zoom deve aparecer
    → preview ao vivo deve carregar
    → viewport deve aceitar clique/arraste

**Estado:** CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

---

## 01/10/2026 — Segundo FAIL físico: CONFIGURAR continua sem abrir

**Resultado físico:** FAIL.

### Cenário

Após a primeira correção defensiva para a nova UI de zoom, o operador repetiu:

    F3
    → CONFIGURAR

### Sintoma observado

- a janela ainda não abriu;
- ao clicar, aparentemente nada acontece;
- não foi exibido traceback ou mensagem útil ao operador.

### Regra das duas tentativas

Este é o segundo FAIL consecutivo do mesmo defeito de abertura de CONFIGURAR.
Conforme AGENTS.md, a etapa seguinte não altera novamente o algoritmo da UI sem
evidência. O trabalho passa para **diagnóstico/instrumentação**.

### Diagnóstico encontrado no caminho de abertura

O método `abrir_configuracao_projeto_display()` captura qualquer exceção do
construtor e grava apenas:

- `_display_f3_last_config_error`.

A exceção era escondida do operador. O status visual também pode não ser
percebido porque a própria janela CONFIGURAR não chegou a existir.

Além disso, o smoke anterior construía a janela com
`frame_provider=lambda: None`, portanto não exercitava a parte nova que:

- recebe frame real;
- renderiza os dois canvases de zoom;
- cria `PhotoImage`;
- aplica callback de preview do zoom físico.

### Instrumentação aplicada

Sem alterar novamente a regra de zoom/enquadramento:

- o traceback completo agora é salvo em
  `_display_f3_last_config_traceback`;
- o traceback também é enviado ao console;
- a falha de abertura agora exibe uma caixa
  **F3 • Erro ao abrir CONFIGURAR** com tipo e mensagem reais da exceção;
- o smoke de CONFIGURAR foi ampliado para usar um frame NumPy 1920x1080 real,
  `source_frame_provider` e callback de zoom físico;
- o teste exige que os canvases e os dois `PhotoImage` de preview tenham sido
  realmente construídos.

### Próximo reteste esperado

    clicar CONFIGURAR
    → se abrir: registrar PASS
    → se ainda falhar: copiar exatamente a mensagem exibida
      em "F3 • Erro ao abrir CONFIGURAR"

Com essa mensagem será possível atacar a causa específica sem terceira tentativa
às cegas.

**Estado:** DIAGNÓSTICO/INSTRUMENTAÇÃO IMPLEMENTADOS — AGUARDANDO EVIDÊNCIA REAL.

---

## 01/10/2026 — Causa reproduzida do CONFIGURAR: contrato de construtor desatualizado

**Estado:** CAUSA IDENTIFICADA E CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

### Reprodução objetiva

Após o segundo FAIL físico, o smoke de CONFIGURAR foi ampliado para abrir a
janela final com:

- frame NumPy 1920x1080 real;
- `source_frame_provider`;
- callback `on_camera_zoom_preview`;
- construção dos dois canvases e dos dois `PhotoImage`.

O CI reproduziu o mesmo defeito de abertura com:

    TypeError:
    presence_init() got an unexpected keyword argument 'source_frame_provider'

### Causa

`display_f3_runtime_contract_fix._install_configuration_constructor_contract()`
instala wrappers explícitos sobre o construtor de CONFIGURAR.

Esses wrappers ainda descreviam o contrato anterior:

    root
    repository
    frame_provider
    heavy_executor
    on_change
    on_close

A nova configuração de zoom acrescentou:

    source_frame_provider
    on_camera_zoom_preview

O construtor real aceitava os novos argumentos, mas o wrapper final
`presence_init` os rejeitava antes que a janela fosse criada. Por isso:

    clicar CONFIGURAR
    → build()
    → DisplayProjectConfigPresenceWindow(...)
    → wrapper presence_init antigo
    → TypeError
    → exceção capturada
    → janela não aparece

### Correção aplicada

O contrato explícito foi atualizado no proprietário do wrapper:

- `DisplayProjectConfigWindow.__init__` wrapper agora aceita e encaminha
  `source_frame_provider` e `on_camera_zoom_preview`;
- `DisplayProjectConfigPresenceWindow.__init__` wrapper agora aceita e encaminha
  os mesmos argumentos;
- o teste permanente do contrato passou a exigir esses dois parâmetros;
- a instrumentação de erro visível permanece ativa para que futuras falhas de
  abertura não sejam silenciosas.

### Próximo reteste esperado

    F3
    → CONFIGURAR
    → janela abre
    → preview fonte aparece
    → saída final aparece
    → zoom físico/software respondem
    → viewport aceita clique/arraste

**Validação física:** pendente.

---

## 01/10/2026 — FAIL físico: viewport de zoom não arrasta e enquadramento volta

**Resultado físico:** FAIL.

### Cenário

Com **CONFIGURAR** novamente abrindo, o operador testou o novo viewport
arrastável da seção de zoom.

### Sintoma observado

- o cursor de mão aparece sobre a área de enquadramento;
- ao tentar pegar e arrastar a janela, ela não acompanha corretamente o mouse;
- durante a tentativa, o zoom/enquadramento visual parece se desfazer.

Não foi fornecido traceback porque o problema é comportamental/visual e a
janela permanece aberta.

### Causa identificada no código

O primeiro contrato de drag fazia duas coisas inadequadas para uma interação
contínua:

1. cada evento `<B1-Motion>` chamava `_rerender_zoom_preview()`;
2. esse rerender reconstruía o canvas-fonte inteiro com `delete("all")`,
   recriando imagem, viewport e cruz central enquanto o botão do mouse ainda
   estava pressionado.

Além disso, o centro do viewport é definido exclusivamente pelo
`software_zoom`. Em `1×`, o recorte é o frame inteiro e o normalizador fixa
o centro em 50%/50%; portanto não existe margem física para deslocar a janela.
O zoom digital da BRIO continua sendo um zoom central controlado pelo driver e
não equivale ao pan do viewport ODIN.

Por fim, o enquadramento alterado em CONFIGURAR só era persistido após SALVAR;
o runtime principal do F3 podia continuar exibindo a configuração salva anterior
durante a edição, dando a impressão de que o zoom havia voltado.

### Correção aplicada

- o gesto agora possui fases explícitas:
  - `Button-1` inicia o drag e guarda o offset entre a mão e o centro;
  - `B1-Motion` atualiza somente centro/overlay/saída final;
  - `ButtonRelease-1` encerra o gesto;
- durante o drag, o canvas-fonte não é mais destruído e recriado a cada pixel;
- somente o overlay `zoom_viewport` é redesenhado enquanto a mão se move;
- o preview final é atualizado separadamente;
- o Zoom ODIN e o centro em edição são publicados em memória no runtime F3,
  sem salvar em disco, para a câmera principal acompanhar imediatamente;
- ao fechar CONFIGURAR sem salvar, o valor persistido continua sendo restaurado;
- em `1×`, o sistema não tenta mais simular um arraste inexistente e informa
  que é necessário usar **Zoom ODIN > 1×** para existir margem de enquadramento;
- nenhum novo timer, worker, scheduler ou autoridade foi criado.

### Próximo reteste esperado

    F3 → CONFIGURAR
    → colocar Zoom ODIN acima de 1×
    → pressionar dentro da janela azul
    → arrastar mantendo o botão pressionado
    → janela acompanha a mão sem piscar/resetar
    → SAÍDA FINAL acompanha o movimento
    → câmera principal do F3 acompanha o enquadramento provisório
    → soltar mouse
    → posição permanece
    → SALVAR fixa o enquadramento no Projeto Display

**Estado:** CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

---

## 01/10/2026 — Segundo FAIL físico do drag: Zoom ODIN volta ao iniciar movimento

**Resultado físico:** FAIL.

### Esclarecimento do operador

O defeito é especificamente no **Zoom ODIN (software)**:

    ajustar Zoom ODIN acima de 1×
    → imagem aproxima corretamente
    → iniciar o arraste do enquadramento
    → o próprio zoom software volta/diminui
    → o operador perde o enquadramento ampliado

Não se trata do zoom digital da Logitech BRIO.

### Regra das duas tentativas

Como o comportamento continuou após a primeira correção do gesto, não foi feita
nova alteração no algoritmo sem reprodução objetiva.

### Diagnóstico adicionado

Foi criado um smoke com **Tkinter real via Xvfb** que:

1. abre a janela CONFIGURAR final;
2. seleciona um Projeto Display;
3. publica frame 1920x1080 real;
4. ajusta `software_zoom_var` explicitamente para 2.0×;
5. executa o mesmo caminho real:
   - `<Button-1>`;
   - `<B1-Motion>`;
   - `<ButtonRelease-1>`;
6. captura o valor do Zoom ODIN após cada fase;
7. exige que continue exatamente em 2.0×;
8. verifica que o centro X realmente se deslocou;
9. registra todos os valores publicados por
   `on_software_zoom_preview` e exige que nenhum callback publique 1.0×.

### Objetivo

Identificar de forma controlada se o reset ocorre:

- no evento Tk de press;
- no evento de motion;
- no release;
- no callback de preview;
- ou em algum refresh assíncrono da janela.

Nenhuma nova correção funcional foi aplicada nesta etapa.

**Estado:** DIAGNÓSTICO EM EXECUÇÃO — AGUARDANDO RESULTADO DO SMOKE REAL.

---

## 01/10/2026 — Diagnóstico do reset do Zoom ODIN durante drag

**Estado:** CAUSA NÃO REPRODUZIDA EM LINUX/XVFB; PROTEÇÃO DEFENSIVA IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

### Resultado do diagnóstico controlado

O smoke com Tkinter real foi ampliado para executar o gesto completo:

    Zoom ODIN = 2.0×
    → Button-1
    → B1-Motion
    → ButtonRelease-1

Primeiro contra a classe base e depois contra a composição final realmente usada
pelo botão CONFIGURAR, incluindo presença, ROI, tracking e contratos instalados.

Nos dois casos o Zoom ODIN permaneceu em 2.0× durante todo o gesto.

Isso indica que o reset físico observado no Windows não foi reproduzido no
backend Tk/Xvfb do CI e pode depender da ordem real de callbacks/variáveis do Tk
no ambiente Windows.

### Proteção aplicada

O drag passou a possuir um snapshot explícito do fator de zoom:

- no `Button-1`, o valor atual de `software_zoom` é capturado em
  `_zoom_drag_software_zoom`;
- enquanto `_zoom_drag_active=True`, `_zoom_values()` usa esse valor travado
  como autoridade do gesto;
- em cada `B1-Motion`, a `DoubleVar` é reafirmada com o zoom capturado;
- no `ButtonRelease-1`, o mesmo valor é reafirmado antes de encerrar o gesto;
- o latch é descartado somente após o release ou fechamento da janela.

Foi incluída uma regressão que simula explicitamente a condição suspeita:

    inicia drag em 2.0×
    → força software_zoom_var = 1.0 no meio do gesto
    → executa motion
    → Zoom ODIN deve voltar imediatamente para 2.0×
    → release mantém 2.0×

Esse contrato garante que um refresh/evento de backend não possa alterar o fator
de zoom enquanto o operador estiver arrastando o enquadramento.

Nenhum novo timer, worker, scheduler ou persistência foi introduzido.

### Próximo reteste esperado

    F3 → CONFIGURAR
    → Zoom ODIN = 2× ou 3×
    → pressionar dentro da janela de enquadramento
    → arrastar mantendo o botão pressionado
    → o fator exibido do Zoom ODIN deve permanecer exatamente no valor escolhido
    → saída final deve apenas mudar de posição, sem perder aproximação
    → soltar
    → zoom continua no mesmo fator

**Validação física:** pendente.

---

## 01/10/2026 — Redesign do zoom: mapa 1× + quadro azul único

**Estado:** IMPLEMENTADO — PENDENTE DE RETESTE FÍSICO.

### Solicitação

A visualização anterior estava confusa porque:

- havia duas imagens grandes;
- a saída final podia aparecer rotacionada;
- não estava claro qual área correspondia ao zoom usado pelo F3;
- ao usar zoom digital da câmera, o operador também queria deslocar a região.

### Implementação

A seção de zoom passou a usar:

**MAPA DA CÂMERA • ARRASTE O QUADRO AZUL**

- mostra a visão completa de referência em 1×;
- sempre usa orientação natural da câmera;
- não aplica rotação visual do F3;
- mantém um quadro azul sobre a área efetivamente usada;
- o tamanho do quadro reflete a composição do zoom da câmera com o Zoom ODIN.

Exemplo:

    câmera 1× + ODIN 2× = quadro 2×
    câmera 2× + ODIN 1× = quadro 2×
    câmera 2× + ODIN 2× = quadro 4×

A visualização secundária foi reduzida para:

**RECORTE ATUAL DO F3 • SEM ROTAÇÃO**

Ela serve apenas para confirmar o conteúdo atual selecionado.

### Movimento do quadro

- com zoom físico da BRIO acima de 1×:
  - arrastar o quadro atualiza `camera_zoom_center.x/y`;
  - o centro é convertido para `CAP_PROP_PAN` e `CAP_PROP_TILT`;
  - Zoom ODIN é recentrado para evitar duas autoridades de deslocamento;
- sem zoom físico:
  - o quadro move `software_zoom_center.x/y`.

O centro físico é salvo por Projeto Display.

### Referência 1×

Antes de aplicar zoom físico, o ODIN preserva em memória uma cópia do frame 1×.
Essa imagem funciona como mapa de navegação enquanto a BRIO passa a entregar
frames já ampliados.

Ela não entra na análise, decisão, tracking, presença ou OK/NG.

### Regressões validadas automaticamente

- composição câmera × ODIN gera o viewport efetivo correto;
- pan/tilt seguem o centro do quadro azul;
- drag com zoom físico altera o centro da câmera;
- drag com Zoom ODIN continua funcionando;
- zoom software não é perdido durante drag;
- centro físico persiste por Projeto Display;
- CONFIGURAR abre com Tkinter real;
- nenhum timer adicional foi criado;
- rearme F3 e controles manuais da câmera permanecem verdes.

### Reteste físico esperado

    F3 → CONFIGURAR
    → observar o MAPA DA CÂMERA em orientação natural
    → ativar zoom digital da câmera em 2×
    → quadro azul deve reduzir para representar a área 2×
    → arrastar quadro azul para esquerda/direita/cima/baixo
    → a BRIO deve mover digitalmente o enquadramento
    → RECORTE ATUAL deve acompanhar sem rotação/inversão
    → testar Zoom ODIN adicional
    → confirmar que o quadro encolhe conforme o zoom combinado
    → Salvar
    → fechar/reabrir F3
    → confirmar persistência do mesmo centro/enquadramento

**Validação física:** pendente.

---

## 01/10/2026 — PASS físico do mapa 1× + quadro azul do zoom

**Resultado físico:** PASS.

### Cenário validado

O operador retestou a nova visualização de enquadramento do F3 após o redesign
registrado na D-049.

Foi confirmado fisicamente que a nova interação ficou correta para o uso
esperado:

- a visualização principal funciona como mapa da câmera;
- o quadro azul representa de forma compreensível a região usada pelo F3;
- o quadro azul pode ser arrastado para reposicionar o enquadramento;
- o fluxo de zoom/enquadramento deixou de apresentar a confusão relatada na
  visualização anterior;
- a interação implementada foi aceita pelo operador no teste real.

O operador não informou valores numéricos específicos de zoom neste reteste;
portanto nenhum fator de zoom foi inferido ou registrado.

### Histórico preservado

Os FAILs anteriores de abertura, drag e reset do Zoom ODIN permanecem neste
arquivo como histórico da sequência real de diagnóstico e correção.

**Estado:** PASS FÍSICO — REDESIGN DE ENQUADRAMENTO VALIDADO.

---

## 01/10/2026 — FAIL físico: zoom e captura de máscaras ignoravam rotação visual

**Resultado físico:** FAIL.

### Cenário observado

Na tela de desenvolvimento do ODIN, o operador configurou a rotação visual para
**180°**.

Ao abrir o F3:

- a visualização de zoom não seguia os 180° configurados;
- em **Máscaras → Capturar foto com a câmera**, a janela de captura mostrava a
  imagem na orientação original em vez de 180°.

### Causa

O redesign D-049 havia definido deliberadamente o mapa/recorte do zoom como
"sem rotação". Esse contrato ficou incompatível com o uso físico real.

A janela `F3MaskReferenceCaptureWindow` também renderizava diretamente o frame
canônico, embora o editor posterior já possuísse infraestrutura para trabalhar
com a rotação visual.

### Correção aplicada

- o runtime passa `visual_rotation` real da tela principal para o preview de
  zoom;
- mapa da câmera e recorte atual são renderizados com
  `preparar_frame_visual_display`;
- o quadro azul é projetado da geometria canônica para a orientação visual;
- clique/drag no mapa rotacionado usa conversão visual → original antes de
  alterar o enquadramento;
- a janela **Capturar foto com a câmera** recebe a rotação visual atual e mostra
  o frame nessa orientação;
- o frame salvo pela captura permanece canônico, evitando rotação dupla no
  editor e nas referências persistidas;
- o status da captura informa explicitamente `VISUAL 0/90/180/270°`;
- D-050 formaliza que a rotação da tela de desenvolvimento é a autoridade de
  apresentação do F3.

### Regressões automáticas

Foram adicionados testes que confirmam:

- um ponto arrastado na visualização 180° é convertido de volta ao referencial
  original corretamente;
- a captura de máscaras mostra 180°;
- a captura ainda salva o frame mestre sem rotação;
- o preview de zoom recebe a rotação visual atual do F3;
- o fluxo de captura recebe a mesma rotação do frame provider.

No HEAD da correção passaram:

- **Display F3 fast H1 BLUE tests**;
- **Display F3 cycle rearm tests**;
- **Camera manual controls tests**.

### Reteste físico esperado

    tela de desenvolvimento → rotação 180°
    → abrir F3 → CONFIGURAR
    → MAPA DA CÂMERA aparece em 180°
    → quadro azul acompanha corretamente a orientação 180°
    → arrastar para um lado move o enquadramento para o mesmo lado visual
    → RECORTE ATUAL também aparece em 180°
    → Máscaras → Capturar foto com a câmera
    → preview ao vivo aparece em 180°
    → CAPTURAR
    → editor/preview salvo continua em 180° sem rotação dupla

**Estado:** CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

---

## 01/10/2026 — PASS físico da rotação visual no zoom e captura de máscaras

**Resultado físico:** PASS.

### Cenário validado

O operador retestou o comportamento após a correção da D-050.

Foi confirmado fisicamente que a rotação visual definida na tela de
desenvolvimento passou a ser respeitada também nas configurações do F3.

### Resultado observado

- a visualização de zoom do F3 acompanha a rotação visual configurada;
- o mapa/quadro azul do enquadramento é apresentado na orientação esperada;
- o recorte visual do F3 acompanha a mesma orientação;
- em **Máscaras → Capturar foto com a câmera**, o preview ao vivo também aparece
  com a rotação configurada;
- o comportamento corrigido foi aceito pelo operador no teste real.

O reteste confirmou a regra funcional solicitada. Não foram informados novos
valores de zoom ou outra rotação além do cenário já documentado de 180°;
portanto nenhum parâmetro adicional foi inferido.

### Histórico preservado

O FAIL anterior — em que zoom e captura de máscaras ignoravam a rotação visual —
permanece registrado para preservar a sequência real de evidência, correção e
validação.

**Estado:** PASS FÍSICO — D-050 VALIDADA.

---

## 01/10/2026 — FAIL físico: reflexos marcados como segmentos acesos no espelho visual H1

**Resultado físico:** FAIL.

### Cenário

Projeto `CM_500_L`, CHECK lógico **H1**, rotação visual 180°, rastreamento
automático desativado.

O operador confirmou que a placa estava fisicamente correta no H1 e informou
como segmentos realmente acesos somente:

    MASK_008
    MASK_013
    MASK_009
    MASK_012
    MASK_011
    MASK_017
    MASK_020

Porém, câmera/visor do espelho visual também apresentavam como acesos, por
reflexo/ruído óptico:

    MASK_010
    MASK_014
    MASK_018
    MASK_021

### Evidência do DEBUG

O gabarito configurado do H1 possui exatamente 7 máscaras ON e 21 OFF.

A análise semântica/produtiva do mesmo caso já classificava
`MASK_010`, `MASK_014`, `MASK_018` e `MASK_021` como OFF. Portanto a origem
dos quatro falsos ON não estava na regra produtiva de CHECK.

O bloco **ESPELHO VISUAL LIVE D-032** registrou:

    tracking_enabled=NÃO
    sample_ready=SIM
    sampled_masks=28
    same_physical_frame=NÃO
    physical_frame_token=--
    visual_ids=11

e publicou:

    MASK_008, MASK_009, MASK_010, MASK_011, MASK_012,
    MASK_013, MASK_014, MASK_017, MASK_018, MASK_020, MASK_021

Assim, os quatro falsos positivos foram isolados no sampler leve
`latest_preview_frame_core_v`.

### Causa no proprietário responsável

`detectar_emissao_visual_ao_vivo_f3()` possui duas formas de aceitar ON:

1. separação relativa entre grupo escuro e grupo luminoso;
2. evidência absoluta forte, criada como fallback para cenas sem contraste
   interno, como todos/quase todos os segmentos acesos.

A segunda regra era aplicada **sempre**, inclusive quando a separação relativa já
estava disponível. Com isso, uma ROI de reflexo suficientemente brilhante podia
ser rejeitada pelo threshold relativo e depois ser recolocada como ON pela regra
absoluta (`score >= 150` e `p_high >= 175`).

### Correção aplicada

- a evidência absoluta forte passou a funcionar somente como **fallback real**,
  quando a evidência relativa não está disponível;
- quando existe separação relativa utilizável, o resultado relativo é preservado
  e candidatos fortes intermediários não são recolocados como ON;
- nenhum threshold produtivo, gabarito, energia, OK/NG, sequência, máscara ou
  geometria foi alterado;
- a correção afeta somente o espelho visual live de câmera + máscaras + visor;
- a proteção D-046 continua válida: classificação física same-mask do mesmo frame
  continua prevalecendo quando estiver disponível;
- não foi criado timer, worker, scheduler ou segundo classificador produtivo.

### Telemetria adicionada

O DEBUG passa a registrar:

    threshold
    baseline
    peak
    dynamic
    cluster_gap
    relative_ready
    absolute_fallback
    strong_candidate_mask_ids
    reflection_rejected_mask_ids

No próximo teste físico, `reflection_rejected_mask_ids` permitirá confirmar se
as ROIs brilhantes descartadas correspondem aos reflexos observados.

### Regressões adicionadas

Foi criado cenário sintético com três níveis:

    fundo/segmentos OFF
    → reflexos intermediários fortes
    → emissão real do display

O contrato exige:

- somente o grupo superior de emissão real fica ON;
- reflexos intermediários são listados como rejeitados;
- o fallback absoluto fica desativado quando há separação relativa;
- o caso legítimo de todos os segmentos acesos continua usando o fallback
  absoluto.

### Reteste físico esperado

    H1 correto
    → câmera/visor devem mostrar ON somente:
      8, 13, 9, 12, 11, 17, 20
    → 10, 14, 18 e 21 devem permanecer OFF
    → copiar DEBUG
    → verificar reflection_rejected_mask_ids
    → confirmar que nenhum segmento realmente ON foi eliminado

**Estado:** CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

## 02/10/2026 — FAIL fisico: BLUE correto ficou preso em 25/28 por falso OFF ambiguo

**Resultado fisico:** FAIL.

### Cenario

Projeto `CM_500_L`, sequencia F3 apos H1 concluido, CHECK logico
`CHECK_002 / BLUE`, configurado como intermitente.

A placa estava no suporte, energizada e visualmente no BLUE correto. Mesmo assim
o CHECK nao foi aprovado e permaneceu em busca.

### Sintoma observado

A tela mostrou:

    PLACA NO SUPORTE • LIGADA • ANALISANDO BLUE
    MASCARAS • BLUE NAO CONFIRMADO • 25/28 CONFORMES
    AUTO • BLUE • leitura incerta • continuando busca

A autoridade efetiva publicou como divergentes:

    MASK_021
    MASK_023
    MASK_024

As tres eram esperadas ON, mas o classificador estrito as publicou OFF com
confiancas proximas do limite:

    MASK_021  confidence=0.5044  ON=129.7533  OFF=127.4452
    MASK_023  confidence=0.5406  ON=5.1261    OFF=4.3409
    MASK_024  confidence=0.5004  ON=99.2755   OFF=99.1093

As regioes permaneciam muito luminosas no mesmo snapshot.

### Evidencias independentes do mesmo caso

O diagnostico pelo gabarito do BLUE identificou as tres como ON:

    MASK_021  template_similarity=0.9164
    MASK_023  template_similarity=0.9717
    MASK_024  template_similarity=0.9078
    threshold=0.8200

A evidencia fisica CHECK x PLACA DESLIGADA publicou:

    expected_on=18
    powered_votes=18
    off_votes=0
    tie_votes=0

incluindo `MASK_021`, `MASK_023` e `MASK_024` como energizadas.

O runtime ja havia observado 22 amostras de fase ON, mas ainda registrava:

    exact_template_veto_ids=[]
    candidate_failed_ids=[]
    persistent_failed_ids=[]

Portanto o caso nao era um NG confirmado. O sistema ficava entre a classificacao
estrita ambigua e a ausencia de uma evidencia auxiliar consumivel pelo runtime.

### Causa identificada

O veto historico de falso OFF de CHECK intermitente dependia de
`template_similarity/template_threshold` presentes na propria linha semantica.
A autoridade final `F3StrictMaskConformityAnalyzer` propositalmente nao usa a
foto do CHECK atual como autoridade semantica, conforme D-038. Assim, a evidencia
fisica positiva existia no DEBUG, mas nao chegava ao contrato de reconciliacao
do BLUE.

### Correcao aplicada

Foi implementada a D-051:

- a autoridade estrita continua sendo a unica classificadora semantica;
- somente um falso OFF **ambiguo** de mascara esperada ON pode receber suporte;
- o suporte reutiliza features ja extraidas/cached da mesma mascara:
  LIVE + ON do CHECK atual + OFF de PLACA DESLIGADA;
- a decisao fisica reutiliza o classificador relativo de energia ja existente;
- ON e OFF precisam ser discriminantes;
- o analyzer apenas anota a evidencia e preserva a classificacao bruta;
- o runtime intermitente consome a anotacao somente durante fase ON valida;
- um frame continua precisando fechar a fase ON completa; segmentos de frames
  diferentes nao sao somados;
- nenhuma aprovacao parcial 25/28 foi criada;
- nenhum threshold global foi reduzido;
- nenhum timer, worker, scheduler ou nova autoridade produtiva foi criado.

### Protecao do defeito real

O caso anteriormente validado de `MASK_024` fisicamente apagada continua
protegido:

    LIVE proximo de OFF
    → suporte fisico nao confirma ON
    → divergencia permanece
    → contador de falha intermitente continua
    → persistencia leva ao NG

Tambem foi adicionada regressao em que a propria referencia ON esta escura e
quase igual a OFF; nesse caso a comparacao fica sem poder discriminante e nao
pode autoaprovar a mascara.

### Proximo reteste fisico esperado

    H1 correto
    → avancar para BLUE
    → BLUE correto deve fechar 28/28 e avancar

Depois, regressao de seguranca:

    H1 correto
    → avancar para BLUE
    → manter MASK_024 realmente apagada
    → MASK_024 nao pode receber suporte ON
    → apos persistencia deve registrar NG

**Estado:** CORRECAO IMPLEMENTADA — PENDENTE DE RETESTE FISICO.

---

## 02/10/2026 — FAIL físico: H1 correto ficou preso em 26/28 por falso OFF ambíguo

**Resultado físico:** FAIL.

### Cenário

Projeto `CM_500_L`, primeiro CHECK `CHECK_001 / H1`, não intermitente,
rotação visual 180°.

A placa estava no suporte e o padrão H1 apresentado era o correto. Os sete
segmentos esperados ON estavam fisicamente acesos, mas a tela permaneceu em:

```text
AGUARDANDO H1
MÁSCARAS • H1 NÃO CONFIRMADO • 26/28 CONFORMES
5 ACESOS • 23 APAGADOS
```

### Evidência do DEBUG congelado

O gate físico não era o bloqueio:

```text
ESTADO DA PLACA: PRESENTE • CONFIRMADA
ENERGIA DO DISPLAY: CONFIRMADA
GATE PRODUTIVO: LIBERADO
CHECK LÓGICO: H1
```

A autoridade semântica estrita publicou duas divergências:

```text
MASK_012 expected=ON classified=OFF confidence≈0.527
MASK_020 expected=ON classified=OFF confidence≈0.511
H1 = 26/28
```

Nos dois casos a confiança estava praticamente empatada, apesar de as ROIs
estarem intensamente luminosas.

Ao mesmo tempo, duas evidências independentes do mesmo frame confirmaram o H1:

```text
GABARITO EXATO H1 = 28/28

MASK_012 template_similarity=0.9926
v_ref≈250.74
v_live≈250.88

MASK_020 template_similarity=0.9901
v_ref≈251.44
v_live≈250.30
```

e a comparação física direta contra PLACA DESLIGADA publicou:

```text
expected_on=7
powered_votes=7
off_votes=0
tie_votes=0
```

Portanto a câmera não estava deixando de enxergar os dois segmentos. O falso
OFF vinha do classificador semântico aprendido, cuja distância ON/OFF ficou
quase empatada para essas máscaras.

### Causa identificada

D-051 tratava esse tipo de falso OFF somente em CHECK intermitente. O H1 é
não intermitente e, portanto, nunca passava pela reconciliação criada para BLUE.

Além disso, o suporte semântico auxiliar baseado nas features aprendidas também
não ajudava `MASK_012` e `MASK_020`: as amostras aprendidas ON/OFF dessas
máscaras eram próximas demais e produziam empate. A comparação física direta
das imagens `BOARD_OFF ↔ LIVE ↔ H1`, porém, separou corretamente as sete
máscaras ON.

### Correção aplicada — D-052

Foi adicionada uma reconciliação exclusiva do primeiro CHECK/reference gate:

- só atua em `expected=ON → classified=OFF`;
- só atua quando a classificação semântica está ambígua
  (`confidence < 0.58`);
- reutiliza a autoridade física existente da mesma máscara;
- exige referência ON/OFF discriminante;
- exige `winner=powered` para o LIVE atual;
- não toca em OFF semântico confiante;
- não toca em máscaras esperadas OFF;
- não usa o gabarito exato isoladamente como aprovação;
- recalcula a conformidade completa depois do desempate;
- H1 continua exigindo 100% das máscaras conformes para avançar.

Nenhum novo timer, worker, scheduler ou loop foi criado. A comparação física
só é solicitada quando existe falso OFF ambíguo no reference gate.

### Proteção do defeito real

```text
segmento H1 realmente apagado
→ LIVE próximo de PLACA DESLIGADA
→ winner=off ou tie
→ máscara continua OFF
→ H1 não recebe OK
```

Também permanece bloqueado qualquer resgate de uma classificação OFF confiante.

### Próximo reteste físico esperado

```text
apresentar H1 correto
→ MASK_012 e MASK_020 deixam de ficar presas em falso OFF
→ H1 fecha 28/28
→ H1 é concluído
→ sequência avança normalmente
```

Depois disso, o teste de segurança do H1 deve ser repetido mantendo
deliberadamente um segmento esperado ON apagado; o H1 não pode avançar.

**Estado:** CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

---

## 02/10/2026 — FAIL físico: reteste D-052 ainda deixou H1 correto preso em 27/28 por MASK_013

**Resultado físico:** FAIL.

### Cenário

Projeto `CM_500_L`, primeiro CHECK `CHECK_001 / H1`, não intermitente,
rotação visual 180°.

Este foi o reteste físico posterior à D-052. O padrão H1 estava fisicamente
correto e todos os sete segmentos esperados ON estavam acesos, porém o fluxo
permaneceu em:

```text
AGUARDANDO H1
MÁSCARAS • H1 NÃO CONFIRMADO • 27/28 CONFORMES
6 ACESOS • 22 APAGADOS • FALHA MASK_013
```

A imagem operacional também mostrava o segmento correspondente à
`MASK_013` emitindo luz, mas o visor lógico do F3 manteve essa máscara como OFF.

### Evidência objetiva do DEBUG do mesmo frame

O frame analisado foi estável e o gate produtivo estava liberado:

```text
frame_id=4025
frame_id_estavel=SIM
ESTADO DA PLACA: PRESENTE • CONFIRMADA
ENERGIA DO DISPLAY: CONFIRMADA
GATE PRODUTIVO: LIBERADO
CHECK LÓGICO: H1
ANÁLISE BRUTA H1: 27/28
```

A única divergência produtiva do H1 era:

```text
MASK_013
expected=ON
classified=OFF
confidence=0.5944
```

O classificador de aprendizado das fotos dos CHECKS também fechou H1 em
`27/28`, novamente somente por `MASK_013`.

Em contraste, o gabarito exato da própria foto H1 reconheceu o mesmo frame como
totalmente conforme:

```text
GABARITO EXATO H1 = 28/28
MASK_013 expected=ON
classified=ON
template_similarity=0.9920
v_ref=250.46
v_live=251.00
```

A comparação física explícita **CHECK x PLACA DESLIGADA** também publicou:

```text
expected_on=7
powered_votes=7
off_votes=0
tie_votes=0
MASK_013 winner=powered
```

Portanto o segmento não estava fisicamente apagado no frame congelado.

### Discrepância adicional encontrada no DEBUG

O mesmo relatório contém duas leituras físicas diferentes para a
`MASK_013`.

O bloco `current_check_power_mask_evidence` registrou:

```text
expected_on_mask_count=7
powered_votes=6
off_votes=1

MASK_013
classified=off
confidence=0.5682
primary_winner=off
winner=off
```

Porém o bloco posterior e explícito
`[EVIDÊNCIA DE ENERGIA: CHECK x PLACA DESLIGADA]` registrou as sete máscaras
ON como `powered`, inclusive `MASK_013`.

Essa divergência precisa ser preservada no histórico porque mostra que o falso
OFF não é falta de emissão na câmera: existem caminhos diagnósticos do mesmo
frame discordando sobre a mesma máscara.

### Relação com D-052

A D-052 foi criada para resgatar falso OFF ambíguo do primeiro CHECK somente
quando:

```text
expected=ON
classified=OFF
confidence < 0.58
evidência física same-mask = powered
```

Neste reteste, a classificação semântica que bloqueou o H1 veio com:

```text
confidence=0.5944
```

ou seja, ficou logo acima da faixa fixa `< 0.58` usada pela D-052, apesar de a
ROI estar saturada e de o gabarito exato + comparação física direta confirmarem
ON.

O teste físico prova que a D-052 resolveu o caso anterior de
`MASK_012/MASK_020`, mas **não cobre de forma suficiente todos os falsos OFF
reais do H1**. O critério não pode ser considerado validado apenas pelos testes
automatizados anteriores.

### Alteração aplicada nesta etapa

Nenhuma alteração de algoritmo foi realizada neste registro.

Apenas o FAIL físico e suas evidências foram documentados para impedir que uma
próxima correção:

- trate novamente o problema como ausência real de luz;
- ignore a diferença entre `current_check_power_mask_evidence` e a comparação
  direta `CHECK x PLACA DESLIGADA`;
- considere D-052 fisicamente validada no H1;
- repita apenas uma mudança arbitrária de threshold sem investigar qual
  evidência física deve ser a fonte correta do desempate.

### Próximo reteste esperado após futura correção

```text
H1 correto
→ 7 segmentos esperados ON fisicamente acesos
→ MASK_013 reconhecida ON
→ H1 fecha 28/28
→ sequência avança para o próximo CHECK
```

E o teste oposto continua obrigatório:

```text
H1 com um segmento esperado ON realmente apagado
→ comparação same-mask deve confirmar OFF/tie
→ nenhuma reconciliação pode promover esse segmento
→ H1 não pode avançar
```

**Estado:** FAIL FÍSICO REGISTRADO — D-052 AINDA NÃO VALIDADA FISICAMENTE PARA H1 — PENDENTE DE DIAGNÓSTICO/CORREÇÃO.

---

## 02/10/2026 — Correção após FAIL H1 27/28: MASK_013 passa a usar reconciliação física sem corte 0.58

**Estado:** CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

### Evidência que motivou a correção

No reteste anterior, H1 estava fisicamente correto mas ficou em 27/28 por
`MASK_013`.

O frame congelado mostrou simultaneamente:

```text
MASK_013 semântico:
expected=ON
classified=OFF
confidence=0.5944

gabarito exato H1:
MASK_013=ON
H1=28/28

comparação física CHECK x PLACA DESLIGADA:
MASK_013=powered
powered_votes=7
off_votes=0
tie_votes=0
```

A D-052 não reconciliou o falso OFF porque consultava/aplicava a prova física
somente quando a confiança semântica era menor que `0.58`.

### Causa confirmada no código

O bloqueio não estava na captura, no gate de presença, na energia geral nem na
falta de emissão de `MASK_013`.

O runtime continha um corte fixo:

```text
semantic confidence < 0.58
→ consultar/aplicar reconciliação física

semantic confidence >= 0.58
→ não consultar/reconciliar
```

A confiança `0.5944` vem da distância no pool aprendido e não é uma medida
física independente de emissão. Por isso ela não pode ser usada para impedir a
comparação direta da mesma ROI quando existe uma referência OFF independente.

Também foi esclarecida a divergência observada no DEBUG:

- `current_check_power_mask_evidence` pertence à autoridade global de energia e
  decide se há energia suficiente no display;
- `CHECK x PLACA DESLIGADA` compara diretamente a mesma `MASK_xxx` entre
  BOARD_OFF, LIVE e foto ON do CHECK atual;
- para reconciliar um falso OFF individual do H1, a segunda evidência é a
  específica para essa pergunta;
- a autoridade global de energia continua intacta e não passa a decidir
  conformidade de máscara.

### Correção aplicada — D-053

Foi removido o corte de confiança semântica da reconciliação física do primeiro
CHECK.

Agora:

```text
H1 / reference gate
+ expected=ON
+ classified=OFF
→ solicitar prova física same-mask

prova disponível
+ same_mask_comparison=True
+ referência ON/OFF discriminante
+ winner=powered
→ reconciliar para ON

winner=off/tie
OU referência não discriminante
OU evidência ausente
→ preservar OFF
```

A confiança semântica anterior continua registrada em telemetria para DEBUG, mas
não funciona mais como veto da prova física.

O H1 continua exigindo 28/28 no mesmo frame. Nenhuma aprovação parcial foi
criada.

### Proteções mantidas

- máscara esperada OFF não participa da reconciliação;
- segmento realmente apagado continua OFF mesmo com confiança semântica alta;
- foto do próprio H1 não aprova sozinha;
- BOARD_OFF independente continua obrigatório para a prova relativa;
- referência ON/OFF não discriminante não possui autoridade;
- nenhum threshold global de ON/OFF foi reduzido;
- nenhum timer, worker, scheduler ou fila foi adicionado.

### Regressões automatizadas

Foram adicionadas/ajustadas regressões para reproduzir exatamente:

```text
MASK_013
confidence=0.5944
semantic=OFF
physical=powered
→ reconciliada ON
```

Também foi mantido o teste oposto:

```text
expected=ON
semantic=OFF com confidence=0.95
physical=off
→ continua OFF
→ H1 não aprova
```

O workflow **Display F3 fast H1 BLUE tests** passou no HEAD da correção.

Os workflows que permanecem vermelhos no repositório são os mesmos que já
falhavam no commit imediatamente anterior a esta mudança; não foram introduzidos
por esta correção.

### Próximo reteste físico

```text
apresentar H1 correto
→ 7 segmentos ON devem ser reconhecidos
→ MASK_013 não deve permanecer OFF
→ H1 deve fechar 28/28
→ avançar para BLUE
```

Depois do PASS, repetir o teste de segurança com um segmento H1 esperado ON
realmente apagado. O H1 não pode avançar nesse cenário.

---

## 02/10/2026 — Registro consolidado das últimas ocorrências: reflexos, BLUE, H1, zoom e D-053

**Tipo:** consolidação histórica das últimas ocorrências e correções.

Este bloco não substitui os registros individuais anteriores. Ele existe para
manter, em um único ponto, a sequência completa de falhas recentes, diagnóstico,
tentativas, correções e estado de validação, evitando que uma manutenção futura
trate cada sintoma como problema novo e repita soluções já descartadas.

### 1. Reflexos no espelho visual do H1

**Resultado físico:** FAIL.

No H1 correto, somente os segmentos:

```text
MASK_008
MASK_009
MASK_011
MASK_012
MASK_013
MASK_017
MASK_020
```

estavam realmente acesos.

O espelho visual também marcava como ON, por reflexo/ruído:

```text
MASK_010
MASK_014
MASK_018
MASK_021
```

A origem foi isolada no sampler visual leve. O fallback de brilho absoluto
voltava a promover como ON ROIs intermediárias que a separação relativa já
havia rejeitado.

**Correção:** o fallback absoluto passou a atuar somente quando a separação
relativa não está disponível. Quando existe contraste relativo utilizável, ele
prevalece e os candidatos intermediários permanecem rejeitados.

**Estado:** correção implementada; reteste físico específico de reflexos
permanece como histórico pendente quando não houver confirmação posterior.

### 2. BLUE correto preso em 25/28

**Resultado físico:** FAIL.

Após H1, o BLUE correto ficou em 25/28 por falso OFF de:

```text
MASK_021
MASK_023
MASK_024
```

A evidência direta `CHECK x PLACA DESLIGADA` mostrava 18/18 máscaras esperadas
ON como energizadas, mas a autoridade semântica estrita mantinha as três como
OFF ambíguas.

**Correção D-051:** CHECK intermitente ganhou suporte físico same-mask somente
para falso OFF ambíguo, preservando a classificação estrita e o debounce de NG.

**Proteção mantida:** `MASK_024` realmente apagada não pode receber suporte
ON e deve continuar chegando a NG após persistência.

**Estado:** correção implementada; validação física completa do BLUE correto e
do BLUE com defeito real continua sendo a referência de segurança.

### 3. H1 correto preso em 26/28

**Resultado físico:** FAIL.

O primeiro H1 apresentou:

```text
MASK_012 expected=ON classified=OFF confidence≈0.527
MASK_020 expected=ON classified=OFF confidence≈0.511
```

enquanto:

```text
GABARITO EXATO H1 = 28/28
CHECK x PLACA DESLIGADA = 7 powered / 0 off / 0 tie
```

D-051 não cobria o caso porque H1 não é intermitente.

**Correção D-052:** foi criada reconciliação física exclusiva do primeiro
CHECK/reference gate, inicialmente limitada a falso OFF semântico com
`confidence < 0.58`.

**Estado:** a implementação resolveu o cenário automatizado de
`MASK_012/MASK_020`, mas o teste físico seguinte provou que o limite fixo ainda
era insuficiente.

### 4. Reteste D-052: H1 correto preso em 27/28 por MASK_013

**Resultado físico:** FAIL.

No reteste seguinte:

```text
H1 = 27/28
MASK_013 expected=ON
semantic classified=OFF
semantic confidence=0.5944
```

No mesmo frame:

```text
gabarito exato = 28/28
MASK_013 template_similarity=0.9920
CHECK x PLACA DESLIGADA:
  powered_votes=7
  off_votes=0
  tie_votes=0
  MASK_013 winner=powered
```

Foi preservada uma divergência importante do DEBUG:

- a autoridade global de energia publicou 6 ON + 1 OFF para `MASK_013`;
- a comparação física direta do CHECK contra BOARD_OFF publicou 7/7 powered.

A conclusão foi que os dois blocos respondem perguntas diferentes:

- autoridade global de energia → existe energia física suficiente no display;
- comparação direta same-mask do CHECK → esta máscara específica está mais
  próxima do extremo ON ou do extremo OFF.

O erro da D-052 foi usar `confidence < 0.58` como condição para permitir a
segunda pergunta.

### 5. Correção D-053 do H1

O limite semântico fixo foi removido como gate da reconciliação física.

Agora, no primeiro CHECK não intermitente:

```text
expected=ON + classified=OFF
→ consultar prova física same-mask

same_mask_comparison=True
+ referência ON/OFF discriminante
+ winner=powered
→ reconciliar para ON

winner=off/tie
OU referência não discriminante
OU evidência indisponível
→ manter OFF
```

A confiança semântica continua registrada em telemetria, mas não pode vetar uma
prova física direta independente.

**Proteções:**

- H1 continua exigindo 100% das máscaras conformes no mesmo frame;
- máscara esperada OFF nunca é promovida por essa regra;
- foto do próprio H1 não aprova sozinha;
- BOARD_OFF independente continua obrigatório;
- segmento realmente apagado continua OFF mesmo com confiança semântica alta;
- nenhum threshold global foi reduzido;
- nenhum timer/worker/scheduler foi criado.

**Validação automática:** o caso real de `MASK_013 confidence=0.5944` foi
reproduzido e passou; o caso oposto `semantic OFF confidence=0.95 +
physical=off` também passou mantendo a falha.

**Validação física D-053:** ainda pendente. O próximo teste esperado é:

```text
H1 correto
→ 7 segmentos esperados ON
→ 28/28
→ H1 CONCLUÍDO
→ avanço para BLUE
```

Depois do PASS, repetir com um segmento H1 esperado ON realmente apagado; o H1
não pode avançar.

### 6. Regressão do zoom físico: zoom "se desfez"

**Resultado físico:** FAIL operacional.

Durante o uso do F3, o zoom físico da câmera deixou de permanecer aplicado,
embora a configuração do Projeto Display continuasse salva.

#### Causa

O runtime guardava uma assinatura lógica do último zoom enviado. Se a câmera ou
o driver reinicializasse `CAP_PROP_ZOOM`/controle equivalente sem alterar essa
assinatura, o ODIN concluía incorretamente:

```text
assinatura não mudou
→ zoom já aplicado
→ não reaplicar
```

Assim, o hardware podia voltar a 1× e o F3 permanecer convencido de que o zoom
configurado ainda estava ativo.

#### Correção aplicada — D-054

A assinatura lógica passou a ser validada contra o readback real do serviço
canônico de controles da câmera, quando esse readback existe.

```text
zoom solicitado = zoom lido do hardware
→ manter assinatura / não duplicar comando

zoom solicitado != zoom lido do hardware
→ considerar zoom físico perdido
→ reaplicar configuração salva
```

Também foram preservadas as seguintes guardas:

- alteração de câmera pendente não recebe comando duplicado;
- enquanto CONFIGURAR está aberto, a recuperação automática não sobrescreve
  ajuste ainda não salvo do operador;
- backend sem readback continua compatível;
- nenhum novo timer, thread, worker ou scheduler foi criado;
- a correção reutiliza o repaint/coordenador canônico existente.

**Validação automática:** passaram os testes de readback igual, reset de
hardware, comando pendente e contratos de zoom/preview.

**Validação física do zoom após D-054:** pendente de confirmação explícita.

### 7. Situação dos testes/CI durante essas correções

O gate específico relacionado ao problema atual ficou verde:

```text
Display F3 fast H1 BLUE tests = PASS
```

Dentro dele passaram, entre outros:

```text
H1 MASK_013 confidence=0.5944 + physical powered → reconciliado
H1 segmento realmente apagado + physical off → não reconciliado
runtime H1 → reconciliação válida → avanço oficial
```

Outros workflows do repositório continuaram vermelhos durante a mesma janela,
mas já apresentavam falhas no HEAD imediatamente anterior às alterações de
D-053. Eles não foram tratados como parte desta etapa para evitar misturar
escopos e mascarar regressões históricas não relacionadas.

### 8. Regra para manutenção futura

Não repetir as seguintes estratégias como solução isolada:

- aumentar arbitrariamente `0.58` para outro threshold próximo;
- usar o gabarito exato do próprio CHECK como aprovação independente;
- usar a autoridade global de energia como substituta da conformidade individual;
- criar outro classificador, timer, worker ou scheduler para contornar o F3;
- concluir que um segmento está realmente apagado quando
  `CHECK x PLACA DESLIGADA` da mesma máscara prova `powered`;
- confiar apenas no último comando lógico de zoom sem observar o readback real,
  quando o backend disponibiliza essa informação.

As autoridades permanecem separadas:

```text
câmera/zoom → serviço canônico de câmera
presença → F3PresenceAuthority
energia → F3PowerAuthority
conformidade por máscara → analyzer estrito + reconciliação física restrita
sequência → state machine do F3
scheduler → F3RuntimeCoordinator
debug → observador
```

**Estado consolidado em 02/10/2026:**

```text
Reflexos live: correção implementada
BLUE 25/28: D-051 implementada
H1 26/28: D-052 implementada, depois refinada
H1 27/28 MASK_013: D-053 implementada
Zoom físico perdido: D-054 implementada
H1 D-053: pendente de reteste físico
Zoom D-054: pendente de reteste físico explícito
```

---

## 02/10/2026 — FAIL físico após D-053: H1 ainda 27/28 porque reconciliação recebeu a autoridade global errada

**Resultado físico:** FAIL.

### Cenário

Projeto `CM_500_L`, primeiro CHECK `CHECK_001 / H1`, não intermitente,
rotação visual 180°.

O operador apresentou o H1 correto, com os sete segmentos esperados ON
fisicamente acesos. Mesmo assim a tela permaneceu em:

```text
AGUARDANDO H1
MÁSCARAS • H1 NÃO CONFIRMADO • 27/28 CONFORMES
6 ACESOS • 22 APAGADOS • FALHA MASK_013
```

### Evidência do mesmo frame

O relatório confirmou:

```text
ESTADO DA PLACA: PRESENTE • CONFIRMADA
ENERGIA DO DISPLAY: CONFIRMADA
CHECK LÓGICO: H1
GATE PRODUTIVO: LIBERADO
ANÁLISE BRUTA H1: 27/28
```

A única divergência semântica continuou sendo:

```text
MASK_013
expected=ON
classified=OFF
confidence=0.5937
```

A comparação física direta do próprio CHECK contra BOARD_OFF, porém, mostrou:

```text
expected_on=7
powered_votes=7
off_votes=0
tie_votes=0
MASK_013 winner=powered
```

### Nova evidência decisiva

Diferente dos testes anteriores, o DEBUG do runtime agora expôs também qual
evidência a D-053 realmente recebeu:

```text
reference_gate_physical_tie_breaker_ids=[]
reference_gate_physical_tie_breaker_source=f3_unified_live_mask_power_authority
effective_failed_mask_ids=[MASK_013]
```

Isto provou que a D-053 não estava falhando por threshold nem porque
`MASK_013` estava fisicamente OFF.

A reconciliação do H1 estava recebendo a **autoridade global de energia**, e não
a comparação direta same-mask que o diagnóstico manual mostrou como 7/7
`powered`.

### Causa confirmada no código

A autoridade unificada v2 mantém compatibilidade com wrappers antigos
substituindo dinamicamente:

```text
avaliar_evidencia_energia_relativa_display_f3
→ avaliar_evidencia_energia_unificada_display_f3
```

O método recém-criado para D-052/D-053,
`F3PowerAuthority.evaluate_current_check_relative()`, chamava esse mesmo nome
substituível.

Portanto a sequência real era:

```text
D-053 pede prova física direta da MASK_013
→ chama nome legado
→ camada v2 já reapontou esse nome
→ retorna f3_unified_live_mask_power_authority
→ MASK_013=off
→ nenhum tie-breaker aplicado
→ H1 permanece 27/28
```

Enquanto isso o diagnóstico direto, que executava a comparação
BOARD_OFF/LIVE/ON do CHECK, continuava publicando `MASK_013=powered`.

### Correção aplicada — D-055

A comparação direta do CHECK atual foi separada em uma primitiva estável:

```text
avaliar_evidencia_energia_check_relativa_display_f3
```

`F3PowerAuthority.evaluate_current_check_relative()` agora chama somente essa
primitiva.

O símbolo legado continua disponível e pode ser reapontado pela energia v2 para
não quebrar consumidores históricos.

Também foi fixada a fonte da comparação direta como:

```text
f3_same_mask_relative_power_authority
```

para que um novo DEBUG deixe explícito se a reconciliação voltou a consumir a
autoridade errada.

### Regressão adicionada

O teste reproduz deliberadamente o conflito:

```text
nome legado → f3_unified_live_mask_power_authority / MASK_013=off
primitiva estável → f3_same_mask_relative_power_authority / MASK_013=powered
```

e exige que `F3PowerAuthority.evaluate_current_check_relative()` use a
primitiva estável.

O gate rápido H1/BLUE também passou a executar explicitamente essa regressão.

### Proteções mantidas

- D-053 continua sem usar threshold semântico como veto;
- H1 continua exigindo 28/28;
- segmento realmente apagado continua sem reconciliação quando a comparação
  física direta retorna OFF/tie;
- máscara esperada OFF não pode ser promovida;
- energia global continua responsável por energia global;
- nenhum novo timer, worker, scheduler, thread ou autoridade foi criado.

### Próximo reteste físico esperado

```text
H1 correto
→ análise semântica pode ainda produzir MASK_013=OFF bruto
→ reference_gate_physical_tie_breaker_source deve ser
   f3_same_mask_relative_power_authority
→ MASK_013 deve entrar em reference_gate_physical_tie_breaker_ids
→ análise efetiva deve fechar 28/28
→ H1 deve concluir e avançar
```

Teste de segurança posterior:

```text
H1 com MASK_013 realmente apagada
→ comparação direta same-mask = off/tie
→ MASK_013 não entra no tie-breaker
→ H1 não avança
```

**Estado:** CORREÇÃO D-055 IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

---

## 02/10/2026 — D-055 PASS físico no H1; novo FAIL no BLUE por falso OFF de MASK_022

### 1. Reteste H1 após D-055

**Resultado físico:** PASS.

O H1 correto deixou de permanecer preso em 27/28. A correção da D-055 passou no
equipamento real e a sequência avançou normalmente para BLUE.

Resultado observado:

```text
H1 correto
→ reconciliação física same-mask aplicada
→ H1 CONCLUÍDO
→ avanço para BLUE
```

**Estado D-055:** VALIDADA FISICAMENTE NO H1 CORRETO.

---

### 2. Novo cenário BLUE

**Resultado físico:** FAIL.

CHECK atual:

```text
CHECK_002 / BLUE
intermittent=true
18 máscaras esperadas ON
10 máscaras esperadas OFF
```

Visualmente, os segmentos 22 e 26 estavam acesos no display real.

A tela terminal mostrou:

```text
BLUE NÃO CONFIRMADO
26/28 CONFORMES
FALHA MASK_022
PLACA NG
```

No visor congelado, `MASK_026` também apareceu como OFF, apesar de estar
fisicamente acesa na imagem da câmera.

### 3. Evidência objetiva do DEBUG

O frame congelado utilizado pelo NG é o frame exato que fechou o debounce.

No analyzer efetivo mais recente:

```text
effective_classifications:
MASK_026=on
MASK_022=off

effective_failed_mask_ids:
MASK_019
MASK_022

effective_confirmed_failed_mask_ids:
MASK_022

effective_validating_mask_ids:
MASK_019
```

A fase intermitente acumulou:

```text
MASK_022 failure_count=3
persistent_failed_ids=[MASK_022]
```

A própria ROI de `MASK_022` estava saturada/acesa no frame:

```text
v_mean≈251
v_p95=251
v_p99=251
percent_hot_235=1.0
percent_hot_245=1.0
glow≈250
```

Mesmo assim o aprendizado semântico produziu:

```text
MASK_022
expected=ON
classified=OFF
confidence=0.6605
```

Para `MASK_026`, outro frame/análise efetiva do mesmo ciclo registrou
`classified=ON`, enquanto o snapshot visual congelado ainda mostrou OFF.

### 4. Prova física independente

A comparação direta:

```text
CHECK BLUE x PLACA DESLIGADA
expected_on=18
powered_votes=18
off_votes=0
tie_votes=0
```

confirmou explicitamente:

```text
MASK_026=powered
MASK_022=powered
```

Portanto o NG de `MASK_022` não corresponde a um segmento fisicamente apagado.

### 5. Causa no código

A D-051 já possuía suporte físico same-mask para falso OFF em CHECK intermitente,
mas a função `anotar_suporte_fisico_intermitente_f3()` continha um gate:

```text
semantic confidence < F3_CHECK_PHOTO_MIN_CONFIDENCE
→ consultar prova física

semantic confidence >= limite
→ não consultar
```

Como `MASK_022` chegou com `confidence=0.6605`, a prova física não foi
anotada:

```text
intermittent_power_support_confirmed_mask_ids=[]
physical_support_veto_ids=[]
MASK_022 acumulou 3 falhas
→ NG
```

A confiança semântica não mede presença física de emissão e não pode impedir a
pergunta mais específica BOARD_OFF/LIVE/ON da mesma máscara.

### 6. Correção aplicada — D-056

O corte de confiança foi removido do suporte físico intermitente.

Agora:

```text
expected=ON + semantic OFF
→ consultar same-mask físico

winner=powered + referência discriminante
→ marcar intermittent_power_confirmation=True
→ zerar contador daquela máscara na fase ON
→ reconciliar efetivamente para ON

winner=off/tie ou referência inválida
→ manter divergência
→ debounce NG segue normal
```

A função continua apenas anotando evidência. A reconciliação permanece no
runtime intermitente já existente.

### 7. Regressões adicionadas

Caso real:

```text
MASK_022
semantic OFF
confidence=0.6605
physical powered
→ suporte físico confirmado
```

Caso de segurança:

```text
semantic OFF
confidence=0.95
segmento fisicamente apagado
physical off
→ nenhum suporte
→ OFF preservado
```

### 8. Próximo reteste físico

```text
H1 correto
→ avança para BLUE

BLUE correto
→ MASK_022 e MASK_026 fisicamente ON
→ ambas devem aparecer ON na análise efetiva/visor
→ nenhuma delas pode acumular falha persistente
→ BLUE deve concluir sem NG
```

Depois repetir com um segmento BLUE esperado ON realmente apagado:

```text
same-mask=off/tie
→ sem suporte físico
→ falha persiste
→ NG correto
```

**Estado:** H1 D-055 PASS FÍSICO; BLUE D-056 CORRIGIDA — PENDENTE DE RETESTE FÍSICO.

---

## 02/10/2026 — Reteste D-056 FAIL físico: falso NG migrou para MASK_024 no BLUE

**Resultado físico:** FAIL.

### Cenário

Projeto `CM_500_L`, CHECK `CHECK_002 / BLUE`, intermitente, após o H1 ter sido
concluído corretamente.

O padrão BLUE apresentado estava correto. Visualmente, o segmento 24 estava
aceso no display físico, mas o ODIN encerrou o CHECK como NG.

A tela terminal mostrou:

```text
PLACA NG
BLUE NÃO CONFIRMADO
24/28 CONFORMES
14 ACESOS
14 APAGADOS
FALHA MASK_024
```

Na câmera congelada, `MASK_024` foi destacada em vermelho mesmo com emissão
visível no segmento físico correspondente.

### Evidência objetiva do DEBUG

O frame congelado é o mesmo frame que fechou o NG.

A análise efetiva registrou:

```text
effective_failed_mask_ids:
MASK_019
MASK_021
MASK_022
MASK_024

effective_confirmed_failed_mask_ids:
MASK_024

effective_validating_mask_ids:
MASK_019
MASK_021
MASK_022
```

No debounce intermitente:

```text
MASK_024 failure_count=3
candidate_failed_ids=[MASK_024]
persistent_failed_ids=[MASK_024]
physical_support_veto_ids=[]
```

Portanto, nesta execução, a falha que efetivamente fechou o NG foi
`MASK_024`.

### Contradição física registrada

O próprio frame mostra evidências conflitantes entre caminhos de análise.

A análise semântica por aprendizado classificou:

```text
MASK_024
expected=ON
classified=OFF
confidence=0.6414
v_mean≈250.99
v_p95=252
v_p99=255
glow≈252.85
```

O gabarito exato da foto do BLUE, porém, classificou a mesma máscara como:

```text
MASK_024
expected=ON
classified=ON
template_similarity=0.9113
```

E a comparação direta:

```text
CHECK BLUE x PLACA DESLIGADA
expected_on=18
powered_votes=18
off_votes=0
tie_votes=0
MASK_024 winner=powered
```

confirmou que `MASK_024` estava no lado físico ON.

### Evidência de que a D-056 ainda não chegou à autoridade correta neste caso

Apesar da prova física direta acima:

```text
intermittent_power_support_confirmed_mask_ids=[]
physical_support_veto_ids=[]
```

No mesmo relatório existe outra leitura de energia do CHECK com:

```text
expected_on=18
powered_votes=15
off_votes=3

MASK_026=off
MASK_022=off
MASK_024=off
```

enquanto a comparação direta `CHECK x PLACA DESLIGADA` registra as 18 como
`powered`.

Isto mostra que o problema remanescente não deve ser tratado simplesmente
aumentando confiança, debounce ou tolerância. Há uma divergência entre a prova
física direta do mesmo CHECK e a evidência que efetivamente alimenta o suporte
intermitente.

### Estado visual congelado

O snapshot terminal registrou:

```text
FALHA MASK_024
visor failed=[MASK_022, MASK_024, MASK_026]
```

e o visor/overlay congelados ainda apresentaram:

```text
MASK_026=off
MASK_022=off
MASK_024=off
```

embora as três sejam configuradas como `ON` no BLUE e a comparação direta
tenha publicado `powered` para as três.

Somente `MASK_024`, porém, estava em
`effective_confirmed_failed_mask_ids` e foi a falha persistente que fechou o
NG desta execução.

### Relação com a D-056

A D-056 removeu o veto por confiança semântica do suporte físico intermitente.
O reteste atual prova que essa alteração, isoladamente, **não resolveu o problema
físico completo**.

A falha mudou de `MASK_022` para `MASK_024`, mas o padrão estrutural
permanece:

```text
segmento esperado ON
+ segmento fisicamente ON
+ comparação direta same-mask = powered
+ suporte intermitente efetivo vazio
→ falso OFF persistente
→ NG indevido
```

### Causa

**Ainda não considerada encerrada.**

A evidência atual aponta para divergência de fonte/autoridade entre:

```text
comparação direta CHECK x BOARD_OFF
```

e

```text
evidência usada pelo suporte físico intermitente
```

Antes de nova alteração algorítmica, a próxima etapa deve identificar
explicitamente qual fonte alimentou `intermittent_power_support` para
`MASK_024` no runtime produtivo e por que ela divergiu da comparação direta
que retornou `powered`.

### Próximo reteste esperado

Após a causa ser corrigida:

```text
H1 correto
→ conclui

BLUE correto
→ MASK_022 ON
→ MASK_024 ON
→ MASK_026 ON
→ suporte físico efetivo coerente com a comparação direta
→ nenhuma dessas máscaras vira persistent_failed
→ BLUE conclui sem NG
```

Teste de segurança posterior:

```text
BLUE com um segmento esperado ON realmente apagado
→ prova física same-mask=off/tie
→ sem reconciliação
→ falha persiste
→ NG correto
```

**Estado:** D-056 RETESTADA FISICAMENTE — FAIL; MASK_024 confirmou falso NG.
Diagnóstico de autoridade/fonte pendente antes de nova correção.

---

## 02/10/2026 — Correção D-057 após falso NG de MASK_024 no BLUE

**Estado:** CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

### Causa confirmada no caminho produtivo

O reteste D-056 mostrou que remover o corte de confiança não bastava.

O `F3StrictMaskConformityAnalyzer` continuava calculando
`intermittent_power_confirmation` com um conjunto local de features derivado do
aprendizado. Essa evidência era a que o debounce consultava.

Em paralelo, `F3PowerAuthority.evaluate_current_check_relative()` comparava
diretamente o mesmo `MASK_xxx` em:

```text
BOARD_OFF
LIVE do frame atual
foto ON do CHECK atual
```

e no frame que fechou o falso NG retornou 18/18 `powered`, inclusive
`MASK_022`, `MASK_024` e `MASK_026`.

Portanto existiam duas respostas concorrentes para a mesma pergunta física.
O debounce estava ligado à resposta local do analyzer, enquanto o DEBUG exibia
a comparação direta canônica.

### Correção aplicada — D-057

Antes de observar/contar a fase intermitente, o runtime agora consulta:

```text
F3PowerAuthority.evaluate_current_check_relative()
```

A análise recebe então a evidência canônica da mesma máscara. Para cada falso
OFF `expected=ON`:

```text
source=f3_same_mask_relative_power_authority
+ same_mask_comparison=True
+ reference_discriminative=True
+ winner=powered
→ intermittent_power_confirmation=True
```

Qualquer confirmação previamente calculada pelo analyzer é preservada apenas
como diagnóstico em `intermittent_learning_support*` e deixa de participar da
decisão.

Se a fonte recebida for `f3_unified_live_mask_power_authority`, a evidência é
explicitamente rejeitada para esse uso individual.

### Efeito esperado no caso físico observado

No BLUE correto do reteste:

```text
MASK_022 direct same-mask=powered
MASK_024 direct same-mask=powered
MASK_026 direct same-mask=powered
```

as três devem ser protegidas antes de incrementar `failure_count`. Assim nenhuma
delas deve alcançar `persistent_failed_ids` por falso OFF semântico.

### Proteções mantidas

- o debounce intermitente continua com 3 amostras para falha real;
- fase OFF/transição do pisca continua sem julgamento de NG;
- máscara esperada OFF não recebe esse suporte;
- `off`/`tie` físico não é promovido;
- H1 continua usando a mesma autoridade física estável já validada pela D-055;
- nenhuma aprovação parcial foi introduzida;
- nenhum timer, thread, worker, scheduler ou nova autoridade foi criado.

### Validação automatizada

Foram adicionadas regressões para:

```text
MASK_024 confidence=0.6414 + direct powered
→ suporte físico canônico confirmado

fonte global/unificada + winner=powered
→ NÃO pode confirmar suporte individual

MASK_022 + MASK_024 + MASK_026 falsos OFF
+ direct same-mask powered para os três
→ runtime reconcilia os três
→ nenhum confirmed_failed
→ BLUE pode avançar
```

### Próximo reteste físico

```text
H1 correto → conclui

BLUE correto
→ MASK_022 ON
→ MASK_024 ON
→ MASK_026 ON
→ physical_support_veto_ids inclui os falsos OFF físicos
→ persistent_failed_ids vazio
→ BLUE conclui sem NG
```

Depois, repetir com um segmento BLUE esperado ON realmente apagado; nesse caso
a autoridade direta deve retornar `off/tie` e o NG deve continuar ocorrendo.

---

## 02/10/2026 — Reteste D-057 FAIL: BLUE correto permanece 26/28

**Resultado físico:** FAIL.

### Cenário

Projeto `CM_500_L`, CHECK `CHECK_002 / BLUE`, intermitente. O H1 já havia
concluído. O operador apresentou o BLUE correto, com os segmentos corretos
acesos/apagados, mas o sistema permaneceu em `AGUARDANDO BLUE`.

Tela observada:

```text
BLUE NÃO CONFIRMADO
26/28 CONFORMES
16 ACESOS
12 APAGADOS
AUTO • BLUE • leitura incerta • continuando busca
```

Não houve NG terminal; o CHECK ficou preso sem avançar.

### Evidência do DEBUG

O frame manual do clique foi `frame_id=550`, estável, com energia confirmada
e gate produtivo liberado.

A comparação física direta do BLUE contra BOARD_OFF confirmou:

```text
expected_on=18
powered_votes=18
off_votes=0
tie_votes=0
```

A D-057 chegou ao runtime: a autoridade física canônica confirmou suporte para
`MASK_019`, `MASK_021`, `MASK_022` e `MASK_024` usando
`f3_same_mask_relative_power_authority`.

Mesmo assim apenas `MASK_021` e `MASK_024` entraram em
`intermittent_physical_support_veto_ids`.

O estado efetivo permaneceu:

```text
effective_failed_mask_ids=[MASK_019, MASK_022]
effective_confirmed_failed_mask_ids=[]
effective_validating_mask_ids=[MASK_019, MASK_022]
effective_matched_mask_count=26
candidate_failed_ids=[]
persistent_failed_ids=[]
```

`MASK_019` e `MASK_022` estavam semanticamente OFF, porém a própria
`F3PowerAuthority` marcou ambas como `powered` e
`intermittent_power_confirmation=true`.

Também foi observada divergência temporal entre o frame manual congelado
(`550`) e o snapshot do runtime/autoridade (`533`). Em CHECK intermitente,
essa diferença precisa ser investigada porque uma fase anterior não pode
continuar bloqueando um frame posterior correto.

### Estado da investigação

**Causa ainda não encerrada.** A autoridade física correta já está chegando ao
runtime, mas existe uma quebra entre a confirmação física, a aplicação do veto
intermitente e a classificação efetiva usada para liberar o OK.

Próxima investigação: rastrear `frame_token/frame_id` e o caminho exato que faz
`MASK_019` e `MASK_022` permanecerem em `effective_failed_mask_ids` mesmo com
confirmação física `powered`.

**Estado:** D-057 RETESTADA FISICAMENTE — FAIL PARCIAL; BLUE preso em 26/28.

---

---

## 02/10/2026 — Correção D-058 após BLUE preso em 26/28

**Estado:** CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

### Causa confirmada

O reteste D-057 mostrou que a F3PowerAuthority já chegava corretamente ao
runtime e publicava quatro falsos OFF fisicamente confirmados:

```text
intermittent_power_support_confirmed_mask_ids:
MASK_019
MASK_021
MASK_022
MASK_024
```

Porém o observador da fase intermitente não consumia essa lista como contrato.
Ele voltava a decidir máscara por máscara por
`intermittent_power_confirmation`, mantendo uma segunda interpretação do
mesmo suporte físico.

O resultado real foi:

```text
canonical confirmed = MASK_019, MASK_021, MASK_022, MASK_024
physical veto       = MASK_021, MASK_024
effective failed    = MASK_019, MASK_022
matched             = 26/28
```

Portanto a falha desta etapa estava no **consumidor da autoridade física**, não
na F3PowerAuthority e não em threshold óptico.

### Correção aplicada — D-058

`_display_auto_observe_intermittent_phase()` agora consome diretamente
`intermittent_power_support_confirmed_mask_ids` quando o envelope confirma:

```text
authoritative=true
source=f3_same_mask_relative_power_authority
authority=f3_power_authority_current_check_relative
```

Para um `expected=ON/classified=OFF` presente nessa lista:

```text
contador de falha = 0
→ entra em physical_support_veto_ids
→ reconciliação efetiva para ON
```

A aplicação ocorre antes do corte de confiança semântica. Assim a evidência
física independente não volta a ser bloqueada por confiança do classificador
aprendido.

A antiga interpretação produtiva por
`_display_auto_physical_support_confirms_expected(item)` foi removida. Os
campos individuais continuam somente como telemetria/DEBUG.

### Proteções mantidas

- fonte global/unificada não concede suporte individual;
- envelope não autorizado não concede veto;
- campo local `intermittent_power_confirmation=True` sozinho não concede veto;
- segmento realmente apagado continua acumulando falha e pode fechar NG após
  debounce;
- nenhuma alteração de threshold, debounce, timer, thread, worker, scheduler ou
  fila;
- nenhuma mudança foi aplicada ao pipeline assíncrono/frame scheduling nesta
  etapa.

### Regressões adicionadas/fortalecidas

```text
019/021/022/024 falsos OFF
+ lista canônica confirma os quatro
+ item local de 019/022 stale
+ confidence de 019/022 abaixo do limiar
→ veto físico contém os quatro
→ 28/28
```

Também foi adicionado o caso de segurança:

```text
campo local diz physical confirmation
+ lista canônica autorizada ausente
→ não recebe veto
→ falha real continua persistente
```

O teste isolado do observador usa `confidence=0.49` para provar que a lista
canônica não é filtrada por confiança semântica. O teste integrado do BLUE usa
o valor observado fisicamente em `MASK_022` (`confidence=0.538`) junto da
prova canônica `powered`; o CHECK deve continuar avançando.

### Próximo reteste físico

```text
H1 correto
→ conclui

BLUE correto
→ qualquer falso OFF semântico que esteja na lista canônica powered
   entra no mesmo physical_support_veto_ids
→ effective_failed_mask_ids=[]
→ 28/28
→ BLUE conclui e avança para USB
```

Depois, repetir com um segmento BLUE esperado ON realmente apagado:

```text
same-mask=off/tie
→ não entra na lista canônica confirmada
→ sem veto
→ falha persiste
→ NG após debounce
```

A diferença já observada entre frame manual 550 e snapshot produtivo 533
permanece registrada. Ela será reavaliada somente se o reteste D-058 ainda
mostrar evidência stale.

---

---

## 02/10/2026 — Reteste D-058 FAIL: BLUE 28/28 não avança

**Resultado físico:** FAIL.

### Cenário

Projeto `CM_500_L`, CHECK `CHECK_002 / BLUE`, intermitente. O H1 concluiu e
o BLUE correto foi apresentado. Visualmente os 18 segmentos esperados ON e os
10 esperados OFF estavam corretos.

A própria UI produtiva confirmou:

```text
MÁSCARAS • BLUE DETECTADO • 28/28 CONFORMES • 18 ACESOS • 10 APAGADOS
ANÁLISE VISUAL: CHECK BLUE • máscaras 28/28
```

Mesmo assim o fluxo permaneceu em:

```text
AGUARDANDO BLUE
AUTO • BLUE • leitura incerta • continuando busca
```

e não avançou para USB.

### Evidência objetiva do DEBUG

Frame manual:

```text
frame_id=708
frame_id_estavel=SIM
CHECK LÓGICO=BLUE
GATE PRODUTIVO=LIBERADO
ENERGIA DO DISPLAY=CONFIRMADA
```

O runtime produtivo observado no mesmo clique publicou:

```text
last_auto_analysis.ready=true
last_auto_analysis.approved=true
effective_matched_mask_count=28
effective_failed_mask_ids=[]
effective_confirmed_failed_mask_ids=[]
effective_validating_mask_ids=[]
```

A D-058 funcionou no ponto que pretendia corrigir: os falsos OFF ainda presentes
no analyzer foram reconciliados pela autoridade física canônica e o estado
efetivo chegou a 28/28. Neste frame, `MASK_019` e `MASK_023` entraram em
`intermittent_physical_support_veto_ids`, sem falha persistente.

Apesar disso, o estado de decisão permaneceu:

```text
sequence.current_check=BLUE
last_decision=null
stable_frames=0
transition_frames=0
manual_entry_signature=null
last_result=null
```

Também aparece no mesmo snapshot uma inconsistência diagnóstica secundária:

```text
exact_all_masks_approved=false
positive_probe_approved=false
positive_probe_reason=check_completo_nao_conforme
```

enquanto a análise produtiva efetiva já está 28/28 e `approved=true`. A sonda
positiva não é autoridade produtiva no runtime canônico, mas essa divergência é
importante para rastrear qual camada ainda está zerando/bloqueando a decisão.

### Conclusão desta etapa

D-058 **resolveu o bloqueio de conformidade das máscaras**, mas não resolveu o
avanço do CHECK. O defeito mudou de estágio:

```text
ANTES:
BLUE correto
→ efetivo 26/28
→ bloqueado por máscaras

AGORA:
BLUE correto
→ efetivo 28/28
→ gate físico liberado
→ ainda não registra/avança
```

Portanto não deve ser aplicada uma terceira alteração algorítmica por tentativa.
Pela regra das duas tentativas, a próxima etapa é diagnóstico do caminho final
de decisão/registro.

### Diagnóstico exigido no próximo reteste

O runtime já foi instrumentado para expor, no snapshot manual:

```text
auto_last_frame_token
auto_decision_trace
final_stability
final_stability_last_frame
physical_transition_authority_status
```

O próximo DEBUG deve mostrar exatamente qual etapa entre:

```text
análise 28/28
→ policy OK
→ estabilidade final
→ autoridade de transição física
→ registrar_resultado_check_display_f3(True)
→ check_advanced
```

está interrompendo o avanço.

**Estado:** D-058 RETESTADA FISICAMENTE — FAIL PARCIAL; conformidade 28/28
confirmada, avanço do BLUE ainda bloqueado.

---
## 02/10/2026 — Mudança de direção após D-058: percepção visual F3 passa para trilha neural

**Estado:** DECISÃO ARQUITETURAL ACEITA — D-059.

O reteste D-058 permanece registrado como FAIL parcial e não é apagado. Porém,
por decisão explícita do produto, a investigação deixou de buscar uma nova
correção convencional para o julgamento visual do F3.

A partir deste ponto:

```text
não continuar:
threshold → veto → probe → debounce → wrapper → novo fix

seguir:
configuração F3 existente
→ referência + contorno + máscaras + mask_states
→ detector neural de estados dos segmentos
→ comparação esperada x observada
→ OK / NG / INCERTO
→ state machine
```

A primeira etapa será restrita ao **H1**. O objetivo é provar fisicamente que a
autoridade neural:

- aprova H1 quando os 28 estados observados correspondem ao configurado;
- rejeita H1 com um único segmento esperado ON apagado;
- não transforma reflexo em segmento ON;
- tolera pequenas variações de posição e iluminação dentro do escopo treinado;
- não introduz latência perceptível no fluxo;
- não depende de nuvem, API paga ou decisão manual do operador.

As imagens, contornos e máscaras já configurados no Projeto Display serão
reaproveitados como referência/anotação inicial.

Os CHECKS ainda não migrados podem continuar temporariamente no caminho atual
para permitir migração incremental, mas a partir da D-059 **não é prioridade
adicionar novas heurísticas convencionais ao H1**.

**Próximo passo:** projetar e implementar somente a Etapa N1 — H1 neural — e
submeter ao reteste físico antes de migrar BLUE.
## 05/10/2026 — N1 físico #1: H1 correto chega à CNN, mas 28/28 ficam INCERTOS

Modo:
- Display F3 em produção;
- CHECK atual: H1 / CHECK_001;
- modelo neural `cm_500_l_segments.onnx` já treinado e aceito pelo gate N1.3;
- placa fisicamente correta;
- H1 fisicamente correto segundo validação do usuário.

Evidência do mesmo snapshot:
- placa PRESENTE e CONFIRMADA;
- energia do display CONFIRMADA;
- gate produtivo LIBERADO;
- autoridade visual produtiva: `f3_h1_neural_segment_detector`;
- `neural_visual_authority=true`;
- `conventional_visual_authority_used=false`;
- modelo `ready=true`;
- batch neural = 28 máscaras;
- `load_count=1`;
- `inference_count=355`;
- limiares produtivos atuais:
  - OFF se `P(ON) <= 0.20`;
  - ON se `P(ON) >= 0.80`;
  - intervalo intermediário = INCERTO;
- resultado final da CNN no frame:
  - `matched_mask_count=0`;
  - `uncertain_mask_count=28`;
  - motivo `h1_neural_incerto`.

Diagnóstico quantitativo da própria saída neural:
- máscaras esperadas ON:
  - `P(ON) min=0.564678`;
  - média `0.666891`;
  - max `0.756886`;
- máscaras esperadas OFF:
  - `P(ON) min=0.291826`;
  - média `0.331517`;
  - max `0.523389`;
- direção bruta por argmax 0.5, **somente para diagnóstico**:
  - 27/28 compatíveis com o H1 correto;
  - única divergência: `MASK_010` esperada OFF com `P(ON)=0.523389`;
- existe separação positiva no frame entre as duas classes:
  - menor ON esperado = `0.564678`;
  - maior OFF esperado = `0.523389`;
  - gap diagnóstico = `+0.041289`;
  - midpoint diagnóstico = `0.544034`.

Interpretação:
- o runtime neural está instalado, carregando o ONNX e inferindo as 28 máscaras;
- o bloqueio atual não é falta de modelo nem veto do classificador convencional;
- a CNN está ordenando ON/OFF de forma útil no frame live, mas os limiares
  `0.20/0.80` estão muito distantes das probabilidades observadas no domínio
  real da câmera;
- ainda não é seguro simplesmente baixar limiares com base em um único frame
  correto, porque precisamos preservar detecção de segmento realmente apagado,
  reflexo, movimento e variação de luz.

Correção de observabilidade aplicada:
- DEBUG TÉCNICO passa a destacar a autoridade neural no topo;
- exibe modelo, batch, inference count e limiares;
- exibe `P(ON)` min/média/max para classes esperadas ON e OFF;
- exibe argmax bruto e máscaras divergentes explicitamente como
  **diagnóstico sem autoridade**;
- exibe gap/midpoint de separação live somente para calibração;
- H1 com 28 máscaras incertas deixa de ser descrito como "NÃO CONFORME" no
  resumo e passa a ser "INDETERMINADO";
- a trava visual legada "aguardando primeiro segmento ON" deixa de esconder a
  decisão neural quando `neural_visual_authority=true`; presença/energia
  continuam com suas autoridades próprias, e a policy neural continua
  responsável por INCERTO/OK/NG.

Resultado:
- N1 físico #1 = **FAIL CONTROLADO / DIAGNÓSTICO OBTIDO**;
- nenhum limiar neural produtivo foi alterado neste passo;
- nenhuma autoridade convencional de ON/OFF foi reativada.

Próximo reteste:
1. atualizar código e repetir H1 correto;
2. capturar DEBUG TÉCNICO em mais de uma condição física correta:
   posição nominal, pequeno deslocamento e pequena variação de iluminação;
3. comparar distribuições `P(ON)` de ON/OFF entre os snapshots;
4. somente então definir calibração neural e repetir:
   H1 correto, um segmento ON apagado, reflexo em OFF e deslocamento.

Não repetir:
- não baixar `0.80/0.20` por tentativa visual sem dados de produção;
- não usar o argmax diagnóstico como autoridade de OK/NG;
- não restaurar o classificador convencional como fallback para fazer H1 passar.

---

## 05/10/2026 — Marco de migração: H1 convencional deixa de ser autoridade visual

**Estado:** MIGRAÇÃO DE AUTORIDADE CONFIRMADA NO RUNTIME — VALIDAÇÃO NEURAL AINDA EM ANDAMENTO.

Este registro torna explícita a mudança de produto iniciada pela D-059.

O primeiro teste físico com o modelo real confirmou no próprio runtime:

```text
CHECK=H1 / CHECK_001
reference_authority=f3_h1_neural_segment_detector
neural_visual_authority=true
conventional_visual_authority_used=false
neural_batch_size=28
neural_model.ready=true
```

Portanto, a partir deste marco:

```text
H1:
frame live
→ geometria/máscaras configuradas
→ CNN ONNX
→ 28 probabilidades ON/OFF
→ comparação determinística expected x observed
→ OK / NG / INCERTO
→ state machine
```

O classificador convencional de ON/OFF **não é mais fallback nem veto produtivo
do H1**. Ele pode existir no código histórico enquanto outros CHECKS ainda o
consomem, mas não pode decidir H1 em paralelo.

Estado da migração por CHECK:

- H1 → **NEURAL / EM VALIDAÇÃO FÍSICA**;
- BLUE → convencional temporário;
- USB → convencional temporário;
- AUX → convencional temporário.

A migração do próximo CHECK somente ocorrerá depois da validação física do H1 e
de autorização explícita para avançar a etapa.

Este marco não transforma o teste atual em PASS: o primeiro H1 correto chegou à
CNN, porém as 28 máscaras ficaram INCERTAS pelos limiares conservadores. A
migração da autoridade está confirmada; a robustez/calibração do modelo ainda
precisa ser concluída.

Não repetir:
- não restaurar o classificador convencional como fallback do H1;
- não adicionar novo threshold óptico convencional para "ajudar" a CNN;
- não migrar BLUE antes de fechar a validação física do H1.

---

## 05/10/2026 — FAIL físico D-054: zoom da câmera volta a se desfazer

**Resultado físico:** FAIL / RECORRÊNCIA DO ZOOM FÍSICO.

### Sintoma informado

Durante o uso do F3, o enquadramento ampliado voltou a se desfazer. Pela
característica observada e pela revisão do código, o suspeito atual é o
**zoom físico da câmera / CAP_PROP_ZOOM**, e não o Zoom ODIN por software.

### Revisão da D-054

A D-054 já havia introduzido a regra de conferir o readback real do hardware
antes de confiar apenas na assinatura lógica do último comando. Porém a revisão
do serviço canônico encontrou uma lacuna objetiva:

```text
CAP_PROP_ZOOM aplicado
→ readback é salvo em _camera_live_valores_hardware
→ driver pode resetar zoom depois
→ _camera_live_valores_hardware não era atualizado novamente
→ F3 continuava lendo o valor antigo
→ assinatura parecia válida
→ zoom não era reaplicado
```

Ou seja, o valor exposto por
`obter_valores_controles_camera_ao_vivo()` podia ser um readback real **antigo**,
não a situação física atual da câmera.

### Correção aplicada

O proprietário canônico da câmera passa a refrescar `CAP_PROP_ZOOM` enquanto
o zoom manual estiver habilitado:

- leitura executada na mesma thread de captura do `VideoCapture`;
- cadência limitada para não acrescentar custo por frame;
- nenhum novo timer, `after()`, worker, scheduler ou serviço;
- valores inválidos/fora da faixa, inclusive `0` típico de backend sem suporte,
  não substituem um readback válido;
- quando o driver realmente voltar a outro zoom, o cache passa a refletir a
  divergência;
- a recuperação continua sendo feita pelo mecanismo existente da D-054:
  Projeto Display → readback divergente → reaplicar zoom/pan/tilt pelo serviço
  canônico.

### Regressões adicionadas

- reset silencioso 250 → 100 precisa aparecer no readback;
- backend que devolve 0 não pode fabricar falso reset;
- zoom desabilitado não dispara leitura/revalidação desnecessária.

### Próximo reteste físico

```text
F3 aberto
→ zoom da câmera configurado > 1×
→ manter em produção por alguns minutos
→ observar se o driver tenta voltar a 1×
→ confirmar que o ODIN detecta a divergência e recupera o zoom
→ confirmar que o enquadramento permanece estável
```

Também confirmar separadamente o Zoom ODIN por software para garantir que o
sintoma atual pertence de fato ao hardware.

**Estado:** CORREÇÃO IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

---

## 05/10/2026 — N1 físico #2: H1 correto separa ON/OFF na CNN, mas thresholds 0.20/0.80 mantêm 27 máscaras INCERTAS

**Resultado físico:** FAIL CONTROLADO / CAUSA OBJETIVA IDENTIFICADA.

### Cenário

- Display F3 em produção;
- Projeto Display: `CM_500_L`;
- CHECK atual: H1 / `CHECK_001`;
- placa fisicamente correta;
- H1 fisicamente correto segundo validação do usuário;
- modelo neural `cm_500_l_segments.onnx` carregado e ativo;
- autoridade visual neural confirmada;
- classificador visual convencional sem autoridade produtiva no H1.

### Evidência produtiva

O runtime publicou:

```text
last_auto_analysis.ready=true
last_auto_analysis.approved=false
last_auto_analysis.reason=h1_neural_incerto
reference_authority=f3_h1_neural_segment_detector
neural_visual_authority=true
conventional_visual_authority_used=false
active_mask_count=28
matched_mask_count=1
uncertain_mask_count=27
```

O modelo continua usando:

```text
OFF  se P(ON) <= 0.20
ON   se P(ON) >= 0.80
INCERTO no intervalo intermediário
```

Somente `MASK_013` atravessou o limiar produtivo de ON neste frame:

```text
MASK_013 esperado ON
P(ON)=0.823357
classified=on
matched=true
```

As outras 27 máscaras permaneceram INCERTAS.

### Diagnóstico quantitativo do frame

Para as sete máscaras esperadas ON:

```text
P(ON) min = 0.684468
P(ON) média = 0.746932
P(ON) max = 0.823357
```

Para as 21 máscaras esperadas OFF:

```text
P(ON) min = 0.305094
P(ON) média = 0.355693
P(ON) max = 0.496080
```

Logo, neste frame correto:

```text
menor ON esperado = 0.684468
maior OFF esperado = 0.496080
gap = +0.188388
midpoint = 0.590274
```

A ordenação bruta por argmax 0.5 ficou **28/28 semanticamente compatível com o
H1 correto**. O bloqueio não é falta de separação entre ON e OFF neste frame;
é a banda de certeza produtiva `0.20/0.80`, que é muito mais conservadora do
que a distribuição real observada.

### Causa encontrada no código

O pipeline de treino exporta atualmente os thresholds do metadata como valores
fixos:

```text
off_max_on_probability = 0.20
on_min_on_probability  = 0.80
```

Esses valores não são calibrados a partir das probabilidades do modelo validado.
O runtime apenas lê e aplica os thresholds gravados no metadata.

Portanto, o gate offline N1.3 garante acurácia por classe/argmax no H1 mantido
fora do treino, mas o runtime produtivo exige adicionalmente probabilidades
extremas abaixo de 0.20 ou acima de 0.80. Essa segunda exigência não é derivada
da calibração real do modelo.

### Inconsistência visual secundária encontrada

A tela exibiu:

```text
H1 DETECTADO • 28/28 CONFORMES • 1 ACESO
```

enquanto a própria análise neural produtiva possuía somente `1/28` matched e
`27/28` uncertain.

O DEBUG mostra simultaneamente:

```text
matched_mask_count=1
uncertain_mask_count=27
effective_matched_mask_count=28
```

A causa é a camada de apresentação `_display_auto_publish_effective_ui_authority`:
ela conta como falha apenas máscaras com `matched is False`. No neural,
`INCERTO` usa `matched=None`; assim nenhuma das 27 incertas entra em
`raw_failed_mask_ids` e a UI calcula incorretamente `28 - 0 = 28`.

Isso é **bug de apresentação/compatibilidade**, não da policy produtiva. A policy
neural usa o `matched_mask_count` real e corretamente manteve:

```text
policy_decision=searching
policy_reason=classificacao_neural_incerta
registration_attempted=false
```

### Comparação com N1 físico #1

No primeiro reteste correto, a separação por argmax ainda era 27/28 e
`MASK_010` ficava ligeiramente do lado ON.

Neste segundo reteste, `MASK_010` esperada OFF chegou a:

```text
P(ON)=0.496080
```

e todas as sete máscaras esperadas ON permaneceram acima disso. Portanto o
segundo frame apresenta uma separação neural mais limpa do que o primeiro.

### Próxima correção recomendada

Não substituir `0.20/0.80` por um número manual escolhido apenas para este
frame.

A correção deve ser dividida em duas responsabilidades:

1. **calibração neural do modelo**
   - deixar de exportar thresholds fixos;
   - calcular/registrar thresholds derivados de evidência validada;
   - preservar uma faixa INCERTO entre OFF e ON;
   - validar também H1 com segmento realmente apagado e reflexo antes de liberar
     thresholds produtivos;

2. **UI neural**
   - `uncertain` não pode aparecer como máscara conforme;
   - status/visor devem refletir `1 conforme + 27 incertas` neste caso;
   - nenhuma correção visual pode alterar a decisão neural.

**Estado:** diagnóstico suficiente para corrigir a causa; nenhuma alteração de
threshold produtivo foi feita por tentativa neste passo.

---

## 05/10/2026 — N1 pós-diagnóstico: calibração neural deixa de usar 0.20/0.80 fixos

**Estado:** CORREÇÃO IMPLEMENTADA — PENDENTE DE RETREINO E RETESTE FÍSICO.

Esta entrada não altera o resultado dos retestes N1 #1 e #2. Ambos permanecem
registrados como FAIL controlado. A alteração abaixo trata a causa encontrada
nesses testes.

### Alteração aplicada

O pipeline neural foi ajustado para que os thresholds do H1 deixem de ser
constantes escolhidas no código.

Novo fluxo offline:

```text
H1 reservado fora do treino
→ validação original 100%
→ H1 reservado + variações determinísticas
→ inferência PyTorch e OpenCV DNN
→ medir P(ON) de OFF e ON
→ exigir max_OFF < min_ON
→ usar o gap como faixa INCERTO
→ metadata schema 3
→ promoção atômica
```

As variações usam o augmentation já existente para cobrir pequenas mudanças de
posição/escala/rotação, brilho/contraste, blur/ruído e hard-negative de reflexo
em OFF. Elas são usadas para **calibração**, não para ensinar H1 ao otimizador.

Se qualquer OFF calibrado alcançar/superar o ON calibrado mais fraco, o treino
é abortado antes da promoção. Não há fallback para `0.20/0.80`.

### Contrato produtivo

O runtime agora exige metadata `schema_version=3` com:

- origem `held_out_h1_augmented_probability_gap`;
- ambas as classes presentes;
- contagens de calibração coerentes;
- gap positivo;
- thresholds coerentes com os extremos calibrados;
- SHA-256 válido do ONNX;
- H1 declarado como CHECK reservado e aceito pelo gate independente.

O artefato anterior schema 2 passa deliberadamente a falhar fechado. Portanto,
antes do próximo teste físico é obrigatório **regenerar ONNX + JSON pelo script
oficial**; não editar o metadata manualmente.

### Correção da apresentação neural

O estado `uncertain` não é mais tratado como máscara conforme somente porque
`matched=None`.

No caso equivalente ao reteste #2:

```text
antes:
1 matched + 27 uncertain
→ UI: 28/28 CONFORMES

agora:
1 matched + 27 uncertain
→ UI: 1/28 CONFORMES • 27 INCERTOS • INDETERMINADO
```

Essa mudança é exclusivamente de apresentação/telemetria. A policy neural
continua sendo a autoridade de OK/NG/INCERTO.

### Validação de software

No HEAD da correção:

- **Display F3 neural dataset tests:** PASS;
- **Display F3 fast H1 BLUE tests:** PASS.

Os workflows de isolamento/UNKNOWN/presença que permanecem vermelhos já estavam
falhando no commit imediatamente anterior à correção; não foram usados para
mascarar nem alterar esta etapa.

Commits:

```text
1d3ca06bd52f427e297ab27b5a745d7b2eface50
08d1cb7c59e373f82e4349eaf14b64d645d27579
```

### Próximo reteste obrigatório

1. executar preflight;
2. retreinar/regenerar o artefato neural do projeto `CM_500_L`;
3. registrar os thresholds e o gap impressos pelo treino;
4. repetir H1 correto em posição nominal;
5. repetir com pequeno deslocamento e pequena variação de iluminação;
6. testar um segmento esperado ON realmente apagado;
7. testar reflexo em segmento esperado OFF;
8. capturar DEBUG caso qualquer máscara permaneça INCERTA ou diverja.

**Resultado físico desta correção:** AINDA NÃO VALIDADO.

---

## 05/10/2026 — N1.4 offline: calibração aumentada encontrou sobreposição OFF/ON; instrumentação obrigatória aplicada

**Resultado:** FAIL CONTROLADO / GATE OFFLINE BLOQUEOU PROMOÇÃO.

Após o preflight real do projeto `CM_500_L` permanecer pronto, o treinamento
voltou a atingir 100% no H1 original mantido fora da otimização:

```text
[008/060] h1_val=1.000
[009/060] h1_val=1.000
[010/060] h1_val=1.000
[011/060] h1_val=1.000
[012/060] h1_val=1.000
Early stop: 5 épocas consecutivas em 100%
```

A nova etapa de calibração N1.4, porém, recusou o artefato:

```text
max_OFF_P(ON)=0.618684
min_ON_P(ON)=0.571600
gap=-0.047084
```

Logo, pelo menos uma variação OFF recebeu `P(ON)` maior que alguma variação
ON. O contrato D-060 agiu corretamente: **nenhum metadata schema 3 foi
promovido** e o artefato produtivo não foi substituído.

### Interpretação desta falha

Este resultado não autoriza:

- reduzir a quantidade de augmentations;
- trocar o seed até "passar";
- escolher threshold manual entre 0.571600 e 0.618684;
- enfraquecer o gate de separação;
- voltar ao classificador convencional.

Também ainda não permite concluir se:

1. a CNN realmente não é robusta para alguma condição plausível; ou
2. alguma combinação sintética do augmentation gerou uma imagem pouco realista
   para o domínio físico da câmera.

Pela regra das duas tentativas, a etapa seguinte é **diagnóstico**, não nova
alteração algorítmica.

### Instrumentação aplicada

O pipeline de treino passa a preservar, sem alterar a geração das amostras:

- máscara física de origem;
- CHECK e estado esperado;
- índice da augmentation;
- seed exato;
- rotação;
- escala;
- deslocamento X/Y;
- alpha/beta de brilho;
- gamma;
- blur;
- ruído e sigma;
- reflexo sintético, centro, eixos, intensidade e ângulo;
- `P(ON)` produzido pelo OpenCV DNN.

A assinatura de `_augment_sample` recebeu apenas um coletor opcional de
diagnóstico. As mesmas chamadas ao RNG e na mesma ordem são preservadas; assim,
habilitar a instrumentação não muda o tensor que seria produzido.

Em cada treino, o ODIN salva automaticamente os cinco OFF com maior `P(ON)` e
os cinco ON com menor `P(ON)`, além de um JSON completo de resumo.

Destino local canônico:

```text
data/models/f3_neural/diagnostics/
  cm_500_l_segments_calibration_latest/
    calibration_diagnostics.json
    off_rank01_*.png
    ...
    on_rank01_*.png
    ...
```

Em instalações cujo `DisplayProjectRepository` fica fora de `data/config`,
o diretório acompanha o mesmo root local de modelos usado pelo projeto.

O console passa a imprimir explicitamente:

```text
Diagnóstico calibração • pior OFF: <MASK> P(ON)=...
Diagnóstico calibração • pior ON: <MASK> P(ON)=...
Diagnóstico calibração salvo em: <pasta>
```

Se o gap continuar negativo, a exceção também informa a pasta preservada.

### Objetivo do próximo passo

Inspecionar visualmente e numericamente os extremos para responder de forma
objetiva:

- o pior OFF representa reflexo/movimento/iluminação plausíveis?
- o pior ON ainda parece fisicamente um segmento aceso?
- a sobreposição vem de uma máscara específica?
- existe uma transformação sintética recorrente nos outliers?

Somente após essa evidência será permitido decidir entre:

- melhorar o modelo/aprendizado; ou
- corrigir uma augmentation comprovadamente irrealista.

**Estado:** INSTRUMENTAÇÃO IMPLEMENTADA — PENDENTE DE NOVA EXECUÇÃO DO TREINO
PARA COLETAR OS EXTREMOS REAIS.

---

## 05/10/2026 — N1.4 diagnóstico: auditoria ON/OFF por máscara física implementada

**Estado:** INSTRUMENTAÇÃO IMPLEMENTADA — AGUARDANDO RESULTADO NO PROJETO REAL.

Motivação:
- os extremos da calibração confirmaram que o problema não é explicado somente
  por um reflexo sintético;
- antes de alterar CNN, contexto espacial ou augmentation, é necessário verificar
  se cada `MASK_xxx` viu no conjunto de treino os estados ON/OFF que o H1 exige;
- exemplo de risco a confirmar: uma máscara fisicamente ON no H1 ter aparecido
  somente como OFF em BLUE/USB/AUX durante o treino.

A auditoria foi incorporada ao mesmo pipeline neural, sem alterar:
- split de treino/validação;
- labels;
- pesos;
- augmentation;
- CNN;
- thresholds;
- gate de promoção.

Para cada máscara física o relatório agora registra:
- estado em cada CHECK configurado;
- quantidade ON e OFF no treino;
- estados efetivamente vistos no treino;
- estado exigido pelo CHECK de validação;
- se esse estado de validação já apareceu no treino;
- classificação diagnóstica:
  - `both_states_seen_in_training`;
  - `single_state_seen_in_training`;
  - `validation_state_unseen_in_training`;
  - `no_training_state`.

O preflight imprime uma matriz legível por CHECK e salva o JSON completo em:

```text
data/models/f3_neural/diagnostics/
  cm_500_l_segments_state_coverage.json
```

O relatório é somente diagnóstico. Mesmo que uma máscara tenha estado de H1
inédito no treino, o preflight não é artificialmente reprovado por essa regra;
o objetivo desta etapa é medir a cobertura real antes de decidir a próxima
mudança algorítmica.

Próximo passo:
1. executar novamente o preflight do `CM_500_L`;
2. enviar a matriz impressa ou o JSON de cobertura;
3. identificar quais máscaras H1 ON/OFF nunca viram esse mesmo estado em
   BLUE/USB/AUX;
4. somente com essa evidência decidir entre ampliar contexto/modelo ou corrigir
   cobertura do dataset.

Não repetir:
- não mudar arquitetura da CNN antes desta auditoria;
- não adicionar exemplos artificiais apenas para equilibrar a matriz sem
  evidência física;
- não voltar ao classificador convencional do H1.

**Resultado físico:** não aplicável; etapa estritamente diagnóstica/offline.

---

## 05/10/2026 — N1.4 cobertura real: cinco máscaras H1 OFF nunca viram OFF no treino

**Resultado:** DIAGNÓSTICO OFFLINE CONFIRMADO.

Preflight real do projeto `CM_500_L`:

```text
sample_count=112
train_count=84
validation_count=28

ambas as classes no treino: 18
somente uma classe no treino: 5
estado exigido pela validação nunca visto no treino: 5
sem estado de treino: 0
```

Máscaras com estado H1 inédito:

```text
MASK_015: H1=OFF | BLUE=ON | USB=ON | AUX=ON
MASK_021: H1=OFF | BLUE=ON | USB=ON | AUX=ON
MASK_022: H1=OFF | BLUE=ON | USB=ON | AUX=ON
MASK_023: H1=OFF | BLUE=ON | USB=ON | AUX=ON
MASK_025: H1=OFF | BLUE=ON | USB=ON | AUX=ON
```

Esse resultado comprova uma lacuna real de cobertura do dataset funcional:
essas máscaras eram exigidas como OFF no H1 reservado, mas o otimizador só
havia visto ON para elas.

Ao mesmo tempo, os ON do H1 estão cobertos, e máscaras como `MASK_010`,
`MASK_014`, `MASK_018` e `MASK_021` reforçam que halo/reflexo de vizinhos
continua sendo requisito de robustez distinto da simples cobertura de classe.

### Alteração aplicada

O dataset neural passa a incorporar a referência já existente
**PLACA DESLIGADA NO SUPORTE** como OFF físico por máscara, conforme D-061.

Regras:
- somente foto BOARD_OFF real;
- somente máscaras locais explicitamente salvas sobre essa foto;
- cada `MASK_xxx` mantém identidade física;
- BOARD_OFF entra apenas no treino;
- H1 continua integralmente reservado;
- nenhuma mudança em CNN, augmentation ou thresholds nesta etapa.

O preflight passa a expor:
- `auxiliary_sources_used`;
- `board_off_reference_configured`;
- `board_off_geometry_configured`;
- `board_off_sample_count`;
- `board_off_invalid_mask_ids`.

### Próximo passo

Executar novamente:

```powershell
python scripts/treinar_f3_segmentos_neural.py --preflight --project CM_500_L
```

Critério esperado se BOARD_OFF possuir as 28 máscaras válidas:

```text
board_off_sample_count=28
validation_state_unseen_in_training_count=0
```

Somente depois desse resultado deve ser executado novo treinamento/calibração.

**Estado físico:** não aplicável; alteração de dataset offline pendente de
preflight real.

---

## 05/10/2026 — N1.5 overlap após BOARD_OFF: augmentation fotométrico cumulativo identificado

**Resultado:** DIAGNÓSTICO OFFLINE CONFIRMADO — CORREÇÃO IMPLEMENTADA,
PENDENTE DE NOVO TREINO LOCAL.

O preflight real após D-061 confirmou:

```text
sample_count=140
board_off_sample_count=28
train_count=112
validation_count=28
ambas as classes no treino=26
somente uma classe no treino=2
estado H1 nunca visto no treino=0
```

Portanto a lacuna de cobertura ON/OFF foi encerrada.

No treino seguinte a CNN atingiu 100% no H1 original e fez early stop após cinco
épocas perfeitas, mas a calibração robusta não foi separável:

```text
worst OFF: MASK_010 aug06 P(ON)=0.736686
worst ON : MASK_012 aug07 P(ON)=0.611381
raw_gap=-0.125305
```

A inspeção das cinco piores amostras OFF e ON mostrou:

- OFF problemáticos predominantemente clareados;
- ON problemáticos predominantemente escurecidos;
- `MASK_010 aug06`: alpha=1.1426, beta=+0.0266, gamma=0.8014 e reflexo
  de intensidade 0.9294;
- `MASK_012 aug07`: alpha=0.7811, beta=-0.0612, gamma=1.2627, sem
  reflexo/ruído/blur;
- outros extremos repetiram o mesmo empilhamento de ganho + offset + gamma,
  inclusive casos OFF sem reflexo.

### Correção desta etapa

Somente a política fotométrica do augmentation foi alterada:

```text
uma amostra → gain OU offset OU gamma
```

Nunca os três juntos.

Faixas:

```text
gain   0.85 .. 1.15
offset -0.06 .. +0.06
gamma  0.85 .. 1.18
```

Permanecem sem alteração:

- arquitetura CNN;
- entrada 4x48x48;
- context ratio;
- split H1 reservado;
- BOARD_OFF;
- 16 variações de calibração por referência;
- blur, ruído, deslocamento, escala e rotação;
- reflexo sintético OFF;
- thresholds derivados do gap;
- autoridade produtiva H1.

Regressões automatizadas foram adicionadas para exigir que apenas um dos três
operadores fotométricos esteja não neutro em cada amostra e para cobrir todas as
três modalidades.

### Próximo reteste

Executar:

```powershell
python scripts/treinar_f3_segmentos_neural.py --project CM_500_L
```

Verificar:

1. H1 original continua 100%;
2. `max_OFF_P(ON) < min_ON_P(ON)`;
3. quais máscaras ficam nos novos extremos;
4. se ainda houver overlap, não alterar threshold: revisar contexto/capacidade
   espacial da CNN como próxima hipótese.

**Validação física produtiva:** ainda não executada; esta etapa é de treino e
calibração offline.

---

## 05/10/2026 — N1.6 H1 nominal multi-frame: 1/5 PASS, MASK_017 incerta em 4/5

**Resultado:** FAIL DE ROBUSTEZ NOMINAL CONFIRMADO — CORREÇÃO DE CALIBRAÇÃO
MULTI-FRAME IMPLEMENTADA, PENDENTE DE APLICAÇÃO/RETESTE.

### Cenário físico

- Projeto: `CM_500_L`;
- CHECK: H1;
- placa fisicamente correta;
- 7 segmentos H1 esperados acesos;
- nenhuma alteração intencional de placa, câmera, zoom ou iluminação entre as
  leituras;
- modelo D-062 carregado com:

```text
OFF <= P(ON) 0.584876
ON  >= P(ON) 0.827438
gap offline  = 0.242561
```

### Resultado de cinco leituras nominais

```text
tentativa 1  MASK_017 P(ON)=0.828465  → ON / 28/28 / PASS
tentativa 2  MASK_017 P(ON)=0.821631  → INCERTO / 27/28
tentativa 3  MASK_017 P(ON)=0.820450  → INCERTO / 27/28
tentativa 4  MASK_017 P(ON)=0.809613  → INCERTO / 27/28
tentativa 5  MASK_017 P(ON)=0.809678  → INCERTO / 27/28
```

Resumo:

```text
PASS nominal = 1/5
INCERTO      = 4/5
máscara recorrente = MASK_017
```

As quatro reprovações de avanço não foram OFF falsos: a autoridade neural
permaneceu fail-closed em `INCERTO`, como exigido por D-060.

### Evidência física ON/OFF do lote

A leitura das probabilidades de todas as 28 máscaras nos cinco frames mostrou:

```text
pior OFF físico:
MASK_010 P(ON)=0.534034

pior ON físico:
MASK_017 P(ON)=0.809613

gap físico:
0.809613 - 0.534034 = +0.275579
```

Portanto as classes continuam fisicamente separáveis nesse lote. O bloqueio vem
do limite ON `0.827438` calibrado com a foto H1 reservada + variações
sintéticas, que não cobriu a distribuição nominal live recorrente da
`MASK_017`.

### Correção aplicada

Conforme D-063, foi implementada calibração física H1 multi-frame offline:

- no mínimo 5 frames congelados únicos;
- entrada pelo DEBUG TÉCNICO já existente;
- rótulos exclusivamente do `mask_states` H1 configurado;
- H1 continua fora do otimizador;
- CNN/ONNX não são retreinados;
- nenhum threshold manual por máscara;
- frames duplicados são removidos por `frame_sha256_24`;
- origem do modelo/calibração e conjunto exato de máscaras são validados;
- extremos físicos e augmented são combinados conservadoramente;
- metadata é atualizado atomicamente;
- runtime valida fail-closed a estrutura física antes de carregar o artefato.

Para este lote, a combinação esperada é:

```text
max OFF final = max(0.584876, 0.534034) = 0.584876
min ON final  = min(0.827438, 0.809613) = 0.809613
gap final ≈ 0.224737
```

Os cinco frames acima passam a ser **dados de calibração** e não poderão ser
usados como prova de robustez depois da atualização.

### Próximo reteste

1. aplicar a calibração multi-frame usando os DEBUGs físicos coletados;
2. confirmar no console os extremos físicos e combinados;
3. reiniciar/recarregar o runtime;
4. executar novos H1 nominais com frames não usados na calibração;
5. somente se o nominal novo for repetível, avançar para deslocamento,
   iluminação, segmento ON apagado e reflexo em OFF.

**BLUE neural:** ainda não autorizado.

---

## 05/10/2026 — N1.7 H1 neural: terceira placa OK aprovada; NG detectado no BLUE convencional

**Resultado:** PASS FÍSICO DO H1 NEURAL EM PLACA INDEPENDENTE + DETECÇÃO NG
CONFIRMADA PELO CHECK BLUE CONVENCIONAL.

### Contexto

Após a calibração física multi-frame definida em D-063, o artefato do projeto
`CM_500_L` passou a usar evidência física acumulada de duas placas corretas:

```text
10 frames físicos
280 observações
OFF <= P(ON) 0.660738
ON  >= P(ON) 0.809613
gap = +0.148875
```

A CNN/ONNX permaneceu a mesma. A atualização foi apenas de metadata/calibração;
o H1 continuou fora da otimização.

### Validação independente

Foi usada uma terceira placa correta que não participou da calibração.

Resultado informado no teste físico:

```text
placa OK
H1 correto
→ H1 NEURAL APROVADO COM SUCESSO
```

Na mesma etapa foi testada uma placa realmente NG. O defeito não estava no H1:
no CHECK BLUE havia um segmento apagado, fazendo o display formar `BLUF`.

```text
H1
→ aprovado pela autoridade neural

BLUE
→ segmento apagado
→ detectado pela autoridade visual convencional
→ placa REPROVADA COM SUCESSO
```

Portanto o melhor estado físico alcançado até esta etapa é:

- H1 correto de placa independente aceito pela autoridade neural;
- H1 da placa NG também aceito quando visualmente correto;
- defeito real no BLUE detectado pelo caminho convencional;
- sequência completa impediu a aprovação da placa NG;
- calibração física do H1 baseada em mais de uma placa;
- `INCERTO` preservado como fail-closed fora das regiões calibradas;
- nenhuma volta ao classificador convencional como autoridade do H1.

### Escopo da autoridade nesta etapa

A migração neural continua **somente no H1**.

```text
H1        → autoridade visual neural
BLUE      → autoridade visual convencional
USB       → autoridade visual convencional
AUX       → autoridade visual convencional
```

Presença, energia, sequência de CHECKS, rearme, resultado terminal e UI
continuam com seus proprietários canônicos. A CNN decide os estados ON/OFF das
28 máscaras apenas no CHECK H1; a comparação com o `mask_states` e a decisão
de sequência permanecem determinísticas.

### Estado

```text
H1 neural nominal em placa independente   PASS
H1 neural na placa posteriormente NG      PASS
BLUE convencional detectando segmento NG  PASS
placa NG bloqueada pela sequência          PASS
CNN retreinada nesta validação             NÃO
ONNX alterado                              NÃO
calibração física                          2 placas / 10 frames
BLUE neural                                NÃO
USB neural                                 NÃO
AUX neural                                 NÃO
```

Este resultado valida o H1 em um nível físico significativamente superior aos
retestes anteriores e confirma que a arquitetura híbrida atual consegue combinar
H1 neural com CHECKS seguintes ainda convencionais. O teste NG desta etapa não
é evidência de detecção neural no BLUE; a detecção do segmento apagado ocorreu
no caminho convencional.

Ainda não está autorizado migrar automaticamente BLUE/USB/AUX: essa progressão
continua dependente dos cenários físicos restantes e de autorização explícita
do usuário, conforme D-059/D-060/D-063.

---

## 05/10/2026 — N2.0 BLUE neural: migração autorizada após aprovação indevida com MASK_024 apagada

**Resultado:** IMPLEMENTAÇÃO N2 APLICADA — PENDENTE DE RETESTE FÍSICO.

### Caso que abriu a etapa

Após o PASS físico N1.7 do H1, o usuário autorizou explicitamente a migração do
CHECK BLUE para IA.

Foi apresentado um caso real em que o display estava em BLUE intermitente e
`MASK_024` permanecia fisicamente apagada, embora o gabarito do projeto espere
essa máscara em `on` no BLUE.

O DEBUG do ciclo anterior registrou simultaneamente:

```text
check_id=CHECK_002
check_name=BLUE
intermittent=true
analysis_ready=true
analysis_approved=true
matched_mask_count=28
active_mask_count=28
intermittent_ready=true
intermittent_seen_on=18
intermittent_expected_on=18
policy_decision=ok
registration_event=check_advanced
registration_approved=true
```

Portanto houve uma aprovação produtiva incompatível com a condição física
informada. O objetivo da N2 não é adicionar outra exceção convencional para
`MASK_024`; é retirar do BLUE os caminhos convencionais capazes de reescrever
a decisão semântica.

### Mudança implementada

Escopo da autoridade após N2.0:

```text
H1        → autoridade visual neural
BLUE      → autoridade visual neural
USB       → autoridade visual convencional
AUX       → autoridade visual convencional
```

O BLUE usa agora o mesmo detector ON/OFF por segmento já usado pelo H1. O
comportamento intermitente permanece tratado fora da CNN:

```text
frame BLUE
→ CNN classifica as máscaras
→ runtime identifica fase ON / OFF / transição

OFF ou transição
→ parte normal do pisca
→ não gera NG

fase ON
→ todos corretos        → candidato a OK
→ divergência certa     → acumula 1/3
→ mesma divergência 3/3 → NG persistente
→ INCERTO               → não aprova e não acumula defeito
```

Para um BLUE neural, foram desativados como autoridades de reclassificação:

- veto por gabarito exato;
- reconciliação BOARD_OFF/LIVE/ON usada nos falsos OFF convencionais;
- sonda exata capaz de avançar CHECK em composição legada.

Energia, presença, tracking/pose, sequência e rearme continuam separados da
autoridade semântica da CNN.

### Proteção específica do caso MASK_024

Foi adicionada regressão automatizada para o cenário:

```text
BLUE em fase ON
17 segmentos esperados ON reconhecidos ON
MASK_024 esperada ON reconhecida OFF
suporte físico convencional tenta confirmar MASK_024
```

Contrato esperado:

```text
suporte convencional NÃO reescreve MASK_024
MASK_024 continua OFF / matched=false
3 fases ON divergentes → persistent_failed_ids contém MASK_024
```

Também foi adicionada regressão para `MASK_024=INCERTO`: o estado não
incrementa nem zera o contador de falha e não pode fechar OK/NG sozinho.

### Reteste físico obrigatório

Ainda falta validar no JIG real:

1. BLUE correto, incluindo vários ciclos do pisca;
2. fase OFF completa sem falso NG;
3. placa deste caso com `MASK_024` apagada;
4. confirmar que a UI mantém `MASK_024` vermelha após o debounce 3/3;
5. confirmar que o CHECK não avança para USB;
6. BLUE correto após uma placa NG;
7. confirmar que USB/AUX permanecem no caminho convencional.

Até esse reteste, o estado é:

```text
H1 neural validado fisicamente    SIM
BLUE neural implementado          SIM
BLUE neural validado fisicamente  NÃO
USB neural                        NÃO
AUX neural                        NÃO
```

---

## 06/10/2026 — N2.1 bloqueio de reteste: H1 correto voltou a ficar 27/28 por MASK_017 INCERTA

**Resultado:** FAIL FÍSICO DE REPETIBILIDADE DO H1 NEURAL — CAUSA IDENTIFICADA NA CALIBRAÇÃO DE CERTEZA; BLUE AINDA NÃO RETESTADO.

### Cenário

Ao iniciar o reteste físico da Etapa N2, o fluxo não chegou ao BLUE porque o
H1 correto deixou de avançar. A tela produtiva permaneceu em:

```text
H1 INDETERMINADO
27/28 CONFORMES
1 INCERTO
AUTO • H1 • leitura neural incerta • continuando busca
```

O DEBUG confirma presença e energia válidas:

```text
ESTADO DA PLACA: PRESENTE • CONFIRMADA
ENERGIA DO DISPLAY: CONFIRMADA
GATE PRODUTIVO: LIBERADO
```

Portanto o bloqueio não veio de presença, energia, rearme ou sequência.

### Evidência neural

A única máscara neural incerta foi `MASK_017`, configurada como `on` no H1:

```text
MASK_017
expected=on
classified=uncertain
P(ON)=0.769281
P(OFF)=0.230719
neural_certain=false
```

O artefato ativo ainda usa:

```text
OFF <= P(ON) 0.660738
ON  >= P(ON) 0.809613
gap = 0.148875
physical_h1_calibration_frame_count = 10
```

Logo `0.769281` cai corretamente na faixa INCERTO do contrato atual.

No mesmo frame, os diagnósticos físicos/convencionais continuam coerentes com
um H1 correto: a autoridade de energia confirmou os 7 segmentos esperados ON e
o aprendizado same-mask diagnóstico classificou o H1 em 28/28. Esses sinais
não podem reclassificar a CNN, mas provam que não há evidência de segmento
fisicamente apagado neste caso.

### Causa

Este FAIL repete a classe de problema já tratada em D-063: a distribuição live
da `MASK_017` correta voltou a ultrapassar a variabilidade coberta pelos frames
físicos usados na calibração anterior.

Não há motivo para alterar o ONNX nem retornar ao classificador convencional.

Para este novo frame:

```text
max OFF P(ON) no frame = 0.539925  (MASK_010)
min ON  P(ON) no frame = 0.769281  (MASK_017)
gap live do frame      = +0.229356
```

Considerando os extremos físicos já acumulados no metadata:

```text
max OFF físico existente = 0.660738
novo min ON físico        = 0.769281
novo gap físico esperado  = +0.108543
```

As classes continuam separáveis. Portanto o caminho canônico é **incorporar
este novo snapshot ao conjunto físico multi-frame existente**, usando o
recalibrador D-063. O próprio pipeline preserva os 10 frames anteriores, elimina
duplicatas por hash e acrescenta o novo frame; não é necessário retreinar a CNN.

### Alteração de runtime

Nenhuma alteração algorítmica foi aplicada ao runtime neste FAIL.

Em particular, não foi criado:

- threshold manual;
- exceção específica para `MASK_017`;
- fallback convencional;
- novo debounce;
- nova autoridade visual.

O mecanismo de recalibração já existente em
`display_f3_neural_physical_calibration.py` é o proprietário correto desta
correção.

### Próximo reteste

1. adicionar este DEBUG H1 ao metadata físico atual com
   `--recalibrate-physical-h1`;
2. confirmar no console que o ONNX foi preservado e que a calibração combinada
   continua com gap positivo;
3. reiniciar/recarregar o ODIN para o detector reler o metadata;
4. usar frames H1 novos, não o frame incorporado à calibração;
5. confirmar repetibilidade do H1 antes de retomar o reteste do BLUE neural.

Estado da Etapa N2 após este FAIL:

```text
H1 neural implementado                  SIM
H1 neural repetibilidade neste reteste  FAIL
causa identificada                      SIM — calibração física
recalibração necessária                 SIM
BLUE neural implementado                SIM
BLUE neural retestado após N2.0         NÃO
USB neural                              NÃO
AUX neural                              NÃO
```

---

## 06/10/2026 — N2.2 cinco H1 confirmam necessidade de fusão híbrida universal

**Resultado:** MUDANÇA ARQUITETURAL APROVADA E IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO.

### Evidência coletada

Após o bloqueio N2.1, foram coletadas cinco novas análises H1 consecutivas da
mesma condição fisicamente correta.

Em todas elas:

```text
ESTADO DA PLACA: PRESENTE • CONFIRMADA
ENERGIA DO DISPLAY: CONFIRMADA
MÁSCARAS LIVE ON CONFIRMADAS: 7
FONTE: same_physical_mask_on_off_learning
APRENDIZADO FÍSICO SAME-MASK H1: 28/28
```

A CNN, porém, não apresentou a mesma repetibilidade:

```text
captura 1 → 27/28 | MASK_017 P(ON)=0.769281
captura 2 → 27/28 | MASK_017 P(ON)=0.796248
captura 3 → 27/28 | MASK_017 P(ON)=0.801410
captura 4 → 25/28 | MASK_017 P(ON)=0.721180
captura 5 → 27/28 | MASK_017 P(ON)=0.801258
```

Na captura 4, três segmentos esperados ON ficaram INCERTOS apesar de a leitura
física continuar coerente com H1:

```text
MASK_008 P(ON)=0.786192
MASK_017 P(ON)=0.721180
MASK_020 P(ON)=0.764196
```

Essa repetição descartou a hipótese de que o problema deveria ser tratado apenas
adicionando mais cinco frames à calibração do limiar global.

### Decisão aprovada pelo usuário

Foi autorizada a mudança "tudo ou nada":

```text
H1          → autoridade híbrida
BLUE        → autoridade híbrida
AUX         → autoridade híbrida
USB         → autoridade híbrida
CHECK futuro→ autoridade híbrida automaticamente
```

A unidade semântica deixa de ser "CNN isolada por CHECK" e passa a ser a
`MASK_xxx` observada por duas fontes internas da mesma autoridade:

1. CNN/ONNX;
2. aprendizado físico ON/OFF da mesma máscara.

### Contrato implementado

```text
CNN certa + físico forte concordam
→ estado confirmado

CNN incerta + físico local forte
→ físico resolve a máscara

CNN certa + físico forte discordam
→ INCERTO

físico local confiável = POUCA LUZ
→ POUCA LUZ

sem físico local forte
→ CNN preserva sua decisão
```

A evidência física usada para resolver a CNN precisa ser
`f3_check_photos_same_mask`. Pool de outras máscaras não ganha autoridade de
resolução.

O runtime intermitente passa a observar a certeza semântica final. Assim, uma
CNN incerta resolvida fisicamente para OFF durante uma fase ON válida do BLUE
pode acumular o debounce de defeito; uma incerteza final continua sem
incrementar nem zerar o contador.

### Aprendizado de NG

Não foi introduzido treinamento online nem requisito de coletar cinco NG por
defeito. O classificador aprende/observa estados físicos ON/OFF; NG continua
sendo derivado deterministicamente por:

```text
estado_observado != estado_esperado
```

Exemplo já existente no projeto: uma máscara pode estar ON em um CHECK e OFF em
outro, fornecendo exemplos dos dois estados físicos sem precisar fabricar uma
placa defeituosa.

### Alterações de código

- `F3HybridCheckAnalyzer` passa a ser o proprietário semântico canônico;
- todos os CHECKS configurados entram no mesmo escopo dinâmico;
- `semantic_certain` representa certeza após a fusão;
- `neural_certain` permanece como telemetria bruta da CNN;
- a sonda exata fica observadora em qualquer CHECK;
- o DEBUG passa a expor CNN, evidência same-mask, resoluções e conflitos;
- aliases neurais antigos permanecem somente por compatibilidade.

A decisão normativa correspondente é **D-065**.

### Relação com N2.1

A instrução anterior de recalibrar estes novos frames no threshold H1 fica
**superseded**. Não executar essa recalibração agora. Os cinco frames foram
usados para demonstrar que continuar expandindo um threshold global não resolve
a arquitetura de forma sustentável.

### Próximo reteste físico

Primeiro lote de validação da autoridade híbrida:

1. H1 correto deve voltar a avançar sem depender de nova recalibração;
2. repetir H1 várias vezes e observar no DEBUG quais máscaras foram resolvidas
   pelo físico;
3. BLUE correto deve atravessar ON/OFF normalmente;
4. BLUE com `MASK_024` realmente apagada deve acumular 3 fases ON e fechar NG;
5. o fluxo não pode avançar para USB nesse NG.

Somente após esse lote deve-se declarar D-065 validada fisicamente.

---

## 06/10/2026 — D-065 autoridade híbrida aprovada no reteste físico H1

**Resultado:** PASS FÍSICO DO H1 COM A AUTORIDADE HÍBRIDA.

Após a implementação de D-065, o usuário executou o reteste físico solicitado
com a nova versão e confirmou que o comportamento ficou correto.

O objetivo específico deste lote era validar que o H1 fisicamente correto
voltasse a avançar sem nova recalibração global da CNN, permitindo que a
evidência física confiável da mesma máscara resolvesse uma eventual incerteza
neural dentro da autoridade híbrida.

Resultado confirmado pelo usuário:

```text
H1 correto com autoridade híbrida        PASS
nova recalibração global necessária      NÃO
fluxo produtivo voltou a funcionar       SIM
comportamento observado                  CORRETO
```

Este PASS confirma fisicamente o primeiro ponto crítico da D-065: uma máscara
que esteja correta no JIG não precisa permanecer bloqueada apenas porque a CNN
isolada caiu na faixa INCERTO, desde que exista evidência física local forte da
mesma `MASK_xxx`.

A arquitetura continua obedecendo às proteções definidas em D-065:

- CNN e same-mask continuam sendo fontes internas da mesma autoridade;
- conflito forte continua resultando em `INCERTO`;
- não foi criado threshold manual novo;
- não foi executada a recalibração dos cinco DEBUGs H1 anteriormente proposta;
- não existe auto-treinamento em produção;
- `semantic_certain` continua sendo a certeza produtiva final;
- `neural_certain` permanece como telemetria da CNN bruta.

### Estado da validação D-065 após este reteste

```text
H1 híbrido implementado                  SIM
H1 híbrido retestado fisicamente         PASS
H1 bloqueado pela MASK_017               RESOLVIDO
recalibração adicional do H1             NÃO
BLUE híbrido implementado                SIM
AUX híbrido implementado                 SIM
USB híbrido implementado                 SIM
CHECKS futuros no escopo híbrido         SIM
```

Este registro encerra o problema físico que motivou a mudança de arquitetura no
H1. A validação completa dos demais cenários de D-065 continua sendo registrada
separadamente conforme forem executados no JIG, especialmente BLUE intermitente
correto e BLUE NG com `MASK_024` apagada.



---

## 06/10/2026 — Tracking ON D-070: homografia ativa, mas cantos do filtro ainda incorretos

**Resultado:** FAIL FÍSICO DE ALINHAMENTO — CAUSA IDENTIFICADA; D-071
IMPLEMENTADA E PENDENTE DE RETESTE.

### Cenário

- projeto: `CM_500_L`;
- CHECK: H1;
- rastreamento automático: ATIVO;
- display H1 fisicamente aceso;
- UI permaneceu em `LOCK ESTRUTURAL • ALINHANDO SEGMENTOS`;
- as 28 máscaras continuaram visivelmente deslocadas dos segmentos reais.

### Evidência objetiva do DEBUG

A infraestrutura projectiva D-070 estava efetivamente ativa:

```text
source_type=neural_filter_pose
reason=locked_neural_filter_pose
projective_pose_ready=true
projective_reprojection_mean_px=0.0
projective_reprojection_max_px=0.0
```

Porém a associação filtro x prior neural continuava distante:

```text
selected_snap_error_px=120.663
max_snap_error_px=180.0
confidence=0.3296
candidate_mode=relaxed_similarity_lmeds
```

A geometria live já estava no novo espaço:

```text
mask_geometry_space=canonical_projective
spatial_alignment_required=true
spatial_alignment_ready=false
spatial_alignment_source=projective_filter_structural
```

A consequência física foi coerente com desalinhamento das ROIs:

```text
H1 esperado ON = 7
live ON confirmadas = 3
live OFF confirmadas = 23
gate produtivo = BLOQUEADO
energia = OFF
```

O tracking luminoso não encontrou suporte geométrico suficiente:

```text
luminous_component_count=2
local_luminous_landmark_count=0
validated_count=0/7
alignment_ready=false
reason=filter_found_without_luminous_segments
```

O diagnóstico D-025 no mesmo frame também não confirmou alinhamento real:

```text
filter_source=projective_filter_structural
tracking_filter_points=4
mean_error_px=47.11
p95_error_px=289.17
ecc=0.1249
refinement_applied=NÃO
```

### Causa identificada

A inspeção do proprietário canônico do tracking encontrou a origem do erro:
`_detect_dark_filter_candidates()` detectava o contorno escuro, mas convertia
esse contorno com:

```text
cv2.minAreaRect(contour)
-> cv2.boxPoints(rect)
-> quatro cantos
-> homografia
```

`minAreaRect` produz o menor retângulo rotacionado que contém o objeto. Ele
remove justamente a perspectiva/trapézio físico que a D-070 passou a querer
preservar.

Assim, `projective_reprojection=0` apenas provava que uma homografia encaixava
perfeitamente os quatro cantos artificiais do retângulo nos quatro cantos
canônicos; não provava alinhamento com os segmentos reais.

### Alteração aplicada

D-071:
- quadriláteros físicos com quatro cantos preservam a perspectiva;
- o contorno escuro passa por `convexHull + approxPolyDP` para recuperar os
  quatro cantos reais;
- `minAreaRect` permanece somente como medição/fallback estrutural;
- fallback `min_area_rect_fallback` NÃO pode publicar homografia 3x3
  produtiva;
- o DEBUG passa a expor a origem dos cantos, os quatro pontos físicos, os
  anchors neurais e o erro por canto.

### Próximo reteste

Testar novamente somente H1 com tracking ON.

Critérios:
1. `filter_corner_source=contour_quad`;
2. `projective_pose_ready=true`;
3. as quatro coordenadas em `filter_points` devem acompanhar os cantos
   trapezoidais reais do filtro;
4. máscaras precisam centralizar nos segmentos;
5. somente depois disso `spatial_alignment_ready=true`;
6. H1 deve usar a mesma autoridade híbrida já validada com tracking OFF.

**Estado após correção:** PENDENTE DE RETESTE FÍSICO.


---

## 07/10/2026 — D-071 PASS funcional; NG correto com freeze visual desalinhado

**Modo:** tracking ON  
**Projeto:** `CM_500_L`  
**CHECKS observados:** H1 -> BLUE

### Resultado físico

A D-071 resolveu o problema principal de alinhamento/decisão:

- H1 foi localizado com as máscaras sobre os segmentos reais;
- H1 correto foi aprovado;
- a sequência avançou para BLUE;
- BLUE defeituoso foi identificado corretamente;
- a placa foi reprovada em BLUE por uma única falha persistente:
  `MASK_024`;
- resultado produtivo: **27/28 conformes -> NG correto**.

Portanto, a geometria D-071 e a decisão híbrida D-065/D-066 funcionaram no
ciclo real até a reprovação.

### Falha visual observada depois do NG

No instante em que o NG foi apresentado:

- o frame foi congelado corretamente como evidência terminal;
- porém as máscaras desenhadas sobre a câmera se deslocaram dos segmentos reais;
- o VISOR DO DISPLAY também deixou de refletir exatamente a classificação
  semântica que fechou o NG.

A decisão produtiva permaneceu correta; o defeito ficou restrito à
**apresentação terminal congelada**.

### Evidência objetiva do DEBUG

Snapshot terminal:

```text
frame_id=1481
frame_source=ng_evidence_frozen
live_camera_ignored=SIM
CHECK=BLUE
```

Resultado produtivo preservado:

```text
last_auto_analysis.ready=true
last_auto_analysis.approved=false
reason=check_hibrido_divergente
matched=27/28
effective_confirmed_failed_mask_ids=[MASK_024]
spatial_alignment_required=true
spatial_alignment_ready=true
spatial_alignment_source=luminous_segment_grid
tracking_geometry_reference=luminous:CHECK_002
tracking_snapshot_explicit=true
```

A análise BLUE também mostrou `MASK_024` esperada ON e observada OFF.

Entretanto o estado visual congelado reportou várias máscaras como falha,
apesar de a análise produtiva ter confirmado somente `MASK_024`. Isso provou
que o renderer terminal estava misturando dados de snapshots diferentes.

### Causa identificada

O pipeline assíncrono mantinha RAW + geometria juntos durante tracking/análise,
mas o payload semântico descartava esses dois elementos antes do registro do
resultado.

No NG:

1. o analyzer decidia usando `raw_frame + tracking_geometry` do mesmo job;
2. o runtime guardava como evidência o `analysis_frame` alinhado/canônico;
3. a geometria exata daquele job não era preservada;
4. `freeze_ng_evidence()` copiava o último overlay live disponível;
5. esse overlay podia pertencer a outro frame;
6. se o contexto já tinha `live_luminous_only=true`, o repaint terminal ainda
   preservava classificações visuais antigas.

Resultado: decisão correta, mas frame/geometria/classificações da apresentação
terminal não eram atômicos.

### Correção aplicada — D-072

O NG passa a preservar como uma unidade:

```text
frame_token
+ raw_frame
+ tracking_geometry
+ analysis
+ logical_context
+ visual_rotation
```

Regras implementadas:

- o semantic payload transporta RAW + geometria do mesmo tracking snapshot;
- o auto-check congela o RAW, não o frame interno alinhado;
- o frame_id vem do mesmo `frame_token`;
- a geometria rastreada é persistida junto da evidência NG;
- o overlay terminal é reconstruído explicitamente com essa geometria;
- `freeze_ng_evidence()` recebe o contexto geométrico exato em vez de usar o
  último repaint live;
- câmera e visor recebem sempre as
  `effective_classifications` da análise que decidiu o NG;
- somente `effective_confirmed_failed_mask_ids` recebe vermelho;
- DEBUG do NG usa a geometria congelada, não a geometria live posterior;
- câmera física continua livre para detectar EMPTY/rearme.

### CI D-072

PASS antes do bloco histórico conhecido:

- compile F3;
- neural geometry tracking;
- pipeline latency;
- D-025;
- luminous tracking;
- live visual sync;
- **D-072 atomic NG snapshot regressions**;
- ROI geometry parity;
- D-042 presence;
- strict mask/segregation.

Os mesmos **7 FAIL + 1 ERROR históricos** do bloco amplo de object tracking
permanecem inalterados em relação ao baseline D-071.

### Estado

- D-071: **PASS FÍSICO para alinhamento + H1 + BLUE NG**;
- D-072: **IMPLEMENTADA — PENDENTE DE RETESTE FÍSICO DO FREEZE NG**.

### Próximo reteste

Repetir somente:

```text
H1 correto
-> avança BLUE
-> BLUE com MASK_024 apagada
-> 27/28
-> PLACA NG
-> frame congela
-> as 28 ROIs permanecem exatamente sobre os segmentos do frame congelado
-> somente MASK_024 fica vermelha
-> visor preserva os mesmos estados do snapshot
```

---

## 07/10/2026 — Reteste pós-D-072: H1 desalinhado com Rastreamento Automático LIGADO

**Escopo obrigatório deste defeito:** somente **Rastreamento Automático do Display F3 LIGADO**.

O comportamento com **Rastreamento Automático DESLIGADO** pertence a outro
caminho operacional e não deve ser alterado, ajustado ou usado como alvo desta
investigação.

**Resultado físico:** FAIL DE ALINHAMENTO — o reteste terminal D-072 não chegou
a ser executado.

Cenário:
- projeto `CM_500_L`;
- CHECK lógico H1;
- câmera 1920x1080;
- visual 180°;
- placa presente;
- H1 fisicamente aceso;
- máscaras visivelmente fora do centro dos segmentos reais;
- UI permaneceu em
  `LOCK ESTRUTURAL • ALINHANDO SEGMENTOS • MÁSCARA CLÁSSICA`.

Evidência do DEBUG técnico:
- frame manual congelado: `1151`;
- resumo do clique: 3 máscaras live ON e 23 OFF;
- gate produtivo bloqueado por energia considerada OFF;
- tracking:
  - `enabled=true`;
  - `locked=true`;
  - frame `1138`;
  - `source_type=neural_filter_pose`;
  - `reason=locked_neural_filter_pose`;
  - rotação ~3.321°;
  - escala ~0.92935;
- prior neural / filtro:
  - `filter_corner_source=contour_quad`;
  - `selected_snap_error_px=134.306`;
  - limite de snap = 180 px;
  - confiança ~0.2539;
  - erro dos quatro cantos contra os anchors neurais:
    69.368 / 185.439 / 254.799 / 332.456 px;
  - erro médio = 210.516 px;
  - erro máximo = 332.456 px;
  - apesar disso, `projective_pose_ready=true` e reprojeção interna ~0.0001 px;
- refinamento luminoso:
  - 7 segmentos ON esperados;
  - 6 componentes luminosos observados;
  - validação base-core = 3/7, mínimo exigido = 4;
  - somente 1 landmark luminoso local;
  - coarse match = 5;
  - final match = 0;
  - `fit_failure_stage=refined_affine_rejected`;
  - `luminous_grid_not_fitted`;
- autoridade espacial:
  - `spatial_alignment_required=true`;
  - `spatial_alignment_ready=false`;
  - `spatial_alignment_source=projective_filter_structural`;
- pipeline observado:
  - worker de tracking ~559.66 ms de idade;
  - semântica usou frame 1118 quando a câmera já estava no 1144;
  - gap = 26 frames;
  - idade total semântica ~925.17 ms;
  - `normal_fresh=false`;
  - `accepted_for_runtime=false`.

Leitura técnica:
- o fail-closed está funcionando: o sistema NÃO declarou alinhamento espacial
  pronto e não registrou H1 com geometria ainda incorreta;
- o problema está no caminho de tracking ON antes da decisão semântica terminal;
- o lock estrutural `neural_filter_pose` aceitou uma pose grosseira cuja
  geometria ainda divergia fortemente dos anchors neurais;
- a reprojeção projectiva próxima de zero não prova alinhamento físico, pois ela
  mede a consistência da homografia com os próprios quatro cantos fornecidos;
- o refinamento luminoso percebeu a inconsistência e rejeitou a pose em vez de
  promovê-la;
- a idade/gap do pipeline também precisa permanecer sob observação, pois pode
  agravar o deslocamento visual entre o frame live e a última geometria
  publicada.

Impacto sobre D-072:
- D-072 continua **IMPLEMENTADA / PENDENTE DE RETESTE FÍSICO**;
- este teste não chegou ao BLUE/NG e portanto não valida nem invalida o freeze
  terminal atômico;
- o bloqueio atual ocorre antes: aquisição/alinhamento H1 com tracking ON.

Próxima investigação:
- atuar somente no proprietário geométrico do tracking ON;
- revisar aceitação/seleção do quadrilátero estrutural e sua coerência com o
  prior neural antes de publicar a pose;
- medir a influência da idade da geometria sobre o preview;
- preservar o refinamento luminoso fail-closed;
- NÃO alterar Hybrid, regras ON/OFF, autoridade de energia, CHECKS ou thresholds
  semânticos para compensar geometria ruim;
- NÃO modificar o caminho com Rastreamento Automático DESLIGADO.

---

## 07/10/2026 — Correção D-073 aplicada ao H1 desalinhado com tracking ON

**Cenário de origem:** reteste pós-D-072, H1, projeto `CM_500_L`,
Rastreamento Automático LIGADO.

**Resultado anterior:** FAIL de alinhamento antes de chegar ao BLUE/NG.

**Causa confirmada no código:** o gate da `neural_filter_pose` aceitava o erro
do affine aproximado, mas a geometria publicada podia ser a homografia
projectiva exata. No frame físico observado:

- affine snap = 134.306 px;
- limite = 180 px;
- erro médio dos cantos projectivos publicados = 210.516 px;
- erro máximo = 332.456 px.

**Alteração aplicada — D-073:**
- pose projetiva agora só pode ser publicada quando os próprios quatro cantos
  que serão usados pelas ROIs passam pelo snap neural;
- usa o mesmo limite já calibrado, sem novo threshold;
- affine continua somente como orientação/diagnóstico;
- tracking desligado permanece intocado.

**CI focado:** PASS até o bloco amplo histórico. O bloco histórico manteve os
mesmos 7 FAIL + 1 ERROR já conhecidos.

**Estado:** PENDENTE DE RETESTE FÍSICO.

**Próximo reteste:**
```text
Rastreamento Automático = LIGADO
-> inserir placa
-> H1 correto
-> observar aquisição
-> ROIs precisam convergir sobre os segmentos
-> spatial_alignment_ready somente com geometria coerente
-> H1 deve ser aprovado
-> avançar para BLUE
```

Se H1 alinhar e avançar, continuar no mesmo ciclo para o reteste D-072:
BLUE com `MASK_024` apagada -> 27/28 -> NG -> freeze alinhado -> somente
`MASK_024` vermelha.

---

## 07/10/2026 — Tracking OFF: BLUE 27/28 correto, VISOR mapeava a falha no slot físico errado

**Cenário:** projeto `CM_500_L`, Produção Display F3, Rastreamento Automático
DESLIGADO, CHECK BLUE, visual 180°.

**Resultado:** PARTIAL PASS / FAIL DE APRESENTAÇÃO.

### O que funcionou

- placa presente e energia confirmada;
- análise produtiva BLUE encontrou `27/28`;
- `MASK_024` foi a única divergência confirmada;
- câmera congelada destacou a máscara física correspondente à falha;
- classificação por `MASK_ID` do VISOR e da câmera era a mesma.

### Falha observada

No `VISOR DO DISPLAY`, o vermelho apareceu em outra barra física do 88:88.
Ou seja, o estado `MASK_024=OFF/NG` estava correto, mas a máscara foi associada
ao slot A..G errado no desenho do visor.

### Evidência objetiva do DEBUG

- `object_tracking=null`, confirmando tracking OFF;
- `last_auto_analysis.ready=true`;
- `last_auto_analysis.approved=false`;
- motivo `check_hibrido_divergente`;
- BLUE `27/28`;
- `effective_failed_mask_ids=[MASK_024]`;
- `effective_confirmed_failed_mask_ids=[MASK_024]`;
- câmera e visor receberam a mesma classificação final por ID.

### Causa identificada

O snapshot terminal de tracking OFF não carregava
`readout_slot_mask_ids`. O renderer do VISOR então usava seu fallback por
ordem numérica dos IDs. Essa ordem não representa a topologia física A..G dos
quatro displays de sete segmentos.

### Alteração aplicada — D-074

- snapshot terminal tracking OFF agora deriva os 28 slots da geometria fixa do
  projeto após a mesma rotação visual da câmera;
- o mapa é entregue ao VISOR como `readout_slot_mask_ids`;
- tracking ON permanece intocado;
- nenhuma regra de classificação, Hybrid, energia ou debounce foi alterada.

### Garantia adicional solicitada: qualquer segmento pode gerar NG

Foi adicionada regressão exaustiva para `MASK_001..MASK_028`.

Para cada uma das 28 máscaras o teste cria uma única divergência e exige NG:

```text
expected ON  + observed OFF -> NG após persistência
expected OFF + observed ON  -> NG após persistência
```

O teste usa o mesmo contrato intermitente de produção com 3 amostras na fase
ON, publica a máscara alvo como única falha confirmada e exige decisão final
`ng`.

**CI D-074:** PASS.

O workflow amplo ainda termina no bloco histórico de object tracking com os
mesmos 7 FAIL + 1 ERROR do baseline, não relacionados a esta alteração.

**Estado:** D-074 IMPLEMENTADA / PENDENTE DE RETESTE FÍSICO.

**Próximo reteste:** repetir a placa real em BLUE com tracking OFF. A
`MASK_024` deve continuar sendo a única falha, mas agora o vermelho do VISOR
deve ocupar exatamente a mesma barra física indicada pela câmera.

---

## 07/10/2026 — D-074 PASS físico: VISOR tracking OFF alinhado à câmera

**Resultado:** PASS FÍSICO.

O usuário repetiu o cenário BLUE com Rastreamento Automático DESLIGADO após a
D-074 e confirmou que o VISOR DO DISPLAY passou a corresponder corretamente às
máscaras apresentadas na câmera ao vivo/congelada.

A falha anterior — `MASK_024` correta na análise/câmera, mas vermelho em outra
barra física do visor — não se repetiu.

Conclusão:

```text
tracking OFF
+ mapeamento físico A..G do snapshot
+ mesma rotação visual
= câmera e VISOR coerentes
```

D-074 fica **VALIDADA FISICAMENTE** para o caso disponível em bancada.

A garantia de que qualquer `MASK_001..MASK_028` pode gerar NG nos dois sentidos
permanece coberta por 56 cenários automatizados; as demais falhas físicas não
podem ser reproduzidas em bancada enquanto não existirem placas com esses
defeitos reais.

### Próxima alteração solicitada — D-075

Substituir completamente a linha operacional `ANÁLISE VISUAL` por uma faixa
de divergência por máscara, por exemplo:

```text
DIVERGÊNCIA • MASK_024 • ESPERADO: ACESO • DETECTADO: APAGADO
```

Estado D-075 após implementação: **PENDENTE DE RETESTE VISUAL**.

