"""Leitura, normalizacao e incorporacao de planilhas de conferencia."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.services.spreadsheet_service import HAS_OPENPYXL, openpyxl


@dataclass(frozen=True)
class ResultadoImportacaoPlanilha:
    dados: list[dict[str, str]]
    abas_lidas: int
    duplicados_ignorados: int
    linhas_lidas: int
    tem_cabecalho: bool


def _carregar_linhas(
    caminho_arquivo: str | Path, limpar_texto: Callable[[Any], str]
) -> tuple[list[str], list[Sequence[Any]], int, int]:
    caminho = str(caminho_arquivo)
    if caminho.lower().endswith(".csv"):
        conteudo = Path(caminho).read_bytes()
        for codificacao in ("utf-8-sig", "cp1252"):
            try:
                texto = conteudo.decode(codificacao)
                break
            except UnicodeDecodeError:
                continue
        primeira = texto.splitlines()[0] if texto else ""
        delimitador = ";" if primeira.count(";") >= primeira.count(",") else ","
        leitor = list(csv.reader(io.StringIO(texto), delimiter=delimitador))
        if not leitor:
            return [], [], 0, 0
        cabecalho = [str(coluna).strip().upper() for coluna in leitor[0]]
        return cabecalho, leitor[1:], 0, 0

    if not HAS_OPENPYXL:
        raise ImportError("Biblioteca 'openpyxl' não encontrada para ler .xlsx.")

    workbook = openpyxl.load_workbook(caminho, data_only=True)
    try:
        abas = []
        for planilha in workbook.worksheets:
            dados_aba = list(planilha.iter_rows(values_only=True))
            if not dados_aba:
                continue
            cabecalho_aba = [str(coluna or "").strip().upper() for coluna in dados_aba[0]]
            if any(cabecalho_aba):
                abas.append((cabecalho_aba, dados_aba[1:]))

        cabecalho: list[str] = []
        for cabecalho_aba, _ in abas:
            for nome in cabecalho_aba:
                if nome and nome not in cabecalho:
                    cabecalho.append(nome)

        linhas = []
        for cabecalho_aba, linhas_aba in abas:
            mapa_colunas = {
                nome: indice for indice, nome in enumerate(cabecalho_aba) if nome
            }
            for linha_aba in linhas_aba:
                linha_alinhada = [None] * len(cabecalho)
                for indice, nome in enumerate(cabecalho):
                    indice_origem = mapa_colunas.get(nome)
                    if indice_origem is not None and indice_origem < len(linha_aba):
                        linha_alinhada[indice] = linha_aba[indice_origem]
                linhas.append(tuple(linha_alinhada))

        linhas_unicas = []
        identidades_vistas = set()
        for linha in linhas:
            identidade_completa = tuple(
                limpar_texto(str(valor) if valor is not None else "").strip().upper()
                for valor in linha
            )
            if identidade_completa not in identidades_vistas:
                identidades_vistas.add(identidade_completa)
                linhas_unicas.append(linha)

        return cabecalho, linhas_unicas, len(abas), len(linhas) - len(linhas_unicas)
    finally:
        workbook.close()


def _mapear_colunas(cabecalho: Sequence[str], campos_al: Sequence[str]) -> dict[str, int]:
    indice_por_campo: dict[str, int] = {}
    for indice, coluna in enumerate(cabecalho):
        nome = str(coluna).strip()
        if nome in campos_al:
            indice_por_campo[nome] = indice
        elif "TERMO" in nome or "CONTROLE" in nome:
            indice_por_campo["TERMO"] = indice
        elif (
            "CPF" in nome
            and "CNPJ" in nome
            and "R/S/U/V" not in nome
            and "EM R" not in nome
        ):
            indice_por_campo["CPF/CNPJ DA GUIA"] = indice
        elif "UF" in nome:
            indice_por_campo["UF"] = indice
        elif "TICKET" in nome:
            indice_por_campo["TICKET"] = indice
        elif "STATUS" in nome:
            indice_por_campo["STATUS CONFERÊNCIA"] = indice
        elif "ORIGINAL" in nome:
            indice_por_campo["CODIGO BARRAS ORIGINAL"] = indice
        elif "(44)" in nome or ("BARRAS" in nome and "ORIGINAL" not in nome):
            indice_por_campo["CODIGO BARRAS"] = indice
        elif "DATA PROCESSAMENTO" in nome:
            indice_por_campo["DATA PROCESSAMENTO"] = indice
        elif "DATA" in nome:
            indice_por_campo["DATA"] = indice
        elif "VENCIMENTO" in nome:
            indice_por_campo["VENCIMENTO"] = indice
        elif "VALOR" in nome:
            indice_por_campo["VALOR"] = indice
        elif nome in ("CTE / REMESSA", "CTE") or "REMESSA" in nome:
            indice_por_campo["CTE / REMESSA"] = indice
        elif "TOMADOR" in nome:
            indice_por_campo["TOMADOR"] = indice
        elif "NÚMERO ARQUIVO" in nome:
            indice_por_campo["NÚMERO ARQUIVO"] = indice
        elif "CHAVE" in nome:
            indice_por_campo["CHAVE ARQUIVO"] = indice
        elif "DACTE" in nome:
            indice_por_campo["DACTE"] = indice
    return indice_por_campo


def carregar_planilha_conferencia(
    caminho_arquivo: str | Path,
    *,
    campos_al: Sequence[str],
    limpar_texto: Callable[[Any], str],
    padronizar_data: Callable[[Any], str],
    timestamp: Callable[[], str],
    ao_progresso: Callable[[int, int], None],
) -> ResultadoImportacaoPlanilha:
    """Lê uma planilha e converte as linhas para o formato de conferência da aplicação."""
    cabecalho, linhas, abas_lidas, duplicados = _carregar_linhas(
        caminho_arquivo, limpar_texto
    )
    indices = _mapear_colunas(cabecalho, campos_al)
    dados: list[dict[str, str]] = []

    for linha in linhas:
        if not any(linha):
            continue
        ao_progresso(len(dados) + 1, len(linhas))

        def obter_valor(campo: str) -> str:
            indice = indices.get(campo, -1)
            if indice < 0 or indice >= len(linha):
                return ""
            valor = linha[indice]
            if valor is None:
                return ""
            texto = str(valor).strip()
            if texto.endswith(".0") and re.match(r"^\d+\.0$", texto):
                texto = texto[:-2]
            return limpar_texto(texto)

        termo = obter_valor("TERMO")
        if not termo:
            continue

        cte = obter_valor("CTE / REMESSA") or obter_valor("CTE")
        item = {
            "TERMO": termo,
            "UF": obter_valor("UF") or "GERAL",
            "CPF/CNPJ DA GUIA": obter_valor("CPF/CNPJ DA GUIA"),
            "TICKET": obter_valor("TICKET"),
            "STATUS CONFERÊNCIA": obter_valor("STATUS CONFERÊNCIA") or "OK",
            "DATA": padronizar_data(obter_valor("DATA")),
            "VENCIMENTO": padronizar_data(obter_valor("VENCIMENTO")) or "Não informado",
            "VALOR": obter_valor("VALOR") or "Não informado",
            "CTE / REMESSA": cte or "Sem CTE",
            "CHAVE ARQUIVO": obter_valor("CHAVE ARQUIVO") or "Sem Arquivo Válido",
            "DACTE": obter_valor("DACTE") or "Sem DACTE",
            "NÚMERO ARQUIVO": obter_valor("NÚMERO ARQUIVO") or "Sem Número",
            "CODIGO BARRAS ORIGINAL": obter_valor("CODIGO BARRAS ORIGINAL") or "Sem Código",
            "CODIGO BARRAS": obter_valor("CODIGO BARRAS") or "Sem Código",
            "TOMADOR": obter_valor("TOMADOR") or "Aguardando Conciliação",
            "DATA PROCESSAMENTO": obter_valor("DATA PROCESSAMENTO") or timestamp(),
        }
        item.update({campo: obter_valor(campo) for campo in campos_al})
        dados.append(item)

    return ResultadoImportacaoPlanilha(
        dados,
        abas_lidas,
        duplicados,
        len(linhas),
        bool(cabecalho),
    )


def mesclar_dados_conferencia(
    novos_dados: Sequence[Mapping[str, Any]],
    memoria_termos: dict[str, dict[str, Any]],
    *,
    campos_al: Sequence[str],
    padronizar_data: Callable[[Any], str],
    normalizar_valor: Callable[[Any], str],
    separar_valores: Callable[[Any], list[str]],
) -> None:
    """Mescla os itens importados na memória mantendo a normalização legada."""
    campos_memoria = [
        "TICKET",
        "UF",
        "CPF/CNPJ DA GUIA",
        "DATA",
        "VENCIMENTO",
        "VALOR",
        "CTE / REMESSA",
        "CHAVE ARQUIVO",
        "DACTE",
        "NÚMERO ARQUIVO",
        "CODIGO BARRAS ORIGINAL",
        "CODIGO BARRAS",
        *campos_al,
    ]
    valores_ignorados = {
        "Sem CTE",
        "Sem Código",
        "Sem Arquivo Válido",
        "Sem DACTE",
        "Sem Número",
        "Não informado",
    }

    for item in novos_dados:
        termo = item["TERMO"]
        if termo not in memoria_termos:
            memoria_termos[termo] = {campo: [] for campo in campos_memoria}

        registro = memoria_termos[termo]
        registro["STATUS CONFERÊNCIA"] = item["STATUS CONFERÊNCIA"]
        registro["TOMADOR"] = item["TOMADOR"]
        registro["DATA PROCESSAMENTO"] = item["DATA PROCESSAMENTO"]

        for campo in campos_memoria:
            valor = item.get(campo, "")
            if campo == "VALOR":
                partes = separar_valores(valor)
            elif campo in ("DATA", "VENCIMENTO", "UF"):
                partes = [parte.strip() for parte in valor.split(",")]
            elif campo in campos_al:
                partes = [valor.strip()]
            else:
                partes = [parte.strip() for parte in valor.split(" ")]

            for parte in partes:
                valor_formatado = (
                    padronizar_data(parte)
                    if campo in ("DATA", "VENCIMENTO")
                    else normalizar_valor(parte)
                    if campo == "VALOR"
                    else parte
                )
                if (
                    valor_formatado
                    and valor_formatado not in registro[campo]
                    and valor_formatado not in valores_ignorados
                ):
                    registro[campo].append(valor_formatado)
