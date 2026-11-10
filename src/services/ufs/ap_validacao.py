# src/services/ufs/ap_validacao.py
"""Liga as regras de AP ao fluxo. Nao reimplementa regra fiscal."""

import re

from src.services.document_classifier import chave_nfe_valida
from src.services.ufs.ap import ler_chave_nfe, so_digitos, validar_guia

_RE_CHAVE = re.compile(r"Chave\s+de\s+Acesso\D{0,20}([\d\s.\-/]{44,70})", re.I)

_CAMPOS_REMETENTE = (
    "remetente", "cnpj_remetente", "cpf_remetente", "emitente", "cnpj_emitente",
)
_CAMPOS_DESTINATARIO = (
    "destinatario", "cnpj_destinatario", "cpf_destinatario", "dest_cnpj", "cnpj_dest",
)
_RE_CAMPO_05 = re.compile(r"\b05\s*[-–—]\s*(.*?)(?=\b06\s*[-–—]|\Z)", re.I | re.S)
_RE_DOCUMENTO = re.compile(r"(?<!\d)(?:\d[\s./-]*){11,14}(?!\d)")


def marcar_status_guia_ap_processada(status: str) -> str:
    if status == "OK":
        return "GUIA JÁ PROCESSADA"
    if "GUIA JÁ PROCESSADA" in status:
        return status
    return f"{status} | GUIA JÁ PROCESSADA"


def validar_chaves_ap(pares_documento: list, chaves_nfe: set[str] | dict) -> str:
    """Compara as chaves de NF-e da guia com as chaves fornecidas pela remessa."""
    chaves_guia = set()
    for par in pares_documento or []:
        try:
            chave = par[0]
        except Exception:
            continue
        if not chave or chave == "Sem Arquivo Válido":
            continue
        if not chave_nfe_valida(str(chave)):
            continue
        chaves_guia.add(re.sub(r"\D", "", str(chave)))
    if not chaves_guia:
        return "INCOMPLETO: chave da guia AP nao localizada"

    chaves_nfe_validas = set()
    for chave in chaves_nfe or []:
        if chave_nfe_valida(str(chave)):
            chaves_nfe_validas.add(re.sub(r"\D", "", str(chave)))
    if not chaves_nfe_validas:
        return "INCOMPLETO: remessa sem chaves de NF-e"
    if chaves_guia.issubset(chaves_nfe_validas):
        return "DOC OK"
    return "QUARENTENA: chave da guia diverge da NF-e"


def _doc_do_par(par):
    return par[0] if isinstance(par, (tuple, list)) and par else par


def documentos_dos_pares(pares):
    """CPF/CNPJ (11 ou 14 digitos) da guia."""
    docs = []
    for par in pares or []:
        d = so_digitos(_doc_do_par(par))
        if len(d) in (11, 14):
            docs.append(d)
    return list(dict.fromkeys(docs))


def doc_do_campo_05(txt_guia):
    """Extrai CPF/CNPJ do campo 05 da guia, sem capturar dígitos de outros campos."""
    match = _RE_CAMPO_05.search(str(txt_guia or ""))
    if not match:
        return ""

    for candidato in _RE_DOCUMENTO.findall(match.group(1)):
        documento = so_digitos(candidato)
        if len(documento) in (11, 14):
            return documento
    return ""


def chaves_dos_pares(pares):
    """Chaves NF-e (44 digitos) da guia. Ficam no [0] do par, igual ao CPF."""
    chaves = []
    for par in pares or []:
        d = so_digitos(_doc_do_par(par))
        if len(d) == 44:
            chaves.append(d)
    return list(dict.fromkeys(chaves))


def chave_do_texto(txt_guia):
    """Chave NF-e do campo 24, restrita ao rotulo. Nada de varrer o texto todo."""
    m = _RE_CHAVE.search(str(txt_guia or ""))
    return ler_chave_nfe(m.group(1)) if m else ""


def _primeiro(dados, campos):
    if not isinstance(dados, dict):
        return ""
    for c in campos:
        if dados.get(c):
            return str(dados[c])
    return ""


def dados_da_remessa(nfe_map):
    """Remetente, destinatario e chaves de NF-e vindos do nfe_map."""
    if not isinstance(nfe_map, dict) or not nfe_map:
        return "", "", []

    rem = dest = ""
    for v in nfe_map.values():
        if not isinstance(v, dict):
            continue
        if not rem:
            rem = _primeiro(v, _CAMPOS_REMETENTE)
        if not dest:
            dest = _primeiro(v, _CAMPOS_DESTINATARIO)
        if rem and dest:
            break

    chaves = []
    for k in nfe_map:
        d = so_digitos(str(k))
        if len(d) == 44 and d not in chaves:
            chaves.append(d)
    return rem, dest, chaves


def validar_guia_ap(pares, txt_guia, nfe_map, doc_guia=""):
    """Retorna (ok, motivo) validando chave NF-e e CPF/CNPJ da guia.

    A chave de 44 digitos da guia precisa existir nas chaves da remessa.
    Quando a remessa inclui remetente ou destinatario, o CPF/CNPJ do campo 05
    tambem precisa corresponder a um deles.
    """
    rem, dest, chaves_remessa = dados_da_remessa(nfe_map)
    docs = [
        doc
        for doc in (
            so_digitos(doc_guia),
            doc_do_campo_05(txt_guia),
            *documentos_dos_pares(pares),
        )
        if len(doc) in (11, 14)
    ]

    chaves_guia = []
    chave_txt = chave_do_texto(txt_guia)
    if len(chave_txt) == 44:
        chaves_guia.append(chave_txt)
    for c in chaves_dos_pares(pares):
        if c not in chaves_guia:
            chaves_guia.append(c)

    if not docs:
        return False, "INCOMPLETO: nenhum CPF/CNPJ no campo 05"
    if not chaves_guia:
        return False, "INCOMPLETO: chave NF-e nao localizada no campo 24"

    if not chaves_remessa:
        return False, "INCOMPLETO: remessa sem chaves de NF-e"

    bate = [c for c in chaves_guia if c in chaves_remessa]
    if not bate:
        return False, "QUARENTENA: chave da guia nao pertence a remessa"

    if not rem and not dest:
        return (
            True,
            "DOC OK: chave da guia encontrada na remessa; "
            "CPF/CNPJ nao validado (remetente/destinatario ausente)",
        )

    motivo = "QUARENTENA: documento da guia nao confere com a NF-e"
    for doc in docs:
        ok, motivo = validar_guia(doc, bate[0], rem, dest, chaves_remessa)
        if ok:
            return True, f"DOC OK: {motivo.removeprefix('OK: ')}"
    return False, motivo


def resumo_nfe_map(nfe_map):
    """Diagnostico: revela o formato do nfe_map sem abrir o codigo."""
    if isinstance(nfe_map, dict):
        ks = [str(k)[:46] for k in list(nfe_map)[:3]]
        return f"dict n={len(nfe_map)} keys={ks}"
    return f"tipo={type(nfe_map).__name__}"
