"""Série de TC completa do paciente: volume 3D e cortes (MPR).

Ao contrário do ficha-dash (que aceitava um único corte só para os metadados),
o ficha-py carrega **todos** os cortes da TC, empilha o volume em HU e gera
cortes axial/sagital/coronal navegáveis, com os contornos do RT Struct
sobrepostos no corte axial.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw

import dicom_rt

# Janelas (WL/WW em HU) usadas pelo visualizador. ``None`` = janela do próprio
# DICOM (a que o planejador exportou).
JANELAS: dict[str, tuple[float, float] | None] = {
    "Planejamento (DICOM)": None,
    "Partes moles": (40, 400),
    "Mediastino": (40, 400),
    "Pulmão": (-600, 1500),
    "Osso": (400, 1800),
    "Cérebro": (40, 80),
}

PLANOS = ("Axial", "Sagital", "Coronal")

# Lado máximo (px) da imagem renderizada — mantém a página leve no navegador.
_LADO_MAX = 520


def _eh_ct(ds) -> bool:
    return str(getattr(ds, "Modality", "")) == "CT"


def carregar_serie(arquivos: list[bytes]) -> "CTSerie":
    """Monta a ``CTSerie`` a partir de uma lista de pacotes/dcm.

    Cada item de ``arquivos`` pode ser um ``.dcm`` solto ou um pacote
    ``.zip``/``.rar`` (a série inteira costuma vir zipada). Os cortes são lidos
    *com* os pixels — diferente do RT Dose, a TC é necessária para as imagens.
    """
    cortes = []
    for raw in arquivos:
        for membro in dicom_rt.iter_dicoms(raw):
            try:
                ds = dicom_rt.carregar(membro, stop_before_pixels=False)
            except Exception:  # noqa: BLE001 — membro não-DICOM no pacote
                continue
            if _eh_ct(ds) and hasattr(ds, "PixelData"):
                cortes.append(ds)
    if not cortes:
        raise ValueError("Nenhum corte de TC (modalidade CT) encontrado no envio.")
    return CTSerie(cortes)


class CTSerie:
    """Volume de TC empilhado em HU, com geometria para gerar os cortes."""

    def __init__(self, slices: list):
        slices = sorted(slices, key=lambda s: float(s.ImagePositionPatient[2]))
        s0 = slices[0]
        self.slices = slices
        self.rows = int(s0.Rows)
        self.cols = int(s0.Columns)
        self.ipp0 = [float(v) for v in s0.ImagePositionPatient]
        self.psr = float(s0.PixelSpacing[0])
        self.psc = float(s0.PixelSpacing[1])
        self.zs = np.array([float(s.ImagePositionPatient[2]) for s in slices])
        difs = np.diff(self.zs)
        self.dz = float(np.median(difs)) if len(difs) else float(getattr(s0, "SliceThickness", 1))
        if self.dz == 0:
            self.dz = float(getattr(s0, "SliceThickness", 1) or 1)

        slope = float(getattr(s0, "RescaleSlope", 1))
        inter = float(getattr(s0, "RescaleIntercept", 0))
        vol = np.stack([s.pixel_array.astype(np.float32) for s in slices])
        self.volume = (vol * slope + inter).astype(np.int16)  # (Z, rows, cols) em HU

        self.wl_padrao = float(np.ravel(getattr(s0, "WindowCenter", 40))[0])
        self.ww_padrao = float(np.ravel(getattr(s0, "WindowWidth", 400))[0])
        self.paciente = dicom_rt.dados_paciente(s0)
        self.descricao = str(getattr(s0, "StudyDescription", "") or "")
        self.data_estudo = dicom_rt._formatar_data(getattr(s0, "StudyDate", ""))
        self.instituicao = str(getattr(s0, "InstitutionName", "") or "")

    # ------------------------------------------------------------------
    # Tamanhos / índices
    # ------------------------------------------------------------------
    @property
    def n_axial(self) -> int:
        return len(self.slices)

    def n_cortes(self, plano: str) -> int:
        return {"Axial": self.n_axial, "Sagital": self.cols, "Coronal": self.rows}[plano]

    def indice_central(self, plano: str) -> int:
        return self.n_cortes(plano) // 2

    # ------------------------------------------------------------------
    # Janela
    # ------------------------------------------------------------------
    def _janela(self, nome_ou_par) -> tuple[float, float]:
        if isinstance(nome_ou_par, tuple):
            return nome_ou_par
        par = JANELAS.get(nome_ou_par, None)
        return par if par is not None else (self.wl_padrao, self.ww_padrao)

    def _para_cinza(self, arr_hu: np.ndarray, janela) -> np.ndarray:
        wl, ww = self._janela(janela)
        lo, hi = wl - ww / 2.0, wl + ww / 2.0
        g = np.clip((arr_hu.astype(np.float32) - lo) / (hi - lo), 0, 1)
        return (g * 255).astype(np.uint8)

    # ------------------------------------------------------------------
    # Cortes
    # ------------------------------------------------------------------
    def _plano_cinza(self, plano: str, idx: int) -> tuple[np.ndarray, tuple[float, float]]:
        """Retorna (imagem_cinza HxW, (escala_y_mm, escala_x_mm)) do corte bruto."""
        if plano == "Axial":
            idx = int(np.clip(idx, 0, self.n_axial - 1))
            arr = self.volume[idx]
            return arr, (self.psr, self.psc)
        if plano == "Sagital":
            idx = int(np.clip(idx, 0, self.cols - 1))
            # volume[:, :, x] -> (Z, rows); topo = superior (z maior).
            arr = self.volume[:, :, idx][::-1, :]
            return arr, (self.dz, self.psr)
        # Coronal
        idx = int(np.clip(idx, 0, self.rows - 1))
        arr = self.volume[:, idx, :][::-1, :]
        return arr, (self.dz, self.psc)

    def render(self, plano: str, idx: int, janela="Planejamento (DICOM)",
               rs=None, mostrar_estruturas: bool = True) -> bytes:
        """Gera o PNG (bytes) de um corte, com escala física e estruturas (axial)."""
        arr, (esc_y, esc_x) = self._plano_cinza(plano, idx)
        cinza = self._para_cinza(arr, janela)
        rgb = np.dstack([cinza] * 3)
        img = Image.fromarray(rgb, "RGB")

        if plano == "Axial" and rs is not None and mostrar_estruturas:
            self._desenhar_estruturas_axial(img, rs, idx)

        # Reescala para proporção física (evita corte "achatado" no MPR).
        h, w = cinza.shape
        alt_mm, larg_mm = h * esc_y, w * esc_x
        escala = _LADO_MAX / max(alt_mm, larg_mm)
        novo = (max(1, int(round(larg_mm * escala))), max(1, int(round(alt_mm * escala))))
        img = img.resize(novo, Image.BILINEAR)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _desenhar_estruturas_axial(self, img: Image.Image, rs, idx: int) -> None:
        z = float(self.zs[int(np.clip(idx, 0, self.n_axial - 1))])
        draw = ImageDraw.Draw(img)
        for r in _contornos_por_roi(rs).values():
            if r["tipo"] == "EXTERNAL":
                continue
            for c in r["contornos"]:
                pts = np.asarray(c.ContourData, dtype=float).reshape(-1, 3)
                if abs(float(pts[0, 2]) - z) > abs(self.dz):
                    continue
                col = (pts[:, 0] - self.ipp0[0]) / self.psc
                row = (pts[:, 1] - self.ipp0[1]) / self.psr
                poly = list(zip(col, row))
                draw.line(poly + [poly[0]], fill=r["cor"], width=2)


def _contornos_por_roi(rs) -> dict:
    """{num_roi: {nome, tipo, cor, contornos}} a partir do RT Struct."""
    nomes = {int(r.ROINumber): str(r.ROIName) for r in rs.StructureSetROISequence}
    tipos = {
        int(o.ReferencedROINumber): str(getattr(o, "RTROIInterpretedType", ""))
        for o in getattr(rs, "RTROIObservationsSequence", [])
    }
    saida = {}
    for rc in getattr(rs, "ROIContourSequence", []):
        num = int(rc.ReferencedROINumber)
        cor = tuple(int(v) for v in getattr(rc, "ROIDisplayColor", [255, 0, 0]))
        saida[num] = {
            "nome": nomes.get(num, str(num)),
            "tipo": tipos.get(num, ""),
            "cor": cor,
            "contornos": list(getattr(rc, "ContourSequence", []) or []),
        }
    return saida
