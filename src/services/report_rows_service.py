"""Monta cabecalhos e linhas para exportacoes de relatorios."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from src.services.ufs.al import AL_CAMPOS_PLANILHA


def cabecalho_relatorio() -> list[str]:
    return [
        "TERMO/CONTROLE",
        "UF",
        "CPF/CNPJ DA GUIA",
        "TICKET",
        "STATUS CONFERÊNCIA",
        "CÓDIGO BARRAS ORIGINAL",
        "CÓDIGO BARRAS (44)",
        "DATA",
        "VENCIMENTO",
        "VALOR (R$)",
        "CTE / REMESSA",
        "TOMADOR",
        "NÚMERO ARQUIVO",
        "CHAVE ARQUIVO (55)",
        "DACTE (57)",
        "DATA PROCESSAMENTO",
        *AL_CAMPOS_PLANILHA,
    ]


def linhas_relatorio_conciliacao(
    itens: Sequence[Mapping[str, Any]],
    *,
    limpar_texto: Callable[[Any], str],
    formatar_texto: Callable[[Any], str],
    padronizar_data: Callable[[Any], str],
    timestamp: Callable[[], str],
) -> list[list[Any]]:
    linhas = []
    for item in itens:
        cte_remessa = item.get("CTE / REMESSA")
        if limpar_texto(cte_remessa or "") in ("", "Sem CTE"):
            cte_remessa = item.get("CTE", "")

        linhas.append(
            [
                item.get("TERMO", ""),
                item.get("UF", "GERAL"),
                formatar_texto(item.get("CPF/CNPJ DA GUIA", "")),
                item.get("TICKET", ""),
                item.get("STATUS CONFERÊNCIA", "OK"),
                item.get("CODIGO BARRAS ORIGINAL", ""),
                item.get("CODIGO BARRAS", ""),
                padronizar_data(item.get("DATA", "")),
                padronizar_data(item.get("VENCIMENTO", "")),
                item.get("VALOR", ""),
                cte_remessa or "Sem CTE",
                item.get("TOMADOR", "Aguardando Conciliação"),
                item.get("NÚMERO ARQUIVO", ""),
                item.get("CHAVE ARQUIVO", ""),
                item.get("DACTE", ""),
                item.get("DATA PROCESSAMENTO", timestamp()),
                *(item.get(campo, "") for campo in AL_CAMPOS_PLANILHA),
            ]
        )
    return linhas


def linhas_relatorio_final(
    itens: Sequence[Mapping[str, Any]],
    *,
    limpar_texto: Callable[[Any], str],
    formatar_texto: Callable[[Any], str],
    padronizar_data: Callable[[Any], str],
    timestamp: Callable[[], str],
) -> list[list[Any]]:
    linhas = []
    for item in itens:
        cte_remessa = item.get("CTE / REMESSA")
        if limpar_texto(cte_remessa or "") in ("", "Sem CTE"):
            cte_remessa = item.get("CTE", "")

        linhas.append(
            [
                item.get("TERMO", ""),
                item.get("UF", "GERAL"),
                formatar_texto(item.get("CPF/CNPJ DA GUIA", "")),
                item.get("TICKET", ""),
                item.get("STATUS CONFERÊNCIA", "OK"),
                item.get("CODIGO BARRAS ORIGINAL", ""),
                item.get("CODIGO BARRAS", ""),
                padronizar_data(item.get("DATA", "")),
                padronizar_data(item.get("VENCIMENTO", "")),
                item.get("VALOR", ""),
                cte_remessa,
                item.get("TOMADOR", "Não Conciliado"),
                item.get("NÚMERO ARQUIVO", ""),
                item.get("CHAVE ARQUIVO (55)") or item.get("CHAVE ARQUIVO", ""),
                item.get("DACTE (57)") or item.get("DACTE", ""),
                item.get("DATA PROCESSAMENTO", timestamp()),
                *(item.get(campo, "") for campo in AL_CAMPOS_PLANILHA),
            ]
        )
    return linhas
