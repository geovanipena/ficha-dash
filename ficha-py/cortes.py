"""Renderização dos cortes (TC + estruturas) com fundo branco fora do corpo.

A TC é janelada para tons de cinza; a região fora do contorno do corpo
(EXTERNAL) é pintada de **branco** (não preto), e os contornos das estruturas
são desenhados por cima. Os cortes sagital/coronal exigem a série de TC
completa; o axial pode ser gerado a partir de um único corte.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw


def _para_cinza(ct, wl: float | None = None, ww: float | None = None) -> np.ndarray:
    """Converte a TC para cinza 0–255 aplicando janela (WL/WW)."""
    arr = ct.pixel_array.astype(np.float32)
    arr = arr * float(getattr(ct, "RescaleSlope", 1)) + float(getattr(ct, "RescaleIntercept", 0))
    if wl is None:
        wl = float(np.ravel(getattr(ct, "WindowCenter", 40))[0])
    if ww is None:
        ww = float(np.ravel(getattr(ct, "WindowWidth", 400))[0])
    lo, hi = wl - ww / 2, wl + ww / 2
    g = np.clip((arr - lo) / (hi - lo), 0, 1)
    return (g * 255).astype(np.uint8)


def _contornos_por_roi(rs):
    """{num_roi: (nome, cor_rgb, [contornos])} com a cor do RT Struct."""
    nomes = {int(r.ROINumber): str(r.ROIName) for r in rs.StructureSetROISequence}
    tipos = {
        int(o.ReferencedROINumber): str(getattr(o, "RTROIInterpretedType", ""))
        for o in rs.RTROIObservationsSequence
    }
    saida = {}
    for rc in rs.ROIContourSequence:
        num = int(rc.ReferencedROINumber)
        cor = tuple(int(v) for v in getattr(rc, "ROIDisplayColor", [255, 0, 0]))
        saida[num] = {
            "nome": nomes.get(num, str(num)),
            "tipo": tipos.get(num, ""),
            "cor": cor,
            "contornos": list(getattr(rc, "ContourSequence", []) or []),
        }
    return saida


def _para_pixel(pts, ipp, psr, psc):
    col = (pts[:, 0] - ipp[0]) / psc
    row = (pts[:, 1] - ipp[1]) / psr
    return list(zip(col, row))


def render_axial(ct, rs, wl: float | None = None, ww: float | None = None) -> bytes:
    """Gera o corte axial da TC com fundo branco fora do corpo e estruturas."""
    cinza = _para_cinza(ct, wl, ww)
    rows, cols = cinza.shape
    ipp = [float(v) for v in ct.ImagePositionPatient]
    psr, psc = float(ct.PixelSpacing[0]), float(ct.PixelSpacing[1])
    z = ipp[2]
    rois = _contornos_por_roi(rs)

    rgb = np.dstack([cinza] * 3)

    # Máscara do corpo (EXTERNAL) -> fora do corpo vira branco.
    body = next((r for r in rois.values() if r["tipo"] == "EXTERNAL"), None)
    if body is not None:
        mask = Image.new("1", (cols, rows), 0)
        d = ImageDraw.Draw(mask)
        for c in body["contornos"]:
            pts = np.array(c.ContourData, dtype=float).reshape(-1, 3)
            if abs(float(pts[0, 2]) - z) > 1.5:
                continue
            d.polygon(_para_pixel(pts, ipp, psr, psc), fill=1)
        fora = ~np.array(mask, dtype=bool)
        rgb[fora] = 255

    # Contornos das estruturas (linhas coloridas) presentes neste corte.
    img = Image.fromarray(rgb, "RGB")
    draw = ImageDraw.Draw(img)
    for r in rois.values():
        if r["tipo"] == "EXTERNAL":
            continue
        for c in r["contornos"]:
            pts = np.array(c.ContourData, dtype=float).reshape(-1, 3)
            if abs(float(pts[0, 2]) - z) > 1.5:
                continue
            poly = _para_pixel(pts, ipp, psr, psc)
            draw.line(poly + [poly[0]], fill=r["cor"], width=2)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
