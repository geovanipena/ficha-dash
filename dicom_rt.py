"""Leitura dos objetos DICOM-RT (TC, RP, RS, RD) para a ficha técnica.

Cada função recebe um ``pydicom.Dataset`` já carregado e devolve um
dicionário com os campos relevantes para a ficha. As funções são tolerantes
a tags ausentes — sempre usam ``getattr``/``.get`` com valor padrão.
"""

from __future__ import annotations

from typing import Any

import pydicom
from pydicom.dataset import Dataset

# Modalidades DICOM dos objetos de interesse.
MODALIDADES = {
    "CT": "TC",
    "RTPLAN": "RP",
    "RTSTRUCT": "RS",
    "RTDOSE": "RD",
}


def carregar(conteudo: bytes) -> Dataset:
    """Carrega um arquivo DICOM a partir de bytes."""
    from io import BytesIO

    return pydicom.dcmread(BytesIO(conteudo), force=True)


def _formatar_nome(valor: Any) -> str:
    """Converte um PersonName DICOM (Sobrenome^Nome) em texto legível."""
    if not valor:
        return ""
    texto = str(valor).replace("^", " ").strip()
    return " ".join(texto.split())


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


def parse_rtplan(ds: Dataset) -> dict:
    """Prescrição, grupo de frações e tabela feixe a feixe do RT Plan."""
    info: dict[str, Any] = {
        "paciente": dados_paciente(ds),
        "rotulo_plano": str(getattr(ds, "RTPlanLabel", "") or ""),
        "nome_plano": str(getattr(ds, "RTPlanName", "") or ""),
        "data_plano": _formatar_data(getattr(ds, "RTPlanDate", "")),
    }

    # Dose de prescrição (DoseReferenceSequence).
    dose_prescrita = None
    for dref in getattr(ds, "DoseReferenceSequence", []):
        if getattr(dref, "TargetPrescriptionDose", None) is not None:
            dose_prescrita = float(dref.TargetPrescriptionDose)
            break

    # Grupo de frações: nº de frações e dose por feixe.
    num_fracoes = None
    dose_por_feixe: dict[int, float] = {}
    grupos = getattr(ds, "FractionGroupSequence", [])
    if grupos:
        fg = grupos[0]
        num_fracoes = getattr(fg, "NumberOfFractionsPlanned", None)
        for rb in getattr(fg, "ReferencedBeamSequence", []):
            num = getattr(rb, "ReferencedBeamNumber", None)
            if num is not None and getattr(rb, "BeamDose", None) is not None:
                dose_por_feixe[int(num)] = float(rb.BeamDose)

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
        feixes.append(
            {
                "numero": numero,
                "nome": str(getattr(beam, "BeamName", "") or ""),
                "radiacao": str(getattr(beam, "RadiationType", "") or ""),
                "tecnica": _tecnica_do_feixe(beam),
                "energia": getattr(cp0, "NominalBeamEnergy", None),
                "gantry": getattr(cp0, "GantryAngle", None),
                "colimador": getattr(cp0, "BeamLimitingDeviceAngle", None),
                "mesa": getattr(cp0, "PatientSupportAngle", None),
                "um": getattr(beam, "FinalCumulativeMetersetWeight", None),
                "dose_feixe": dose_por_feixe.get(int(numero)) if numero is not None else None,
            }
        )

    energias = {f["energia"] for f in feixes if f["energia"] is not None}
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
            "energia": ", ".join(f"{e:g} MV" for e in sorted(energias)) if energias else "",
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
