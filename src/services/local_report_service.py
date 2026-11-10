"""Transforma registros extraidos localmente no mapa usado pelo relatorio."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.services.local_pdf_service import (
    RegistroPDFLocal,
    ResultadoLotePDFLocal,
    processar_pdfs_locais,
)
from src.services.ufs.al import AL_CAMPOS_PLANILHA


@dataclass(frozen=True)
class ResultadoRelatorioPastaLocal:
    lote_pdf: ResultadoLotePDFLocal
    termos_map: dict[str, dict[str, Any]]


def processar_pasta_local_para_relatorio(
    pasta_origem: str,
    memoria_termos: Mapping[str, Any],
    *,
    limpar_texto: Callable[[str], str],
    formatar_numero_relatorio: Callable[[str], str],
    padronizar_data_relatorio: Callable[[Any], str],
    **opcoes_extracao: Any,
) -> ResultadoRelatorioPastaLocal:
    """Lê PDFs locais e monta os dados agrupados para o relatório final."""
    lote_pdf = processar_pdfs_locais(pasta_origem, **opcoes_extracao)
    termos_map = montar_mapa_relatorio_local(
        lote_pdf.registros,
        lote_pdf.nfe_map,
        lote_pdf.doc_ap05_por_chave,
        memoria_termos,
        limpar_texto=limpar_texto,
        formatar_numero=formatar_numero_relatorio,
        padronizar_data=padronizar_data_relatorio,
    )
    return ResultadoRelatorioPastaLocal(lote_pdf, termos_map)


def montar_mapa_relatorio_local(
    registros: Sequence[RegistroPDFLocal],
    nfe_map: Mapping[str, Any],
    doc_ap05_por_chave: Mapping[str, str],
    memoria_termos: Mapping[str, Any],
    *,
    limpar_texto: Callable[[str], str],
    formatar_numero: Callable[[str], str],
    padronizar_data: Callable[[Any], str],
    data_atual: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Agrupa documentos locais por termo ou chave, preservando regras atuais."""
    data_registro = data_atual or datetime.now().strftime("%d/%m/%Y")
    mapa_chaves_termo_ap = {}
    for termo, pares, _, _, _, _, uf, _, _ in registros:
        if uf == "AP" and termo and termo != "Não localizado":
            for chave, _ in pares:
                if chave and chave != "Sem Arquivo Válido":
                    mapa_chaves_termo_ap[chave] = termo

    termos_map: dict[str, dict[str, Any]] = {}
    for indice, registro in enumerate(registros, 1):
        (
            termo_pdf,
            pares,
            codigo_barras_orig,
            codigo_barras,
            vencimento_pdf,
            valor_pdf,
            uf_item,
            caminho_completo,
            status_ap,
        ) = registro

        if uf_item == "AP" and (not termo_pdf or termo_pdf == "Não localizado"):
            for chave, _ in pares:
                if chave in mapa_chaves_termo_ap:
                    termo_pdf = mapa_chaves_termo_ap[chave]
                    break

        if not termo_pdf or termo_pdf == "Não localizado":
            chave_map = (
                f"ARQ_{hashlib.md5(caminho_completo.encode('utf-8')).hexdigest()[:10]}"
            )
        else:
            chave_ref = ""
            for par in pares or []:
                chave = par[0] if isinstance(par, (tuple, list)) and par else par
                chave_limpa = re.sub(r"\D", "", str(chave or ""))
                if len(chave_limpa) == 44:
                    chave_ref = chave_limpa
                    break
            chave_map = chave_ref or termo_pdf

        if uf_item == "AP" and (not termo_pdf or termo_pdf == "Não localizado"):
            chave_map = f"AP::{caminho_completo}::{indice}::Não_localizado"

        status_conf = (
            status_ap
            if uf_item == "AP"
            else (
                "GUIA JÁ PROCESSADA"
                if termo_pdf in memoria_termos
                else "OK"
            )
        )
        if uf_item == "AL":
            if codigo_barras == "Sem Código" and termo_pdf != "Não localizado":
                status_conf = "INCOMPLETO: Falta Guia (DAR)"
            elif codigo_barras != "Sem Código" and termo_pdf == "Não localizado":
                status_conf = "INCOMPLETO: Falta Termo"

        if chave_map not in termos_map:
            termos_map[chave_map] = {
                "TERMO_REAL": termo_pdf or "Não localizado",
                "TICKET": ["Local"],
                "UF": [uf_item],
                "DATA": [data_registro],
                "VENCIMENTO": [],
                "VALOR": [],
                "CTE": [],
                "CHAVE ARQUIVO": [],
                "DACTE": [],
                "NÚMERO ARQUIVO": [],
                "CODIGO BARRAS ORIGINAL": [],
                "CODIGO BARRAS": [],
                "CPF/CNPJ DA GUIA": [],
                **{campo: [] for campo in AL_CAMPOS_PLANILHA},
                "STATUS CONFERÊNCIA": status_conf,
            }

        if uf_item == "AP":
            doc_guia = doc_ap05_por_chave.get(chave_map, "")
            if not doc_guia:
                for par in pares or []:
                    candidato = par[0] if isinstance(par, (tuple, list)) and par else par
                    digitos = re.sub(r"\D", "", str(candidato or ""))
                    if len(digitos) in (11, 14):
                        doc_guia = digitos
                        break
        else:
            doc_guia = nfe_map.get(f"DOC_MS_{termo_pdf}", "")
        doc_guia = "".join(caractere for caractere in str(doc_guia or "") if caractere.isdigit())
        if doc_guia and doc_guia not in termos_map[chave_map]["CPF/CNPJ DA GUIA"]:
            termos_map[chave_map]["CPF/CNPJ DA GUIA"].append(doc_guia)

        if uf_item == "AL":
            campos_al = nfe_map.get(f"AL_CAMPOS_{termo_pdf}", {})
            for campo in AL_CAMPOS_PLANILHA:
                valor_campo = limpar_texto(campos_al.get(campo, ""))
                if valor_campo and valor_campo not in termos_map[chave_map][campo]:
                    termos_map[chave_map][campo].append(valor_campo)

        if (
            vencimento_pdf != "Não informado"
            and vencimento_pdf not in termos_map[chave_map]["VENCIMENTO"]
        ):
            termos_map[chave_map]["VENCIMENTO"].append(
                padronizar_data(vencimento_pdf)
            )
        if valor_pdf != "Não informado" and valor_pdf not in termos_map[chave_map]["VALOR"]:
            termos_map[chave_map]["VALOR"].append(valor_pdf)
        if codigo_barras_orig not in ["Sem Código", "Sem Código de Barras"]:
            termos_map[chave_map]["CODIGO BARRAS ORIGINAL"].append(codigo_barras_orig)
        if codigo_barras not in ["Sem Código", "Sem Código de Barras"]:
            termos_map[chave_map]["CODIGO BARRAS"].append(codigo_barras)

        for chave, numero_documento in pares:
            chave_limpa = re.sub(r"\D", "", str(chave or ""))
            if len(chave_limpa) == 44:
                if chave_limpa[20:22] == "57":
                    if chave_limpa not in termos_map[chave_map]["DACTE"]:
                        termos_map[chave_map]["DACTE"].append(chave_limpa)
                elif chave_limpa not in termos_map[chave_map]["CHAVE ARQUIVO"]:
                    termos_map[chave_map]["CHAVE ARQUIVO"].append(chave_limpa)

            numero_formatado = formatar_numero(numero_documento)
            numeros_arquivo = termos_map[chave_map]["NÚMERO ARQUIVO"]
            if numero_formatado not in numeros_arquivo and numero_formatado != "Sem Número":
                numeros_arquivo.append(numero_formatado)

    return termos_map
