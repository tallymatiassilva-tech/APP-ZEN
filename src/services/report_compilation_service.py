"""Combina memoria de termos e prepara linhas de relatorio sem gravar arquivos."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.services.ufs.al import AL_CAMPOS_PLANILHA


@dataclass(frozen=True)
class RelatorioCompilado:
    cabecalho: list[str]
    itens: list[dict[str, str]]
    linhas: list[list[str]]


def compilar_relatorio_e_atualizar_dados(
    termos_map: Mapping[str, dict[str, Any]],
    memoria_termos: dict[str, dict[str, Any]],
    dados_em_memoria: list[dict[str, str]],
    data_processamento: str,
    *,
    lock: Any,
    persistir_memoria: Callable[[], None],
    limpar_texto: Callable[[Any], str],
    formatar_texto: Callable[[Any], str],
    formatar_numero: Callable[[str], str],
    padronizar_data: Callable[[Any], str],
    normalizar_valor: Callable[[Any], str],
    separar_valores: Callable[[Any], list[str]],
) -> RelatorioCompilado:
    """Atualiza a memória e prepara o relatório, preservando a sequência de persistência."""
    with lock:
        atualizar_memoria_termos(
            termos_map,
            memoria_termos,
            data_processamento,
            limpar_texto=limpar_texto,
            formatar_numero=formatar_numero,
            padronizar_data=padronizar_data,
            normalizar_valor=normalizar_valor,
            separar_valores=separar_valores,
        )

    persistir_memoria()

    with lock:
        resultado = preparar_dados_relatorio(
            termos_map,
            memoria_termos,
            data_processamento,
            limpar_texto=limpar_texto,
            formatar_texto=formatar_texto,
            formatar_numero=formatar_numero,
            padronizar_data=padronizar_data,
            normalizar_valor=normalizar_valor,
            separar_valores=separar_valores,
        )
        dados_em_memoria.extend(resultado.itens)
    return resultado


def atualizar_memoria_termos(
    termos_map: Mapping[str, dict[str, Any]],
    memoria_termos: dict[str, dict[str, Any]],
    data_processamento: str,
    *,
    limpar_texto: Callable[[Any], str],
    formatar_numero: Callable[[str], str],
    padronizar_data: Callable[[Any], str],
    normalizar_valor: Callable[[Any], str],
    separar_valores: Callable[[Any], list[str]],
) -> None:
    """Mescla o lote atual na memoria; o chamador protege e persiste o estado."""
    campos_memoria = [
        "TICKET",
        "UF",
        "CPF/CNPJ DA GUIA",
        "DATA",
        "VENCIMENTO",
        "VALOR",
        "CTE",
        "CHAVE ARQUIVO",
        "DACTE",
        "NÚMERO ARQUIVO",
        "CODIGO BARRAS ORIGINAL",
        "CODIGO BARRAS",
        *AL_CAMPOS_PLANILHA,
        "STATUS CONFERÊNCIA",
        "DATA PROCESSAMENTO",
    ]

    for termo_key, data_dict in termos_map.items():
        termo_exibicao = data_dict.get("TERMO_REAL", termo_key)
        linha_individual = str(termo_key).startswith("AP::")

        if termo_exibicao not in memoria_termos:
            memoria_termos[termo_exibicao] = {campo: [] for campo in campos_memoria}
            memoria_termos[termo_exibicao]["TOMADOR"] = "Aguardando Conciliação"

        dados_memoria = memoria_termos[termo_exibicao]
        for campo in campos_memoria:
            if campo not in dados_memoria:
                dados_memoria[campo] = []
        if "TOMADOR" not in dados_memoria:
            dados_memoria["TOMADOR"] = "Aguardando Conciliação"
        dados_memoria["DATA PROCESSAMENTO"] = data_processamento

        ufs_atual = data_dict.get("UF", [])
        if isinstance(ufs_atual, str):
            ufs_atual = [ufs_atual]
        if any(str(uf).strip().upper() == "AP" for uf in ufs_atual):
            dados_memoria["VALOR"] = []
            dados_memoria["CPF/CNPJ DA GUIA"] = []

        for campo in ("CHAVE ARQUIVO", "DACTE"):
            for valor in data_dict.get(campo, []):
                if valor not in dados_memoria[campo]:
                    dados_memoria[campo].append(valor)

        for numero in data_dict.get("NÚMERO ARQUIVO", []):
            numero_formatado = formatar_numero(numero)
            if numero_formatado not in dados_memoria["NÚMERO ARQUIVO"]:
                dados_memoria["NÚMERO ARQUIVO"].append(numero_formatado)

        campos_agregados = [
            campo
            for campo in campos_memoria
            if campo
            not in (
                "CHAVE ARQUIVO",
                "DACTE",
                "NÚMERO ARQUIVO",
                "STATUS CONFERÊNCIA",
            )
        ]
        for campo in campos_agregados:
            for valor in data_dict.get(campo, []):
                valores = separar_valores(valor) if campo == "VALOR" else [valor]
                for valor_item in valores:
                    valor_limpo = (
                        padronizar_data(valor_item)
                        if campo in ("DATA", "VENCIMENTO")
                        else (
                            normalizar_valor(valor_item)
                            if campo == "VALOR"
                            else limpar_texto(valor_item)
                        )
                    )
                    if (
                        valor_limpo
                        and valor_limpo != "Não informado"
                        and valor_limpo not in dados_memoria[campo]
                    ):
                        if campo == "TICKET" and valor_limpo == "Local":
                            continue
                        dados_memoria[campo].append(valor_limpo)

            valores_memoria = list(dados_memoria[campo])
            if campo == "CTE" and any(str(uf).strip().upper() == "AL" for uf in ufs_atual):
                ctes_do_termo = [
                    limpar_texto(cte)
                    for cte in data_dict.get("CTE", [])
                    if cte and limpar_texto(cte)
                ]
                valores_memoria = list(dict.fromkeys(ctes_do_termo + valores_memoria))
                dados_memoria[campo] = valores_memoria
            if not linha_individual:
                if (
                    campo == "TICKET"
                    and not valores_memoria
                    and "Local" in data_dict.get("TICKET", [])
                ):
                    data_dict["TICKET"] = ["Local"]
                else:
                    data_dict[campo] = valores_memoria

        dados_memoria["STATUS CONFERÊNCIA"] = data_dict.get("STATUS CONFERÊNCIA", "OK")


def preparar_dados_relatorio(
    termos_map: Mapping[str, dict[str, Any]],
    memoria_termos: Mapping[str, Mapping[str, Any]],
    data_processamento: str,
    *,
    limpar_texto: Callable[[Any], str],
    formatar_texto: Callable[[Any], str],
    formatar_numero: Callable[[str], str],
    padronizar_data: Callable[[Any], str],
    normalizar_valor: Callable[[Any], str],
    separar_valores: Callable[[Any], list[str]],
) -> RelatorioCompilado:
    """Prepara os itens finais e linhas da planilha sem alterar a memoria."""
    cabecalho = [
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

    itens: list[dict[str, str]] = []
    linhas: list[list[str]] = []
    for termo_key, data in termos_map.items():
        termo_exibicao = data.get("TERMO_REAL", termo_key)

        datas = list(
            dict.fromkeys(
                padronizar_data(valor) for valor in data["DATA"] if valor and str(valor).strip()
            )
        )
        data_str = ", ".join(datas) if datas else "Não Informado"

        ufs = [
            limpar_texto(valor)
            for valor in data.get("UF", [])
            if valor and valor.strip() and valor != "GERAL"
        ]
        uf_str = ", ".join(dict.fromkeys(ufs)) if ufs else "GERAL"

        ctes = [limpar_texto(valor) for valor in data["CTE"] if valor]
        cte_str = " ".join(dict.fromkeys(ctes)) if ctes else "Sem CTE"
        cte_formatado = formatar_texto(cte_str) if cte_str != "Sem CTE" else "Sem CTE"

        codigos_barras = list(
            dict.fromkeys(
                limpar_texto(valor)
                for valor in data["CODIGO BARRAS"]
                if valor and valor != "Sem Código"
            )
        )
        cb_arrecadacao = [
            valor for valor in codigos_barras if valor.startswith("8") and len(valor) in (43, 44)
        ]
        cb_valido = (
            cb_arrecadacao[0]
            if cb_arrecadacao
            else (codigos_barras[0] if codigos_barras else "Sem Código")
        )
        cb_formatado = formatar_texto(cb_valido) if cb_valido != "Sem Código" else "Sem Código"

        barras_originais = list(
            dict.fromkeys(
                limpar_texto(valor)
                for valor in data["CODIGO BARRAS ORIGINAL"]
                if valor and valor != "Sem Código"
            )
        )
        barras_arrecadacao = [
            valor for valor in barras_originais if re.sub(r"\D", "", valor).startswith("8")
        ]
        cbo_valido = (
            barras_arrecadacao[0]
            if barras_arrecadacao
            else (barras_originais[0] if barras_originais else "Sem Código")
        )
        cbo_formatado = formatar_texto(cbo_valido) if cbo_valido != "Sem Código" else "Sem Código"

        numeros_arquivo = []
        for valor in data.get("NÚMERO ARQUIVO", []):
            if not valor or not str(valor).strip() or str(valor).strip() == "Sem Número":
                continue
            numero = formatar_numero(valor)
            if numero != "Sem Número":
                if "AL" in uf_str.upper() and re.fullmatch(r"\d{1,9}", numero):
                    numero = str(int(numero)) if numero != "0" else "0"
                numeros_arquivo.append(numero)
        numero_str = " ".join(dict.fromkeys(numeros_arquivo)) if numeros_arquivo else "Sem Número"

        chaves = list(
            dict.fromkeys(
                limpar_texto(valor)
                for valor in data.get("CHAVE ARQUIVO", [])
                if valor and valor.strip() and valor != "Sem Arquivo Válido"
            )
        )
        chave_str = formatar_texto(" ".join(chaves)) if chaves else "Sem Arquivo Válido"
        dactes = list(
            dict.fromkeys(
                limpar_texto(valor)
                for valor in data.get("DACTE", [])
                if valor and valor.strip() and valor != "Sem DACTE"
            )
        )
        dacte_str = formatar_texto(" ".join(dactes)) if dactes else "Sem DACTE"

        status_raw = data.get("STATUS CONFERÊNCIA", "OK")
        status = (
            status_raw[0]
            if isinstance(status_raw, list) and status_raw
            else (status_raw if isinstance(status_raw, str) else "OK")
        )
        vencimentos = list(
            dict.fromkeys(
                padronizar_data(valor)
                for valor in data.get("VENCIMENTO", [])
                if valor and limpar_texto(valor) != "Não informado"
            )
        )
        vencimento_str = ", ".join(vencimentos) if vencimentos else "Não informado"

        valores = list(
            dict.fromkeys(
                normalizar_valor(valor)
                for item_valor in data.get("VALOR", [])
                for valor in separar_valores(item_valor)
                if limpar_texto(valor) != "Não informado"
            )
        )
        valor_str = ", ".join(valores) if valores else "Não informado"
        documentos = list(
            dict.fromkeys(
                limpar_texto(valor)
                for valor in data.get("CPF/CNPJ DA GUIA", [])
                if valor and limpar_texto(valor)
            )
        )

        faltantes = []
        if termo_exibicao in ("Não localizado", "Sem Número", ""):
            faltantes.append("Termo")
        if cb_valido in ("Sem Código", ""):
            faltantes.append("Código de Barras")
        if vencimento_str in ("Não informado", ""):
            faltantes.append("Vencimento")
        if valor_str in ("Não informado", ""):
            faltantes.append("Valor")
        if status == "OK" and faltantes:
            status = f"INCOMPLETO: Sem {', '.join(faltantes)}"

        memoria = memoria_termos.get(termo_exibicao, {})
        item = {
            "TERMO": termo_exibicao,
            "UF": uf_str,
            "CPF/CNPJ DA GUIA": " ".join(documentos),
            "TICKET": " ".join(dict.fromkeys(limpar_texto(valor) for valor in data["TICKET"])),
            "STATUS CONFERÊNCIA": status,
            "DATA": data_str,
            "VENCIMENTO": vencimento_str,
            "VALOR": valor_str,
            "CTE": cte_formatado,
            "CHAVE ARQUIVO": chave_str,
            "DACTE": dacte_str,
            "NÚMERO ARQUIVO": numero_str,
            "CODIGO BARRAS ORIGINAL": cbo_formatado,
            "CODIGO BARRAS": cb_formatado,
            "TOMADOR": memoria.get("TOMADOR", "Aguardando Conciliação"),
            "DATA PROCESSAMENTO": memoria.get("DATA PROCESSAMENTO", data_processamento),
        }
        for campo in AL_CAMPOS_PLANILHA:
            valores_campo = list(
                dict.fromkeys(
                    limpar_texto(valor)
                    for valor in data.get(campo, [])
                    if valor and limpar_texto(valor)
                )
            )
            item[campo] = " | ".join(valores_campo)

        itens.append(item)
        linhas.append(
            [
                item["TERMO"],
                item["UF"],
                formatar_texto(item.get("CPF/CNPJ DA GUIA", "")),
                item["TICKET"],
                item["STATUS CONFERÊNCIA"],
                item["CODIGO BARRAS ORIGINAL"],
                item["CODIGO BARRAS"],
                item["DATA"],
                item["VENCIMENTO"],
                item["VALOR"],
                item["CTE"],
                item["TOMADOR"],
                item["NÚMERO ARQUIVO"],
                item["CHAVE ARQUIVO"],
                item["DACTE"],
                item["DATA PROCESSAMENTO"],
                *(item[campo] for campo in AL_CAMPOS_PLANILHA),
            ]
        )

    return RelatorioCompilado(cabecalho=cabecalho, itens=itens, linhas=linhas)
