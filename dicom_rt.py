"""Leitura dos objetos DICOM-RT (TC, RP, RS, RD) para a ficha técnica.

Cada função recebe um ``pydicom.Dataset`` já carregado e devolve um
dicionário com os campos relevantes para a ficha. As funções são tolerantes
a tags ausentes — sempre usam ``getattr``/``.get`` com valor padrão.
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from collections.abc import Iterator
from typing import Any

import pydicom
from pydicom.dataset import Dataset
from pydicom.multival import MultiValue

# Modalidades DICOM dos objetos de interesse.
MODALIDADES = {
    "CT": "TC",
    "RTPLAN": "RP",
    "RTSTRUCT": "RS",
    "RTDOSE": "RD",
}


def carregar(conteudo: bytes, stop_before_pixels: bool = True) -> Dataset:
    """Carrega um arquivo DICOM a partir de bytes.

    Por padrão ignora os dados de pixel/matriz de dose (``stop_before_pixels``),
    que podem ter centenas de MB no RT Dose e não são necessários para a ficha.
    """
    return pydicom.dcmread(io.BytesIO(conteudo), force=True, stop_before_pixels=stop_before_pixels)


def _eh_dicom(b: bytes) -> bool:
    """Heurística: arquivo DICOM tem o marcador 'DICM' no offset 128."""
    return len(b) > 132 and b[128:132] == b"DICM"


def iter_dicoms(raw: bytes) -> Iterator[bytes]:
    """Itera os bytes de cada DICOM contido em ``raw``.

    Aceita um DICOM solto ou um pacote ``.zip``/``.rar`` (descompactado em
    memória/temporário), entregando um membro de cada vez para manter o uso de
    memória baixo mesmo com RT Dose grande.
    """
    if raw[:4] == b"PK\x03\x04":  # ZIP
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            for nome in z.namelist():
                if nome.endswith("/"):
                    continue
                yield z.read(nome)
    elif raw[:4] == b"Rar!":  # RAR
        try:
            import rarfile
        except ImportError as exc:
            raise RuntimeError("Suporte a .rar indisponível; envie um .zip.") from exc

        with tempfile.NamedTemporaryFile(suffix=".rar") as tf:
            tf.write(raw)
            tf.flush()
            try:
                with rarfile.RarFile(tf.name) as rf:
                    for info in rf.infolist():
                        if info.is_dir():
                            continue
                        yield rf.read(info)
            except rarfile.RarCannotExec as exc:
                raise RuntimeError(
                    "Para abrir .rar o servidor precisa de 'unrar'/'7z'; envie um .zip."
                ) from exc
    else:  # DICOM solto
        yield raw


def _formatar_nome(valor: Any) -> str:
    """Converte um PersonName DICOM em nome na ordem natural (nome sobrenome).

    O DICOM armazena ``Família^Nome^Meio`` (sobrenome primeiro). A ficha usa a
    ordem natural brasileira, então reordenamos para ``Nome Meio Família``.
    """
    if not valor:
        return ""
    familia = str(getattr(valor, "family_name", "") or "").strip()
    nome = str(getattr(valor, "given_name", "") or "").strip()
    meio = str(getattr(valor, "middle_name", "") or "").strip()
    if familia or nome:
        # Alguns sistemas repetem o sobrenome dentro do componente "nome"
        # (ex.: 'Monteiro^Paula Monteiro Amorim'); nesse caso não duplicamos.
        if familia and familia.lower() in nome.lower():
            completo = nome
        else:
            completo = " ".join(p for p in (nome, meio, familia) if p)
    else:
        completo = str(valor).replace("^", " ")
    return " ".join(completo.split())


def _primeiro_nome(valor: Any) -> str:
    """Formata o primeiro nome de um campo que pode ser multivalorado."""
    if valor is None or valor == "":
        return ""
    if isinstance(valor, MultiValue):
        valor = valor[0] if len(valor) else ""
    return _formatar_nome(valor)


def _formatar_data(valor: Any) -> str:
    """Converte uma data DICOM (YYYYMMDD) em DD/MM/YYYY."""
    if not valor or len(str(valor)) < 8:
        return str(valor or "")
    s = str(valor)
    return f"{s[6:8]}/{s[4:6]}/{s[0:4]}"


def identificar(ds: Dataset) -> str:
    """Retorna o código (TC/RP/RS/RD) a partir da modalidade do dataset."""
    return MODALIDADES.get(getattr(ds, "Modality", ""), getattr(ds, "Modality", "?"))


def dados_paciente(ds: Dataset) -> dict:
    """Demografia do paciente — presente em qualquer objeto DICOM."""
    return {
        "nome": _formatar_nome(getattr(ds, "PatientName", "")),
        "registro": str(getattr(ds, "PatientID", "") or ""),
        "nascimento": _formatar_data(getattr(ds, "PatientBirthDate", "")),
        "sexo": str(getattr(ds, "PatientSex", "") or ""),
    }


def parse_ct(ds: Dataset) -> dict:
    """Dados do exame de TC."""
    return {
        "paciente": dados_paciente(ds),
        "instituicao": str(getattr(ds, "InstitutionName", "") or ""),
        "data_estudo": _formatar_data(getattr(ds, "StudyDate", "")),
        "descricao_estudo": str(getattr(ds, "StudyDescription", "") or ""),
        "espessura_corte": getattr(ds, "SliceThickness", None),
    }


def _tecnica_do_feixe(beam: Dataset) -> str:
    """Infere a técnica de tratamento a partir do feixe do RTPLAN."""
    beam_type = str(getattr(beam, "BeamType", "")).upper()
    radiacao = str(getattr(beam, "RadiationType", "")).upper()
    cps = getattr(beam, "ControlPointSequence", [])
    if radiacao == "ELECTRON":
        return "Elétrons"
    if beam_type == "DYNAMIC":
        # Gantry varia entre control points -> arco (VMAT); caso contrário, IMRT dinâmico.
        angulos = {getattr(cp, "GantryAngle", None) for cp in cps if hasattr(cp, "GantryAngle")}
        return "VMAT" if len(angulos) > 1 else "IMRT"
    return "3D Conformacional (3D-CRT)"


def _cm(valor_mm: Any) -> float | None:
    """Converte milímetros (DICOM) em centímetros, com 1 casa."""
    return round(float(valor_mm) / 10.0, 1) if valor_mm is not None else None


def _mordentes(cp0: Dataset) -> dict:
    """Posições dos mordentes (X1/X2/Y1/Y2) em cm a partir do control point."""
    res: dict[str, float | None] = {}
    for dev in getattr(cp0, "BeamLimitingDevicePositionSequence", []):
        tipo = str(getattr(dev, "RTBeamLimitingDeviceType", "")).upper()
        pos = list(getattr(dev, "LeafJawPositions", []) or [])
        if len(pos) < 2:
            continue
        if tipo in {"X", "ASYMX"}:
            res["x1"], res["x2"] = abs(_cm(pos[0])), abs(_cm(pos[1]))
        elif tipo in {"Y", "ASYMY"}:
            res["y1"], res["y2"] = abs(_cm(pos[0])), abs(_cm(pos[1]))
    return res


def _energia_rotulo(beam: Dataset, cp0: Dataset) -> str:
    """Energia no formato da ficha: '10FFF', '6 MV', '9 MeV'."""
    energia = getattr(cp0, "NominalBeamEnergy", None)
    if energia is None:
        return ""
    radiacao = str(getattr(beam, "RadiationType", "")).upper()
    unidade = "MeV" if radiacao == "ELECTRON" else "MV"
    # Modo de fluência FFF (flattening filter free).
    fff = False
    for fm in getattr(beam, "PrimaryFluenceModeSequence", []):
        if str(getattr(fm, "FluenceModeID", "")).upper() == "FFF":
            fff = True
        if str(getattr(fm, "FluenceMode", "")).upper() == "NON_STANDARD" and getattr(
            fm, "FluenceModeID", ""
        ):
            fff = str(fm.FluenceModeID).upper() == "FFF"
    return f"{energia:g}FFF" if fff else f"{energia:g} {unidade}"


def _filtro(beam: Dataset) -> str:
    """Indica a presença de filtro/cunha (wedge) no feixe."""
    if getattr(beam, "NumberOfWedges", 0):
        seq = getattr(beam, "WedgeSequence", [])
        if seq:
            return str(getattr(seq[0], "WedgeID", "") or getattr(seq[0], "WedgeAngle", "") or "Cunha")
        return "Cunha"
    return "-"


def parse_rtplan(ds: Dataset) -> dict:
    """Prescrição, grupo de frações e tabela feixe a feixe do RT Plan."""
    info: dict[str, Any] = {
        "paciente": dados_paciente(ds),
        "rotulo_plano": str(getattr(ds, "RTPlanLabel", "") or ""),
        "nome_plano": str(getattr(ds, "RTPlanName", "") or ""),
        "data_plano": _formatar_data(getattr(ds, "RTPlanDate", "")),
        "medico": _primeiro_nome(getattr(ds, "PhysiciansOfRecord", "")),
        "fisico": _primeiro_nome(
            getattr(ds, "ReviewerName", "") or getattr(ds, "OperatorsName", "")
        ),
        "aprovacao": str(getattr(ds, "ApprovalStatus", "") or ""),
    }

    # Dose de prescrição (DoseReferenceSequence).
    dose_prescrita = None
    for dref in getattr(ds, "DoseReferenceSequence", []):
        if getattr(dref, "TargetPrescriptionDose", None) is not None:
            dose_prescrita = float(dref.TargetPrescriptionDose)
            break

    # Grupo de frações: nº de frações, dose e MU (BeamMeterset) por feixe.
    num_fracoes = None
    dose_por_feixe: dict[int, float] = {}
    mu_por_feixe: dict[int, float] = {}
    grupos = getattr(ds, "FractionGroupSequence", [])
    if grupos:
        fg = grupos[0]
        num_fracoes = getattr(fg, "NumberOfFractionsPlanned", None)
        for rb in getattr(fg, "ReferencedBeamSequence", []):
            num = getattr(rb, "ReferencedBeamNumber", None)
            if num is None:
                continue
            if getattr(rb, "BeamDose", None) is not None:
                dose_por_feixe[int(num)] = float(rb.BeamDose)
            if getattr(rb, "BeamMeterset", None) is not None:
                mu_por_feixe[int(num)] = float(rb.BeamMeterset)

    # Tabela de feixes.
    feixes = []
    maquina = ""
    for beam in getattr(ds, "BeamSequence", []):
        if str(getattr(beam, "TreatmentDeliveryType", "TREATMENT")).upper() == "SETUP":
            continue  # ignora feixes de setup/imagem
        cps = getattr(beam, "ControlPointSequence", [])
        cp0 = cps[0] if cps else Dataset()
        maquina = maquina or str(getattr(beam, "TreatmentMachineName", "") or "")
        numero = getattr(beam, "BeamNumber", None)
        jaws = _mordentes(cp0)
        feixes.append(
            {
                "numero": numero,
                "nome": str(getattr(beam, "BeamName", "") or ""),
                "radiacao": str(getattr(beam, "RadiationType", "") or ""),
                "tecnica": _tecnica_do_feixe(beam),
                "energia": getattr(cp0, "NominalBeamEnergy", None),
                "energia_rotulo": _energia_rotulo(beam, cp0),
                "ssd": _cm(getattr(cp0, "SourceToSurfaceDistance", None)),
                "x1": jaws.get("x1"),
                "x2": jaws.get("x2"),
                "y1": jaws.get("y1"),
                "y2": jaws.get("y2"),
                "gantry": getattr(cp0, "GantryAngle", None),
                "colimador": getattr(cp0, "BeamLimitingDeviceAngle", None),
                "mesa": getattr(cp0, "PatientSupportAngle", None),
                "bolus": "Sim" if getattr(beam, "NumberOfBoli", 0) else "-",
                "filtro": _filtro(beam),
                "um": mu_por_feixe.get(int(numero)) if numero is not None else None,
                "dose_feixe": dose_por_feixe.get(int(numero)) if numero is not None else None,
            }
        )

    energias = {f["energia_rotulo"] for f in feixes if f["energia_rotulo"]}
    tecnicas = {f["tecnica"] for f in feixes if f["tecnica"]}

    info.update(
        {
            "dose_total": dose_prescrita,
            "num_fracoes": num_fracoes,
            "dose_fracao": (
                round(dose_prescrita / num_fracoes, 2)
                if dose_prescrita and num_fracoes
                else None
            ),
            "maquina": maquina,
            "energia": ", ".join(sorted(energias)),
            "tecnica": ", ".join(sorted(tecnicas)),
            "num_feixes": len(feixes),
            "feixes": feixes,
        }
    )
    return info


# Tipos de estrutura considerados alvos (target).
_TIPOS_ALVO = {"PTV", "CTV", "GTV"}


def parse_rtstruct(ds: Dataset) -> dict:
    """Lista de estruturas/volumes (alvos e órgãos de risco) do RT Struct."""
    # Mapeia número da ROI -> tipo interpretado (PTV, ORGAN, EXTERNAL, ...).
    tipos: dict[int, str] = {}
    for obs in getattr(ds, "RTROIObservationsSequence", []):
        num = getattr(obs, "ReferencedROINumber", None)
        if num is not None:
            tipos[int(num)] = str(getattr(obs, "RTROIInterpretedType", "") or "")

    alvos, oars, outras = [], [], []
    for roi in getattr(ds, "StructureSetROISequence", []):
        num = getattr(roi, "ROINumber", None)
        nome = str(getattr(roi, "ROIName", "") or "")
        tipo = tipos.get(int(num), "") if num is not None else ""
        item = {"nome": nome, "tipo": tipo}
        nome_up = nome.upper()
        if tipo in _TIPOS_ALVO or any(t in nome_up for t in _TIPOS_ALVO):
            alvos.append(item)
        elif tipo in {"ORGAN", "AVOIDANCE"}:
            oars.append(item)
        elif tipo != "EXTERNAL":
            outras.append(item)

    return {
        "paciente": dados_paciente(ds),
        "rotulo": str(getattr(ds, "StructureSetLabel", "") or ""),
        "alvos": alvos,
        "orgaos_risco": oars,
        "outras": outras,
    }


def parse_rtdose(ds: Dataset) -> dict:
    """Resumo da matriz de dose do RT Dose."""
    linhas = getattr(ds, "Rows", None)
    colunas = getattr(ds, "Columns", None)
    frames = getattr(ds, "NumberOfFrames", None)
    return {
        "paciente": dados_paciente(ds),
        "unidade": str(getattr(ds, "DoseUnits", "") or ""),
        "tipo": str(getattr(ds, "DoseType", "") or ""),
        "soma": str(getattr(ds, "DoseSummationType", "") or ""),
        "escala": getattr(ds, "DoseGridScaling", None),
        "dimensoes": f"{colunas}×{linhas}×{frames}" if linhas and colunas else "",
    }


PARSERS = {
    "TC": parse_ct,
    "RP": parse_rtplan,
    "RS": parse_rtstruct,
    "RD": parse_rtdose,
}


def processar(conteudo: bytes) -> tuple[str, dict]:
    """Carrega um DICOM, identifica o tipo e devolve (código, dados extraídos)."""
    ds = carregar(conteudo)
    codigo = identificar(ds)
    parser = PARSERS.get(codigo)
    return codigo, (parser(ds) if parser else {"paciente": dados_paciente(ds)})
