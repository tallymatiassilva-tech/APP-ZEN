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


def documentos_dos_pares(pares):
    """CPF/CNPJ da guia. Cada par e (documento, numero); o doc e o [0]."""
    docs = []
    for par in pares or []:
        bruto = par[0] if isinstance(par, (tuple, list)) and par else par
        d = so_digitos(bruto)
        if len(d) in (11, 14):
            docs.append(d)
    return list(dict.fromkeys(docs))


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

    valores = [v for v in nfe_map.values() if isinstance(v, dict)]
    alvo = valores[0] if valores else nfe_map
    chaves = [str(k) for k in nfe_map if len(so_digitos(k)) == 44]
    return (
        _primeiro(alvo, _CAMPOS_REMETENTE),
        _primeiro(alvo, _CAMPOS_DESTINATARIO),
        chaves,
    )


def validar_guia_ap(pares, txt_guia, nfe_map):
    """Retorna (ok, motivo). Usa apenas as regras de ap.py."""
    docs = documentos_dos_pares(pares)
    if not docs:
        return False, "INCOMPLETO: nenhum CPF/CNPJ no campo 05"

    chave = chave_do_texto(txt_guia)
    if len(chave) != 44:
        return False, "INCOMPLETO: chave NF-e nao localizada no campo 24"

    rem, dest, chaves = dados_da_remessa(nfe_map)
    motivo = ""
    for doc in docs:
        ok, motivo = validar_guia(doc, chave, rem, dest, chaves)
        if ok:
            return True, motivo
    return False, motivo


def resumo_nfe_map(nfe_map):
    """Diagnostico: revela o formato do nfe_map sem abrir o codigo."""
    if isinstance(nfe_map, dict):
        ks = [str(k)[:46] for k in list(nfe_map)[:3]]
        return f"dict n={len(nfe_map)} keys={ks}"
    return f"tipo={type(nfe_map).__name__}"
