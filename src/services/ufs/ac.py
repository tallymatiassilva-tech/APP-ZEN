# src/services/ufs/ac.py
"""Regras exclusivas de AC. Nenhum if de outra UF aqui."""

from __future__ import annotations

import re

from src.services.document_classifier import (
    e_dar_documento,
    extrair_codigo_barras_pdf,
    extrair_numero_termo_pdf,
)
from src.utils.text_mono import (
    formatar_numero_arquivo,
    padronizar_data_ddmmyyyy,
)


def _extrair_regras_ac(txt_pdf: str, nome_anexo: str, nfe_map: dict):
    # sourcery skip: low-code-quality
    txt_upper = txt_pdf.upper()
    is_dar = (
        e_dar_documento(txt_pdf)
        or "NOTIFICAÇÃO DO ICMS" in txt_upper
        or "TERMO DE APREENSÃO" in txt_upper
        or "VIA BANCO" in txt_upper
    )

    termo = "Não localizado"
    m_num = re.search(r"Número[\s\n\r:]*([\d\.]+)", txt_pdf, re.IGNORECASE)
    if m_num:
        termo = re.sub(r"\D", "", m_num[1])
    elif m_proc := re.search(r"Processo[\s\n\r]*Ativo\s*(\d+/\d{4})", txt_pdf, re.IGNORECASE):
        termo = m_proc[1].strip()
    elif termo_alt := extrair_numero_termo_pdf(txt_pdf, nome_anexo):
        termo = termo_alt

    if m_doc_ac := re.search(
        r"(?:N[º°o]*\s*no\s*CNPJ|CNPJ/CPF|CNPJ|CPF|INSCRI[ÇC][ÃA]O\s*ESTADUAL)\s*[\n\r:]*\s*([\d\.\/-]{11,18})",
        txt_pdf,
        re.IGNORECASE,
    ):
        doc_guia_ac = re.sub(r"\D", "", m_doc_ac[1])
        if termo != "Não localizado" and doc_guia_ac:
            nfe_map[f"DOC_MS_{termo}"] = doc_guia_ac

    # 3. Extrair Código de Barras (Preservando TODOS os números, removendo apenas espaços)
    barras_orig, barras_44 = "Sem Código", "Sem Código"
    if m_barras_ac := re.search(r"(8(?:[\s\.-]*\d){43,50})", txt_pdf):
        # Apenas remove espaços e pontuações, preservando rigorosamente TODOS os números sem cortar nenhum dígito
        apenas_numeros = re.sub(r"\D", "", m_barras_ac[1])
        barras_orig = apenas_numeros
        barras_44 = apenas_numeros
    else:
        barras_orig, barras_44 = extrair_codigo_barras_pdf(txt_pdf)

    vencimento = "Não informado"
    m_venc = re.search(
        r"(?:Data\s*de\s*Vencimento|Válido\s*para\s*pagamento\s*até)\s*[:|-]?\s*[\n\r|]*\s*(\d{2}/\d{2}/\d{2,4})",
        txt_pdf,
        re.IGNORECASE,
    )
    if m_venc:
        venc_raw = m_venc[1].strip()
        if len(venc_raw) == 8:
            partes = venc_raw.split("/")
            vencimento = f"{partes[0]}/{partes[1]}/20{partes[2]}"
        else:
            vencimento = venc_raw
    vencimento = padronizar_data_ddmmyyyy(vencimento)

    valor = "Não informado"
    m_val = re.search(
        r"Total\s+do\s+ICMS\s+a\s+recolher[\s\n\r:]*(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})",
        txt_pdf,
        re.IGNORECASE,
    )
    if m_val:
        valor = m_val[1].strip()
    elif is_dar and (
        m_val_alt := re.search(
            r"(?:Total|Valor)[\s\n\r:]*(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})",
            txt_pdf,
            re.IGNORECASE,
        )
    ):
        valor = m_val_alt[1].strip()

    pares_documento, chaves_encontradas = [], []
    for ch in re.findall(r"\b(\d{44})\b", txt_pdf):
        if ch != barras_44 and ch not in chaves_encontradas and not ch.startswith("8"):
            chaves_encontradas.append(ch)

    for chave in chaves_encontradas:
        num_doc = nfe_map.get(chave, formatar_numero_arquivo(chave[25:34]))
        pares_documento.append((chave, num_doc))

    if not pares_documento:
        pares_documento.append(("Sem Arquivo Válido", "Sem Número"))

    return (
        termo,
        list(dict.fromkeys(pares_documento)),
        barras_orig,
        barras_44,
        vencimento,
        valor,
        "AC",
    )
