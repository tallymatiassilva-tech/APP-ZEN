# src/services/ufs/ap.py
"""Regras exclusivas de AP. Lida com lotes de guias (DAR) e validação da Nota (DANFE)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.services.document_classifier import (
    e_dar_documento,
    extrair_codigo_barras_pdf,
    extrair_numero_termo_pdf,
    linha_digitavel_para_codigo_barras,
)
from src.utils.text_mono import (
    formatar_numero_arquivo,
    normalizar_valor_monetario,
    padronizar_data_ddmmyyyy,
)


def preparar_codigos_barras_ap(codigo_original: str, codigo_barras: str) -> tuple[str, str]:
    codigo_original_normalizado = " ".join(str(codigo_original or "").strip().split())
    digitos_originais = re.sub(r"\D", "", codigo_original_normalizado)

    if len(digitos_originais) == 48:
        if "-" in codigo_original_normalizado or " " in codigo_original_normalizado:
            codigo_original = codigo_original_normalizado
        else:
            codigo_original = (
                f"{digitos_originais[0:11]}-{digitos_originais[11]} "
                f"{digitos_originais[12:23]}-{digitos_originais[23]} "
                f"{digitos_originais[24:35]}-{digitos_originais[35]} "
                f"{digitos_originais[36:47]}-{digitos_originais[47]}"
            )
    elif codigo_original_normalizado:
        codigo_original = codigo_original_normalizado

    digitos_barras = re.sub(r"\D", "", str(codigo_barras or ""))
    if len(digitos_barras) == 48 and digitos_barras.startswith("8"):
        codigo_barras = linha_digitavel_para_codigo_barras(digitos_barras)
    elif len(digitos_barras) == 44:
        codigo_barras = digitos_barras
    elif len(digitos_originais) == 48 and digitos_originais.startswith("8"):
        codigo_barras = linha_digitavel_para_codigo_barras(digitos_originais)
    elif len(digitos_originais) == 44:
        codigo_barras = digitos_originais

    return codigo_original, codigo_barras


def extrair_valor_total_recolher_ap(texto_pdf: str) -> str:
    if not texto_pdf:
        return "Não informado"

    padroes_valor_ap = [
        r"(?:14\s*-\s*TOTAL\s+A\s+RECOLHER|TOTAL\s+A\s+RECOLHER)\s*[:=-]?\s*(?:R\$\s*)?(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})",
        r"(?:R\$\s*)?(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})\s*(?:\r?\n)?\s*14\s*-\s*TOTAL\s+A\s+RECOLHER",
        r"(?:10\s*-\s*Valor\s+Principal|Valor\s+Principal|Total\s+do\s+DAR)\s*[:=-]?\s*(?:R\$\s*)?(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})",
    ]

    for padrao in padroes_valor_ap:
        match = re.search(padrao, texto_pdf, re.IGNORECASE)
        if match:
            return normalizar_valor_monetario(match.group(1).strip())

    valores = re.findall(r"\b(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})\b", texto_pdf)
    if valores:
        return normalizar_valor_monetario(valores[-1])

    return "Não informado"


def extrair_id_controle_ap(texto: str) -> str | None:
    texto_normalizado = str(texto or "").replace("\r\n", "\n").replace("\r", "\n")
    match = re.search(
        r"(?:18\s*-\s*)?N[º°o\.]?\s*Controle[\s\S]{0,50}?\b(\d{8,15})\b",
        texto_normalizado,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    match_fallback = re.search(
        r"\b(?:Controle|Número\s+do\s+DAR|N[º°o\.]*\s*DAR)[\s\S]{0,50}?\b(\d{8,15})\b",
        texto_normalizado,
        re.IGNORECASE,
    )
    if match_fallback:
        return match_fallback.group(1).strip()
    return None


def separar_guias_ap(texto_pdf: str) -> list[tuple[str | None, str]]:
    """Separa guias AP por controle, descartando controles repetidos no mesmo lote."""
    texto_normalizado = str(texto_pdf or "").replace("\r\n", "\n").replace("\r", "\n")
    controles_encontrados = re.findall(
        r"(?:18\s*-\s*)?N[º°o\.]?\s*Controle[\s\S]{0,50}?\b(\d{8,15})\b",
        texto_normalizado,
        re.IGNORECASE,
    )
    controles_unicos = list(dict.fromkeys(c for c in controles_encontrados if c))

    if len(controles_unicos) <= 1:
        termo = (
            controles_unicos[0] if controles_unicos else extrair_id_controle_ap(texto_normalizado)
        )
        if not termo or termo == "Não localizado":
            termo = extrair_numero_termo_pdf(texto_normalizado, "")
        return [(termo, texto_normalizado)]

    linhas = texto_normalizado.split("\n")
    marcadores = []
    controle_atual = None
    for indice, linha in enumerate(linhas):
        match = re.search(
            r"(?:18\s*-\s*)?N[º°o\.]?\s*Controle[\s\S]{0,50}?\b(\d{8,15})\b",
            linha,
            re.IGNORECASE,
        )
        if match:
            controle = match.group(1).strip()
            if controle != controle_atual and controle in controles_unicos:
                marcadores.append((indice, controle))
                controle_atual = controle

    if len(marcadores) <= 1:
        return [(controles_unicos[0] if controles_unicos else None, texto_normalizado)]

    guias = []
    ids_unicos = set()
    for indice, (inicio, controle) in enumerate(marcadores):
        fim = marcadores[indice + 1][0] if indice + 1 < len(marcadores) else len(linhas)
        bloco = "\n".join(linhas[inicio:fim]).strip()
        if not bloco or controle in ids_unicos:
            continue
        ids_unicos.add(controle)
        guias.append((controle, bloco))

    return guias or [(controles_unicos[0] if controles_unicos else None, texto_normalizado)]


def extrair_remessas_ap(texto: str) -> list[str]:
    padrao_remessa = re.compile(
        r"\b(?:REMESSA|CTE|CONHECIMENTO|MINUTA)\s*"
        r"(?:N[º°O.]?\s*)?[:=-]?\s*(\d{14})(?!\d)",
        re.IGNORECASE,
    )
    remessas = []
    for match in padrao_remessa.finditer(str(texto or "")):
        remessa = match.group(1)
        if remessa not in remessas:
            remessas.append(remessa)

    texto = str(texto or "")
    for match in re.finditer(r"(?<!\d)\d{14}(?!\d)", texto):
        remessa = match.group(0)
        contexto_anterior = texto[max(0, match.start() - 24) : match.start()]
        if re.search(r"(?:CNPJ|CPF)\s*[:\-]?\s*$", contexto_anterior, re.IGNORECASE):
            continue
        if remessa not in remessas:
            remessas.append(remessa)
    return remessas


def _extrair_regras_ap(txt_pdf: str, nome_anexo: str, nfe_map: dict):
    # sourcery skip: low-code-quality
    # sourcery skip: low-code-quality
    txt_upper = txt_pdf.upper()

    # 1. VALIDAÇÃO DA NOTA FISCAL (DANFE)
    # Extrai APENAS a Chave de Acesso para cruzar e validar com a Guia.
    # Não extrai Valores nem Datas para não sujar os dados do imposto da Guia.
    if any(k in txt_upper for k in ["DANFE", "RECEBEMOS DE", "DOCUMENTO AUXILIAR DA NOTA"]):
        chaves_encontradas = []
        for ch_raw in re.findall(r"(?<!\d)(?:(?:\d[\s\.-]*){44})(?!\d)", txt_pdf):
            ch_clean = re.sub(r"\D", "", ch_raw)
            if not ch_clean.startswith("8") and ch_clean not in chaves_encontradas:
                nfe_map[ch_clean] = formatar_numero_arquivo(ch_clean[25:34].lstrip("0") or "0")
                chaves_encontradas.append(ch_clean)

        pares = [(ch, nfe_map.get(ch, "Sem Número")) for ch in chaves_encontradas] or [
            ("Sem Arquivo Válido", "Sem Número")
        ]

        # O "Não localizado" permite que o motor principal funda esta Nota com a Guia através da Chave
        return (
            "Não localizado",
            pares,
            "Sem Código",
            "Sem Código",
            "Não informado",
            "Não informado",
            "AP",
        )

    # 2. LÓGICA NORMAL PARA AS GUIAS (DAR)
    (e_dar_documento(txt_pdf) or "GOVERNO DO ESTADO DO AMAPÁ" in txt_upper or "SEFAZ" in txt_upper)  # type: ignore

    # Extrair Termo / N. Controle (Campo 18)
    termo = "Não localizado"
    m_termo = re.search(
        r"(?:18\s*-\s*)?N[º°o\.]?\s*Controle[\s\S]{0,50}?\b(\d{8,15})\b",
        txt_pdf,
        re.IGNORECASE,
    )
    if m_termo:
        termo = m_termo[1].strip()
    elif termo_alt := extrair_numero_termo_pdf(txt_pdf, nome_anexo):
        termo = termo_alt

    # Extrair CNPJ/CPF do Contribuinte (Campo 05)
    if m_doc := re.search(
        r"05\s*-\s*Inscri[çc][ãa]o\s+Estadual/CGC/CPF[\s\S]{0,50}?\b([\d\.\/-]{11,18})\b",
        txt_pdf,
        re.IGNORECASE,
    ):
        doc_guia_ap = re.sub(r"\D", "", m_doc[1])
        if termo != "Não localizado" and doc_guia_ap:
            nfe_map[f"DOC_MS_{termo}"] = doc_guia_ap

    # Extrair Código de Barras (Preservando os 48 números intactos)
    barras_orig, barras_44 = extrair_codigo_barras_pdf(txt_pdf)
    if m_barras := re.search(r"(8(?:[\s\.-]*\d){43,50})", txt_pdf):
        apenas_numeros = re.sub(r"\D", "", m_barras[1])

        if len(apenas_numeros) >= 44:
            barras_orig = apenas_numeros
            barras_44 = linha_digitavel_para_codigo_barras(apenas_numeros)

    m_venc = re.search(
        r"(?:NAO\s*RECEBER\s*AP[OÓ]S\s*[:\-]?\s*|07\s*-\s*Data\s+de\s+Vencimento[\s\S]{0,40}?)\b(\d{2}/\d{2}/\d{4})\b",
        txt_pdf,
        re.IGNORECASE,
    )
    vencimento = m_venc[1].strip() if m_venc else "Não informado"
    vencimento = padronizar_data_ddmmyyyy(vencimento)

    # Extrair Valor (Último valor em Reais)
    valor = "Não informado"
    padroes_valor_ap = [
        r"(?:14\s*-\s*TOTAL\s+A\s+RECOLHER|TOTAL\s+A\s+RECOLHER)\s*[:=-]?\s*[\n\r]*\s*(?:R\$\s*)?(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})",
        r"(?:R\$\s*)?(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})\s*(?:\r?\n)?\s*14\s*-\s*TOTAL\s+A\s+RECOLHER",
    ]
    for pat in padroes_valor_ap:
        if match := re.search(pat, txt_pdf, re.IGNORECASE):
            valor = match[1].strip()
            break

    if valor == "Não informado" and (
        valores := re.findall(r"R\$\s*(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})", txt_pdf)
    ):
        valor = valores[-1]

    # Extrair Chaves e Números NF-e (lida com chaves formatadas com espaços)
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
        num_doc = nfe_map.get(chave, formatar_numero_arquivo(chave[25:34].lstrip("0") or "0"))
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
        "AP",
    )

# ===== BLOCO ADITIVO: leitura por origem e validacao =====
MODELO_NFE = "55"
MODELO_CTE = "57"


def so_digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def modelo(chave) -> str:
    d = so_digitos(chave)
    return d[20:22] if len(d) == 44 else ""


@dataclass(frozen=True)
class CodigoBarras:
    original: str
    digitos48: str
    codigo44: str

    @property
    def blocos(self):
        return self.original.split()


def ler_codigo_barras(campo26) -> CodigoBarras:
    original = str(campo26 or "").strip()
    blocos = original.split()
    if len(blocos) != 4:
        raise ValueError(f"campo 26: esperados 4 blocos, encontrados {len(blocos)}")
    limpos = [so_digitos(b) for b in blocos]
    for i, b in enumerate(limpos, start=1):
        if len(b) != 12:
            raise ValueError(f"campo 26, bloco {i}: {len(b)} digitos, esperados 12")
    return CodigoBarras(
        original=original,
        digitos48="".join(limpos),
        codigo44="".join(b[:-1] for b in limpos),
    )


def _candidatos_44(texto) -> list:
    achados = re.findall(r"\d[\d\s.\-/]{40,80}\d", str(texto or ""))
    return [d for d in (so_digitos(b) for b in achados) if len(d) == 44]


def ler_chave_nfe(campo24) -> str:
    for d in _candidatos_44(campo24):
        if modelo(d) == MODELO_NFE:
            return d
    return ""


def conferir_origens(codigo: CodigoBarras, chave: str) -> None:
    if len(codigo.codigo44) != 44:
        raise ValueError(f"codigo de barras com {len(codigo.codigo44)} digitos")
    if len(chave) != 44:
        raise ValueError(f"chave NF-e com {len(chave)} digitos")
    if codigo.codigo44 == chave:
        raise ValueError("codigo de barras e chave NF-e iguais: leitura cruzada")
    if modelo(chave) != MODELO_NFE:
        raise ValueError(f"chave com modelo {modelo(chave)}, esperado {MODELO_NFE}")


def validar_guia(campo05, chave_guia, remetente, destinatario, chaves_remessa):
    ident = so_digitos(campo05)
    if not ident:
        return False, "INCOMPLETO: identificador ausente no campo 05"
    papeis = {
        "remetente": so_digitos(remetente),
        "destinatario": so_digitos(destinatario),
    }
    papeis = {k: v for k, v in papeis.items() if v}
    if not papeis:
        return False, "INCOMPLETO: remetente e destinatario ausentes na remessa"
    lado = next((k for k, v in papeis.items() if v == ident), None)
    if not lado:
        return False, "QUARENTENA: identificador nao consta na remessa"
    chave = so_digitos(chave_guia)
    if len(chave) != 44:
        return False, "INCOMPLETO: chave da guia nao localizada no campo 24"
    notas = {so_digitos(c) for c in chaves_remessa if modelo(c) == MODELO_NFE}
    if not notas:
        return False, "INCOMPLETO: remessa sem chave de modelo 55"
    if chave not in notas:
        return False, "QUARENTENA: chave da guia nao e de NF-e desta remessa"
    return True, f"OK: identificador ({lado}) e chave NF-e conferem"
