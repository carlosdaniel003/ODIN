# Regras de Engenharia e Mudanças

## 1. Objetivo

Este documento define como bugs, features, refatorações e otimizações devem ser implementados no ODIN.

A regra principal é:

**mude a causa no módulo responsável; não empilhe outra correção sobre o sintoma.**

## 2. Classifique o trabalho antes de editar

Toda tarefa deve ser reconhecida como uma ou mais destas categorias:

- correção funcional;
- nova funcionalidade;
- refatoração;
- otimização de desempenho;
- mudança de plataforma;
- alteração de persistência/schema;
- alteração de UI;
- alteração de diagnóstico.

Cada categoria exige validação própria.

## 3. Protocolo obrigatório antes da alteração

Antes de escrever código:

1. reproduza ou descreva precisamente o comportamento;
2. localize o método/caminho real;
3. pesquise definições e chamadas;
4. pesquise mixins, wrappers e `instalar_*` relacionados;
5. identifique timers, threads e estado compartilhado;
6. identifique testes existentes;
7. identifique a autoridade canônica;
8. formule uma hipótese de causa;
9. defina critérios de aceitação;
10. defina o menor conjunto coerente de arquivos a alterar.

Para performance, capture baseline antes de otimizar quando houver meios de medição.

## 4. Uma hipótese por vez

Não aplique várias correções independentes na mesma tentativa apenas para aumentar a chance de funcionar.

Fluxo preferido:

~~~text
hipótese
  ↓
mudança
  ↓
teste
  ↓
resultado
  ├── confirmou → consolidar
  └── não confirmou → reverter/reavaliar
~~~

Isso torna causa e efeito rastreáveis.

## 5. Correção canônica

Se o defeito está em um módulo que já é proprietário da responsabilidade, altere esse módulo.

Antes de criar novo arquivo, pergunte:

- existe módulo canônico que deveria receber essa lógica?
- o novo arquivo representa responsabilidade duradoura?
- ele reduz acoplamento ou só contorna uma implementação existente?
- ele terá API clara e testes próprios?

Um novo módulo não é justificável apenas porque é mais fácil evitar editar código antigo.

## 6. Política de patches

Arquivos com nomes como:

- `fix`;
- `v2`;
- `final`;
- `compat`;
- `authority`;
- `guard`;

não são proibidos de forma absoluta, mas **não são a estratégia padrão**.

Quando um patch temporário for inevitável, documente:

- por que a implementação canônica não pode ser modificada imediatamente;
- qual comportamento ele substitui;
- como será testado;
- qual é o critério para incorporá-lo ao módulo canônico;
- qual caminho antigo será removido depois.

Patch sem plano de consolidação é dívida nova.

## 7. Não manter duas verdades

Para uma mesma pergunta de negócio não devem existir várias respostas independentes.

Exemplos:

- duas autoridades diferentes dizendo se a placa está presente;
- dois cálculos diferentes de energia do display;
- dois schedulers decidindo quando analisar;
- UI e runtime calculando separadamente o mesmo status semântico.

Se dois métodos precisam coexistir, um deles deve ser explicitamente diagnóstico/fallback e sua precedência deve estar documentada.

## 8. Regra das duas tentativas

Duas tentativas fracassadas para o mesmo problema encerram o modo "tentativa de correção".

A próxima ação obrigatória é diagnóstico:

- instrumentar tempo;
- registrar quantidade de chamadas;
- identificar thread atual;
- registrar identificadores de frame;
- verificar estado antes/depois;
- identificar qual wrapper executou;
- identificar qual autoridade publicou o resultado;
- verificar se há chamadas duplicadas.

Somente após evidência nova deve existir terceira tentativa.

## 9. Refatorações

Refatoração deve preservar comportamento salvo quando a mudança funcional estiver explicitamente no escopo.

Refatorações grandes devem ser incrementais.

Sequência preferida:

1. contrato/teste do comportamento atual;
2. extrair responsabilidade;
3. adaptar consumidor;
4. executar regressões;
5. remover caminho antigo;
6. limpar compatibilidade temporária.

Não misture, sem necessidade, refatoração arquitetural e alteração de algoritmo óptico no mesmo passo.

## 10. Features novas

Uma feature nova deve entrar por um contrato claro.

Antes de implementar:

- qual domínio é dono?
- qual serviço recebe a responsabilidade?
- qual estado novo é necessário?
- qual persistência muda?
- qual UI apenas apresenta isso?
- quais testes provam isolamento?

Não conectar uma feature diretamente a atributos internos de vários mixins apenas porque estão acessíveis.

## 11. Tratamento de erros

Novos códigos não devem usar `except Exception: pass` como comportamento normal.

Quando uma exceção precisa ser absorvida para preservar a UI:

- limite o bloco ao menor trecho possível;
- registre diagnóstico suficiente;
- não esconda mudança de estado importante;
- não transforme erro de programação em fallback silencioso.

## 12. Concorrência

Todo worker precisa de:

- proprietário;
- nome;
- política de início;
- política de parada;
- cancelamento ou encerramento;
- limite de concorrência;
- contrato de retorno;
- regra de acesso a estado.

Não criar uma thread nova por clique/frame sem controle.

Não manipular Tkinter a partir de worker.

## 13. Filas e backpressure

Filas precisam de limite explícito.

Para frames de câmera ao vivo, usar latest-frame-wins em vez de fila histórica.

Para tarefas que precisam preservar ordem, declarar:

- tamanho máximo;
- política de descarte;
- prioridade;
- comportamento quando cheia.

Nenhuma fila pode crescer indefinidamente.

## 14. Caches

Cache é otimização, não fonte secundária de verdade.

Todo cache precisa definir:

- chave;
- limite;
- invalidação;
- comportamento após escrita;
- comportamento após troca de projeto;
- comportamento após mudança de referência/resolução.

## 15. Auditoria de resíduos

Ao finalizar uma mudança, procure no escopo:

- funções substituídas;
- imports mortos;
- estados antigos;
- callbacks duplicados;
- timers duplicados;
- aliases de migração;
- classes sem consumidores;
- comentários obsoletos;
- testes exclusivos de código já removido.

Se um resíduo não puder ser removido ainda, documente por quê.

## 16. Testes

Testes devem validar comportamento, contratos e regressões.

Evite testes que apenas confirmam texto do código-fonte quando um teste comportamental é viável.

Para mudanças críticas:

- teste unitário do serviço;
- teste do contrato entre camadas;
- regressão do fluxo;
- teste de isolamento F2/F3 quando necessário;
- teste de lifecycle para timer/thread quando necessário.

## 17. Commits

Prefira commits pequenos, coerentes e reversíveis.

Um commit deve contar uma história técnica única.

Evite commits que simultaneamente:

- mudam algoritmo;
- reorganizam dezenas de arquivos;
- alteram UI;
- atualizam plataforma;
- removem legado.

Isso dificulta regressão e revisão.

## 18. Critério de qualidade

Uma solução melhor não é necessariamente a que possui menos linhas.

Ela é a que deixa:

- menos autoridades;
- menos caminhos concorrentes;
- menos estado implícito;
- menos processamento redundante;
- responsabilidade mais clara;
- testes mais fortes;
- menor custo de manutenção.
