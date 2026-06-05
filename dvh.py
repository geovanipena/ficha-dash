"""Cálculo e plotagem do DVH (histograma dose-volume) a partir de RT Dose + RT Struct.

Para cada estrutura, os contornos (axiais, ``CLOSED_PLANAR``) são rasterizados
sobre a grade de dose do RT Dose, amostrando a dose dos voxels internos e
montando o DVH cumulativo (volume % × dose).
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw

# Cores aproximadas do modelo (por nome de estrutura, em minúsculas).
CORES_PADRAO = {
    "reto": "#2E75B6",
    "ptv": "#ED7D31",
    "femur e": "#548235",
    "femur d": "#C00000",
    "bexiga": "#7030A0",
}


def _cor(nome: str, idx: int) -> str:
    chave = nome.lower()
    for k, c in CORES_PADRAO.items():
        if k in chave:
            return c
    paleta = ["#264478", "#9E480E", "#636363", "#997300", "#43682B", "#000000"]
    return paleta[idx % len(paleta)]


def _z_das_frames(rd) -> np.ndarray:
    z0 = float(rd.ImagePositionPatient[2])
    return np.array([z0 + float(o) for o in rd.GridFrameOffsetVector])


def _mapa_roi(rs) -> dict[int, str]:
    return {int(r.ROINumber): str(r.ROIName) for r in rs.StructureSetROISequence}


def _mascara_estrutura(contornos, rd, zgrid, dose_shape) -> dict[int, np.ndarray]:
    """Rasteriza os contornos da estrutura em máscaras 2D por frame de dose."""
    frames, rows, cols = dose_shape
    ipp = [float(v) for v in rd.ImagePositionPatient]
    psr, psc = float(rd.PixelSpacing[0]), float(rd.PixelSpacing[1])
    dz = abs(zgrid[1] - zgrid[0]) if len(zgrid) > 1 else 1.0
    mascaras: dict[int, np.ndarray] = {}
    for c in contornos:
        pts = np.array(c.ContourData, dtype=float).reshape(-1, 3)
        k = int(np.argmin(np.abs(zgrid - pts[0, 2])))
        if abs(zgrid[k] - pts[0, 2]) > dz:
            continue
        col = (pts[:, 0] - ipp[0]) / psc
        row = (pts[:, 1] - ipp[1]) / psr
        img = Image.new("1", (cols, rows), 0)
        ImageDraw.Draw(img).polygon(list(zip(col, row)), fill=1)
        m = np.array(img, dtype=bool)
        # Múltiplos contornos no mesmo plano (ilhas/buracos) -> XOR.
        mascaras[k] = np.logical_xor(mascaras[k], m) if k in mascaras else m
    return mascaras


def calcular_dvh(rd, rs, nomes: list[str], n_bins: int = 200) -> dict:
    """Calcula o DVH cumulativo das estruturas indicadas.

    Devolve ``{nome: {'dose': array, 'volume': array, 'd_max', 'd_media'}}``.
    """
    dose = rd.pixel_array  # (frames, rows, cols), inteiro
    escala = float(rd.DoseGridScaling)
    zgrid = _z_das_frames(rd)
    roi_nome = _mapa_roi(rs)
    nome_roi = {v: k for k, v in roi_nome.items()}

    resultado: dict[str, dict] = {}
    for nome in nomes:
        num = nome_roi.get(nome)
        if num is None:
            continue
        rc = next((r for r in rs.ROIContourSequence if int(r.ReferencedROINumber) == num), None)
        if rc is None or not getattr(rc, "ContourSequence", None):
            continue
        mascaras = _mascara_estrutura(rc.ContourSequence, rd, zgrid, dose.shape)
        amostras = [dose[k][m] for k, m in mascaras.items() if m.any()]
        if not amostras:
            continue
        valores = np.concatenate(amostras).astype(np.float64) * escala
        resultado[nome] = valores
    return _curvas(resultado, n_bins)


def _curvas(amostras_por_nome: dict[str, np.ndarray], n_bins: int) -> dict:
    d_max_geral = max((v.max() for v in amostras_por_nome.values()), default=1.0)
    bins = np.linspace(0, d_max_geral * 1.02, n_bins)
    curvas = {}
    for nome, valores in amostras_por_nome.items():
        total = valores.size
        volume = np.array([100.0 * np.count_nonzero(valores >= b) / total for b in bins])
        curvas[nome] = {
            "dose": bins,
            "volume": volume,
            "d_max": float(valores.max()),
            "d_media": float(valores.mean()),
            "d_min": float(valores.min()),
        }
    return curvas


def plotar_dvh(curvas: dict, titulo: str = "") -> bytes:
    """Gera o gráfico DVH (PNG em bytes) no estilo do modelo."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.0, 3.4), dpi=150)
    for i, (nome, c) in enumerate(curvas.items()):
        ax.plot(c["dose"], c["volume"], color=_cor(nome, i), linewidth=1.3, label=nome)
    ax.set_xlabel("Dose [Gy]")
    ax.set_ylabel("Volume da Estrutura [%]")
    ax.set_xlim(left=0)
    ax.set_ylim(0, 100)
    ax.set_yticks(range(0, 101, 10))
    ax.grid(True, linewidth=0.3, alpha=0.5)
    ax.legend(fontsize=7, loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False)
    if titulo:
        ax.set_title(titulo, fontsize=9)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
