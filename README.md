# Ficha-Py

Versão **local e interativa** do [ficha-dash](https://github.com/geovanipena/ficha-dash):
gera a **ficha técnica de tratamento em radioterapia** e, diferente do ficha-dash
(em que a TC era opcional e usava só um corte), o Ficha-Py carrega a **série de
TC completa** do paciente e oferece um visualizador navegável dos cortes.

## O que ele faz

- **Importa a TC completa** (todos os cortes, em `.zip`/`.rar` ou vários `.dcm`)
  e o plano DICOM-RT (`RP` + `RS` + `RD`).
- **Visualizador interativo** da TC:
  - planos **axial / sagital / coronal** (reconstrução multiplanar);
  - **slider** para navegar corte a corte;
  - **janelas** de visualização (partes moles, pulmão, osso, cérebro…);
  - **contornos do RT Struct** sobrepostos no corte axial.
- Preenche automaticamente paciente, prescrição, feixes e equipe a partir do plano.
- **Exporta a ficha em PDF** já com a página de imagens (cortes ortogonais +
  corpo 3D + **DVH**), além da ficha técnica e do mapa de frações.

## Como rodar (local)

Requer Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

`run.py` sobe o servidor e **abre o navegador** automaticamente em
http://127.0.0.1:8050. Opções:

```bash
python run.py --port 9000          # outra porta
python run.py --no-browser         # não abrir o navegador
```

Também é possível rodar direto com `python app.py` (modo debug).

## Fluxo de uso

1. **TC completa** — solte o `.zip` (ou os `.dcm`) da série inteira no primeiro
   botão. O visualizador aparece com o número de cortes detectado.
2. **Plano** — solte `RP` + `RS` + `RD` (soltos ou zipados) no segundo botão.
   Paciente, prescrição, feixes e estruturas são preenchidos.
3. Navegue pelos cortes (plano + slider + janela) e confira os contornos.
4. **Gerar ficha em PDF** — baixa o PDF com a página de imagens + ficha + frações.

## Estrutura

```
ficha-py/
├── run.py            # launcher local (abre o navegador)
├── app.py            # aplicação Dash (layout, callbacks, visualizador)
├── ct_series.py      # série de TC completa: volume 3D e cortes (MPR)
├── dicom_rt.py       # leitura dos objetos DICOM-RT (TC/RP/RS/RD)
├── cortes.py         # render do corte axial com estruturas
├── corpo3d.py        # render 3D do corpo (contorno EXTERNAL)
├── dvh.py            # cálculo e plot do histograma dose-volume
├── ficha_pdf.py      # PDF (página de imagens + ficha + frações)
├── assets/           # logo e estáticos
└── requirements.txt
```

## Observações

- A série de TC é mantida **em memória** durante a sessão (app local, um
  usuário). Nada é enviado para fora da sua máquina.
- Suporte a `.rar` exige `unrar`/`7z` instalados; `.zip` funciona sem
  dependências externas.
