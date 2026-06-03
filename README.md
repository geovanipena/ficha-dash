# Ficha Dash

Aplicação web para elaborar, visualizar e exportar a **ficha técnica de
tratamento em radioterapia**, construída com [Plotly Dash](https://dash.plotly.com/).

## Funcionalidades

- Formulário estruturado em seções: paciente, diagnóstico, prescrição e equipe.
- Conferência automática da dose (dose/fração × nº de frações vs. dose total).
- Exportação da ficha em **PDF** (ReportLab).
- Base preparada para assistência via API da Claude (`anthropic`).

## Stack

- Plotly Dash + `dash-bootstrap-components` (UI)
- Plotly / Pandas (dados e gráficos)
- ReportLab + pypdf (geração de PDF)
- Anthropic SDK (recursos de IA)
- Gunicorn (produção)

## Como rodar (desenvolvimento)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

A aplicação fica disponível em http://localhost:8050.

## Produção

```bash
gunicorn app:server
```

## Variáveis de ambiente

| Variável            | Descrição                                  |
| ------------------- | ------------------------------------------ |
| `ANTHROPIC_API_KEY` | Chave da API da Claude (recursos de IA).   |

## Estrutura

```
ficha-dash/
├── app.py            # Aplicação Dash (layout, callbacks, geração de PDF)
├── requirements.txt
├── Procfile          # gunicorn app:server
└── .claude/          # Configuração de tooling (ruff)
```
