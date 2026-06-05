"""Ficha-Py — ficha técnica de radioterapia com TC completa, para rodar local.

Versão local e interativa do ficha-dash: além de extrair o plano (RP/RS/RD), o
ficha-py carrega a **série de TC completa** do paciente e oferece um
visualizador navegável (axial/sagital/coronal, janela, contornos) e a geração
da ficha em PDF já com a página de imagens (cortes + DVH).

Rode com ``python run.py`` (abre o navegador) ou ``python app.py``.
"""

from __future__ import annotations

import base64
import uuid

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, dcc, html, no_update

import ct_series
import dicom_rt
import ficha_pdf

OBJETOS_PLANO = ("RP", "RS", "RD")

# Cache em processo (app local, um único usuário) para os objetos pesados que
# não cabem/serializam bem no dcc.Store: a CTSerie e os datasets RS/RD.
RECURSOS: dict[str, dict] = {}


def _recursos(token: str) -> dict:
    return RECURSOS.setdefault(token, {"ct": None, "rs": None, "rd": None})


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.FLATLY, dbc.icons.FONT_AWESOME],
    title="Ficha-Py — Radioterapia",
    suppress_callback_exceptions=True,
)
server = app.server


def _campo(label, componente, md=4):
    return dbc.Col([dbc.Label(label, className="fw-semibold"), componente], md=md, className="mb-3")


def zona_upload(upload_id, status_id, rotulo, multiple):
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
            dbc.CardHeader([html.I(className="fa-solid fa-file-import me-2"), "Importar exame e plano"]),
            dbc.CardBody(
                [
                    dbc.Row(
                        [
                            zona_upload(
                                "upload-tc",
                                "status-tc",
                                "TC completa — todos os cortes (.zip/.rar ou vários .dcm)",
                                multiple=True,
                            ),
                            zona_upload(
                                "upload-plano",
                                "status-plano",
                                "Plano — RP + RS + RD (.dcm, .zip ou .rar)",
                                multiple=True,
                            ),
                        ]
                    ),
                    html.Div(
                        [
                            html.I(className="fa-solid fa-circle-info me-1"),
                            "Envie a série de TC inteira para navegar pelos cortes e gerar a "
                            "página de imagens. O paciente e a prescrição vêm do RP/RS/RD.",
                        ],
                        className="small text-muted mt-2",
                    ),
                ]
            ),
        ],
        className="mb-4 shadow-sm",
    )


def secao_visualizador():
    return dbc.Card(
        [
            dbc.CardHeader([html.I(className="fa-solid fa-layer-group me-2"), "Visualizador da TC"]),
            dbc.CardBody(
                [
                    dbc.Row(
                        [
                            _campo(
                                "Plano",
                                dbc.Select(
                                    id="viz-plano",
                                    options=[{"label": p, "value": p} for p in ct_series.PLANOS],
                                    value="Axial",
                                ),
                                md=3,
                            ),
                            _campo(
                                "Janela",
                                dbc.Select(
                                    id="viz-janela",
                                    options=[{"label": k, "value": k} for k in ct_series.JANELAS],
                                    value="Partes moles",
                                ),
                                md=3,
                            ),
                            dbc.Col(
                                dbc.Checklist(
                                    id="viz-estruturas",
                                    options=[{"label": " Contornos (RS)", "value": "on"}],
                                    value=["on"],
                                    switch=True,
                                    className="mt-4",
                                ),
                                md=3,
                            ),
                            dbc.Col(html.Div(id="viz-info", className="small text-muted mt-4"), md=3),
                        ]
                    ),
                    html.Div(
                        html.Img(
                            id="viz-img",
                            style={"maxWidth": "100%", "maxHeight": "560px", "background": "#fff"},
                        ),
                        className="text-center border rounded p-2 bg-light",
                    ),
                    html.Div(
                        dcc.Slider(id="viz-slice", min=0, max=0, step=1, value=0,
                                   marks=None, tooltip={"placement": "bottom"}),
                        className="mt-3",
                    ),
                ]
            ),
        ],
        id="card-visualizador",
        className="mb-4 shadow-sm d-none",
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
                            _campo("Dose total (Gy)",
                                   dbc.Input(id="rx-dose-total", type="number", min=0, step=0.1)),
                            _campo("Dose / fração (Gy)",
                                   dbc.Input(id="rx-dose-fracao", type="number", min=0, step=0.1)),
                            _campo("Nº de frações",
                                   dbc.Input(id="rx-fracoes", type="number", min=0, step=1)),
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
                    [html.I(className="fa-solid fa-file-medical me-2"), "Ficha-Py — Radioterapia"],
                    className="mb-0",
                ),
                html.P(
                    "Importe a TC completa e o plano (DICOM-RT), navegue pelos cortes e gere a ficha.",
                    className="text-muted",
                ),
            ],
            className="my-4",
        ),
        secao_upload(),
        secao_visualizador(),
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
    _, b64 = contents.split(",", 1)
    return base64.b64decode(b64)


def _status_ok(txt):
    return html.Span([html.I(className="fa-solid fa-circle-check text-success me-1"), txt])


def _status_erro(txt):
    return html.Span([html.I(className="fa-solid fa-circle-xmark text-danger me-1"), txt])


# ---------------------------------------------------------------------------
# Ingestão (TC completa + plano)
# ---------------------------------------------------------------------------


@app.callback(
    Output("store-dicom", "data"),
    Output("status-tc", "children"),
    Output("status-plano", "children"),
    Input("upload-tc", "contents"),
    Input("upload-plano", "contents"),
    State("store-dicom", "data"),
    prevent_initial_call=True,
)
def importar(c_tc, c_plano, store):
    store = dict(store or {})
    store.setdefault("token", uuid.uuid4().hex)
    store.setdefault("dados", {})
    rec = _recursos(store["token"])
    disparo = dash.callback_context.triggered_id
    status_tc, status_plano = no_update, no_update

    if disparo == "upload-tc" and c_tc:
        arquivos = c_tc if isinstance(c_tc, list) else [c_tc]
        try:
            serie = ct_series.carregar_serie([_decodificar(a) for a in arquivos])
            rec["ct"] = serie
            store["dados"]["TC"] = {
                "paciente": serie.paciente,
                "descricao_estudo": serie.descricao,
                "data_estudo": serie.data_estudo,
                "instituicao": serie.instituicao,
            }
            store["viewer"] = {p: serie.n_cortes(p) for p in ct_series.PLANOS}
            status_tc = _status_ok(f"TC carregada — {serie.n_axial} cortes")
        except Exception as exc:  # noqa: BLE001
            status_tc = _status_erro(f"Falha: {exc}")

    if disparo == "upload-plano" and c_plano:
        arquivos = c_plano if isinstance(c_plano, list) else [c_plano]
        carregados, erros = [], []
        for contents in arquivos:
            try:
                for membro in dicom_rt.iter_dicoms(_decodificar(contents)):
                    try:
                        ds = dicom_rt.carregar(membro)
                        codigo = dicom_rt.identificar(ds)
                    except Exception:  # noqa: BLE001
                        continue
                    if codigo not in OBJETOS_PLANO:
                        continue
                    store["dados"][codigo] = dicom_rt.PARSERS[codigo](ds)
                    carregados.append(codigo)
                    if codigo == "RS":
                        rec["rs"] = ds  # contornos (sem pixels) bastam
                    elif codigo == "RD":
                        # RT Dose precisa da matriz de dose para o DVH.
                        rec["rd"] = dicom_rt.carregar(membro, stop_before_pixels=False)
            except Exception as exc:  # noqa: BLE001
                erros.append(str(exc))
        faltando = [c for c in OBJETOS_PLANO if c not in store["dados"]]
        partes = []
        if carregados:
            partes.append(_status_ok(", ".join(sorted(set(carregados))) + " carregado(s)"))
        if faltando:
            partes.append(html.Span(f" · faltando: {', '.join(faltando)}", className="text-warning"))
        if erros:
            partes.append(_status_erro(" · " + "; ".join(erros)))
        status_plano = html.Span(partes) if partes else _status_erro("Nenhum RP/RS/RD encontrado")

    return store, status_tc, status_plano


# ---------------------------------------------------------------------------
# Visualizador
# ---------------------------------------------------------------------------


@app.callback(
    Output("card-visualizador", "className"),
    Output("viz-slice", "max"),
    Output("viz-slice", "value"),
    Output("viz-info", "children"),
    Input("store-dicom", "data"),
    Input("viz-plano", "value"),
    prevent_initial_call=True,
)
def ajustar_slider(store, plano):
    viewer = (store or {}).get("viewer")
    if not viewer:
        return "mb-4 shadow-sm d-none", 0, 0, ""
    n = int(viewer.get(plano, 1))
    central = n // 2
    info = f"{n} cortes · plano {plano.lower()}"
    return "mb-4 shadow-sm", max(n - 1, 0), central, info


@app.callback(
    Output("viz-img", "src"),
    Input("viz-plano", "value"),
    Input("viz-slice", "value"),
    Input("viz-janela", "value"),
    Input("viz-estruturas", "value"),
    State("store-dicom", "data"),
)
def render_corte(plano, idx, janela, estruturas, store):
    token = (store or {}).get("token")
    rec = RECURSOS.get(token or "")
    if not rec or rec.get("ct") is None:
        return no_update
    png = rec["ct"].render(
        plano,
        int(idx or 0),
        janela=janela,
        rs=rec.get("rs"),
        mostrar_estruturas=bool(estruturas),
    )
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


# ---------------------------------------------------------------------------
# Formulário (auto-preenchimento)
# ---------------------------------------------------------------------------


def _paciente_do_store(dados: dict) -> dict:
    for codigo in ("RP", "RS", "RD", "TC"):
        if dados.get(codigo, {}).get("paciente"):
            return dados[codigo]["paciente"]
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
    Output("eq-medico", "value"),
    Output("eq-fisico", "value"),
    Input("store-dicom", "data"),
    prevent_initial_call=True,
)
def preencher_formulario(store):
    dados = (store or {}).get("dados") or {}
    if not dados:
        return (no_update,) * 11
    pac = _paciente_do_store(dados)
    rp = dados.get("RP", {})
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
        rp.get("medico") or no_update,
        rp.get("fisico") or no_update,
    )


def _grau(v, sufixo="°"):
    return f"{float(v):g}{sufixo}" if v is not None else "—"


@app.callback(Output("tabela-feixes", "children"), Input("store-dicom", "data"))
def render_feixes(store):
    feixes = ((store or {}).get("dados") or {}).get("RP", {}).get("feixes") or []
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
        bordered=True, hover=True, striped=True, size="sm",
    )


@app.callback(Output("lista-estruturas", "children"), Input("store-dicom", "data"))
def render_estruturas(store):
    rs = ((store or {}).get("dados") or {}).get("RS", {})
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
    if dose_fracao and fracoes:
        calculada = round(dose_fracao * fracoes, 2)
        msg = f"Dose total calculada: {calculada} Gy ({fracoes} × {dose_fracao} Gy)."
        if dose_total and abs(calculada - dose_total) > 0.5:
            return f"⚠️ {msg} Diverge da dose total informada ({dose_total} Gy)."
        return f"✓ {msg}"
    return ""


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


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
def gerar_pdf(n_clicks, store, pac_nome, pac_registro, pac_nascimento, dx_local, dx_cid, dx_tnm,
              rx_dose_total, rx_dose_fracao, rx_fracoes, rx_tecnica, rx_energia, rx_equipamento,
              eq_medico, eq_fisico, eq_dosimetrista):
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
        "maquina": rx_equipamento,
        "eq_medico": eq_medico,
        "eq_fisico": eq_fisico,
        "eq_dosimetrista": eq_dosimetrista,
    }
    store = store or {}
    plano_store = {"RP": (store.get("dados") or {}).get("RP", {})}
    recursos = RECURSOS.get(store.get("token") or "")
    pdf_bytes = ficha_pdf.gerar_ficha(dados, plano_store, recursos=recursos)
    nome_arquivo = f"ficha_{(pac_nome or 'paciente').strip().replace(' ', '_').lower()}.pdf"
    return dcc.send_bytes(pdf_bytes, nome_arquivo)


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=8050)
