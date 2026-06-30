# Estrutura do Projeto — ODIN v10

## Objetivo desta versão

Modularizar somente o arquivo `src/ui/main_window.py`, mantendo a classe pública `ODINView` e preservando nomes de funções, variáveis, callbacks e regras de negócio.

## Estrutura da interface modularizada

```text
src/ui/
│   main_window.py
│   __init__.py
│
└───main_window_parts
    │   __init__.py
    │
    ├───canvas
    ├───history
    ├───image
    ├───layout
    ├───lifecycle
    ├───panels
    ├───settings
    ├───state
    ├───updates
    └───widgets
```

## Regra aplicada

`src/ui/main_window.py` continua sendo o ponto público usado pelo restante do sistema:

```python
from src.ui.main_window import ODINView
```

Os métodos foram movidos para `src/ui/main_window_parts/` e vinculados novamente dentro da classe `ODINView`, mantendo os mesmos nomes.

## Responsabilidades por pasta

| Pasta | Responsabilidade |
|---|---|
| `lifecycle` | inicialização da janela |
| `layout` | montagem estrutural do layout |
| `panels` | painéis principais da interface |
| `widgets` | componentes reutilizáveis |
| `settings` | janela de configurações |
| `image` | redimensionamento, exibição e conversão de coordenadas da imagem |
| `canvas` | desenho de imagem, LEDs, resultados e placeholders |
| `state` | normalização de listas/estado visual |
| `updates` | atualização de textos, resumo, KPIs e renderizações |
| `history` | histórico, observações, barra de confiança e data/hora |

## Observação

Esta etapa não altera regra de classificação, extração de features, salvamento, seleção ou callbacks. É somente refatoração estrutural da interface.
