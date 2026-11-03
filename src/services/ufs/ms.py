# src/services/ufs/ms.py
"""Regras exclusivas de MS. DAEMS + Termo de Apreensão no mesmo controle."""

from __future__ import annotations

import re

from src.services.document_classifier import (
    extrair_codigo_barras_pdf,
    extrair_numero_termo_pdf,
    linha_digitavel_para_codigo_barras,
)
from src.utils.text_mono import (
    formatar_numero_arquivo,
    padronizar_data_ddmmyyyy,
)


def _so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def _extrair_termo_ms(txt_pdf: str, nome_anexo: str) -> str:
    m_ta = re.search(r"POSTO[^\d]{0,12}\d+[^\d]{0,16}:\s*(\d{6,15})", txt_pdf, re.IGNORECASE)
    if not m_ta:
        m_ta = re.search(
            r"TERMO\s*DE\s*APREENS[AÃ]O\s*N[º°o\.]*\s*(\d{6,15})",
            txt_pdf,
            re.IGNORECASE,
        )
    if m_ta:
        return m_ta.group(1).strip()
    return extrair_numero_termo_pdf(txt_pdf, nome_anexo) or "Não localizado"


def _extrair_doc_campo_03(txt_pdf: str) -> str:
    """Campo 03 do DAEMS: CPF, CNPJ ou IE, mesmo com texto no meio."""
    janela = re.search(r"03\s*[-–—]?\s*CPF[\s\S]{0,220}", txt_pdf, re.IGNORECASE)
    if not janela:
        return ""
    trecho = janela.group(0)
    padroes = (
        r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}",
        r"\d{3}\.\d{3}\.\d{3}-\d{2}",
        r"\d{2,3}\.\d{3}\.\d{3}-\d{1,2}",
        r"\b\d{9,14}\b",
    )
    for padrao in padroes:
        for bruto in re.findall(padrao, trecho):
            doc = _so_digitos(bruto)
            if 9 <= len(doc) <= 14 and not doc.startswith("8"):
                return doc
    return ""


def _extrair_valor_total_ms(txt_pdf: str) -> str:
    m_val = re.search(
        r"10\s*[-–—]?\s*T[O0]TAL[\s\S]{0,220}?(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*\s*,\s*\d{2})",
        txt_pdf,
        re.IGNORECASE,
    )
    if not m_val:
        return "Não informado"
    return re.sub(r"\s+", "", m_val.group(1))


def _extrair_barras_ms(txt_pdf: str) -> tuple[str, str]:
    barras_orig, barras_44 = extrair_codigo_barras_pdf(txt_pdf)
    m_barras = re.search(r"(8(?:[\s.-]*\d){43,50})", txt_pdf)
    if not m_barras:
        return barras_orig, barras_44
    codigo_impresso = m_barras.group(1).strip()
    apenas_numeros = _so_digitos(codigo_impresso)
    if len(apenas_numeros) == 48:
        return (
            codigo_impresso,
            apenas_numeros[0:11]
            + apenas_numeros[12:23]
            + apenas_numeros[24:35]
            + apenas_numeros[36:47],
        )
    if len(apenas_numeros) >= 44:
        return codigo_impresso, linha_digitavel_para_codigo_barras(apenas_numeros)
    return barras_orig, barras_44


def _extrair_regras_ms(txt_pdf: str, nome_anexo: str, nfe_map: dict):
    termo = _extrair_termo_ms(txt_pdf, nome_anexo)
    barras_orig, barras_44 = _extrair_barras_ms(txt_pdf)

    doc_guia = _extrair_doc_campo_03(txt_pdf)
    if doc_guia and termo != "Não localizado":
        nfe_map[f"DOC_MS_{termo}"] = doc_guia

    vencimento = "Não informado"
    m_nr = re.search(
        r"N[AÃ]O\s*RECEBER\s*AP[OÓ]S\s*[:|-]?\s*(\d{2}/\d{2}/\d{4})",
        txt_pdf,
        re.IGNORECASE,
    )
    if m_nr:
        vencimento = m_nr.group(1).strip()
    else:
        m_venc = re.search(
            r"02\s*[-–—]?\s*VENCIMENTO[\s\S]{0,40}?(\d{2}/\d{2}/\d{4})",
            txt_pdf,
            re.IGNORECASE,
        )
        if m_venc:
            vencimento = m_venc.group(1).strip()
    vencimento = padronizar_data_ddmmyyyy(vencimento)

    valor = _extrair_valor_total_ms(txt_pdf)

    notas_guia = []
    for bloco in re.findall(
        r"NOTAS\s*FISCAIS\s*[:|-]?[\s\n\r]*([\d\s,/-]+)", txt_pdf, re.IGNORECASE
    ):
        for n in re.findall(r"\b\d{1,9}\b", bloco):
            n_fmt = formatar_numero_arquivo(n)
            if n_fmt != "Sem Número" and n_fmt not in notas_guia:
                notas_guia.append(n_fmt)
    num_nota = notas_guia[0] if notas_guia else "Sem Número"

    chaves = []
    for ch in re.findall(r"\b(\d{44})\b", txt_pdf):
        if ch == barras_44 or ch.startswith("8") or ch in chaves:
            continue
        chaves.append(ch)
        if ch[20:22] != "57":
            nfe_map.setdefault(ch, formatar_numero_arquivo(ch[25:34].lstrip("0") or "0"))

    pares = []
    if chaves:
        for chave in chaves:
            if chave[20:22] == "57":
                num_ref = (
                    num_nota
                    if num_nota != "Sem Número"
                    else formatar_numero_arquivo(chave[25:34].lstrip("0") or "0")
                )
            else:
                num_ref = (
                    num_nota
                    if num_nota != "Sem Número"
                    else nfe_map.get(
                        chave, formatar_numero_arquivo(chave[25:34].lstrip("0") or "0")
                    )
                )
            pares.append((chave, num_ref))
    elif num_nota != "Sem Número":
        pares.append(("Sem Arquivo Válido", num_nota))
    else:
        pares.append(("Sem Arquivo Válido", "Sem Número"))

    return (
        termo,
        list(dict.fromkeys(pares)),
        barras_orig,
        barras_44,
        vencimento,
        valor,
        "MS",
    )
