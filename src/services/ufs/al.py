# src/services/ufs/al.py
"""Regras exclusivas de AL. Nenhum if de outra UF aqui."""
from __future__ import annotations

import io
import re

import pypdf

from src.services.document_classifier import (
    e_dar_documento,
    extrair_codigo_barras_pdf,
    extrair_numero_termo_pdf,
    extrair_vencimento_e_valor_pdf,
)
from src.utils.text_mono import (
    formatar_numero_arquivo,
    limpar_texto_excel,
    padronizar_data_ddmmyyyy,
)

AL_CAMPOS_PLANILHA = (
    'EMITENTE - NOME/RAZÃO SOCIAL',
    'EMITENTE - CPF/CNPJ',
    'EMITENTE - IE',
    'DESTINATÁRIO - NOME/RAZÃO SOCIAL',
    'DESTINATÁRIO - CPF/CNPJ',
    'DESTINATÁRIO - IE',
)


def ordenar_pares_documento_por_aparicao(txt_pdf: str, pares_documento: list[tuple[str, str]]) -> list[tuple[str, str]]:
    if not pares_documento:
        return pares_documento

    pares_unicos = list(dict.fromkeys(pares_documento))
    posicoes = {}
    for idx, (chave, _) in enumerate(pares_unicos):
        if chave and chave != "Sem Arquivo Válido":
            posicoes[(chave, idx)] = txt_pdf.find(chave)

    def chave_ordem(item: tuple[str, str]) -> tuple[int, int]:
        chave, _ = item
        if chave and chave != "Sem Arquivo Válido":
            pos = txt_pdf.find(chave)
            if pos >= 0:
                return (0, pos)
        return (1, 10**9)

    return sorted(pares_unicos, key=chave_ordem)


def _extrair_campos_al_pdf(pdf_bytes: bytes | None) -> dict[str, str]:
    if not pdf_bytes:
        return {}

    page = pypdf.PdfReader(io.BytesIO(pdf_bytes), strict=False).pages[0]
    elementos = []

    def capturar_texto(texto, cm, tm, font_dict, font_size):
        del cm, font_dict, font_size
        texto_limpo = ' '.join(str(texto).split())
        if texto_limpo:
            elementos.append((float(tm[4]), float(tm[5]), texto_limpo))

    page.extract_text(visitor_text=capturar_texto)
    campos = {}
    rotulos_partes = (
        ('EMITENTE', re.compile(r'^Emitente$', re.IGNORECASE)),
        ('DESTINATÁRIO', re.compile(r'^Destinat', re.IGNORECASE)),
        ('TRANSPORTADOR', re.compile(r'^Transportador$', re.IGNORECASE)),
    )
    cabecalhos_partes = sorted(
        (
            (y, nome)
            for _, y, texto in elementos
            for nome, padrao in rotulos_partes
            if padrao.search(texto)
        ),
        reverse=True,
    )

    for indice, (y_cabecalho, nome_parte) in enumerate(cabecalhos_partes):
        y_limite_inferior = (
            cabecalhos_partes[indice + 1][0]
            if indice + 1 < len(cabecalhos_partes)
            else y_cabecalho - 38
        )
        itens_linha = [
            (x, y, texto)
            for x, y, texto in elementos
            if y_limite_inferior < y < y_cabecalho
            and y_cabecalho - y <= 32
        ]

        nomes = [
            texto for x, _, texto in itens_linha
            if x < 250
            and re.search(r'[A-Za-zÀ-ÿ]{2}', texto)
            and not re.search(
                r'Raz[aã]o Social|CPF/CNPJ|^IE$|^Emitente$|^Destinat|^Transportador$',
                texto,
                re.IGNORECASE,
            )
        ]
        documentos = [
            (x, re.sub(r'\D', '', texto))
            for x, _, texto in itens_linha
            if x >= 250
            and re.search(r'\d', texto)
            and not re.search(r'CPF/CNPJ|Raz[aã]o Social', texto, re.IGNORECASE)
        ]
        documentos = [
            (x, valor)
            for x, valor in documentos
            if 5 <= len(re.sub(r'\D', '', valor)) <= 18
        ]

        prefixo = nome_parte
        if nomes:
            campos[f'{prefixo} - NOME/RAZÃO SOCIAL'] = max(
                nomes, key=lambda nome: len(nome)
            ).strip()

        documentos_fiscais = [
            valor for x, valor in documentos if 250 <= x < 430
        ]
        inscricoes_estaduais = [
            valor for x, valor in documentos if x >= 430
        ]
        if documentos_fiscais:
            campos[f'{prefixo} - CPF/CNPJ'] = documentos_fiscais[0]
        if inscricoes_estaduais:
            campos[f'{prefixo} - IE'] = inscricoes_estaduais[0]

    rotulos_nome_guia = [
        (y, x)
        for x, y, texto in elementos
        if re.search(r'Nome\s*/\s*Raz[aã]o Social', texto, re.IGNORECASE)
    ]
    if rotulos_nome_guia:
        y_rotulo, x_rotulo = max(rotulos_nome_guia)
        nomes_guia = [
            texto for x, y, texto in elementos
            if x >= x_rotulo
            and x < 250
            and 0 < y_rotulo - y <= 20
            and re.search(r'[A-Za-zÀ-ÿ]{2}', texto)
            and not re.search(r'Nome\s*/\s*Raz[aã]o Social', texto, re.IGNORECASE)
        ]
        if nomes_guia:
            campos['GUIA - NOME/RAZÃO SOCIAL'] = min(
                nomes_guia, key=lambda nome: len(nome)
            ).strip()

    inscricoes_caceal = []
    inscricoes_guia = []
    rotulos_inscricao = [
        (x, y)
        for x, y, texto in elementos
        if re.fullmatch(r'Inscri.{0,3}o', texto.strip(), re.IGNORECASE)
    ]
    for x_rotulo, y_rotulo in rotulos_inscricao:
        for x, y, texto in elementos:
            distancia_vertical = y_rotulo - y
            if not (0 < distancia_vertical <= 22 and abs(x - x_rotulo) <= 45):
                continue

            match_inscricao = re.search(
                r'(?:CACEAL|CNPJ\s*/\s*CPF|CPF\s*/\s*CNPJ|CNPJ|CPF|IE|'
                r'INSCRI[ÇC][ÃA]O(?:\s+ESTADUAL)?)\s*[:=-]?\s*'
                r'([\d][\d./-]{4,24})',
                texto,
                re.IGNORECASE,
            )
            if match_inscricao:
                valor_inscricao = match_inscricao.group(1).strip()
                inscricoes_guia.append((distancia_vertical, valor_inscricao))
                if re.search(r'CACEAL', texto, re.IGNORECASE):
                    inscricoes_caceal.append((y, valor_inscricao))

    if not inscricoes_guia:
        inscricoes_guia = [
            (0, re.sub(r'\D', '', match.group(1)))
            for _, _, texto in elementos
            if (match := re.search(
                r'(?:CNPJ\s*/\s*CPF|CPF\s*/\s*CNPJ|CNPJ|CPF|IE|'
                r'INSCRI[ÇC][ÃA]O(?:\s+ESTADUAL)?)\s*[:=-]?\s*'
                r'([\d][\d./-]{4,24})',
                texto,
                re.IGNORECASE,
            ))
        ]

    if inscricoes_guia:
        campos['GUIA - INSCRIÇÃO (CPF/CNPJ/IE)'] = min(
            inscricoes_guia, key=lambda inscricao: inscricao[0]
        )[1]
    if inscricoes_caceal:
        campos['GUIA - INSCRIÇÃO CACEAL'] = max(inscricoes_caceal)[1]

    return campos


def _extrair_regras_al(
    txt_pdf: str,
    nome_anexo: str,
    nfe_map: dict,
    pdf_bytes: bytes | None = None,
):
    is_dar = e_dar_documento(txt_pdf)
    termo = extrair_numero_termo_pdf(txt_pdf, nome_anexo) or "Não localizado"
    if termo != "Não localizado":
        campos_al = _extrair_campos_al_pdf(pdf_bytes)
        if campos_al:
            nfe_map.setdefault(f"AL_CAMPOS_{termo}", {}).update(campos_al)
            inscricao_guia = re.sub(
                r'\D', '',
                campos_al.get('GUIA - INSCRIÇÃO (CPF/CNPJ/IE)', '')
                or campos_al.get('GUIA - INSCRIÇÃO CACEAL', '')
            )
            if inscricao_guia:
                nfe_map[f"DOC_MS_{termo}"] = inscricao_guia
    barras_orig, barras_44 = extrair_codigo_barras_pdf(txt_pdf)
    vencimento, valor = extrair_vencimento_e_valor_pdf(txt_pdf)
    vencimento = padronizar_data_ddmmyyyy(vencimento)

    doc_guia_al = ""
    m_doc_al = re.search(
        r'(?:CACEAL|CNPJ\s*/\s*CPF|CPF\s*/\s*CNPJ|CNPJ|CPF|I\.?E\.?|'
        r'INSCRI[ÇC][ÃA]O\s*(?:ESTADUAL)?(?:\s*/\s*CNPJ)?)'
        r'\s*[:=-]?\s*([\d\.\/-]{5,25})',
        txt_pdf,
        re.IGNORECASE,
    )
    if m_doc_al and not nfe_map.get(f"DOC_MS_{termo}"):
        doc_guia_al = re.sub(r'\D', '', m_doc_al.group(1))
        if termo != "Não localizado":
            nfe_map[f"DOC_MS_{termo}"] = doc_guia_al

    pares_documento = []
    chaves_usadas = []
    numeros_usados = []

    chaves_termo_al = []
    for match in re.finditer(r'\b\d{44}\b', txt_pdf):
        chave = match.group(0)
        if chave == barras_44 or chave.startswith('8'):
            continue
        if chave not in chaves_termo_al:
            chaves_termo_al.append(chave)

    termo_limpo = re.sub(r'\D', '', str(termo or ''))

    sec_match = re.search(r'Documentos\b([\s\S]*?)(?:Infra[çc][õo]es|Total\b|Autuado\b|FISCAIS\s+AUTUANTES|$)', txt_pdf, re.IGNORECASE)
    trecho_alvo = sec_match.group(1) if sec_match else txt_pdf

    numeros_termo_al = []
    padroes_numero_al = [
        re.compile(r'(?i)\b(?:DANFE|CT-?E|NF-?E|CTE|NFE|DOCUMENTO)\b[^\d\n\r]*?(?:\b\d{44}\b[^\d\n\r]*?)?(\d{1,9})\b'),
        re.compile(r'(?i)\b(?:NF|NOTA\s*FISCAL|NOTA)\s*[:=-]?\s*(\d{1,9})\b'),
    ]
    for padrao in padroes_numero_al:
        for match in padrao.finditer(trecho_alvo):
            num_raw = match.group(1).strip()
            if termo != "Não localizado" and num_raw == termo_limpo:
                continue
            num_fmt = formatar_numero_arquivo(num_raw)
            if num_fmt != "Sem Número" and num_fmt not in numeros_termo_al:
                numeros_termo_al.append(num_fmt)

    notas_termo_al = []
    if not is_dar:
        for match in re.finditer(r'(?i)\b(?:DANFE|NF-?E|NFE|NF|NOTA)\s*[:=-]?\s*(\d{1,9})\b', txt_pdf):
            num_raw = match.group(1).strip()
            if termo != "Não localizado" and num_raw == termo_limpo:
                continue
            n_fmt = formatar_numero_arquivo(num_raw)
            if n_fmt != "Sem Número" and n_fmt not in numeros_termo_al and n_fmt not in notas_termo_al:
                notas_termo_al.append(n_fmt)

    numeros_ordenados = numeros_termo_al or notas_termo_al

    if chaves_termo_al or numeros_ordenados:
        total_itens = max(len(chaves_termo_al), len(numeros_ordenados))
        for idx in range(total_itens):
            chave = chaves_termo_al[idx] if idx < len(chaves_termo_al) else "Sem Arquivo Válido"
            num_doc = numeros_ordenados[idx] if idx < len(numeros_ordenados) else ""
            if chave != "Sem Arquivo Válido" and not num_doc:
                num_doc = nfe_map.get(chave, "Sem Número")
            if chave == "Sem Arquivo Válido" and not num_doc:
                continue
            chave_armazenada = chave if chave != "Sem Arquivo Válido" else f"Sem Arquivo Válido::{idx}"
            if chave_armazenada not in chaves_usadas:
                pares_documento.append((chave_armazenada, num_doc or "Sem Número"))
                chaves_usadas.append(chave_armazenada)
                if num_doc and num_doc != "Sem Número":
                    numeros_usados.append(num_doc)

    outras_chaves = []
    for ch in re.findall(r'\b(\d{44})\b', txt_pdf):
        if ch != barras_44 and ch not in chaves_usadas and ch not in outras_chaves and not ch.startswith('8'):
            outras_chaves.append(ch)

    max_len = max(len(outras_chaves), len(notas_termo_al))
    for idx in range(max_len):
        chave = outras_chaves[idx] if idx < len(outras_chaves) else "Sem Arquivo Válido"
        num_doc = notas_termo_al[idx] if idx < len(notas_termo_al) else ""

        if chave != "Sem Arquivo Válido" and not num_doc:
            num_doc = nfe_map.get(chave, "Sem Número")

        if chave == "Sem Arquivo Válido" and not num_doc:
            continue
        chave_armazenada = chave if chave != "Sem Arquivo Válido" else f"Sem Arquivo Válido::{idx}"
        if chave_armazenada not in chaves_usadas:
            pares_documento.append((chave_armazenada, num_doc or "Sem Número"))
            chaves_usadas.append(chave_armazenada)

    pares_documento = ordenar_pares_documento_por_aparicao(txt_pdf, pares_documento)

    return termo, list(dict.fromkeys(pares_documento)), barras_orig, barras_44, vencimento, valor, 'AL'