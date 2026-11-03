# src/services/ufs/geral.py
"""Regra fallback GERAL. Não citar AL, AP, AC, MS ou AM aqui."""

from __future__ import annotations

import re

from src.services.document_classifier import (
    e_dar_documento,
    extrair_codigo_barras_pdf,
    extrair_numero_termo_pdf,
    extrair_vencimento_e_valor_pdf,
)
from src.utils.text_mono import (
    formatar_numero_arquivo,
    padronizar_data_ddmmyyyy,
)


def _extrair_regras_geral(txt_pdf: str, nome_anexo: str, nfe_map: dict):
    is_dar = e_dar_documento(txt_pdf)
    termo = extrair_numero_termo_pdf(txt_pdf, nome_anexo) or "Não localizado"
    barras_orig, barras_44 = extrair_codigo_barras_pdf(txt_pdf)
    vencimento, valor = extrair_vencimento_e_valor_pdf(txt_pdf)
    vencimento = padronizar_data_ddmmyyyy(vencimento)

    pares_documento, chaves_encontradas = [], []
    if not is_dar:
        for ch in re.findall(r"\b(\d{44})\b", txt_pdf):
            if ch not in chaves_encontradas:
                chaves_encontradas.append(ch)
        for chave in chaves_encontradas:
            num_doc = nfe_map.get(chave, formatar_numero_arquivo(chave[25:34]))
            pares_documento.append((chave, num_doc))
            if termo == "Não localizado":
                termo = chave

    return (
        termo,
        list(dict.fromkeys(pares_documento)),
        barras_orig,
        barras_44,
        vencimento,
        valor,
        "GERAL",
    )
