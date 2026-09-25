# Estrutura do Projeto — registro histórico v10

> **Documento histórico. Não é a arquitetura normativa atual do ODIN.**
>
> Para decisões atuais, leia `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/ENGINEERING_RULES.md`, `docs/PERFORMANCE.md`, `docs/AI_WORKFLOW.md` e `docs/DECISIONS.md`.

## Contexto histórico

A versão v10 teve como objetivo modularizar somente o arquivo `src/ui/main_window.py`, mantendo a classe pública `ODINView` e preservando nomes de funções, variáveis, callbacks e regras de negócio.

A estrutura criada foi:

~~~text
src/ui/
│   main_window.py
│   __init__.py
│
└── main_window_parts/
    ├── canvas/
    ├── history/
    ├── image/
    ├── layout/
    ├── lifecycle/
    ├── panels/
    ├── settings/
    ├── state/
    ├── updates/
    └── widgets/
~~~

`src/ui/main_window.py` continuou sendo o ponto público usado pelo restante do sistema:

~~~python
from src.ui.main_window import ODINView
~~~

Os métodos foram distribuídos em `src/ui/main_window_parts/` e vinculados novamente dentro da classe `ODINView`.

## Responsabilidades históricas

| Pasta | Responsabilidade |
| --- | --- |
| `lifecycle` | inicialização da janela |
| `layout` | montagem estrutural do layout |
| `panels` | painéis principais |
| `widgets` | componentes reutilizáveis |
| `settings` | configurações |
| `image` | redimensionamento, exibição e coordenadas |
| `canvas` | desenho de imagem, LEDs e resultados |
| `state` | normalização de estado visual |
| `updates` | textos, resumo, KPIs e renderizações |
| `history` | histórico e informações auxiliares |

## Regra atual

Essa refatoração continua válida como registro do que aconteceu, mas não deve ser usada para concluir que "mais arquivos = melhor modularização".

A regra atual é modularizar por **responsabilidade coesa e contrato claro**, conforme `docs/ARCHITECTURE.md`.
