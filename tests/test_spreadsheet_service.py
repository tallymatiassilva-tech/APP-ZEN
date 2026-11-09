import csv

import pytest

from src.services import spreadsheet_service

CABECALHO = [
    "TERMO/CONTROLE",
    "STATUS CONFERÊNCIA",
    "VENCIMENTO",
    "VALOR (R$)",
    "CÓDIGO BARRAS",
    "CPF/CNPJ DA GUIA",
    "EMITENTE - CPF/CNPJ",
]
LINHA_OK = [
    "123456789",
    "OK",
    "01/01/2000",
    "10,00",
    "8" * 44,
    "12345678000190",
    "12345678000190",
]
LINHA_INCOMPLETA = [
    "Não localizado",
    "OK",
    "Não informado",
    "Não informado",
    "Sem Código",
    "",
    "",
]


def test_exporta_excel_com_abas_formula_e_quarentena(tmp_path):
    if not spreadsheet_service.HAS_OPENPYXL:
        pytest.skip("openpyxl não está disponível")

    caminho = spreadsheet_service.salvar_planilha_multisheets(
        str(tmp_path / "relatorio.xlsx"),
        CABECALHO,
        [LINHA_OK, LINHA_INCOMPLETA],
    )

    assert caminho == str(tmp_path / "relatorio.xlsx")
    workbook = spreadsheet_service.openpyxl.load_workbook(caminho, data_only=False)
    assert workbook.sheetnames == [
        "DOCUMENTOS_OK",
        "LEITURA_GERAL_TOTAL",
        "QUARENTENA",
    ]

    aba_ok = workbook["DOCUMENTOS_OK"]
    assert aba_ok.cell(row=2, column=8).value == '=IF(OR($F2=$G2),"SIM","NÃO")'
    assert aba_ok.cell(row=2, column=3).fill.fgColor.rgb.endswith("FDE9D9")
    assert workbook["QUARENTENA"].cell(row=2, column=2).value == (
        "INCOMPLETO: Sem Termo, Vencimento, Valor, Código de Barras"
    )


def test_exporta_csv_quando_excel_nao_esta_disponivel(tmp_path, monkeypatch):
    monkeypatch.setattr(spreadsheet_service, "HAS_OPENPYXL", False)

    resultado = spreadsheet_service.salvar_planilha_multisheets(
        str(tmp_path / "relatorio.xlsx"),
        CABECALHO,
        [LINHA_OK, LINHA_INCOMPLETA],
    )

    arquivo_ok = tmp_path / "relatorio_DOCUMENTOS_OK.csv"
    arquivo_quarentena = tmp_path / "relatorio_QUARENTENA.csv"
    assert resultado == f"{arquivo_ok} / {arquivo_quarentena}"
    with arquivo_ok.open(encoding="utf-8-sig", newline="") as arquivo:
        assert list(csv.reader(arquivo, delimiter=";")) == [CABECALHO, LINHA_OK]
    with arquivo_quarentena.open(encoding="utf-8-sig", newline="") as arquivo:
        linhas = list(csv.reader(arquivo, delimiter=";"))
    assert linhas[0] == CABECALHO
    assert linhas[1][1] == "INCOMPLETO: Sem Termo, Vencimento, Valor, Código de Barras"


def test_classifica_status_validado_com_dados_completos():
    linha = list(LINHA_OK)
    linha[1] = "VALIDADO: chave conferida"

    assert spreadsheet_service.e_linha_valida_ok(CABECALHO, linha) == (True, "OK")
