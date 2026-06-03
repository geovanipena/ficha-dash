"""Ficha Dash — Ficha técnica de tratamento em radioterapia.

Aplicação Dash que recebe os objetos DICOM-RT (TC, RP, RS, RD) exportados do
sistema de planejamento, extrai os dados do plano e elabora/exporta (PDF) a
ficha técnica de tratamento.
"""

from __future__ import annotations

import base64
import io
from datetime import date

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, dcc, html, no_update
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

import dicom_rt

# ---------------------------------------------------------------------------
# Constantes do domínio (radioterapia)
# ---------------------------------------------------------------------------

TECNICAS = ["3D Conformacional (3D-CRT)", "IMRT", "VMAT", "SBRT/SABR", "Elétrons", "2D"]
ENERGIAS = ["6 MV", "10 MV", "15 MV", "6 FFF", "10 FFF", "6 MeV", "9 MeV", "12 MeV"]
EQUIPAMENTOS = ["LINAC TrueBeam", "LINAC Halcyon", "LINAC Versa HD", "Tomotherapy", "Cyberknife"]

# Objetos DICOM lidos pelo botão do plano (identificados pela modalidade).
OBJETOS_PLANO = ("RP", "RS", "RD")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.FLATLY, dbc.icons.FONT_AWESOME],
    title="Ficha Dash — Radioterapia",
    suppress_callback_exceptions=True,
)
server = app.server  # ponto de entrada para o gunicorn


def _campo(label: str, componente):
    """Agrupa um rótulo e um input em uma coluna do formulário."""
    return dbc.Col([dbc.Label(label, className="fw-semibold"), componente], md=4, className="mb-3")


def zona_upload(upload_id: str, status_id: str, rotulo: str, multiple: bool):
    """Área de upload (dcc.Upload) com rótulo e status."""
    return dbc.Col(
        [
            dcc.Upload(
                id=upload_id,
                multiple=multiple,
                children=html.Div(
                    [html.I(className="fa-solid fa-cloud-arrow-up fa-lg mb-1"), html.Br(), rotulo],
                    className="text-center py-4",
                ),
                className="border border-2 border-dashed rounded text-muted",
                style={"cursor": "pointer"},
            ),
            html.Div(id=status_id, className="small mt-1 text-center"),
        ],
        md=6,
        className="mb-2",
    )


def secao_upload():
    return dbc.Card(
        [
            dbc.CardHeader([html.I(className="fa-solid fa-file-import me-2"), "Importar plano (DICOM-RT)"]),
            dbc.CardBody(
                dbc.Row(
                    [
                        zona_upload("upload-tc", "status-tc", "TC (imagens CT)", multiple=True),
                        zona_upload(
                            "upload-plano",
                            "status-plano",
                            "Plano — RP + RS + RD",
                            multiple=True,
                        ),
                    ]
                )
            ),
        ],
        className="mb-4 shadow-sm",
    )


def secao_paciente():
    return dbc.Card(
        [
            dbc.CardHeader([html.I(className="fa-solid fa-user me-2"), "Dados do paciente"]),
            dbc.CardBody(
                dbc.Row(
                    [
                        _campo("Nome", dbc.Input(id="pac-nome", placeholder="Nome completo")),
                        _campo("Registro / Prontuário", dbc.Input(id="pac-registro")),
                        _campo("Nascimento", dbc.Input(id="pac-nascimento", placeholder="DD/MM/AAAA")),
                    ]
                )
            ),
        ],
        className="mb-4 shadow-sm",
    )


def secao_diagnostico():
    return dbc.Card(
        [
            dbc.CardHeader([html.I(className="fa-solid fa-notes-medical me-2"), "Diagnóstico"]),
            dbc.CardBody(
                dbc.Row(
                    [
                        _campo("Localização do tumor", dbc.Input(id="dx-local")),
                        _campo("CID-10", dbc.Input(id="dx-cid", placeholder="ex.: C50.9")),
                        _campo("Estadiamento (TNM)", dbc.Input(id="dx-tnm", placeholder="ex.: T2N0M0")),
                    ]
                )
            ),
        ],
        className="mb-4 shadow-sm",
    )


def secao_prescricao():
    return dbc.Card(
        [
            dbc.CardHeader([html.I(className="fa-solid fa-radiation me-2"), "Prescrição"]),
            dbc.CardBody(
                [
                    dbc.Row(
                        [
                            _campo(
                                "Dose total (Gy)",
                                dbc.Input(id="rx-dose-total", type="number", min=0, step=0.1),
                            ),
                            _campo(
                                "Dose / fração (Gy)",
                                dbc.Input(id="rx-dose-fracao", type="number", min=0, step=0.1),
                            ),
                            _campo(
                                "Nº de frações",
                                dbc.Input(id="rx-fracoes", type="number", min=0, step=1),
                            ),
                        ]
                    ),
                    dbc.Row(
                        [
                            _campo("Técnica", dbc.Input(id="rx-tecnica")),
                            _campo("Energia", dbc.Input(id="rx-energia")),
                            _campo("Equipamento", dbc.Input(id="rx-equipamento")),
                        ]
                    ),
                    html.Div(id="rx-resumo", className="text-muted fst-italic"),
                ]
            ),
        ],
        className="mb-4 shadow-sm",
    )


def secao_feixes():
    return dbc.Card(
        [
            dbc.CardHeader([html.I(className="fa-solid fa-arrows-to-dot me-2"), "Feixes"]),
            dbc.CardBody(html.Div(id="tabela-feixes", className="text-muted small")),
        ],
        className="mb-4 shadow-sm",
    )


def secao_estruturas():
    return dbc.Card(
        [
            dbc.CardHeader([html.I(className="fa-solid fa-draw-polygon me-2"), "Volumes e órgãos de risco"]),
            dbc.CardBody(html.Div(id="lista-estruturas", className="text-muted small")),
        ],
        className="mb-4 shadow-sm",
    )


def secao_equipe():
    return dbc.Card(
        [
            dbc.CardHeader([html.I(className="fa-solid fa-user-doctor me-2"), "Equipe responsável"]),
            dbc.CardBody(
                dbc.Row(
                    [
                        _campo("Médico radio-oncologista", dbc.Input(id="eq-medico")),
                        _campo("Físico médico", dbc.Input(id="eq-fisico")),
                        _campo("Dosimetrista", dbc.Input(id="eq-dosimetrista")),
                    ]
                )
            ),
        ],
        className="mb-4 shadow-sm",
    )


app.layout = dbc.Container(
    [
        dcc.Store(id="store-dicom", data={}),
        html.Div(
            [
                html.H2(
                    [html.I(className="fa-solid fa-file-medical me-2"), "Ficha técnica — Radioterapia"],
                    className="mb-0",
                ),
                html.P("Importe o plano (DICOM-RT) e gere a ficha técnica.", className="text-muted"),
            ],
            className="my-4",
        ),
        secao_upload(),
        secao_paciente(),
        secao_diagnostico(),
        secao_prescricao(),
        secao_feixes(),
        secao_estruturas(),
        secao_equipe(),
        dbc.Row(
            dbc.Col(
                dbc.Button(
                    [html.I(className="fa-solid fa-file-pdf me-2"), "Gerar ficha em PDF"],
                    id="btn-pdf",
                    color="primary",
                    size="lg",
                ),
                width="auto",
            ),
            justify="end",
            className="mb-5",
        ),
        dcc.Download(id="download-pdf"),
    ],
    fluid="lg",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decodificar(contents: str) -> bytes:
    """Decodifica o conteúdo base64 de um dcc.Upload."""
    _, b64 = contents.split(",", 1)
    return base64.b64decode(b64)


# ---------------------------------------------------------------------------
# Callbacks — ingestão DICOM
# ---------------------------------------------------------------------------


def _status_ok(txt):
    return html.Span([html.I(className="fa-solid fa-circle-check text-success me-1"), txt])


def _status_erro(txt):
    return html.Span([html.I(className="fa-solid fa-circle-xmark text-danger me-1"), txt])


@app.callback(
    Output("store-dicom", "data"),
    Output("status-tc", "children"),
    Output("status-plano", "children"),
    Input("upload-tc", "contents"),
    Input("upload-plano", "contents"),
    State("store-dicom", "data"),
    prevent_initial_call=True,
)
def importar_dicom(c_tc, c_plano, store):
    """Processa os uploads (TC e o pacote do plano) e acumula no store."""
    store = dict(store or {})
    disparo = dash.callback_context.triggered_id
    status_tc, status_plano = no_update, no_update

    # Botão da TC — pode vir uma série; usamos o primeiro corte para metadados.
    if disparo == "upload-tc" and c_tc:
        primeiro = c_tc[0] if isinstance(c_tc, list) else c_tc
        try:
            lido, dados = dicom_rt.processar(_decodificar(primeiro))
            if lido == "TC":
                store["TC"] = dados
                n = len(c_tc) if isinstance(c_tc, list) else 1
                status_tc = _status_ok(f"TC carregada ({n} arquivo(s))")
            else:
                status_tc = _status_erro(f"Arquivo é {lido}, esperado TC")
        except Exception as exc:  # noqa: BLE001 — feedback ao usuário, não interrompe
            status_tc = _status_erro(f"Falha: {exc}")

    # Botão do plano — identifica RP/RS/RD automaticamente pela modalidade.
    if disparo == "upload-plano" and c_plano:
        arquivos = c_plano if isinstance(c_plano, list) else [c_plano]
        carregados, erros = [], []
        for contents in arquivos:
            try:
                lido, dados = dicom_rt.processar(_decodificar(contents))
                if lido in OBJETOS_PLANO:
                    store[lido] = dados
                    carregados.append(lido)
                else:
                    erros.append(f"{lido} ignorado")
            except Exception as exc:  # noqa: BLE001
                erros.append(str(exc))
        faltando = [c for c in OBJETOS_PLANO if c not in store]
        partes = []
        if carregados:
            partes.append(_status_ok(", ".join(sorted(set(carregados))) + " carregado(s)"))
        if faltando:
            partes.append(html.Span(f" · faltando: {', '.join(faltando)}", className="text-warning"))
        if erros:
            partes.append(_status_erro(" · " + "; ".join(erros)))
        status_plano = html.Span(partes) if partes else _status_erro("Nenhum RP/RS/RD encontrado")

    return store, status_tc, status_plano


def _paciente_do_store(store: dict) -> dict:
    """Demografia do paciente, priorizando RP > RS > RD > TC."""
    for codigo in ("RP", "RS", "RD", "TC"):
        if store.get(codigo, {}).get("paciente"):
            return store[codigo]["paciente"]
    return {}


@app.callback(
    Output("pac-nome", "value"),
    Output("pac-registro", "value"),
    Output("pac-nascimento", "value"),
    Output("rx-dose-total", "value"),
    Output("rx-dose-fracao", "value"),
    Output("rx-fracoes", "value"),
    Output("rx-tecnica", "value"),
    Output("rx-energia", "value"),
    Output("rx-equipamento", "value"),
    Input("store-dicom", "data"),
    prevent_initial_call=True,
)
def preencher_formulario(store):
    """Auto-preenche paciente e prescrição a partir dos objetos importados."""
    store = store or {}
    if not store:
        return (no_update,) * 9
    pac = _paciente_do_store(store)
    rp = store.get("RP", {})
    return (
        pac.get("nome") or no_update,
        pac.get("registro") or no_update,
        pac.get("nascimento") or no_update,
        rp.get("dose_total") or no_update,
        rp.get("dose_fracao") or no_update,
        rp.get("num_fracoes") or no_update,
        rp.get("tecnica") or no_update,
        rp.get("energia") or no_update,
        rp.get("maquina") or no_update,
    )


def _grau(v, sufixo="°"):
    return f"{float(v):g}{sufixo}" if v is not None else "—"


@app.callback(Output("tabela-feixes", "children"), Input("store-dicom", "data"))
def render_feixes(store):
    """Renderiza a tabela feixe a feixe do RT Plan."""
    feixes = (store or {}).get("RP", {}).get("feixes") or []
    if not feixes:
        return "Importe o RP (RT Plan) para listar os feixes."
    cabecalho = ["#", "Nome", "Técnica", "Energia", "Gantry", "Colim.", "Mesa", "UM", "Dose (Gy)"]
    linhas = [
        html.Tr(
            [
                html.Td(f.get("numero") or "—"),
                html.Td(f.get("nome") or "—"),
                html.Td(f.get("tecnica") or "—"),
                html.Td(f"{float(f['energia']):g} MV" if f.get("energia") else "—"),
                html.Td(_grau(f.get("gantry"))),
                html.Td(_grau(f.get("colimador"))),
                html.Td(_grau(f.get("mesa"))),
                html.Td(f"{float(f['um']):g}" if f.get("um") is not None else "—"),
                html.Td(f"{float(f['dose_feixe']):g}" if f.get("dose_feixe") is not None else "—"),
            ]
        )
        for f in feixes
    ]
    return dbc.Table(
        [html.Thead(html.Tr([html.Th(c) for c in cabecalho])), html.Tbody(linhas)],
        bordered=True,
        hover=True,
        striped=True,
        size="sm",
    )


@app.callback(Output("lista-estruturas", "children"), Input("store-dicom", "data"))
def render_estruturas(store):
    """Lista os volumes-alvo e os órgãos de risco do RT Struct."""
    rs = (store or {}).get("RS", {})
    if not rs:
        return "Importe o RS (RT Struct) para listar os volumes e órgãos de risco."
    alvos = rs.get("alvos") or []
    oars = rs.get("orgaos_risco") or []

    def badges(itens, cor):
        return [dbc.Badge(i["nome"], color=cor, className="me-1 mb-1") for i in itens] or ["—"]

    return html.Div(
        [
            html.Div([html.Strong("Volumes-alvo: "), *badges(alvos, "danger")], className="mb-2"),
            html.Div([html.Strong("Órgãos de risco: "), *badges(oars, "info")]),
        ]
    )


@app.callback(
    Output("rx-resumo", "children"),
    Input("rx-dose-total", "value"),
    Input("rx-dose-fracao", "value"),
    Input("rx-fracoes", "value"),
)
def resumo_prescricao(dose_total, dose_fracao, fracoes):
    """Confere a coerência entre dose total, dose/fração e número de frações."""
    if dose_fracao and fracoes:
        calculada = round(dose_fracao * fracoes, 2)
        msg = f"Dose total calculada: {calculada} Gy ({fracoes} × {dose_fracao} Gy)."
        if dose_total and abs(calculada - dose_total) > 0.5:
            return f"⚠️ {msg} Diverge da dose total informada ({dose_total} Gy)."
        return f"✓ {msg}"
    return ""


# ---------------------------------------------------------------------------
# Callbacks — geração de PDF
# ---------------------------------------------------------------------------


def _tabela_pdf(linhas, larguras):
    tabela = Table(linhas, colWidths=larguras)
    tabela.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f3f5")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return tabela


def _construir_pdf(dados: dict, store: dict) -> bytes:
    """Gera o PDF da ficha técnica a partir do formulário e dos dados DICOM."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm)
    estilos = getSampleStyleSheet()
    elementos = [
        Paragraph("Ficha Técnica de Tratamento — Radioterapia", estilos["Title"]),
        Spacer(1, 5 * mm),
    ]

    secoes = {
        "Paciente": [
            ("Nome", dados.get("pac_nome")),
            ("Registro", dados.get("pac_registro")),
            ("Nascimento", dados.get("pac_nascimento")),
        ],
        "Diagnóstico": [
            ("Localização", dados.get("dx_local")),
            ("CID-10", dados.get("dx_cid")),
            ("TNM", dados.get("dx_tnm")),
        ],
        "Prescrição": [
            ("Dose total (Gy)", dados.get("rx_dose_total")),
            ("Dose/fração (Gy)", dados.get("rx_dose_fracao")),
            ("Nº de frações", dados.get("rx_fracoes")),
            ("Técnica", dados.get("rx_tecnica")),
            ("Energia", dados.get("rx_energia")),
            ("Equipamento", dados.get("rx_equipamento")),
        ],
        "Equipe": [
            ("Médico", dados.get("eq_medico")),
            ("Físico", dados.get("eq_fisico")),
            ("Dosimetrista", dados.get("eq_dosimetrista")),
        ],
    }

    for titulo, linhas in secoes.items():
        elementos.append(Paragraph(titulo, estilos["Heading2"]))
        elementos.append(
            _tabela_pdf(
                [[rotulo, str(valor or "—")] for rotulo, valor in linhas],
                [55 * mm, 110 * mm],
            )
        )
        elementos.append(Spacer(1, 4 * mm))

    # Tabela de feixes (RT Plan).
    feixes = store.get("RP", {}).get("feixes") or []
    if feixes:
        elementos.append(Paragraph("Feixes", estilos["Heading2"]))
        cab = ["#", "Nome", "Técnica", "Energia", "Gantry", "Colim.", "Mesa", "UM", "Dose"]
        corpo = [cab] + [
            [
                str(f.get("numero") or "—"),
                f.get("nome") or "—",
                f.get("tecnica") or "—",
                f"{float(f['energia']):g} MV" if f.get("energia") else "—",
                f"{float(f['gantry']):g}°" if f.get("gantry") is not None else "—",
                f"{float(f['colimador']):g}°" if f.get("colimador") is not None else "—",
                f"{float(f['mesa']):g}°" if f.get("mesa") is not None else "—",
                f"{float(f['um']):g}" if f.get("um") is not None else "—",
                f"{float(f['dose_feixe']):g}" if f.get("dose_feixe") is not None else "—",
            ]
            for f in feixes
        ]
        elementos.append(_tabela_pdf(corpo, None))
        elementos.append(Spacer(1, 4 * mm))

    # Volumes e órgãos de risco (RT Struct).
    rs = store.get("RS", {})
    if rs:
        alvos = ", ".join(a["nome"] for a in rs.get("alvos", [])) or "—"
        oars = ", ".join(o["nome"] for o in rs.get("orgaos_risco", [])) or "—"
        elementos.append(Paragraph("Volumes e órgãos de risco", estilos["Heading2"]))
        elementos.append(
            _tabela_pdf(
                [["Volumes-alvo", alvos], ["Órgãos de risco", oars]],
                [55 * mm, 110 * mm],
            )
        )
        elementos.append(Spacer(1, 4 * mm))

    elementos.append(Spacer(1, 6 * mm))
    elementos.append(
        Paragraph(f"Documento gerado em {date.today().strftime('%d/%m/%Y')}.", estilos["Italic"])
    )
    doc.build(elementos)
    return buffer.getvalue()


@app.callback(
    Output("download-pdf", "data"),
    Input("btn-pdf", "n_clicks"),
    State("store-dicom", "data"),
    State("pac-nome", "value"),
    State("pac-registro", "value"),
    State("pac-nascimento", "value"),
    State("dx-local", "value"),
    State("dx-cid", "value"),
    State("dx-tnm", "value"),
    State("rx-dose-total", "value"),
    State("rx-dose-fracao", "value"),
    State("rx-fracoes", "value"),
    State("rx-tecnica", "value"),
    State("rx-energia", "value"),
    State("rx-equipamento", "value"),
    State("eq-medico", "value"),
    State("eq-fisico", "value"),
    State("eq-dosimetrista", "value"),
    prevent_initial_call=True,
)
def gerar_pdf(
    n_clicks,
    store,
    pac_nome,
    pac_registro,
    pac_nascimento,
    dx_local,
    dx_cid,
    dx_tnm,
    rx_dose_total,
    rx_dose_fracao,
    rx_fracoes,
    rx_tecnica,
    rx_energia,
    rx_equipamento,
    eq_medico,
    eq_fisico,
    eq_dosimetrista,
):
    dados = {
        "pac_nome": pac_nome,
        "pac_registro": pac_registro,
        "pac_nascimento": pac_nascimento,
        "dx_local": dx_local,
        "dx_cid": dx_cid,
        "dx_tnm": dx_tnm,
        "rx_dose_total": rx_dose_total,
        "rx_dose_fracao": rx_dose_fracao,
        "rx_fracoes": rx_fracoes,
        "rx_tecnica": rx_tecnica,
        "rx_energia": rx_energia,
        "rx_equipamento": rx_equipamento,
        "eq_medico": eq_medico,
        "eq_fisico": eq_fisico,
        "eq_dosimetrista": eq_dosimetrista,
    }
    pdf_bytes = _construir_pdf(dados, store or {})
    nome_arquivo = f"ficha_{(pac_nome or 'paciente').strip().replace(' ', '_').lower()}.pdf"
    return dcc.send_bytes(pdf_bytes, nome_arquivo)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
