"""Helpers puros para preparar PDFs e referencias extraidos de tickets Zendesk."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, TypeAlias

from src.services.attachment_service import (
    calcular_hash_md5,
    determinar_quarentena_al,
    limpar_nome_anexo,
    propagar_vencimento_dar_ap,
    salvar_anexos_processados,
)

PDFExtraido: TypeAlias = tuple[str, str, bytes]
ComentarioZendesk: TypeAlias = Mapping[str, Any]
RegistroZendesk: TypeAlias = tuple[Any, ...]


@dataclass(frozen=True)
class ResultadoProcessamentoPDFTicket:
    tem_dar_pdf: bool
    tem_termo_pdf: bool


@dataclass(frozen=True)
class ResultadoTicketPlanilha:
    data_ticket: str
    uf_ticket: str
    registros: list[RegistroZendesk]
    status_conf: str
    mapa_termo_cte: dict[str, list[str]]
    lista_ctes_ordenada: list[str]
    nfe_map: dict[str, Any]


@dataclass(frozen=True)
class ResultadoAnexosTicket:
    anexos: list[Any]
    em_quarentena: bool
    motivo_quarentena: str | None


def agregar_registros_ticket(
    ticket_id: str,
    data_ticket: str,
    registros: Sequence[RegistroZendesk],
    termos_map: dict[str, dict[str, Any]],
    mapa_termo_cte: Mapping[str, list[str]],
    lista_ctes_ordenada: Sequence[str],
    nfe_map: Mapping[str, Any],
    status_conf: str,
    *,
    campos_al: Sequence[str],
    limpar_texto: Callable[[Any], str],
    formatar_numero: Callable[[str], str],
    padronizar_data: Callable[[Any], str],
    marcar_ap_processada: Callable[[str], str],
) -> None:
    """Agrupa os registros do ticket por termo/chave, preservando regras AP/AL."""
    mapa_chaves_termo_ap = {}
    for termo, pares, _, _, _, _, uf, _ in registros:
        if uf == "AP" and termo and termo != "Não localizado":
            for chave, _ in pares:
                if chave and chave != "Sem Arquivo Válido":
                    mapa_chaves_termo_ap[chave] = termo

    controles_ap = {
        str(registro[0])
        for registro in registros
        if registro[6] == "AP" and registro[0] and registro[0] != "Não localizado"
    }
    controles_al = {
        str(registro[0])
        for registro in registros
        if registro[6] == "AL" and registro[0] and registro[0] != "Não localizado"
    }
    indice_guia_ap = 0
    for indice, registro in enumerate(registros):
        (
            termo_pdf,
            pares,
            codigo_barras_original,
            codigo_barras,
            vencimento,
            valor,
            uf,
            status_item,
        ) = registro

        if uf == "AP" and (not termo_pdf or termo_pdf == "Não localizado"):
            for chave, _ in pares:
                if chave in mapa_chaves_termo_ap:
                    termo_pdf = mapa_chaves_termo_ap[chave]
                    break

        ctes_associados = list(mapa_termo_cte.get(termo_pdf, []))
        if uf == "AP":
            if len(controles_ap) == 1 and lista_ctes_ordenada:
                ctes_associados = list(lista_ctes_ordenada)
            elif not ctes_associados and indice_guia_ap < len(lista_ctes_ordenada):
                ctes_associados = [lista_ctes_ordenada[indice_guia_ap]]
            indice_guia_ap += 1
        elif uf == "AL":
            if len(controles_al) == 1 and lista_ctes_ordenada:
                ctes_associados = list(lista_ctes_ordenada)
            elif not ctes_associados and indice < len(lista_ctes_ordenada):
                ctes_associados = [lista_ctes_ordenada[indice]]
            ctes_unicos = list(dict.fromkeys(ctes_associados))
            ordem_cte_ticket = {cte: posicao for posicao, cte in enumerate(lista_ctes_ordenada)}
            ctes_associados = sorted(
                ctes_unicos,
                key=lambda cte: ordem_cte_ticket.get(cte, len(ordem_cte_ticket)),
            )
        elif not ctes_associados and indice < len(lista_ctes_ordenada):
            ctes_associados = [lista_ctes_ordenada[indice]]

        if uf == "AP":
            chave_nfe_ap = next(
                (chave for chave, _ in pares if chave and chave != "Sem Arquivo Válido"),
                None,
            )
            if chave_nfe_ap:
                chave_linha = f"AP::{termo_pdf}::{chave_nfe_ap}"
            elif termo_pdf and termo_pdf != "Não localizado":
                chave_linha = f"AP::{termo_pdf}::{indice}"
            else:
                chave_linha = f"AP::{ticket_id}::Linha_{indice}"
        else:
            chave_linha = termo_pdf

        if (
            uf == "AP"
            and chave_linha in termos_map
            and ticket_id not in termos_map[chave_linha].get("TICKET", [])
            and any(
                str(valor_uf).strip().upper() == "AP"
                for valor_uf in termos_map[chave_linha].get("UF", [])
            )
        ):
            status_item = marcar_ap_processada(
                str(termos_map[chave_linha].get("STATUS CONFERÊNCIA", status_item or "OK"))
            )

        if chave_linha not in termos_map:
            termos_map[chave_linha] = {
                "TERMO_REAL": termo_pdf,
                "TICKET": [],
                "UF": [],
                "DATA": [],
                "VENCIMENTO": [],
                "VALOR": [],
                "CTE": [],
                "CHAVE ARQUIVO": [],
                "DACTE": [],
                "NÚMERO ARQUIVO": [],
                "CODIGO BARRAS ORIGINAL": [],
                "CODIGO BARRAS": [],
                "CPF/CNPJ DA GUIA": [],
                **{campo: [] for campo in campos_al},
                "STATUS CONFERÊNCIA": status_item or status_conf,
            }
        dados_linha = termos_map[chave_linha]
        for cte in ctes_associados:
            if cte not in dados_linha["CTE"]:
                dados_linha["CTE"].append(cte)

        documento_guia = nfe_map.get(f"DOC_MS_{termo_pdf}", "")
        if documento_guia and documento_guia not in dados_linha["CPF/CNPJ DA GUIA"]:
            dados_linha["CPF/CNPJ DA GUIA"].append(documento_guia)

        if uf == "AL":
            campos_al_termo = nfe_map.get(f"AL_CAMPOS_{termo_pdf}", {})
            for campo in campos_al:
                valor_campo = limpar_texto(campos_al_termo.get(campo, ""))
                if valor_campo and valor_campo not in dados_linha[campo]:
                    dados_linha[campo].append(valor_campo)

        dados_linha["TICKET"].append(ticket_id)
        dados_linha["UF"].append(uf)
        dados_linha["DATA"].append(data_ticket)
        dados_linha["STATUS CONFERÊNCIA"] = status_item or status_conf
        if vencimento != "Não informado":
            dados_linha["VENCIMENTO"].append(padronizar_data(vencimento))
        if valor != "Não informado":
            dados_linha["VALOR"].append(valor)
        if codigo_barras_original not in ("Sem Código", "Sem Código de Barras"):
            dados_linha["CODIGO BARRAS ORIGINAL"].append(codigo_barras_original)
        if codigo_barras not in ("Sem Código", "Sem Código de Barras"):
            dados_linha["CODIGO BARRAS"].append(codigo_barras)

        for chave, numero_documento in pares:
            chave_limpa = re.sub(r"\D", "", str(chave or ""))
            if len(chave_limpa) == 44:
                modelo = chave_limpa[20:22]
                campo_chaves = "DACTE" if modelo == "57" else "CHAVE ARQUIVO"
                if chave_limpa not in dados_linha[campo_chaves]:
                    dados_linha[campo_chaves].append(chave_limpa)

            numero_formatado = formatar_numero(numero_documento)
            if (
                numero_formatado not in dados_linha["NÚMERO ARQUIVO"]
                and numero_formatado != "Sem Número"
            ):
                dados_linha["NÚMERO ARQUIVO"].append(numero_formatado)


def mapear_chaves_nfe_pdf(
    texto: str,
    conteudo: bytes,
    obter_chaves: Callable[[str, bytes | None], list[str]],
    formatar_numero: Callable[[str], str],
) -> dict[str, str]:
    """Monta o mapa chave NF-e -> número de nota usado pelos leitores de guias."""
    match_nota = re.search(r"NF-e[\s\n\r]+N[ºo\.]*\s*([\d\.]+)", texto, re.IGNORECASE)
    match_alternativo = None
    if not match_nota:
        match_alternativo = re.search(
            r"N[ºo\.]*\s*(\d{3}\.\d{3}\.\d{3}|\d{1,9})", texto, re.IGNORECASE
        )
    numero_nota = (
        match_nota.group(1).strip()
        if match_nota
        else (match_alternativo.group(1).strip() if match_alternativo else "")
    )
    if numero_nota:
        numero_nota = formatar_numero(numero_nota)
    return {chave: numero_nota for chave in obter_chaves(texto, conteudo)}


def processar_guias_ap_ticket(
    texto_pdf: str,
    nome_anexo: str,
    nfe_map: dict[str, Any],
    registros: list[tuple[Any, ...]],
    ids_guias_ap: set[str],
    indices_guias_ap: dict[str, list[int]],
    historico_termos: Mapping[str, Any],
    *,
    separar_guias: Callable[[str], list[tuple[str | None, str]]],
    extrair_documento: Callable[..., tuple[Any, Any, Any, Any, Any, Any, Any]],
    validar_guia: Callable[..., tuple[bool, str]],
    marcar_processada: Callable[[str], str],
    padronizar_data: Callable[[Any], str],
    resumir_nfe_map: Callable[[dict[str, Any]], str],
    ao_log: Callable[[str, str], None],
) -> None:
    """Extrai e valida guias AP, preservando a detecção de duplicatas do lote."""
    for id_guia, bloco_guia in separar_guias(texto_pdf):
        repetida_no_lote = bool(id_guia and id_guia in ids_guias_ap)
        historico_ap = historico_termos.get(id_guia or "")
        if id_guia:
            ids_guias_ap.add(id_guia)
        if repetida_no_lote:
            for indice_linha in indices_guias_ap.get(id_guia, []):
                linha_existente = registros[indice_linha]
                registros[indice_linha] = (
                    *linha_existente[:7],
                    marcar_processada(linha_existente[7]),
                )
            continue

        (
            termo,
            pares,
            codigo_barras_original,
            codigo_barras,
            vencimento,
            valor,
            uf,
        ) = extrair_documento("AP", bloco_guia, nome_anexo, nfe_map)
        ok, status = validar_guia(pares, bloco_guia, nfe_map)
        ao_log(
            "INFO",
            "AP-guia: ok=%s motivo=%s nfe_map=%s" % (ok, status, resumir_nfe_map(nfe_map)),
        )
        if historico_ap:
            status = marcar_processada(status)

        pares_ap = pares or [("Sem Arquivo Válido", "Sem Número")]
        indices_linhas_ap = []
        for par in pares_ap:
            registro = (
                termo,
                [par],
                codigo_barras_original,
                codigo_barras,
                padronizar_data(vencimento),
                valor,
                uf,
                status,
            )
            registros.append(registro)
            indices_linhas_ap.append(len(registros) - 1)
        if id_guia:
            indices_guias_ap[id_guia] = indices_linhas_ap


def processar_pdfs_ticket(
    pdfs: Sequence[PDFExtraido],
    uf_ticket: str,
    nfe_map: dict[str, Any],
    registros: list[RegistroZendesk],
    mapa_termo_cte: MutableMapping[str, list[str]],
    lista_ctes_ordenada: list[str],
    ids_guias_ap: set[str],
    indices_guias_ap: dict[str, list[int]],
    historico_termos: Mapping[str, Any],
    *,
    identificar_uf: Callable[[str], str],
    eh_nota_fiscal: Callable[[str, str], bool],
    eh_dar: Callable[[str], bool],
    eh_termo: Callable[[str], bool],
    obter_chaves_nfe: Callable[[str, bytes | None], list[str]],
    formatar_numero: Callable[[str], str],
    separar_guias_ap: Callable[[str], list[tuple[str | None, str]]],
    extrair_documento: Callable[..., tuple[Any, Any, Any, Any, Any, Any, Any]],
    validar_guia_ap: Callable[..., tuple[bool, str]],
    marcar_ap_processada: Callable[[str], str],
    padronizar_data: Callable[[Any], str],
    resumir_nfe_map: Callable[[dict[str, Any]], str],
    ao_log: Callable[[str, str], None],
    identificar_layout: Callable[..., Mapping[str, Any] | None],
) -> ResultadoProcessamentoPDFTicket:
    """Classifica e extrai documentos de um ticket sem depender da interface."""
    tem_dar_pdf = False
    tem_termo_pdf = False

    for nome_anexo, texto, conteudo in pdfs:
        uf_pdf = identificar_uf(texto)
        if uf_pdf == "GERAL":
            uf_pdf = uf_ticket

        if eh_dar(texto):
            tem_dar_pdf = True
        if eh_termo(texto):
            tem_termo_pdf = True

        eh_nfe_ap = (uf_pdf == "AP" or uf_ticket == "AP") and any(
            marcador in texto.upper()
            for marcador in ("DOCUMENTO AUXILIAR DA NOTA", "DANFE", "RECEBEMOS DE")
        )
        if eh_nota_fiscal(texto, nome_anexo) or eh_nfe_ap:
            nfe_map.update(
                mapear_chaves_nfe_pdf(texto, conteudo, obter_chaves_nfe, formatar_numero)
            )
            continue

        if uf_pdf == "AP":
            processar_guias_ap_ticket(
                texto,
                nome_anexo,
                nfe_map,
                registros,
                ids_guias_ap,
                indices_guias_ap,
                historico_termos,
                separar_guias=separar_guias_ap,
                extrair_documento=extrair_documento,
                validar_guia=validar_guia_ap,
                marcar_processada=marcar_ap_processada,
                padronizar_data=padronizar_data,
                resumir_nfe_map=resumir_nfe_map,
                ao_log=ao_log,
            )
            continue

        dados_layout = identificar_layout(texto, nome_anexo, pdf_bytes=conteudo)
        if dados_layout and uf_pdf not in ("AL", "AP", "AC", "MS"):
            termo = dados_layout.get("termo") or "Não localizado"
            codigo_barras_original = dados_layout.get("cod_barras_orig", "Sem Código")
            codigo_barras = dados_layout.get("cod_barras", "Sem Código")
            vencimento = padronizar_data(dados_layout.get("vencimento", "Não informado"))
            valor = dados_layout.get("valor", "Não informado")
            pares = dados_layout.get("pares_documento", [])
            uf_layout = dados_layout.get("uf", uf_pdf)

            cte = dados_layout.get("cte")
            if cte and cte not in lista_ctes_ordenada:
                lista_ctes_ordenada.append(cte)
                mapa_termo_cte.setdefault(termo, []).append(cte)

            registros.append(
                (
                    termo,
                    pares,
                    codigo_barras_original,
                    codigo_barras,
                    vencimento,
                    valor,
                    uf_layout,
                    "OK",
                )
            )
            continue

        termo, pares, barras_orig, barras, vencimento, valor, uf_resultado = extrair_documento(
            uf_pdf, texto, nome_anexo, nfe_map, conteudo
        )
        registros.append(
            (
                termo,
                pares,
                barras_orig,
                barras,
                padronizar_data(vencimento),
                valor,
                uf_resultado,
                "OK",
            )
        )

    return ResultadoProcessamentoPDFTicket(tem_dar_pdf, tem_termo_pdf)


def processar_ticket_para_planilha(
    ticket_id: str,
    ticket: Mapping[str, Any],
    comentarios: Sequence[ComentarioZendesk],
    historico_termos: Mapping[str, Any],
    *,
    padronizar_data: Callable[[str], str],
    identificar_uf: Callable[[Mapping[str, Any] | None, str], str],
    baixar_conteudo: Callable[[str], tuple[bytes | None, str]],
    extrair_texto: Callable[[bytes], tuple[str, str]],
    eh_nota_fiscal: Callable[[str, str], bool],
    eh_dar: Callable[[str], bool],
    eh_termo: Callable[[str], bool],
    extrair_remessas_ap: Callable[[str], list[str]],
    obter_chaves_nfe: Callable[[str, bytes | None], list[str]],
    formatar_numero: Callable[[str], str],
    separar_guias_ap: Callable[[str], list[tuple[str | None, str]]],
    extrair_documento: Callable[..., tuple[Any, Any, Any, Any, Any, Any, Any]],
    validar_guia_ap: Callable[..., tuple[bool, str]],
    marcar_ap_processada: Callable[[str], str],
    resumir_nfe_map: Callable[[dict[str, Any]], str],
    ao_log: Callable[[str, str], None],
    identificar_layout: Callable[..., Mapping[str, Any] | None],
) -> ResultadoTicketPlanilha:
    """Executa a extração e classificação dos PDFs de um ticket para a planilha."""
    data_ticket = padronizar_data(str(ticket.get("created_at", ""))[:10])
    texto_completo = str(ticket.get("description", ""))
    uf_ticket_tag = identificar_uf(ticket, "")

    pdfs = extrair_pdfs_dos_comentarios(comentarios, baixar_conteudo, extrair_texto)
    pdfs = ordenar_pdfs_nota_primeiro(pdfs, eh_nota_fiscal)
    uf_ticket = determinar_uf_ticket(
        pdfs,
        uf_ticket_tag,
        lambda texto: identificar_uf(None, texto),
    )
    mapa_termo_cte, lista_ctes_ordenada = mapear_termo_cte_ticket(
        texto_completo, uf_ticket, extrair_remessas_ap
    )

    nfe_map: dict[str, Any] = {}
    registros: list[RegistroZendesk] = []
    resultado_pdfs = processar_pdfs_ticket(
        pdfs,
        uf_ticket,
        nfe_map,
        registros,
        mapa_termo_cte,
        lista_ctes_ordenada,
        set(),
        {},
        historico_termos,
        identificar_uf=lambda texto: identificar_uf(None, texto),
        eh_nota_fiscal=eh_nota_fiscal,
        eh_dar=eh_dar,
        eh_termo=eh_termo,
        obter_chaves_nfe=obter_chaves_nfe,
        formatar_numero=formatar_numero,
        separar_guias_ap=separar_guias_ap,
        extrair_documento=extrair_documento,
        validar_guia_ap=validar_guia_ap,
        marcar_ap_processada=marcar_ap_processada,
        padronizar_data=padronizar_data,
        resumir_nfe_map=resumir_nfe_map,
        ao_log=ao_log,
        identificar_layout=identificar_layout,
    )

    status_conf = "OK"
    if uf_ticket == "AL":
        if resultado_pdfs.tem_dar_pdf and not resultado_pdfs.tem_termo_pdf:
            status_conf = "INCOMPLETO: Falta Termo"
        elif resultado_pdfs.tem_termo_pdf and not resultado_pdfs.tem_dar_pdf:
            status_conf = "INCOMPLETO: Falta Guia (DAR)"

    return ResultadoTicketPlanilha(
        data_ticket,
        uf_ticket,
        registros,
        status_conf,
        dict(mapa_termo_cte),
        lista_ctes_ordenada,
        nfe_map,
    )


def processar_e_agregar_ticket_para_planilha(
    ticket_id: str,
    ticket: Mapping[str, Any],
    comentarios: Sequence[ComentarioZendesk],
    historico_termos: Mapping[str, Any],
    termos_map: dict[str, dict[str, Any]],
    *,
    opcoes_processamento: Mapping[str, Any],
    lock_termos: Any,
    campos_al: Sequence[str],
    limpar_texto: Callable[[Any], str],
    formatar_numero: Callable[[str], str],
    padronizar_data: Callable[[Any], str],
    marcar_ap_processada: Callable[[str], str],
) -> None:
    """Processa um ticket e incorpora os registros ao relatório compartilhado."""
    resultado = processar_ticket_para_planilha(
        ticket_id,
        ticket,
        comentarios,
        historico_termos,
        **opcoes_processamento,
    )
    with lock_termos:
        agregar_registros_ticket(
            ticket_id,
            resultado.data_ticket,
            resultado.registros,
            termos_map,
            resultado.mapa_termo_cte,
            resultado.lista_ctes_ordenada,
            resultado.nfe_map,
            resultado.status_conf,
            campos_al=campos_al,
            limpar_texto=limpar_texto,
            formatar_numero=formatar_numero,
            padronizar_data=padronizar_data,
            marcar_ap_processada=marcar_ap_processada,
        )


def coletar_anexos_ticket(
    ticket: Mapping[str, Any],
    comentarios: Sequence[ComentarioZendesk],
    ticket_id: str,
) -> list[Mapping[str, Any]]:
    """Combina links da descrição e anexos de comentários na ordem atual do fluxo."""
    anexos: list[Mapping[str, Any]] = []
    if "description" in ticket:
        for url in re.findall(
            r'https?://[^\s<>"]+attachment[^\s<>"]+', ticket["description"]
        ):
            anexos.append({"file_name": f"anexo_{ticket_id}.pdf", "content_url": url})

    for comentario in comentarios:
        anexos.extend(comentario.get("attachments", []))
    return anexos


def extrair_pdfs_dos_comentarios(
    comentarios: Sequence[ComentarioZendesk],
    baixar_conteudo: Callable[[str], tuple[bytes | None, str]],
    extrair_texto: Callable[[bytes], tuple[str, str]],
) -> list[PDFExtraido]:
    """Baixa e extrai anexos PDF dos comentários, ignorando downloads sem conteúdo."""
    pdfs: list[PDFExtraido] = []
    for comentario in comentarios:
        for anexo_item in comentario.get("attachments", []):
            nome_anexo = str(anexo_item["file_name"]).lower()
            if not nome_anexo.endswith(".pdf"):
                continue
            conteudo, _status_download = baixar_conteudo(anexo_item["content_url"])
            if not conteudo:
                continue
            texto, _status_extracao = extrair_texto(conteudo)
            pdfs.append((nome_anexo, texto, conteudo))
    return pdfs


def ordenar_pdfs_nota_primeiro(
    pdfs: Sequence[PDFExtraido],
    eh_nota_fiscal: Callable[[str, str], bool],
) -> list[PDFExtraido]:
    """Ordena PDFs de notas fiscais antes dos demais, mantendo a ordem original."""
    return sorted(pdfs, key=lambda pdf: 0 if eh_nota_fiscal(pdf[1], pdf[0]) else 1)


def analisar_anexo_baixado(
    ticket_id: str,
    nome_anexo: str,
    conteudo: bytes,
    uf_ticket: str,
    duplicado: bool,
    *,
    extrair_texto: Callable[[bytes], tuple[str, str]],
    identificar_uf: Callable[[str], str],
    identificar_layout: Callable[..., Mapping[str, Any] | None],
    eh_dar: Callable[[str], bool],
    eh_termo: Callable[[str], bool],
    eh_nota_fiscal: Callable[[str, str], bool],
    extrair_vencimento_valor: Callable[[str], tuple[str, str]],
    padronizar_data: Callable[[Any], str],
    documento_vencido: Callable[[str], bool],
    extrair_vencimento_nota: Callable[[str], str],
) -> dict[str, Any]:
    """Classifica um anexo baixado e prepara os campos usados na organização."""
    nome_limpo = limpar_nome_anexo(nome_anexo)
    uf_final = "GERAL"
    subpasta = "OUTROS"
    is_dar = False
    is_termo = False
    is_nota = False
    vencimento_dar = "Não informado"
    texto_anexo = ""

    if nome_limpo.lower().endswith(".pdf"):
        texto_anexo, _status_pdf = extrair_texto(conteudo)

        uf_pdf = identificar_uf(texto_anexo)
        if uf_pdf != "GERAL":
            uf_final = uf_pdf
        else:
            dados_layout = identificar_layout(texto_anexo, nome_limpo, pdf_bytes=conteudo)
            if dados_layout and dados_layout.get("uf") and dados_layout.get("uf") != "GERAL":
                uf_final = dados_layout["uf"]
            else:
                uf_final = uf_ticket if uf_ticket != "GERAL" else "AL"

        is_dar = eh_dar(texto_anexo)
        is_termo = eh_termo(texto_anexo)
        is_nota = eh_nota_fiscal(texto_anexo, nome_limpo)

        if re.search(
            r"AMAP[AÁ]|GOVERNO\s+DO\s+ESTADO\s+DO\s+AMAP[AÁ]",
            texto_anexo,
            re.IGNORECASE,
        ):
            uf_final = "AP"

        if uf_final == "AP":
            eh_danfe_ap = any(
                marcador in texto_anexo.upper()
                for marcador in ("DOCUMENTO AUXILIAR DA NOTA", "DANFE", "RECEBEMOS DE")
            )
            if eh_danfe_ap:
                is_nota = True
                is_dar = False
                is_termo = False
                subpasta = "NOTAS"
            else:
                is_nota = False
                is_dar = True
                subpasta = "DAR"

        if is_nota:
            subpasta = "NOTAS" if uf_final == "AP" else "NOTA"
        elif is_dar:
            subpasta = "DAR"
            vencimento, _valor = extrair_vencimento_valor(texto_anexo)
            vencimento_dar = padronizar_data(vencimento)
            dados_layout = identificar_layout(texto_anexo, nome_limpo, pdf_bytes=conteudo)
            if (
                dados_layout
                and dados_layout.get("vencimento")
                and dados_layout.get("vencimento") != "Não informado"
            ):
                vencimento_dar = padronizar_data(dados_layout.get("vencimento"))
        elif is_termo:
            subpasta = "TERMO"
        else:
            subpasta = "PDFs_GERAIS"
    else:
        uf_final = uf_ticket if uf_ticket != "GERAL" else "AL"

    is_vencido = False
    if uf_final == "AP":
        if is_dar and vencimento_dar != "Não informado":
            is_vencido = documento_vencido(vencimento_dar)
    elif is_dar and vencimento_dar != "Não informado":
        is_vencido = documento_vencido(vencimento_dar)
    elif is_nota:
        vencimento_nota = extrair_vencimento_nota(texto_anexo)
        is_vencido = documento_vencido(vencimento_nota)

    return {
        "tid": ticket_id,
        "nome_limpo": nome_limpo,
        "conteudo": conteudo,
        "uf_final": uf_final,
        "subpasta": subpasta,
        "is_dar": is_dar,
        "is_termo": is_termo,
        "is_nota": is_nota,
        "is_duplicado": duplicado,
        "is_vencido": is_vencido,
        "vencimento_dar": vencimento_dar,
    }


def baixar_e_analisar_anexos_ticket(
    anexos: Sequence[Mapping[str, Any]],
    ticket_id: str,
    uf_ticket: str,
    hashes_baixados: set[str],
    *,
    cancelar: Callable[[], bool],
    baixar_conteudo: Callable[[str], tuple[bytes | None, str]],
    analisar_anexo: Callable[[str, str, bytes, str, bool], Any],
    ao_erro_download: Callable[[str, str, str], None],
    ao_detectar_duplicado: Callable[[str, str], None],
    max_workers: int = 8,
) -> list[Any]:
    """Baixa e classifica anexos do ticket em paralelo, preservando a detecção de duplicatas."""
    lock_hashes = threading.Lock()

    def baixar_e_analisar(anexo: Mapping[str, Any]) -> Any | None:
        if cancelar():
            return None

        nome = str(anexo["file_name"])
        nome_limpo = limpar_nome_anexo(nome)
        conteudo, status_download = baixar_conteudo(anexo["content_url"])
        if not conteudo:
            ao_erro_download(nome, ticket_id, status_download)
            return None

        hash_conteudo = calcular_hash_md5(conteudo)
        with lock_hashes:
            duplicado = hash_conteudo in hashes_baixados
            hashes_baixados.add(hash_conteudo)

        if duplicado:
            ao_detectar_duplicado(nome_limpo, ticket_id)

        return analisar_anexo(ticket_id, nome, conteudo, uf_ticket, duplicado)

    processados = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futuros = [executor.submit(baixar_e_analisar, anexo) for anexo in anexos]
        for futuro in as_completed(futuros):
            resultado = futuro.result()
            if resultado:
                processados.append(resultado)
    return processados


def processar_anexos_ticket(
    ticket_id: str,
    ticket: Mapping[str, Any],
    comentarios: Sequence[ComentarioZendesk],
    uf_ticket: str,
    hashes_baixados: set[str],
    *,
    cancelar: Callable[[], bool],
    baixar_conteudo: Callable[[str], tuple[bytes | None, str]],
    analisar_anexo: Callable[[str, str, bytes, str, bool], Any],
    ao_erro_download: Callable[[str, str, str], None],
    ao_detectar_duplicado: Callable[[str, str], None],
) -> ResultadoAnexosTicket:
    """Coleta, baixa, classifica e prepara anexos de um ticket para gravação."""
    anexos = coletar_anexos_ticket(ticket, comentarios, ticket_id)
    processados = baixar_e_analisar_anexos_ticket(
        anexos,
        ticket_id,
        uf_ticket,
        hashes_baixados,
        cancelar=cancelar,
        baixar_conteudo=baixar_conteudo,
        analisar_anexo=analisar_anexo,
        ao_erro_download=ao_erro_download,
        ao_detectar_duplicado=ao_detectar_duplicado,
    )
    em_quarentena, motivo = determinar_quarentena_al(uf_ticket, processados)
    propagar_vencimento_dar_ap(uf_ticket, processados)
    return ResultadoAnexosTicket(processados, em_quarentena, motivo)


def processar_e_salvar_anexos_ticket(
    ticket_id: str,
    pasta_destino: str,
    hashes_baixados: set[str],
    *,
    obter_ticket: Callable[[str], Mapping[str, Any] | None],
    obter_comentarios: Callable[[str], Sequence[ComentarioZendesk]],
    identificar_uf: Callable[[Mapping[str, Any]], str],
    cancelar: Callable[[], bool],
    baixar_conteudo: Callable[[str], tuple[bytes | None, str]],
    analisar_anexo: Callable[[str, str, bytes, str, bool], Any],
    ao_erro_download: Callable[[str, str, str], None],
    ao_detectar_duplicado: Callable[[str, str], None],
    ao_entrar_quarentena: Callable[[str, ResultadoAnexosTicket], None],
) -> tuple[str, ResultadoAnexosTicket] | None:
    """Obtém, processa e salva os anexos de um ticket Zendesk."""
    ticket = obter_ticket(ticket_id)
    if not ticket:
        return None

    uf_ticket = identificar_uf(ticket)
    resultado = processar_anexos_ticket(
        ticket_id,
        ticket,
        obter_comentarios(ticket_id),
        uf_ticket,
        hashes_baixados,
        cancelar=cancelar,
        baixar_conteudo=baixar_conteudo,
        analisar_anexo=analisar_anexo,
        ao_erro_download=ao_erro_download,
        ao_detectar_duplicado=ao_detectar_duplicado,
    )
    if resultado.em_quarentena:
        ao_entrar_quarentena(ticket_id, resultado)

    salvar_anexos_processados(
        pasta_destino, resultado.anexos, resultado.em_quarentena
    )
    return uf_ticket, resultado


def determinar_uf_ticket(
    pdfs: Sequence[PDFExtraido],
    uf_ticket_tag: str,
    identificar_uf: Callable[[str], str],
) -> str:
    """Usa a primeira UF reconhecida nos PDFs, com fallback para ticket e AL."""
    for _, texto, _ in pdfs:
        uf_detectada = identificar_uf(texto)
        if uf_detectada != "GERAL":
            return uf_detectada
    return uf_ticket_tag if uf_ticket_tag != "GERAL" else "AL"


def identificar_uf_ticket(
    ticket_data: Mapping[str, Any] | None, txt_pdf: str = ""
) -> str:
    """Identifica a UF primeiro pelo texto do PDF e depois pelas tags do ticket."""
    ufs_validas = {
        "AC",
        "AL",
        "AP",
        "AM",
        "BA",
        "CE",
        "DF",
        "ES",
        "GO",
        "MA",
        "MT",
        "MS",
        "MG",
        "PA",
        "PB",
        "PR",
        "PE",
        "PI",
        "RJ",
        "RN",
        "RS",
        "RO",
        "RR",
        "SC",
        "SP",
        "SE",
        "TO",
    }
    if txt_pdf:
        txt_upper = txt_pdf.upper()

        mapa_nomes = [
            ("GOVERNO DO ESTADO DO AMAPÁ", "AP"),
            ("GOVERNO DO ESTADO DO ACRE", "AC"),
            ("GOVERNO DO ESTADO DO PARÁ", "PA"),
            ("GOVERNO DO ESTADO DO PARA", "PA"),
            ("ESTADO DO MATO GROSSO DO SUL", "MS"),
            ("MATO GROSSO DO SUL", "MS"),
            ("ESPÍRITO SANTO", "ES"),
            ("ESPIRITO SANTO", "ES"),
            ("RIO GRANDE DO NORTE", "RN"),
            ("RIO GRANDE DO SUL", "RS"),
            ("DISTRITO FEDERAL", "DF"),
            ("MINAS GERAIS", "MG"),
            ("SANTA CATARINA", "SC"),
            ("RIO DE JANEIRO", "RJ"),
            ("SÃO PAULO", "SP"),
            ("SAO PAULO", "SP"),
            ("PERNAMBUCO", "PE"),
            ("MARANHÃO", "MA"),
            ("MARANHAO", "MA"),
            ("TOCANTINS", "TO"),
            ("AMAZONAS", "AM"),
            ("RONDÔNIA", "RO"),
            ("RONDONIA", "RO"),
            ("RORAIMA", "RR"),
            ("PARAÍBA", "PB"),
            ("PARAIBA", "PB"),
            ("ALAGOAS", "AL"),
            ("SERGIPE", "SE"),
            ("PIAUÍ", "PI"),
            ("PIAUI", "PI"),
            ("CEARÁ", "CE"),
            ("CEARA", "CE"),
            ("GOIÁS", "GO"),
            ("GOIAS", "GO"),
            ("BAHIA", "BA"),
            ("MATO GROSSO", "MT"),
            ("AMAPÁ", "AP"),
            ("AMAPA", "AP"),
        ]
        for nome_estado, uf_code in mapa_nomes:
            if re.search(r"\b" + re.escape(nome_estado) + r"\b", txt_upper):
                return uf_code

        if re.search(r"\bPARÁ\b|\bSEFAZ[/\s-]*PA\b|\bESTADO\s+DO\s+PAR[AÁ]\b", txt_upper):
            return "PA"

        if re.search(r"\bACRE\b", txt_upper):
            return "AC"

        match_sefaz = re.search(r"\bSEFAZ[/\s-]*([A-Z]{2})\b", txt_upper)
        if match_sefaz and match_sefaz.group(1) in ufs_validas:
            return match_sefaz.group(1)

        match_uf = re.search(r"\bUF\s*[:=]?\s*([A-Z]{2})\b", txt_upper)
        if match_uf and match_uf.group(1) in ufs_validas:
            return match_uf.group(1)

    if ticket_data:
        tags = [str(tag).lower() for tag in ticket_data.get("tags", [])]
        for uf_candidate in [
            "ap",
            "ms",
            "ac",
            "al",
            "am",
            "ba",
            "ce",
            "df",
            "es",
            "go",
            "ma",
            "mt",
            "mg",
            "pa",
            "pb",
            "pr",
            "pe",
            "pi",
            "rj",
            "rn",
            "rs",
            "ro",
            "rr",
            "sc",
            "sp",
            "se",
            "to",
        ]:
            if uf_candidate in tags:
                return uf_candidate.upper()

    return "GERAL"


def mapear_termo_cte_ticket(
    texto_completo: str,
    uf_ticket: str,
    extrair_remessas_ap: Callable[[str], list[str]],
) -> tuple[dict[str, list[str]], list[str]]:
    """Associa termos do ticket aos CT-e/remessas conforme as regras atuais."""
    mapa_termo_cte: dict[str, list[str]] = {}
    lista_ctes_ordenada: list[str] = []

    if uf_ticket == "AP":
        lista_ctes_ordenada = extrair_remessas_ap(texto_completo)
        for linha in texto_completo.splitlines():
            remessas_linha = extrair_remessas_ap(linha)
            for termo in re.findall(r"\b\d{6,15}\b", linha):
                remessas = mapa_termo_cte.setdefault(termo, [])
                remessas.extend(remessa for remessa in remessas_linha if remessa not in remessas)
        return mapa_termo_cte, lista_ctes_ordenada

    termo_atual = "Não localizado"
    for numero in re.findall(r"\b\d+\b", texto_completo):
        if 6 <= len(numero) <= 9:
            termo_atual = numero
            mapa_termo_cte.setdefault(termo_atual, [])
        elif len(numero) >= 14:
            ctes_termo = mapa_termo_cte.setdefault(termo_atual, [])
            if numero not in ctes_termo:
                ctes_termo.append(numero)
            if numero not in lista_ctes_ordenada:
                lista_ctes_ordenada.append(numero)

    return mapa_termo_cte, lista_ctes_ordenada
