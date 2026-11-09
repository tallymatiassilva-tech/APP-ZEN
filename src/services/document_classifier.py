"""Document classification. Regex and fiscal logic preserved 1:1."""

from __future__ import annotations

import io
import re

import pypdf

from src.utils.text_mono import padronizar_data_ddmmyyyy


def e_dar_documento(texto_pdf: str) -> bool:
    u = texto_pdf.upper()
    if any(
        k in u
        for k in [
            "DOCUMENTO DE ARRECADA",
            "1ª VIA - BANCO",
            "2ª VIA - CONTRIBUINTE",
            "NÚMERO DO DAR",
            "TOTAL DO DAR",
            "T.DAR",
            "TDAR",
            "DAEMS",
            "DARE",
            "DAR/AL",
            "DAR MODELO 1",
            "ESTADO DO AMAP",
        ]
    ):
        return True
    if re.search(
        r"\b8\d{10}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d\b|\b8\d{43,47}\b",
        texto_pdf,
    ):
        return True
    return False


def e_termo_documento(texto_pdf: str) -> bool:
    if e_dar_documento(texto_pdf):
        return False
    u = texto_pdf.upper()
    return any(
        k in u
        for k in [
            "TERMO DE AVERIGUA",
            "AVERIGUACAO",
            "AVERIGUAÇÃO",
            "TERMO DE APREENSAO",
            "TERMO DE APREENSÃO",
            "TERMO DE VERIFICACAO FISCAL",
            "TERMO DE VERIFICAÇÃO FISCAL",
        ]
    )


def e_nota_fiscal(texto_pdf: str, nome_anexo: str) -> bool:
    u = texto_pdf.upper()
    nl = nome_anexo.lower()
    if e_termo_documento(texto_pdf) or "termo" in nl:
        return False
    if e_dar_documento(texto_pdf) or "dar" in nl:
        return False
    if any(k in u for k in ["DANFE", "DOCUMENTO AUXILIAR DA NOTA FISCAL", "RECEBEMOS DE"]):
        return True
    if "NOTA FISCAL" in u and "SEFAZ" not in u:
        return True
    if (
        "download" in nl
        and "CHAVE DE ACESSO" in u
        and ("PROTOCOLO DE AUTORIZACAO" in u or "PROTOCOLO DE AUTORIZAÇÃO" in u)
    ):
        return True
    return False


def extrair_vencimento_nota(texto_pdf: str) -> str:
    match = re.search(
        r"(?:VENCIMENTO|VALIDADE|VALIDO\s+ATE|VÁLIDO\s+ATÉ)"
        r"[^\d]{0,40}(\d{2}[/-]\d{2}[/-]\d{2,4})",
        texto_pdf or "",
        re.IGNORECASE,
    )
    return padronizar_data_ddmmyyyy(match.group(1)) if match else "Não informado"


def linha_digitavel_para_codigo_barras(linha: str) -> str:
    n = re.sub(r"\D", "", str(linha or ""))
    if len(n) == 48:
        return n[0:11] + n[12:23] + n[24:35] + n[36:47]
    if len(n) == 47:
        return n[0:3] + n[3:4] + n[32:33] + n[33:47] + n[4:9] + n[10:20] + n[21:31]
    if len(n) == 44:
        return n
    return n if n else "Sem Código"


def extrair_codigo_barras_pdf(texto_pdf: str) -> tuple[str, str]:
    if not e_dar_documento(texto_pdf):
        return "Sem Código", "Sem Código"

    match_febraban = re.search(
        r"\b(8\d{10}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d)\b",
        texto_pdf,
    )
    if match_febraban:
        bruto = " ".join(match_febraban.group(1).split())
        digits = re.sub(r"\D", "", bruto)
        if len(digits) == 48:
            return bruto, linha_digitavel_para_codigo_barras(digits)

    match_boleto = re.search(
        r"\b(\d{5}[\.-]?\d{5}\s*\d{5}[\.-]?\d{6}\s*\d{5}[\.-]?\d{6}\s*\d\s*\d{14})\b",
        texto_pdf,
    )
    if match_boleto:
        bruto = " ".join(match_boleto.group(1).split())
        digits = re.sub(r"\D", "", bruto)
        if len(digits) == 47:
            return bruto, linha_digitavel_para_codigo_barras(digits)

    nums = re.sub(r"\D", "", texto_pdf)
    m48 = re.search(r"(8\d{47})", nums)
    if m48:
        return m48.group(1), linha_digitavel_para_codigo_barras(m48.group(1))
    m44 = re.search(r"(8\d{43})", nums)
    if m44:
        return m44.group(1), m44.group(1)
    return "Sem Código", "Sem Código"


def extrair_vencimento_e_valor_pdf(texto_pdf: str) -> tuple[str, str]:
    vencimento, valor = "Não informado", "Não informado"
    if not e_dar_documento(texto_pdf):
        return vencimento, valor

    m_nr = re.search(
        r"NAO\s*RECEBER\s*APOS\s*[:|-]?\s*(\d{2}/\d{2}/\d{4})", texto_pdf, re.IGNORECASE
    )
    if m_nr:
        vencimento = m_nr.group(1).strip()
    else:
        match_venc = re.search(
            r"(?:07\s*-\s*Data\s+de\s+Vencimento|Vencimento\s+do\s+DAR|Vencimento\s*[:|]?|Data\s+de\s+vencimento\s+da\s+obriga[çc][ãa]o).{0,50}?\b(\d{2}/\d{2}/\d{4})\b",
            texto_pdf,
            re.IGNORECASE | re.DOTALL,
        )
        if match_venc:
            vencimento = match_venc.group(1)
        else:
            datas = re.findall(r"\b(\d{2}/\d{2}/\d{4})\b", texto_pdf)
            if datas:
                vencimento = datas[0]

    from src.utils.text_mono import padronizar_data_ddmmyyyy

    vencimento = padronizar_data_ddmmyyyy(vencimento)

    m_val = re.search(
        r"(?:14\s*-\s*TOTAL\s+A\s+RECOLHER|10\s*-\s*TOTAL|\(=\)\s*Valor\s*Total|Valor\s*Total\s*\(R\$\)|Total\s*do\s*DAR\s*\(R\$\)|Total\s*do\s*DAR).{0,50}?(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})",
        texto_pdf,
        re.IGNORECASE | re.DOTALL,
    )
    if m_val:
        valor = m_val.group(1)
    else:
        m_dar_val = re.search(
            r"Número\s+do\s+DAR.{0,30}?\b(\d{1,3}(?:\.\d{3})*,\d{2})\b",
            texto_pdf,
            re.IGNORECASE | re.DOTALL,
        )
        if m_dar_val:
            valor = m_dar_val.group(1)
        else:
            vals = re.findall(r"\b(\d{1,3}(?:\.\d{3})*,\d{2})\b", texto_pdf)
            if vals:
                valor = vals[-1]

    return vencimento, valor


def extrair_numero_termo_pdf(texto_pdf: str, nome_anexo: str) -> str | None:
    patterns = [
        r"(?:TERMO\s*DE\s*AVERIGUA[ÇC][ÃA]O|TERMO\s*DE\s*APREENSÃO)\s*[-:]?\s*N?[º°o\.]*\s*(\d{6,15})",
        r"18\s*-\s*N\.?\s*Controle\s*[\n\r:]*\s*(\d{6,15})",
        r"N\.?\s*Controle\s*[\n\r:]*\s*(\d{8,15})",
        r"POSTO\s*:?\s*\d+\s+TA\s*:?\s*(\d{6,15})",
        r"(?:TERMO|TDAR|T\.DAR)\s*[:=-]?\s*(\d{6,15})\b",
        r"(?:Número\s*do\s*Documento|N[º°o\.]*\s*Doc\.?|Documento|Referência|Ref\.?|Auto\s*de\s*Infra[çc][ãa]o)\s*[:=-]?\s*(\d{6,15})\b",
        r"(\d{6,12})\s*N[º°o\.]*\s*:",
        r"N[º°o\.]*\s*:\s*(\d{6,12})\b",
    ]
    for pat in patterns:
        m = re.search(pat, texto_pdf, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    match_fallback = re.search(r"(?:tdar|termo|dar|guia)\D*?(\d{6,15})", nome_anexo, re.IGNORECASE)
    if match_fallback:
        return match_fallback.group(1).strip()
    return None


def chave_nfe_valida(chave: str) -> bool:
    chave_limpa = re.sub(r"\D", "", str(chave or ""))
    if len(chave_limpa) != 44:
        return False

    soma = 0
    peso = 2
    for digito in reversed(chave_limpa[:43]):
        soma += int(digito) * peso
        peso = 2 if peso == 9 else peso + 1

    digito_verificador = 11 - (soma % 11)
    if digito_verificador >= 10:
        digito_verificador = 0
    return digito_verificador == int(chave_limpa[-1])


def normalizar_documento_fiscal(valor: object) -> str:
    """Retorna CPF/CNPJ apenas com dígitos se tiver 11 ou 14 caracteres."""
    digitos = re.sub(r"\D", "", str(valor or ""))
    return digitos if len(digitos) in (11, 14) else ""


def extrair_chaves_nfe_pdf(texto_pdf: str, pdf_bytes: bytes | None = None) -> list[str]:
    textos = [str(texto_pdf or "")]
    if pdf_bytes:
        try:
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            textos.append("\n".join(page.extract_text() or "" for page in reader.pages))
        except Exception as e:
            print(f"[Aviso] Falha ao extrair chave NF-e com pypdf: {e}")

    chaves = []
    for texto in textos:
        for match in re.finditer(r"(?<!\d)(?:\d[\s.-]*){44}(?!\d)", texto):
            chave = re.sub(r"\D", "", match.group(0))
            if chave_nfe_valida(chave) and chave not in chaves:
                chaves.append(chave)
    return chaves
