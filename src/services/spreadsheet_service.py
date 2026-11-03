"""Funções de validação usadas na geração de planilhas."""

from __future__ import annotations

import contextlib
import csv
import re
from datetime import datetime

from src.services.uf_rules import (
    AL_CAMPOS_PLANILHA,
    formatar_texto_excel,
    limpar_texto_excel,
    padronizar_data_ddmmyyyy,
)

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


def sanitizar_celula_excel(val: object) -> str:
    val_str = str(val or "").strip()
    match = re.match(r'^=\s*"([^"]*)"$', val_str)
    return match[1] if match else val_str


def e_linha_valida_ok(cabecalho: list, row: list) -> tuple[bool, str]:
    idx_status = cabecalho.index("STATUS CONFERÊNCIA") if "STATUS CONFERÊNCIA" in cabecalho else -1
    status = str(row[idx_status]).strip() if idx_status != -1 and idx_status < len(row) else "OK"
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
    for nome_coluna, nome_exibicao in colunas_verificar:
        if nome_coluna in cabecalho:
            indice = cabecalho.index(nome_coluna)
            if indice < len(row):
                valor = sanitizar_celula_excel(row[indice]).strip().lower()
                if valor in maldados:
                    faltantes.append(nome_exibicao)

    if faltantes:
        return False, f"INCOMPLETO: Sem {', '.join(faltantes)}"

    return True, "OK"


def e_registro_vencido(row_list: list, cabecalho: list) -> bool:
    hoje = datetime.now().date()
    idx_vencimento = cabecalho.index("VENCIMENTO") if "VENCIMENTO" in cabecalho else -1

    if idx_vencimento != -1 and idx_vencimento < len(row_list):
        vencimento = str(row_list[idx_vencimento] or "")
        if vencimento and vencimento != "Não informado":
            for parte in vencimento.split(","):
                parte_limpa = sanitizar_celula_excel(parte).strip()
                with contextlib.suppress(ValueError):
                    data = datetime.strptime(parte_limpa, "%d/%m/%Y").date()
                    if data < hoje:
                        return True
    return False


class SpreadsheetService:
    def carregar_planilha(self, caminho_arquivo: str) -> list:
        linhas = []
        cabecalho = []

        # LEITURA DE ARQUIVOS CSV
        if caminho_arquivo.lower().endswith(".csv"):
            with open(caminho_arquivo, mode="r", encoding="utf-8-sig") as f:
                leitor = list(csv.reader(f, delimiter=";"))
                if leitor:
                    cabecalho = [str(c).strip().upper() for c in leitor[0]]
                    linhas = leitor[1:]

        # LEITURA DE ARQUIVOS EXCEL (.XLSX)
        elif HAS_OPENPYXL:
            wb = openpyxl.load_workbook(caminho_arquivo, data_only=True)
            try:
                dados_abas = []
                for ws in wb.worksheets:
                    dados_aba = list(ws.iter_rows(values_only=True))
                    if not dados_aba:
                        continue
                    cabecalho_aba = [str(c or "").strip().upper() for c in dados_aba[0]]
                    if any(cabecalho_aba):
                        dados_abas.append((cabecalho_aba, dados_aba[1:]))

                colunas_unificadas = []
                for cabecalho_aba, _ in dados_abas:
                    for nome in cabecalho_aba:
                        if nome and nome not in colunas_unificadas:
                            colunas_unificadas.append(nome)
                cabecalho = colunas_unificadas

                for cabecalho_aba, linhas_aba in dados_abas:
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

                # Remover duplicados
                nomes_identidade = {
                    "TERMO/CONTROLE",
                    "TICKET",
                    "CTE / REMESSA",
                    "NÚMERO ARQUIVO",
                    "CHAVE ARQUIVO (55)",
                    "DACTE (57)",
                }
                indices_identidade = [
                    idx for idx, nome in enumerate(cabecalho) if nome in nomes_identidade
                ]
                linhas_unicas, identidades_vistas = [], set()
                for linha in linhas:
                    identidade = tuple(
                        limpar_texto_excel(str(linha[i] or "")).strip().upper()
                        for i in indices_identidade
                        if i < len(linha)
                    )
                    identidade_completa = (
                        identidade if any(identidade) else tuple(str(v or "") for v in linha)
                    )
                    if identidade_completa not in identidades_vistas:
                        identidades_vistas.add(identidade_completa)
                        linhas_unicas.append(linha)
                linhas = linhas_unicas
            finally:
                wb.close()
        else:
            raise RuntimeError("Biblioteca 'openpyxl' não encontrada para ler .xlsx.")

        if not linhas or not cabecalho:
            return []

        # Mapeamento de colunas
        idx_map = {}
        for i, col_name in enumerate(cabecalho):
            n = str(col_name).strip()
            if n in AL_CAMPOS_PLANILHA:
                idx_map[n] = i
            elif "TERMO" in n or "CONTROLE" in n:
                idx_map["TERMO"] = i
            elif "CPF" in n and "CNPJ" in n and "R/S/U/V" not in n and "EM R" not in n:
                idx_map["CPF/CNPJ DA GUIA"] = i
            elif "UF" in n:
                idx_map["UF"] = i
            elif "TICKET" in n:
                idx_map["TICKET"] = i
            elif "STATUS" in n:
                idx_map["STATUS CONFERÊNCIA"] = i
            elif "ORIGINAL" in n:
                idx_map["CODIGO BARRAS ORIGINAL"] = i
            elif "(44)" in n or ("BARRAS" in n and "ORIGINAL" not in n):
                idx_map["CODIGO BARRAS"] = i
            elif "DATA PROCESSAMENTO" in n:
                idx_map["DATA PROCESSAMENTO"] = i
            elif "DATA" in n:
                idx_map["DATA"] = i
            elif "VENCIMENTO" in n:
                idx_map["VENCIMENTO"] = i
            elif "VALOR" in n:
                idx_map["VALOR"] = i
            elif "CTE / REMESSA" == n or "CTE" == n or "REMESSA" in n:
                idx_map["CTE / REMESSA"] = i
            elif "TOMADOR" in n:
                idx_map["TOMADOR"] = i
            elif "NÚMERO ARQUIVO" in n:
                idx_map["NÚMERO ARQUIVO"] = i
            elif "CHAVE" in n:
                idx_map["CHAVE ARQUIVO"] = i
            elif "DACTE" in n:
                idx_map["DACTE"] = i

        novos_dados = []
        for row in linhas:
            if not any(row):
                continue

            def get_val(key):
                idx = idx_map.get(key, -1)
                if idx != -1 and idx < len(row):  # noqa: B023
                    v_raw = row[idx]  # noqa: B023
                    if v_raw is None:
                        return ""
                    v_str = str(v_raw).strip()
                    if v_str.endswith(".0") and re.match(r"^\d+\.0$", v_str):
                        v_str = v_str[:-2]
                    return limpar_texto_excel(v_str)
                return ""

            termo_val = get_val("TERMO")
            if not termo_val:
                continue

            item = {
                "TERMO": termo_val,
                "UF": get_val("UF") or "GERAL",
                "CPF/CNPJ DA GUIA": get_val("CPF/CNPJ DA GUIA"),
                "TICKET": get_val("TICKET"),
                "STATUS CONFERÊNCIA": get_val("STATUS CONFERÊNCIA") or "OK",
                "DATA": padronizar_data_ddmmyyyy(get_val("DATA")),
                "VENCIMENTO": padronizar_data_ddmmyyyy(get_val("VENCIMENTO")) or "Não informado",
                "VALOR": get_val("VALOR") or "Não informado",
                "CTE / REMESSA": get_val("CTE / REMESSA") or get_val("CTE") or "Sem CTE",
                "CHAVE ARQUIVO": get_val("CHAVE ARQUIVO") or "Sem Arquivo Válido",
                "DACTE": get_val("DACTE") or "Sem DACTE",
                "NÚMERO ARQUIVO": get_val("NÚMERO ARQUIVO") or "Sem Número",
                "CODIGO BARRAS ORIGINAL": get_val("CODIGO BARRAS ORIGINAL") or "Sem Código",
                "CODIGO BARRAS": get_val("CODIGO BARRAS") or "Sem Código",
                "TOMADOR": get_val("TOMADOR") or "Aguardando Conciliação",
                "DATA PROCESSAMENTO": get_val("DATA PROCESSAMENTO")
                or datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                **{campo: get_val(campo) for campo in AL_CAMPOS_PLANILHA},
            }
            novos_dados.append(item)
        return novos_dados

    def exportar_multisheets(self, caminho_arquivo: str, dados_memoria: list) -> str:
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

        linhas_totais = []
        for i in dados_memoria:
            linhas_totais.append(
                [
                    i.get("TERMO", ""),
                    i.get("UF", "GERAL"),
                    formatar_texto_excel(i.get("CPF/CNPJ DA GUIA", "")),
                    i.get("TICKET", ""),
                    i.get("STATUS CONFERÊNCIA", "OK"),
                    i.get("CODIGO BARRAS ORIGINAL", ""),
                    i.get("CODIGO BARRAS", ""),
                    i.get("DATA", ""),
                    i.get("VENCIMENTO", ""),
                    i.get("VALOR", ""),
                    i.get("CTE / REMESSA", "Sem CTE"),
                    i.get("TOMADOR", "Não Conciliado"),
                    i.get("NÚMERO ARQUIVO", ""),
                    i.get("CHAVE ARQUIVO", ""),
                    i.get("DACTE", ""),
                    i.get("DATA PROCESSAMENTO", ""),
                    *(i.get(c, "") for c in AL_CAMPOS_PLANILHA),
                ]
            )

        linhas_ok, linhas_faltando = [], []
        idx_st = cabecalho.index("STATUS CONFERÊNCIA")

        for row in linhas_totais:
            # USA A SUA FUNÇÃO DE VALIDAÇÃO
            is_ok, motivo = e_linha_valida_ok(cabecalho, row)

            if is_ok:
                linhas_ok.append(row)
            else:
                row_list = list(row)
                if (
                    idx_st != -1
                    and idx_st < len(row_list)
                    and str(row_list[idx_st]).strip().upper() == "OK"
                ):
                    row_list[idx_st] = motivo
                linhas_faltando.append(row_list)

        if not HAS_OPENPYXL:
            caminho_csv = caminho_arquivo.replace(".xlsx", ".csv")
            with open(caminho_csv, "w", newline="", encoding="utf-8-sig") as f:
                escritor = csv.writer(f, delimiter=";")
                escritor.writerow(cabecalho)
                escritor.writerows(linhas_totais)
            return caminho_csv

        caminho_xlsx = (
            caminho_arquivo if caminho_arquivo.endswith(".xlsx") else f"{caminho_arquivo}.xlsx"
        )
        wb = openpyxl.Workbook()
        fill_destaque = PatternFill(start_color="FDE9D9", end_color="FDE9D9", fill_type="solid")
        font_destaque = Font(color="7A4B1F", bold=False)

        def add_aba(ws, linhas_dados):
            ws.append(cabecalho)
            for idx, c_nome in enumerate(cabecalho, 1):
                if "ORIGINAL" in c_nome:
                    ws.column_dimensions[get_column_letter(idx)].width = 56
                elif "BARRAS" in c_nome:
                    ws.column_dimensions[get_column_letter(idx)].width = 50

            for r_idx, r in enumerate(linhas_dados, 2):
                ws.append(r)

                # USA A SUA FUNÇÃO PARA DESTACAR VENCIDOS E INCOMPLETOS
                if e_registro_vencido(r, cabecalho) or not e_linha_valida_ok(cabecalho, r)[0]:
                    for col_idx in [
                        cabecalho.index("VENCIMENTO") + 1,
                        cabecalho.index("VALOR (R$)") + 1,
                        idx_st + 1,
                    ]:
                        ws.cell(row=r_idx, column=col_idx).fill = fill_destaque
                        ws.cell(row=r_idx, column=col_idx).font = font_destaque

        ws_ok = wb.active
        ws_ok.title = "DOCUMENTOS_OK"
        add_aba(ws_ok, linhas_ok)

        ws_geral = wb.create_sheet(title="LEITURA_GERAL_TOTAL")
        add_aba(ws_geral, linhas_totais)

        ws_quar = wb.create_sheet(title="QUARENTENA")
        add_aba(ws_quar, linhas_faltando)

        wb.save(caminho_xlsx)
        return caminho_xlsx
