"""Ficha Dash — Ficha técnica de tratamento em radioterapia.

Aplicação Dash para elaborar, visualizar e exportar (PDF) a ficha técnica
de um tratamento de radioterapia. Estrutura inicial (scaffold) pronta para
receber as próximas orientações de regras clínicas e campos adicionais.
"""

from __future__ import annotations

import io
from datetime import date

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, dcc, html
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

# ---------------------------------------------------------------------------
# Constantes do domínio (radioterapia)
# ---------------------------------------------------------------------------

TECNICAS = ["3D Conformacional (3D-CRT)", "IMRT", "VMAT", "SBRT/SABR", "Eletróns", "2D"]
ENERGIAS = ["6 MV", "10 MV", "15 MV", "6 FFF", "10 FFF", "6 MeV", "9 MeV", "12 MeV"]
EQUIPAMENTOS = ["LINAC TrueBeam", "LINAC Halcyon", "LINAC Versa HD", "Tomotherapy", "Cyberknife"]

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


def secao_paciente():
    return dbc.Card(
        [
            dbc.CardHeader([html.I(className="fa-solid fa-user me-2"), "Dados do paciente"]),
            dbc.CardBody(
                dbc.Row(
                    [
                        _campo("Nome", dbc.Input(id="pac-nome", placeholder="Nome completo")),
                        _campo("Registro / Prontuário", dbc.Input(id="pac-registro")),
                        _campo(
                            "Data de nascimento",
                            dcc.DatePickerSingle(id="pac-nascimento", display_format="DD/MM/YYYY"),
                        ),
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
                            _campo("Técnica", dbc.Select(id="rx-tecnica", options=TECNICAS)),
                            _campo("Energia", dbc.Select(id="rx-energia", options=ENERGIAS)),
                            _campo("Equipamento", dbc.Select(id="rx-equipamento", options=EQUIPAMENTOS)),
                        ]
                    ),
                    html.Div(id="rx-resumo", className="text-muted fst-italic"),
                ]
            ),
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
        html.Div(
            [
                html.H2(
                    [html.I(className="fa-solid fa-file-medical me-2"), "Ficha técnica — Radioterapia"],
                    className="mb-0",
                ),
                html.P(
                    "Elaboração e exportação da ficha técnica de tratamento.",
                    className="text-muted",
                ),
            ],
            className="my-4",
        ),
        secao_paciente(),
        secao_diagnostico(),
        secao_prescricao(),
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
# Callbacks
# ---------------------------------------------------------------------------


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
        if dose_total and abs(calculada - dose_total) > 0.01:
            return f"⚠️ {msg} Diverge da dose total informada ({dose_total} Gy)."
        return f"✓ {msg}"
    return ""


def _construir_pdf(dados: dict) -> bytes:
    """Gera o PDF da ficha técnica a partir dos dados do formulário."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    estilos = getSampleStyleSheet()
    elementos = [
        Paragraph("Ficha Técnica de Tratamento — Radioterapia", estilos["Title"]),
        Spacer(1, 6 * mm),
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
        tabela = Table(
            [[rotulo, str(valor or "—")] for rotulo, valor in linhas],
            colWidths=[55 * mm, 110 * mm],
        )
        tabela.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f3f5")),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        elementos.append(tabela)
        elementos.append(Spacer(1, 5 * mm))

    elementos.append(Spacer(1, 8 * mm))
    elementos.append(
        Paragraph(
            f"Documento gerado em {date.today().strftime('%d/%m/%Y')}.",
            estilos["Italic"],
        )
    )
    doc.build(elementos)
    return buffer.getvalue()


@app.callback(
    Output("download-pdf", "data"),
    Input("btn-pdf", "n_clicks"),
    State("pac-nome", "value"),
    State("pac-registro", "value"),
    State("pac-nascimento", "date"),
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
    pdf_bytes = _construir_pdf(dados)
    nome_arquivo = f"ficha_{(pac_nome or 'paciente').strip().replace(' ', '_').lower()}.pdf"
    return dcc.send_bytes(pdf_bytes, nome_arquivo)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
