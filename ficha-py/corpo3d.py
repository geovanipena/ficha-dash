"""Renderização 3D opaca do corpo do paciente a partir do contorno EXTERNAL.

O RT Struct guarda o contorno do corpo (BODY/EXTERNAL) como uma pilha de
polígonos axiais. Aqui cada corte é reamostrado angularmente para um número
fixo de pontos e os cortes consecutivos são costurados em uma malha fechada,
renderizada como superfície **opaca** (não se vê o interior).
"""

from __future__ import annotations

import io

import numpy as np


def _contornos_body(rs) -> dict[int, list]:
    """ROI EXTERNAL -> {índice_de_corte: maior polígono (N,3)}. Agrupa por z."""
    nums = {
        int(o.ReferencedROINumber): str(getattr(o, "RTROIInterpretedType", ""))
        for o in rs.RTROIObservationsSequence
    }
    externos = [n for n, t in nums.items() if t == "EXTERNAL"]
    if not externos:
        return {}
    alvo = externos[0]
    rc = next((r for r in rs.ROIContourSequence if int(r.ReferencedROINumber) == alvo), None)
    if rc is None:
        return {}
    por_z: dict[float, np.ndarray] = {}
    for c in getattr(rc, "ContourSequence", []):
        pts = np.array(c.ContourData, dtype=float).reshape(-1, 3)
        z = round(float(pts[0, 2]), 1)
        # Mantém o maior polígono por corte (ignora ilhas menores, ex.: mesa).
        if z not in por_z or len(pts) > len(por_z[z]):
            por_z[z] = pts
    return {i: por_z[z] for i, z in enumerate(sorted(por_z))}


def _reamostrar_angular(pts: np.ndarray, n: int) -> np.ndarray:
    """Reamostra um polígono axial para ``n`` pontos por ângulo (corte ~convexo)."""
    cx, cy = pts[:, 0].mean(), pts[:, 1].mean()
    ang = np.arctan2(pts[:, 1] - cy, pts[:, 0] - cx)
    rad = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
    ordem = np.argsort(ang)
    ang, rad = ang[ordem], rad[ordem]
    # Fecha o círculo para interpolação periódica.
    ang_ext = np.concatenate([ang - 2 * np.pi, ang, ang + 2 * np.pi])
    rad_ext = np.concatenate([rad, rad, rad])
    alvo = np.linspace(-np.pi, np.pi, n, endpoint=False)
    r = np.interp(alvo, ang_ext, rad_ext)
    return np.column_stack([cx + r * np.cos(alvo), cy + r * np.sin(alvo)])


def _sombrear(faces, base, luz):
    """Cor por face simulando iluminação difusa (look 3D, mantendo opacidade)."""
    base = np.array(base)
    luz = np.array(luz, dtype=float)
    luz /= np.linalg.norm(luz)
    cores = []
    for f in faces:
        f = np.array(f)
        normal = np.cross(f[1] - f[0], f[2] - f[0])
        norma = np.linalg.norm(normal)
        intensidade = 0.55
        if norma > 1e-9:
            intensidade = 0.45 + 0.55 * abs(np.dot(normal / norma, luz))
        cores.append(tuple(np.clip(base * intensidade, 0, 1)) + (1.0,))
    return cores


def renderizar_corpo(rs, n_pontos: int = 72, passo: int = 1, elev: float = 14,
                     azim: float = -60) -> bytes | None:
    """Gera o PNG (bytes) do corpo 3D opaco. Devolve None se não houver EXTERNAL."""
    cortes = _contornos_body(rs)
    if len(cortes) < 3:
        return None
    indices = sorted(cortes)[::passo]
    aneis = []
    for i in indices:
        pts = cortes[i]
        xy = _reamostrar_angular(pts, n_pontos)
        z = float(pts[0, 2])
        aneis.append(np.column_stack([xy, np.full(n_pontos, z)]))
    aneis = np.array(aneis)  # (S, N, 3)

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    faces = []
    s_n = len(aneis)
    for s in range(s_n - 1):
        for j in range(n_pontos):
            j2 = (j + 1) % n_pontos
            faces.append([aneis[s, j], aneis[s, j2], aneis[s + 1, j2], aneis[s + 1, j]])
    # Tampas (topo e base) para fechar a superfície.
    centro_topo = aneis[0].mean(axis=0)
    centro_base = aneis[-1].mean(axis=0)
    for j in range(n_pontos):
        j2 = (j + 1) % n_pontos
        faces.append([aneis[0, j], aneis[0, j2], centro_topo])
        faces.append([aneis[-1, j], aneis[-1, j2], centro_base])

    cores = _sombrear(faces, base=(0.62, 0.71, 0.80), luz=(-0.4, -0.5, 0.75))

    fig = plt.figure(figsize=(3.2, 4.0), dpi=150)
    ax = fig.add_subplot(111, projection="3d")
    malha = Poly3DCollection(faces, alpha=1.0, facecolors=cores, edgecolor="none",
                             linewidths=0)
    ax.add_collection3d(malha)

    todos = aneis.reshape(-1, 3)
    ax.set_xlim(todos[:, 0].min(), todos[:, 0].max())
    ax.set_ylim(todos[:, 1].min(), todos[:, 1].max())
    ax.set_zlim(todos[:, 2].min(), todos[:, 2].max())
    ax.set_box_aspect(
        (
            np.ptp(todos[:, 0]),
            np.ptp(todos[:, 1]),
            np.ptp(todos[:, 2]),
        )
    )
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    fig.tight_layout(pad=0)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", transparent=True)
    plt.close(fig)
    return buf.getvalue()
