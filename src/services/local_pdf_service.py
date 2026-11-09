"""Leitura de PDFs locais sem dependencias da interface grafica."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.services.document_classifier import extrair_chaves_nfe_pdf
from src.services.extraction_service import extrair_documento
from src.services.pdf_service import extrair_texto_pdf
from src.services.ufs.ap_validacao import (
    chaves_dos_pares,
    doc_do_campo_05,
    documentos_dos_pares,
    resumo_nfe_map,
    validar_guia_ap,
)
from src.services.zendesk_pdf_service import mapear_chaves_nfe_pdf
from src.utils.text_mono import formatar_numero_arquivo, padronizar_data_ddmmyyyy

RegistroPDFLocal = tuple[str, list, str, str, str, str, str, str, str]
ResultadoExtracao = tuple[str, list, str, str, str, str, str]


@dataclass(frozen=True)
class PDFLocal:
    caminho: str
    nome: str
    conteudo: bytes
    texto: str
    status_leitura: str
    uf: str


@dataclass(frozen=True)
class ResultadoLotePDFLocal:
    quantidade_arquivos: int
    registros: list[RegistroPDFLocal]
    nfe_map: dict[str, Any]
    doc_ap05_por_chave: dict[str, str]
    ap_total: int
    ap_ok: int
    ap_quarentena: int
    ap_corrigidas: int
    cancelado: bool = False


def listar_pdfs_locais(pasta_origem: str | os.PathLike[str]) -> list[str]:
    """Lista PDFs recursivamente, priorizando arquivos em pastas de notas."""
    arquivos_pdf = []
    for raiz, _, arquivos in os.walk(pasta_origem):
        for nome in arquivos:
            if nome.lower().endswith(".pdf"):
                arquivos_pdf.append(os.path.join(raiz, nome))

    return sorted(
        arquivos_pdf,
        key=lambda caminho: (
            0
            if any(
                "nota" in parte.lower() or "danfe" in parte.lower() for parte in Path(caminho).parts
            )
            else 1
        ),
    )


def carregar_pdf_local(
    caminho: str | os.PathLike[str],
    identificar_uf: Callable[[str], str],
) -> PDFLocal:
    """Lê um PDF local, extrai seu texto e identifica a UF sem ocultar erros."""
    caminho_str = os.fspath(caminho)
    conteudo = Path(caminho).read_bytes()
    texto, status = extrair_texto_pdf(conteudo)

    return PDFLocal(
        caminho=caminho_str,
        nome=os.path.basename(caminho_str),
        conteudo=conteudo,
        texto=texto,
        status_leitura=status,
        uf=identificar_uf(texto),
    )


def processar_pdfs_locais(
    pasta_origem: str | os.PathLike[str],
    *,
    identificar_uf: Callable[[str], str],
    eh_nota_fiscal: Callable[[str, str], bool],
    separar_guias_ap: Callable[[str], list[tuple[str | None, str]]],
    identificar_layout: Callable[..., dict | None],
    historico_termos: Mapping[str, Any],
    marcar_ap_processada: Callable[[str], str],
    cancelado: Callable[[], bool],
    ao_inicio: Callable[[int], None],
    ao_progresso: Callable[[int, int], None],
    ao_log: Callable[[str, str], None],
    ao_aviso: Callable[[str], None],
    ao_erro: Callable[[str, Exception], None],
    obter_chaves_nfe: Callable[[str, bytes | None], list[str]] = extrair_chaves_nfe_pdf,
    extrair: Callable[..., ResultadoExtracao] = extrair_documento,
    validar_ap: Callable[..., tuple[bool, str]] = validar_guia_ap,
    extrair_doc_campo_05: Callable[[str], str] = doc_do_campo_05,
    extrair_documentos_pares: Callable[[list], list[str]] = documentos_dos_pares,
    extrair_chaves_pares: Callable[[list], list[str]] = chaves_dos_pares,
    formatar_numero: Callable[[str], str] = formatar_numero_arquivo,
    padronizar_data: Callable[[Any], str] = padronizar_data_ddmmyyyy,
) -> ResultadoLotePDFLocal:
    """Orquestra a leitura e extração de um lote local, sem depender da GUI."""
    arquivos_pdf = listar_pdfs_locais(pasta_origem)
    nfe_map: dict[str, Any] = {}
    registros: list[RegistroPDFLocal] = []
    doc_ap05_por_chave: dict[str, str] = {}
    ids_guias_ap: set[str] = set()
    indices_guias_ap: dict[str, list[int]] = {}
    if arquivos_pdf:
        ao_inicio(len(arquivos_pdf))

    for indice, caminho_pdf in enumerate(arquivos_pdf, 1):
        if cancelado():
            return ResultadoLotePDFLocal(
                len(arquivos_pdf),
                registros,
                nfe_map,
                doc_ap05_por_chave,
                0,
                0,
                0,
                0,
                cancelado=True,
            )

        nome_arquivo = os.path.basename(caminho_pdf)
        ao_log(
            "PROGRESSO",
            f"Lendo PDF {indice} de {len(arquivos_pdf)}: {nome_arquivo}...",
        )
        try:
            documento = carregar_pdf_local(caminho_pdf, identificar_uf)
            nome_arquivo = documento.nome
            texto = documento.texto
            if not texto:
                ao_aviso(f"Leitura local do arquivo '{nome_arquivo}': {documento.status_leitura}")

            uf = documento.uf
            if eh_nota_fiscal(texto, nome_arquivo):
                nfe_map.update(
                    mapear_chaves_nfe_pdf(
                        texto,
                        documento.conteudo,
                        obter_chaves_nfe,
                        formatar_numero,
                    )
                )
                ao_progresso(indice, len(arquivos_pdf))
                continue

            if uf in {"AL", "AP", "AC", "MS"}:
                if uf == "AP":
                    for id_guia, bloco_guia in separar_guias_ap(texto):
                        repetida = bool(id_guia and id_guia in ids_guias_ap)
                        historico_ap = historico_termos.get(id_guia or "")
                        if id_guia:
                            ids_guias_ap.add(id_guia)
                        if repetida:
                            for indice_linha in indices_guias_ap.get(id_guia, []):
                                linha = registros[indice_linha]
                                registros[indice_linha] = (
                                    *linha[:8],
                                    marcar_ap_processada(linha[8]),
                                )
                            continue

                        (
                            termo,
                            pares,
                            barras_orig,
                            barras,
                            vencimento,
                            valor,
                            uf_resultado,
                        ) = extrair("AP", bloco_guia, nome_arquivo, nfe_map)
                        doc_guia = extrair_doc_campo_05(bloco_guia)
                        if not doc_guia:
                            documentos = extrair_documentos_pares(pares)
                            doc_guia = documentos[0] if documentos else ""
                        if doc_guia:
                            for chave in extrair_chaves_pares(pares or []):
                                doc_ap05_por_chave[chave] = doc_guia

                        _, status = validar_ap(pares, bloco_guia, nfe_map, doc_guia)
                        ao_log(
                            "INFO",
                            "AP-guia: ok=%s motivo=%s nfe_map=%s"
                            % (
                                status.startswith("DOC OK"),
                                status,
                                resumo_nfe_map(nfe_map),
                            ),
                        )
                        if historico_ap:
                            status = marcar_ap_processada(status)

                        linhas_guia = []
                        for par in pares or [("Sem Arquivo Válido", "Sem Número")]:
                            registros.append(
                                (
                                    termo,
                                    [par],
                                    barras_orig,
                                    barras,
                                    padronizar_data(vencimento),
                                    valor,
                                    uf_resultado,
                                    caminho_pdf,
                                    status,
                                )
                            )
                            linhas_guia.append(len(registros) - 1)
                        if id_guia:
                            indices_guias_ap[id_guia] = linhas_guia
                else:
                    termo, pares, barras_orig, barras, vencimento, valor, uf_resultado = extrair(
                        uf, texto, nome_arquivo, nfe_map, documento.conteudo
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
                            caminho_pdf,
                            "",
                        )
                    )
            else:
                dados_layout = identificar_layout(texto, nome_arquivo, pdf_bytes=documento.conteudo)
                if dados_layout:
                    registros.append(
                        (
                            dados_layout.get("termo") or "Não localizado",
                            dados_layout.get("pares_documento", []),
                            dados_layout.get("cod_barras_orig", "Sem Código"),
                            dados_layout.get("cod_barras", "Sem Código"),
                            padronizar_data(dados_layout.get("vencimento", "Não informado")),
                            dados_layout.get("valor", "Não informado"),
                            dados_layout.get("uf", uf),
                            caminho_pdf,
                            "",
                        )
                    )
                else:
                    termo, pares, barras_orig, barras, vencimento, valor, uf_resultado = extrair(
                        uf, texto, nome_arquivo, nfe_map, documento.conteudo
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
                            caminho_pdf,
                            "",
                        )
                    )
        except Exception as erro:
            ao_erro(nome_arquivo, erro)
        ao_progresso(indice, len(arquivos_pdf))

    ap_total = ap_ok = ap_quarentena = ap_corrigidas = 0
    for indice, linha in enumerate(registros):
        if len(linha) < 9 or linha[6] != "AP":
            continue
        antigo = linha[8]
        chaves = extrair_chaves_pares(linha[1])
        doc_guia = doc_ap05_por_chave.get(chaves[0], "") if chaves else ""
        _, novo = validar_ap(linha[1], "", nfe_map, doc_guia)
        if novo != antigo:
            registros[indice] = (*linha[:8], novo)
            ap_corrigidas += 1
        ap_total += 1
        if "DOC OK" in novo:
            ap_ok += 1
        else:
            ap_quarentena += 1

    ao_log(
        "INFO",
        "[AP] Pos-leitura: %d guia(s) | DOC OK: %d | QUARENTENA: %d | "
        "corrigidas: %d | notas no mapa: %d"
        % (ap_total, ap_ok, ap_quarentena, ap_corrigidas, len(nfe_map)),
    )
    return ResultadoLotePDFLocal(
        len(arquivos_pdf),
        registros,
        nfe_map,
        doc_ap05_por_chave,
        ap_total,
        ap_ok,
        ap_quarentena,
        ap_corrigidas,
    )
