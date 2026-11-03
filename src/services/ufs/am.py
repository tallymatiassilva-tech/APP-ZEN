# src/services/ufs/am.py
"""Regras exclusivas de AM. Lida com guias Dar-Avulso e silencia Notas Fiscais."""

from __future__ import annotations

import re

from src.services.document_classifier import (
    e_dar_documento,
    extrair_codigo_barras_pdf,
    extrair_numero_termo_pdf,
    linha_digitavel_para_codigo_barras,
)
from src.utils.text_mono import (
    formatar_numero_arquivo,
    padronizar_data_ddmmyyyy,
)


def _extrair_regras_am(txt_pdf: str, nome_anexo: str, nfe_map: dict):
    txt_upper = txt_pdf.upper()

    # 0. TRAVA EXCLUSIVA: Silencia Notas Fiscais (DANFE) para evitar linhas duplas
    # A nota apenas empresta a chave para cruzamento, não gerando linha própria.
    if any(
        k in txt_upper for k in ["DANFE", "RECEBEMOS DE", "DOCUMENTO AUXILIAR DA NOTA"]
    ):
        chaves_encontradas = []
        for ch_raw in re.findall(r"(?<!\d)(?:(?:\d[\s\.-]*){44})(?!\d)", txt_pdf):
            ch_clean = re.sub(r"\D", "", ch_raw)
            if not ch_clean.startswith("8") and ch_clean not in chaves_encontradas:
                nfe_map[ch_clean] = formatar_numero_arquivo(
                    ch_clean[25:34].lstrip("0") or "0"
                )
                chaves_encontradas.append(ch_clean)

        pares = [(ch, nfe_map.get(ch, "Sem Número")) for ch in chaves_encontradas] or [
            ("Sem Arquivo Válido", "Sem Número")
        ]
        return (
            "Não localizado",
            pares,
            "Sem Código",
            "Sem Código",
            "Não informado",
            "Não informado",
            "AM",
        )

    # 1. Extrair Termo / Controle (Ex: Controle: 6530394572218)
    termo = "Não localizado"
    m_termo = re.search(r"Controle[\s:]*(\d{10,15})", txt_pdf, re.IGNORECASE)
    if m_termo:
        termo = m_termo.group(1).strip()
    else:
        termo_alt = extrair_numero_termo_pdf(txt_pdf, nome_anexo)
        if termo_alt:
            termo = termo_alt

    # 2. Extrair CNPJ/CPF (Código do Contribuinte)
    if m_doc := re.search(
        r"C[OÓ]DIGO\s+DO\s+CONTRIBUINTE[\s\S]{0,20}?\b([\d\.\/-]{11,18})\b",
        txt_pdf,
        re.IGNORECASE,
    ):
        doc_guia_am = re.sub(r"\D", "", m_doc.group(1))
        if termo != "Não localizado" and doc_guia_am:
            nfe_map[f"DOC_MS_{termo}"] = doc_guia_am

    # 3. Extrair Código de Barras (48 limpo e 44 verificado)
    barras_orig, barras_44 = extrair_codigo_barras_pdf(txt_pdf)
    m_barras = re.search(r"(8(?:[\s\.-]*\d){43,50})", txt_pdf)
    if m_barras:
        # Tira espaços e traços, mantendo TODOS os números intactos
        apenas_numeros = re.sub(r"\D", "", m_barras.group(1))
        if len(apenas_numeros) >= 44:
            barras_orig = apenas_numeros
            barras_44 = linha_digitavel_para_codigo_barras(apenas_numeros)

    # 4. Extrair Vencimento (Prioriza 'Válido até')
    vencimento = "Não informado"

    # Procura primeiro pelo "Válido até" (ex: ** Válido até 13/07/2026 **)
    m_venc = re.search(
        r"V[áa]lido\s+at[ée][\s\S]{0,30}?\b(\d{2}/\d{2}/\d{4})\b",
        txt_pdf,
        re.IGNORECASE,
    )

    # Se não encontrar, usa o campo 06 DATA DE VENCIMENTO como plano B (fallback)
    if not m_venc:
        m_venc = re.search(
            r"06\s*DATA\s+DE\s+VENCIMENTO[\s\S]{0,30}?\b(\d{2}/\d{2}/\d{4})\b",
            txt_pdf,
            re.IGNORECASE,
        )

    if m_venc:
        vencimento = m_venc.group(1).strip()
    vencimento = padronizar_data_ddmmyyyy(vencimento)

    # 5. Extrair Valor (Campo TOTAL 18 VALOR)
    valor = "Não informado"
    m_val = re.search(
        r"TOTAL\s*(?:\|\s*)?18\s*VALOR\s*(?:\|\s*)?(?:R\$\s*)?(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})",
        txt_pdf,
        re.IGNORECASE,
    )
    if m_val:
        valor = m_val.group(1).strip()
    else:
        # Fallback de segurança para capturar o último valor
        valores = re.findall(r"(?:R\$\s*)?(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})", txt_pdf)
        if valores:
            valor = valores[-1]

    # 6. Extrair Chaves de NF-e presentes na guia (CHAVE NF-E)
    pares_documento, chaves_encontradas = [], []
    chaves_raw = re.findall(r"(?<!\d)(?:(?:\d[\s\.-]*){44})(?!\d)", txt_pdf)

    for ch_raw in chaves_raw:
        ch_clean = re.sub(r"\D", "", ch_raw)
        if (
            ch_clean != barras_44
            and ch_clean not in chaves_encontradas
            and not ch_clean.startswith("8")
        ):
            chaves_encontradas.append(ch_clean)

    for chave in chaves_encontradas:
        num_doc = nfe_map.get(
            chave, formatar_numero_arquivo(chave[25:34].lstrip("0") or "0")
        )
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
        "AM",
    )
