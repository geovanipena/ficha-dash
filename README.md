# Ficha Dash

Aplicação web para elaborar, visualizar e exportar a **ficha técnica de
tratamento em radioterapia**, construída com [Plotly Dash](https://dash.plotly.com/).

## Funcionalidades

- Importação do plano via **`.dcm` soltos, `.zip` ou `.rar`** (o pacote é
  descompactado no servidor, evitando subir o RT Dose cru — que pode ter
  centenas de MB). Para `.rar` o ambiente precisa de `unrar`/`7z`; `.zip`
  funciona sem dependências externas.
- Formulário estruturado em seções: paciente, diagnóstico, prescrição e equipe.
- Conferência automática da dose (dose/fração × nº de frações vs. dose total).
- Exportação da ficha em **PDF** (ReportLab).

> Todo o processamento é **local e offline**: os objetos DICOM são lidos e a
> ficha é gerada na própria máquina, sem enviar dados do paciente para
> serviços externos.

## Stack

- Plotly Dash + `dash-bootstrap-components` (UI)
- Plotly / Pandas (dados e gráficos)
- ReportLab + pypdf (geração de PDF)
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

A aplicação não exige variáveis de ambiente para funcionar.

## Estrutura

```
ficha-dash/
├── app.py            # Aplicação Dash (layout, callbacks, upload DICOM)
├── dicom_rt.py       # Leitura dos objetos DICOM-RT (TC/RP/RS/RD)
├── ficha_pdf.py      # Geração do PDF no layout institucional (Cebrom)
├── assets/           # Logo e estáticos servidos pelo Dash
├── requirements.txt
├── Procfile          # gunicorn app:server
└── .claude/          # Configuração de tooling (ruff)
```

## Geração da ficha (PDF)

`ficha_pdf.gerar_ficha(dados, store)` reproduz o formulário institucional:

- **Página 2** — Ficha Técnica de Tratamento (cabeçalho + paciente, tabela do
  plano, tabela de campos/feixes, observações e checklist pré-tratamento).
- **Página 3** — mapa de acompanhamento das frações com dose cumulativa.
- **Página 1** (cortes ortogonais + DVH) — em desenvolvimento; requer a série
  de TC e o RT Dose/Struct para renderização das imagens e do histograma.
