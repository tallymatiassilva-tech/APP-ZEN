# src/services/ufs/ap_validacao.py
"""Liga as regras de AP ao fluxo. Nao reimplementa regra fiscal."""

import re

from src.services.ufs.ap import ler_chave_nfe, so_digitos, validar_guia

_RE_CHAVE = re.compile(r"Chave\s+de\s+Acesso\D{0,20}([\d\s.\-/]{44,70})", re.I)

_CAMPOS_REMETENTE = (
    "remetente", "cnpj_remetente", "cpf_remetente", "emitente", "cnpj_emitente",
)
_CAMPOS_DESTINATARIO = (
    "destinatario", "cnpj_destinatario", "cpf_destinatario", "dest_cnpj", "cnpj_dest",
)


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


def validar_guia_ap(pares, txt_guia, nfe_map):
    """Retorna (ok, motivo). O motivo sempre comeca por DOC OK ou QUARENTENA.

    Regra principal: a chave de 44 digitos da guia precisa existir nas chaves
    da remessa. Regra secundaria: quando o nfe_map trouxer remetente ou
    destinatario, o CPF/CNPJ da guia tambem precisa conferir.
    """
    rem, dest, chaves_remessa = dados_da_remessa(nfe_map)

    chaves_guia = []
    chave_txt = chave_do_texto(txt_guia)
    if len(chave_txt) == 44:
        chaves_guia.append(chave_txt)
    for c in chaves_dos_pares(pares):
        if c not in chaves_guia:
            chaves_guia.append(c)

    if not chaves_guia:
        return False, "QUARENTENA: chave NF-e ausente na guia"

    if not chaves_remessa:
        return False, "QUARENTENA: remessa sem chaves de NF-e"

    bate = [c for c in chaves_guia if c in chaves_remessa]
    if not bate:
        return False, "QUARENTENA: chave da guia nao pertence a remessa"

    docs = documentos_dos_pares(pares)
    if docs and (rem or dest):
        for doc in docs:
            ok, motivo = validar_guia(doc, bate[0], rem, dest, chaves_remessa)
            if ok:
                return True, "DOC OK: chave e documento conferem"
        return False, "QUARENTENA: documento da guia nao confere com a NF-e"

    return True, "DOC OK: chave da guia encontrada na remessa"


def resumo_nfe_map(nfe_map):
    """Diagnostico: revela o formato do nfe_map sem abrir o codigo."""
    if isinstance(nfe_map, dict):
        ks = [str(k)[:46] for k in list(nfe_map)[:3]]
        return f"dict n={len(nfe_map)} keys={ks}"
    return f"tipo={type(nfe_map).__name__}"
