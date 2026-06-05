"""Geração do PDF da Ficha Técnica de Tratamento (modelo Cebrom).

Reproduz fielmente o formulário institucional:

* Página 1 (retrato): cortes ortogonais + DVH — gerada quando há série de TC
  e RT Dose/Struct (ver ``cortes_dvh``); caso contrário é omitida.
* Página 2 (paisagem): Ficha Técnica de Tratamento.
* Página 3 (paisagem): mapa de acompanhamento das frações.

As coordenadas usam o canto superior esquerdo como origem (mais intuitivo
para um formulário), convertidas para o sistema do ReportLab nos helpers.
"""

from __future__ import annotations

import io
import os
from datetime import date

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

LOGO = os.path.join(os.path.dirname(__file__), "assets", "logo_cebrom.png")

# Paleta do modelo.
LARANJA = HexColor("#F8CBAD")
AMARELO = HexColor("#FFF2CC")
CINZA = HexColor("#D9D9D9")
LARANJA_FORTE = HexColor("#FFC000")


# ---------------------------------------------------------------------------
# Helpers de desenho (origem no canto superior esquerdo)
# ---------------------------------------------------------------------------


def br(valor, casas: int = 1) -> str:
    """Formata número no padrão brasileiro (vírgula decimal). Vazio -> ''."""
    if valor is None or valor == "":
        return ""
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return f"{f:.{casas}f}".replace(".", ",")


class Tela:
    """Canvas com origem no topo-esquerda e helpers de célula/grade."""

    def __init__(self, c: canvas.Canvas, largura: float, altura: float):
        self.c = c
        self.W = largura
        self.H = altura

    def ret(self, x, y, w, h, fill=None, stroke=True, lw=0.6):
        c = self.c
        if fill is not None:
            c.setFillColor(fill)
        c.setStrokeColor(black)
        c.setLineWidth(lw)
        c.rect(x, self.H - (y + h), w, h, stroke=1 if stroke else 0, fill=1 if fill else 0)

    def txt(self, x, y, s, font="Helvetica", size=7.5, align="l", w=None, h=None, color=black):
        if s is None or s == "":
            return
        c = self.c
        c.setFont(font, size)
        c.setFillColor(color)
        baseline = self.H - (y + (h / 2 + size * 0.36 if h else size))
        if align == "c" and w:
            c.drawCentredString(x + w / 2, baseline, str(s))
        elif align == "r" and w:
            c.drawRightString(x + w - 3, baseline, str(s))
        else:
            c.drawString(x + 3, baseline, str(s))

    def celula(self, x, y, w, h, valor="", label=None, font="Helvetica", size=7.5,
               align="l", fill=None, label_font="Helvetica-Bold"):
        """Desenha uma célula com borda; opcionalmente rótulo em negrito + valor."""
        self.ret(x, y, w, h, fill=fill)
        if label is not None:
            self.txt(x, y, label, font=label_font, size=size, h=h)
            lw = self.c.stringWidth(label, label_font, size) + 6
            self.txt(x + lw, y, valor, font=font, size=size, h=h)
        else:
            self.txt(x, y, valor, font=font, size=size, align=align, w=w, h=h)


# ---------------------------------------------------------------------------
# Página 2 — Ficha Técnica de Tratamento
# ---------------------------------------------------------------------------

CHECKLIST_ITENS = [
    "Nome, D.N, RGH, Foto",
    "Prescrição Médica (capa x ficha)",
    "Contra-Capa Completa",
    "Exames Complementares",
    "Acessórios Presentes",
    "Lateralidade e Anatomia",
]

CAMPOS_LINHAS = [
    ("Campo", "numero"),
    ("Fase", "fase"),
    ("Energia", "energia_rotulo"),
    ("SSD", "ssd"),
    ("Y1", "y1"),
    ("Y2", "y2"),
    ("X1", "x1"),
    ("X2", "x2"),
    ("Gantry", "gantry"),
    ("Coll", "colimador"),
    ("Mesa", "mesa"),
    ("Bólus", "bolus"),
    ("Filtro", "filtro"),
    ("UM", "um"),
]

N_CAMPOS = 21  # colunas de campo no formulário


def _cabecalho(t: Tela, dados: dict):
    M = 14
    x, y, W = M, 14, t.W - 2 * M
    h = 72
    # Logo.
    xl = x
    wl = 150
    if os.path.exists(LOGO):
        try:
            t.c.drawImage(LOGO, xl + 6, t.H - (y + h - 6), wl - 12, h - 18,
                          preserveAspectRatio=True, mask="auto", anchor="c")
        except Exception:  # noqa: BLE001
            pass
    # Título.
    xt = xl + wl
    wt = 176
    t.ret(xt, y, wt, h)
    t.txt(xt, y + 16, "Ficha Técnica", font="Helvetica-Bold", size=17, align="c", w=wt)
    t.txt(xt, y + 40, "de Tratamento", font="Helvetica-Bold", size=17, align="c", w=wt)
    # Caixa do paciente (4 linhas).
    xp = xt + wt
    wp = 360
    lh = h / 4
    meia = wp / 2
    t.celula(xp, y, wp, lh, valor=dados.get("pac_nome", ""), label="Nome:", size=8,
             font="Helvetica-Bold")
    t.celula(xp, y + lh, meia, lh, valor=dados.get("pac_registro", ""), label="RGH:", size=7.5)
    t.celula(xp + meia, y + lh, wp - meia, lh, valor=dados.get("pac_nascimento", ""),
             label="Data de Nasc:", size=7.5)
    t.celula(xp, y + 2 * lh, wp, lh, valor=dados.get("eq_medico", ""), label="Médico(a):", size=7.5)
    t.celula(xp, y + 3 * lh, wp - 130, lh, valor=dados.get("eq_fisico", ""), label="Físico(a):",
             size=7.5)
    t.celula(xp + wp - 130, y + 3 * lh, 130, lh, valor=dados.get("maquina", ""), label="AL:",
             size=7.5)
    # Cubo de coordenadas (esquemático).
    xc = xp + wp
    wc = x + W - xc
    t.ret(xc, y, wc, h, stroke=False)
    _cubo(t, xc, y, wc, h)
    return y + h + 4


def _cubo(t: Tela, x, y, w, h):
    """Desenha o cubo isométrico de coordenadas TrueBeam/VitalBeam."""
    c = t.c
    c.setLineWidth(0.7)
    c.setStrokeColor(black)
    cx, cy, s, d = x + w / 2 - 18, y + h / 2, 34, 14

    def P(px, py):
        return px, t.H - py

    pts = [(cx, cy), (cx + s, cy), (cx + s, cy - s), (cx, cy - s)]
    back = [(p[0] + d, p[1] - d) for p in pts]
    for a, b in zip(pts, [pts[1], pts[2], pts[3], pts[0]]):
        c.line(*P(*a), *P(*b))
    for a, b in zip(back, [back[1], back[2], back[3], back[0]]):
        c.line(*P(*a), *P(*b))
    for a, b in zip(pts, back):
        c.line(*P(*a), *P(*b))
    t.txt(x, y + 2, "(1,2,…)", size=6, align="c", w=w)
    t.txt(x, y + h - 22, "270°", size=6)
    t.txt(x + w - 30, y + h - 22, "90°", size=6)
    t.txt(x, y + h - 12, "(Coordenadas TrueBeam/VitalBeam)", size=5.5, align="c", w=w)


def _tabela_plano(t: Tela, y0: float, dados: dict, rp: dict):
    M = 14
    x0, W = M, t.W - 2 * M
    simples = [
        ("Gating", 64, dados.get("gating", "")),
        ("Fase", 38, "1"),
        ("Plano", 96, rp.get("rotulo_plano") or rp.get("nome_plano", "")),
        ("Qtde de\nFrações", 46, rp.get("num_fracoes")),
        ("Dose/dia\n(cGy)", 46, br((rp.get("dose_fracao") or 0) * 100, 0) if rp.get("dose_fracao") else ""),
        ("Dose\n(cGy)", 46, br((rp.get("dose_total") or 0) * 100, 0) if rp.get("dose_total") else ""),
        ("Fracio-\nnamento", 50, dados.get("fracionamento", "")),
    ]
    grupos = [("SSD TP0 (cm)", ["G0", "G270", "G90"]),
              ("Deslocamento (cm)", ["Lat.", "Long.", "Vert."]),
              ("SSD Iso (cm)", ["G0", "G270", "G90"])]
    larg_simples = sum(w for _, w, _ in simples)
    larg_sub = (W - larg_simples) / 9
    hh = 14  # altura de uma sub-linha de cabeçalho
    hcab = 2 * hh
    hlin = 15

    # Cabeçalho — colunas simples (2 linhas).
    x = x0
    for nome, w, _ in simples:
        t.ret(x, y0, w, hcab, fill=white)
        linhas = nome.split("\n")
        for i, ln in enumerate(linhas):
            t.txt(x, y0 + (hcab / 2 - len(linhas) * 5) + i * 9, ln, font="Helvetica-Bold",
                  size=6.8, align="c", w=w)
        x += w
    # Cabeçalho — grupos.
    for titulo, subs in grupos:
        wg = larg_sub * len(subs)
        t.ret(x, y0, wg, hh, fill=white)
        t.txt(x, y0, titulo, font="Helvetica-Bold", size=6.8, align="c", w=wg, h=hh)
        for j, sub in enumerate(subs):
            t.ret(x + j * larg_sub, y0 + hh, larg_sub, hh, fill=white)
            t.txt(x + j * larg_sub, y0 + hh, sub, font="Helvetica-Bold", size=6.5, align="c",
                  w=larg_sub, h=hh)
        x += wg

    # Linhas de dados (4); a 1ª preenchida.
    for r in range(4):
        yr = y0 + hcab + r * hlin
        x = x0
        for _, w, val in simples:
            t.ret(x, yr, w, hlin)
            if r == 0:
                t.txt(x, yr, val, size=7.5, align="c", w=w, h=hlin)
            x += w
        for _ in range(9):
            t.ret(x, yr, larg_sub, hlin)
            x += larg_sub
    return y0 + hcab + 4 * hlin + 4


def _tabela_campos(t: Tela, y0: float, feixes: list):
    M = 14
    x0, W = M, t.W - 2 * M
    wlbl = 50
    wcol = (W - wlbl) / N_CAMPOS
    hlin = 13.5
    for i, (rotulo, chave) in enumerate(CAMPOS_LINHAS):
        yr = y0 + i * hlin
        fill = LARANJA_FORTE if rotulo == "Fase" else None
        # Rótulo (à esquerda).
        t.ret(x0, yr, wlbl, hlin, fill=fill)
        t.txt(x0, yr, rotulo + ":", font="Helvetica-Bold", size=7, align="r", w=wlbl, h=hlin)
        # Colunas dos campos.
        for col in range(N_CAMPOS):
            xc = x0 + wlbl + col * wcol
            t.ret(xc, yr, wcol, hlin, fill=fill)
            if col < len(feixes):
                f = feixes[col]
                if chave == "numero":
                    valor = col + 1
                elif chave == "fase":
                    valor = f.get("fase", 1)
                elif chave in ("ssd", "y1", "y2", "x1", "x2"):
                    valor = br(f.get(chave), 1)
                elif chave in ("gantry", "colimador", "mesa"):
                    valor = br(f.get(chave), 0)
                elif chave == "um":
                    valor = br(f.get("um"), 1)
                else:
                    valor = f.get(chave, "")
                t.txt(xc, yr, valor, size=6.6, align="c", w=wcol, h=hlin)
    return y0 + len(CAMPOS_LINHAS) * hlin + 6


def _obs_checklist(t: Tela, y0: float):
    M = 14
    x0, W = M, t.W - 2 * M
    h_titulo = 14
    h_corpo = t.H - 24 - y0 - h_titulo
    wobs = W * 0.60
    wchk = W - wobs - 8
    xchk = x0 + wobs + 8

    # Observações.
    t.txt(x0, y0, "Observações gerais do tratamento", font="Helvetica-Bold", size=8)
    t.ret(x0, y0 + h_titulo, wobs, h_corpo)

    # Checklist.
    t.txt(xchk, y0, "Checklist Pré-Tratamento", font="Helvetica-Bold", size=8, align="c", w=wchk)
    cols = ["C", "N/C", "N/A", "Cor."]
    wc = 26
    wlbl = wchk - len(cols) * wc
    hr = 14
    yh = y0 + h_titulo
    # Cabeçalho de colunas.
    t.ret(xchk, yh, wlbl, hr, fill=white)
    cores = [AMARELO, AMARELO, white, LARANJA]
    for j, cab in enumerate(cols):
        xc = xchk + wlbl + j * wc
        t.ret(xc, yh, wc, hr, fill=white)
        t.txt(xc, yh, cab, font="Helvetica-Bold", size=7, align="c", w=wc, h=hr)
    # Itens.
    for i, item in enumerate(CHECKLIST_ITENS):
        yr = yh + hr + i * hr
        t.ret(xchk, yr, wlbl, hr)
        t.txt(xchk, yr, item, size=7, align="c", w=wlbl, h=hr)
        for j in range(len(cols)):
            t.ret(xchk + wlbl + j * wc, yr, wc, hr, fill=cores[j])
    yfim = yh + hr + len(CHECKLIST_ITENS) * hr
    t.txt(xchk, yfim + 4, "Nome, Carimbo e Data", size=7, align="c", w=wchk)
    t.txt(xchk, yfim + 16, "C: conforme; N/C: não conforme; N/A: não se aplica; Cor.: corrigido",
          size=5.5, align="c", w=wchk)


def pagina_ficha(c: canvas.Canvas, dados: dict, store: dict):
    W, H = landscape(A4)
    t = Tela(c, W, H)
    rp = store.get("RP", {})
    feixes = rp.get("feixes", [])
    y = _cabecalho(t, dados)
    y = _tabela_plano(t, y, dados, rp)
    y = _tabela_campos(t, y, feixes)
    _obs_checklist(t, y)
    t.txt(14, H - 18, f"Impresso em {date.today().strftime('%d/%m/%Y')}", size=6)


# ---------------------------------------------------------------------------
# Página 3 — Mapa de frações
# ---------------------------------------------------------------------------


def pagina_fracoes(c: canvas.Canvas, dados: dict, store: dict):
    W, H = landscape(A4)
    t = Tela(c, W, H)
    M = 14
    rp = store.get("RP", {})
    nfr = int(rp.get("num_fracoes") or 0)
    dose_dia = (rp.get("dose_fracao") or 0) * 100

    # Cabeçalho com logo e paciente.
    if os.path.exists(LOGO):
        try:
            c.drawImage(LOGO, M, H - 44, 90, 30, preserveAspectRatio=True, mask="auto")
        except Exception:  # noqa: BLE001
            pass
    t.txt(M + 100, 14, "Nome:", font="Helvetica-Bold", size=9, h=18)
    t.txt(M + 140, 14, dados.get("pac_nome", ""), size=9, h=18)
    t.txt(M + 470, 8, "Data de", font="Helvetica-Bold", size=7)
    t.txt(M + 470, 18, "Nascimento:", font="Helvetica-Bold", size=7)
    t.txt(M + 528, 14, dados.get("pac_nascimento", ""), size=9, h=18)

    # Grade de frações.
    y0 = 40
    W_util = W - 2 * M
    col_fracao, col_data, col_hora, col_t, col_tec, col_img = 36, 70, 56, 44, 70, 56
    col_med, col_dose = 56, 70
    # 21 subcolunas de imagem (1-1, 1-2, ...).
    n_sub = 21
    larg_fixa = col_fracao + col_data + col_hora + col_t + col_tec + col_img
    larg_obs_med_dose = col_med + col_dose
    larg_sub = (W_util - larg_fixa - 200 - larg_obs_med_dose) / n_sub  # 200 p/ Observações
    col_obs = 200
    hh = 14
    cabs = [("Fração", col_fracao), ("Data", col_data), ("Horário", col_hora),
            ("T (min)", col_t), ("Técnicos", col_tec), ("Imagem", col_img)]
    x = M
    for nome, w in cabs:
        t.ret(x, y0, w, hh, fill=white)
        t.txt(x, y0, nome, font="Helvetica-Bold", size=7, align="c", w=w, h=hh)
        x += w
    for j in range(n_sub):
        t.ret(x, y0, larg_sub, hh, fill=LARANJA_FORTE if j < 2 else CINZA)
        x += larg_sub
    t.ret(x, y0, col_obs, hh, fill=white)
    t.txt(x, y0, "Observações", font="Helvetica-Bold", size=7, align="c", w=col_obs, h=hh)
    x += col_obs
    t.ret(x, y0, col_med, hh, fill=white)
    t.txt(x, y0, "Med/Enf", font="Helvetica-Bold", size=7, align="c", w=col_med, h=hh)
    x += col_med
    t.ret(x, y0, col_dose, hh, fill=white)
    t.txt(x, y0, "Dose", font="Helvetica-Bold", size=7, align="c", w=col_dose, h=hh)

    # Linhas (até 39 ou nº de frações + folga).
    total_linhas = max(39, nfr)
    hlin = (H - 24 - (y0 + hh)) / total_linhas
    hlin = min(hlin, 14)
    for i in range(total_linhas):
        yr = y0 + hh + i * hlin
        x = M
        t.ret(x, yr, col_fracao, hlin)
        t.txt(x, yr, i + 1, size=7, align="c", w=col_fracao, h=hlin)
        x += col_fracao
        for w in (col_data, col_hora, col_t, col_tec, col_img):
            t.ret(x, yr, w, hlin)
            x += w
        for _ in range(n_sub):
            t.ret(x, yr, larg_sub, hlin, fill=CINZA)
            x += larg_sub
        t.ret(x, yr, col_obs, hlin)
        x += col_obs
        t.ret(x, yr, col_med, hlin)
        x += col_med
        # Dose cumulativa para as frações planejadas.
        t.ret(x, yr, col_dose, hlin)
        if i < nfr and dose_dia:
            t.txt(x, yr, br(dose_dia * (i + 1), 0), size=6.5, align="c", w=col_dose, h=hlin,
                  color=HexColor("#C55A11"))


# ---------------------------------------------------------------------------
# Página 1 — Cortes ortogonais + DVH (requer a TC completa)
# ---------------------------------------------------------------------------


def _img(c: canvas.Canvas, png: bytes, x, y, w, h, H, legenda=""):
    """Desenha um PNG (bytes) numa caixa, com origem no topo-esquerda."""
    t = Tela(c, c._pagesize[0], H)
    t.ret(x, y, w, h)
    try:
        c.drawImage(ImageReader(io.BytesIO(png)), x + 2, H - (y + h - 12), w - 4, h - 16,
                    preserveAspectRatio=True, mask="auto", anchor="c")
    except Exception:  # noqa: BLE001
        pass
    if legenda:
        t.txt(x, y + h - 12, legenda, font="Helvetica-Bold", size=7, align="c", w=w)


def pagina_cortes_dvh(c: canvas.Canvas, dados: dict, recursos: dict):
    """Página retrato com TC (axial/sagital/coronal), corpo 3D e DVH."""
    W, H = portrait(A4)
    t = Tela(c, W, H)
    M = 22
    ct = recursos.get("ct")
    rs = recursos.get("rs")
    rd = recursos.get("rd")

    # Cabeçalho.
    if os.path.exists(LOGO):
        try:
            c.drawImage(LOGO, M, H - 50, 96, 34, preserveAspectRatio=True, mask="auto")
        except Exception:  # noqa: BLE001
            pass
    t.txt(M + 110, 16, "Imagens do planejamento", font="Helvetica-Bold", size=13, h=20)
    t.txt(M + 110, 36, f"Paciente: {dados.get('pac_nome', '')}", size=9)
    t.txt(W - 220, 36, f"RGH: {dados.get('pac_registro', '')}", size=9)

    # Cortes ortogonais (linha de três).
    y0 = 70
    wcell = (W - 2 * M - 16) / 3
    hcell = wcell * 1.05
    if ct is not None:
        planos = [
            ("Axial", ct.indice_central("Axial"), "Axial"),
            ("Sagital", ct.indice_central("Sagital"), "Sagital"),
            ("Coronal", ct.indice_central("Coronal"), "Coronal"),
        ]
        for i, (plano, idx, legenda) in enumerate(planos):
            png = ct.render(plano, idx, janela="Partes moles", rs=rs)
            _img(c, png, M + i * (wcell + 8), y0, wcell, hcell, H, legenda=legenda)
    else:
        t.ret(M, y0, W - 2 * M, hcell)
        t.txt(M, y0 + hcell / 2, "TC não carregada — importe a série completa.",
              size=9, align="c", w=W - 2 * M)
    y = y0 + hcell + 16

    # Corpo 3D (esquerda) + DVH (direita).
    h_bloco = 250
    w_corpo = (W - 2 * M - 16) * 0.42
    w_dvh = (W - 2 * M - 16) - w_corpo
    if rs is not None:
        try:
            import corpo3d

            png3d = corpo3d.renderizar_corpo(rs)
            if png3d:
                _img(c, png3d, M, y, w_corpo, h_bloco, H, legenda="Corpo (EXTERNAL)")
            else:
                t.ret(M, y, w_corpo, h_bloco)
        except Exception:  # noqa: BLE001
            t.ret(M, y, w_corpo, h_bloco)
    else:
        t.ret(M, y, w_corpo, h_bloco)

    x_dvh = M + w_corpo + 16
    if rs is not None and rd is not None:
        try:
            import dvh

            nomes = _estruturas_para_dvh(rs)
            curvas = dvh.calcular_dvh(rd, rs, nomes)
            if curvas:
                _img(c, dvh.plotar_dvh(curvas, "Histograma Dose-Volume"),
                     x_dvh, y, w_dvh, h_bloco, H)
            else:
                t.ret(x_dvh, y, w_dvh, h_bloco)
                t.txt(x_dvh, y + h_bloco / 2, "DVH indisponível.", size=8, align="c", w=w_dvh)
        except Exception as exc:  # noqa: BLE001
            t.ret(x_dvh, y, w_dvh, h_bloco)
            t.txt(x_dvh, y + h_bloco / 2, f"DVH: {exc}", size=7, align="c", w=w_dvh)
    else:
        t.ret(x_dvh, y, w_dvh, h_bloco)
        t.txt(x_dvh, y + h_bloco / 2, "DVH requer RT Struct + RT Dose.",
              size=8, align="c", w=w_dvh)

    t.txt(M, H - 18, f"Impresso em {date.today().strftime('%d/%m/%Y')}", size=6)


def _estruturas_para_dvh(rs, limite: int = 8) -> list[str]:
    """Seleciona alvos e órgãos de risco (nomes) que tenham contorno, para o DVH."""
    com_contorno = {
        int(rc.ReferencedROINumber)
        for rc in getattr(rs, "ROIContourSequence", [])
        if getattr(rc, "ContourSequence", None)
    }
    tipos = {
        int(o.ReferencedROINumber): str(getattr(o, "RTROIInterpretedType", ""))
        for o in getattr(rs, "RTROIObservationsSequence", [])
    }
    nomes = []
    for r in rs.StructureSetROISequence:
        num = int(r.ROINumber)
        if num not in com_contorno or tipos.get(num) == "EXTERNAL":
            continue
        nomes.append(str(r.ROIName))
    return nomes[:limite]


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------


def gerar_ficha(dados: dict, store: dict, recursos: dict | None = None) -> bytes:
    """Monta o PDF completo da ficha e devolve os bytes.

    ``recursos`` (opcional) carrega a TC completa e os datasets RS/RD para a
    página 1 (cortes + DVH). Sem ele, o PDF começa na ficha (página 2).
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    if recursos and recursos.get("ct") is not None:
        c.setPageSize(portrait(A4))
        pagina_cortes_dvh(c, dados, recursos)
        c.showPage()
        c.setPageSize(landscape(A4))
    pagina_ficha(c, dados, store)
    c.showPage()
    pagina_fracoes(c, dados, store)
    c.showPage()
    c.save()
    return buffer.getvalue()
