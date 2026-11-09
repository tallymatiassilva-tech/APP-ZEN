"""Exportacao de relatorios para Excel e CSV."""

from __future__ import annotations

import csv
import os
import re
from datetime import datetime
from typing import Any

openpyxl: Any = None
PatternFill: Any = None
Font: Any = None
get_column_letter: Any = None
HAS_OPENPYXL = False
try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    HAS_OPENPYXL = True
except ImportError:
    pass


def sanitizar_celula_excel(valor: Any) -> str:
    texto = str(valor or "").strip()
    match = re.match(r'^=\s*"([^"]*)"$', texto)
    return match.group(1) if match else texto


def e_linha_valida_ok(cabecalho: list, linha: list) -> tuple[bool, str]:
    idx_status = cabecalho.index("STATUS CONFERÊNCIA") if "STATUS CONFERÊNCIA" in cabecalho else -1
    status = (
        str(linha[idx_status]).strip() if idx_status != -1 and idx_status < len(linha) else "OK"
    )
    status_normalizado = status.upper()

    if (
        status_normalizado not in ("OK", "")
        and not status_normalizado.startswith("OK")
        and not status_normalizado.startswith("VALIDADO")
    ):
        return False, status

    maldados = [
        "sem código",
        "não localizado",
        "não informado",
        "sem arquivo válido",
        "sem número",
        "sem cte",
        "",
    ]
    coluna_codigo_barras = next(
        (
            nome
            for nome in cabecalho
            if "CÓDIGO BARRAS" in str(nome).upper() and "ORIGINAL" not in str(nome).upper()
        ),
        None,
    )
    colunas_verificar = [
        ("TERMO/CONTROLE", "Termo"),
        ("VENCIMENTO", "Vencimento"),
        ("VALOR (R$)", "Valor"),
    ]
    if coluna_codigo_barras:
        colunas_verificar.append((coluna_codigo_barras, "Código de Barras"))

    faltantes = []
    for nome_coluna, exibicao in colunas_verificar:
        if nome_coluna in cabecalho:
            indice = cabecalho.index(nome_coluna)
            if indice < len(linha):
                valor = sanitizar_celula_excel(linha[indice]).strip().lower()
                if valor in maldados:
                    faltantes.append(exibicao)

    if faltantes:
        return False, f"INCOMPLETO: Sem {', '.join(faltantes)}"
    return True, "OK"


def e_registro_vencido(linha: list, cabecalho: list) -> bool:
    hoje = datetime.now().date()
    indice_vencimento = cabecalho.index("VENCIMENTO") if "VENCIMENTO" in cabecalho else -1
    if indice_vencimento == -1 or indice_vencimento >= len(linha):
        return False

    vencimentos = str(linha[indice_vencimento] or "")
    if not vencimentos or vencimentos == "Não informado":
        return False
    for parte in vencimentos.split(","):
        texto_data = sanitizar_celula_excel(parte).strip()
        try:
            if datetime.strptime(texto_data, "%d/%m/%Y").date() < hoje:
                return True
        except ValueError:
            continue
    return False


def salvar_planilha_multisheets(
    caminho_arquivo: str,
    cabecalho: list,
    linhas_totais: list,
) -> str:
    idx_status = cabecalho.index("STATUS CONFERÊNCIA") if "STATUS CONFERÊNCIA" in cabecalho else -1

    linhas_ok, linhas_faltando = [], []
    for linha in linhas_totais:
        linha_atual = list(linha)
        is_ok, motivo = e_linha_valida_ok(cabecalho, linha_atual)
        if is_ok:
            linhas_ok.append(linha_atual)
        else:
            if (
                idx_status != -1
                and idx_status < len(linha_atual)
                and linha_atual[idx_status] == "OK"
            ):
                linha_atual[idx_status] = motivo
            linhas_faltando.append(linha_atual)

    base_path, extensao = os.path.splitext(caminho_arquivo)
    if HAS_OPENPYXL:
        caminho_xlsx = base_path + ".xlsx" if extensao.lower() != ".xlsx" else caminho_arquivo
        try:
            workbook = openpyxl.Workbook()
            fill_destaque = PatternFill(start_color="FDE9D9", end_color="FDE9D9", fill_type="solid")
            font_destaque = Font(color="7A4B1F", bold=False)

            def aplicar_destaque_vencimento(ws, indice_linha: int) -> None:
                colunas_destaque = [
                    indice + 1
                    for indice, titulo in enumerate(cabecalho)
                    if any(
                        termo in str(titulo).upper()
                        for termo in (
                            "VENCIMENTO",
                            "VALOR (R$)",
                            "STATUS CONFERÊNCIA",
                        )
                    )
                ]
                for indice_coluna in colunas_destaque:
                    celula = ws.cell(row=indice_linha, column=indice_coluna)
                    celula.fill = fill_destaque
                    celula.font = font_destaque

            def adicionar_e_formatar_aba(ws, linhas_dados: list) -> None:
                coluna_extra = "CPF/CNPJ GUIA EM R/S/U/V"
                ja_tem_coluna_extra = coluna_extra in cabecalho
                cabecalho_exportacao = (
                    list(cabecalho) if ja_tem_coluna_extra else list(cabecalho) + [coluna_extra]
                )
                ws.append([sanitizar_celula_excel(c) for c in cabecalho_exportacao])
                for indice, titulo in enumerate(cabecalho_exportacao, start=1):
                    titulo_normalizado = str(titulo).upper()
                    if "CÓDIGO BARRAS ORIGINAL" in titulo_normalizado:
                        ws.column_dimensions[ws.cell(row=1, column=indice).column_letter].width = 56
                    elif (
                        "CÓDIGO BARRAS" in titulo_normalizado
                        and "ORIGINAL" not in titulo_normalizado
                    ):
                        ws.column_dimensions[ws.cell(row=1, column=indice).column_letter].width = 50

                coluna_guia = next(
                    (
                        indice + 1
                        for indice, coluna in enumerate(cabecalho)
                        if coluna == "CPF/CNPJ DA GUIA"
                    ),
                    None,
                )
                colunas_documento = [
                    next(
                        (indice + 1 for indice, coluna in enumerate(cabecalho) if coluna == nome),
                        None,
                    )
                    for nome in (
                        "EMITENTE - CPF/CNPJ",
                        "EMITENTE - IE",
                        "DESTINATÁRIO - CPF/CNPJ",
                        "DESTINATÁRIO - IE",
                    )
                ]

                for indice_linha, linha in enumerate(linhas_dados, start=2):
                    valores_linha = [sanitizar_celula_excel(c) for c in linha]
                    if not ja_tem_coluna_extra:
                        if coluna_guia is not None and get_column_letter:
                            letra_guia = get_column_letter(coluna_guia)
                            letras_alvo = [
                                get_column_letter(coluna)
                                for coluna in colunas_documento
                                if coluna is not None
                            ]
                            formula = (
                                f'=IF(OR({",".join(f"${letra_guia}{indice_linha}=${alvo}{indice_linha}" for alvo in letras_alvo)}),"SIM","NÃO")'
                                if letras_alvo
                                else f'=IF(OR($C{indice_linha}=$R{indice_linha},$C{indice_linha}=$S{indice_linha},$C{indice_linha}=$U{indice_linha},$C{indice_linha}=$V{indice_linha}),"SIM","NÃO")'
                            )
                            valores_linha.append(formula)
                        elif "CPF/CNPJ DA GUIA" in cabecalho:
                            valores_linha.append(
                                f'=IF(OR($C{indice_linha}=$R{indice_linha},$C{indice_linha}=$S{indice_linha},$C{indice_linha}=$U{indice_linha},$C{indice_linha}=$V{indice_linha}),"SIM","NÃO")'
                            )
                        else:
                            valores_linha.append("")
                    ws.append(valores_linha)
                    if e_registro_vencido(linha, cabecalho):
                        aplicar_destaque_vencimento(ws, indice_linha)

            aba_ok = workbook.active
            aba_ok.title = "DOCUMENTOS_OK"
            adicionar_e_formatar_aba(aba_ok, linhas_ok)

            aba_geral = workbook.create_sheet(title="LEITURA_GERAL_TOTAL")
            adicionar_e_formatar_aba(aba_geral, linhas_totais)

            aba_quarentena = workbook.create_sheet(title="QUARENTENA")
            adicionar_e_formatar_aba(aba_quarentena, linhas_faltando)

            workbook.save(caminho_xlsx)
            return caminho_xlsx
        except Exception as erro:  # noqa: BLE001
            print(f"[Erro Excel] Falha ao gravar .xlsx via openpyxl: {erro}")

    caminho_csv_ok = base_path + "_DOCUMENTOS_OK.csv"
    caminho_csv_quarentena = base_path + "_QUARENTENA.csv"
    if linhas_ok:
        with open(caminho_csv_ok, mode="w", newline="", encoding="utf-8-sig") as arquivo:
            escritor = csv.writer(arquivo, delimiter=";")
            escritor.writerow(cabecalho)
            escritor.writerows(linhas_ok)
    if linhas_faltando:
        with open(caminho_csv_quarentena, mode="w", newline="", encoding="utf-8-sig") as arquivo:
            escritor = csv.writer(arquivo, delimiter=";")
            escritor.writerow(cabecalho)
            escritor.writerows(linhas_faltando)
    return f"{caminho_csv_ok} / {caminho_csv_quarentena}"
