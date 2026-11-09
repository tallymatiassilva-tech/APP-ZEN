import pytest

from src.services import spreadsheet_import_service
from src.services.ufs.al import AL_CAMPOS_PLANILHA


def test_carrega_csv_e_normaliza_campos_de_conferencia(tmp_path):
    caminho = tmp_path / "conferencia.csv"
    caminho.write_text(
        "TERMO/CONTROLE;UF;TICKET;CTE / REMESSA;VALOR (R$);VENCIMENTO;STATUS CONFERÊNCIA\n"
        "123.0;AL;456;789;10,00;09/11/2026;\n",
        encoding="utf-8-sig",
    )
    progresso = []

    resultado = spreadsheet_import_service.carregar_planilha_conferencia(
        caminho,
        campos_al=AL_CAMPOS_PLANILHA,
        limpar_texto=lambda valor: str(valor).strip(),
        padronizar_data=lambda valor: f"data:{valor}" if valor else "",
        timestamp=lambda: "agora",
        ao_progresso=lambda atual, total: progresso.append((atual, total)),
    )

    assert resultado.abas_lidas == 0
    assert resultado.duplicados_ignorados == 0
    assert resultado.dados == [
        {
            "TERMO": "123",
            "UF": "AL",
            "CPF/CNPJ DA GUIA": "",
            "TICKET": "456",
            "STATUS CONFERÊNCIA": "OK",
            "DATA": "",
            "VENCIMENTO": "data:09/11/2026",
            "VALOR": "10,00",
            "CTE / REMESSA": "789",
            "CHAVE ARQUIVO": "Sem Arquivo Válido",
            "DACTE": "Sem DACTE",
            "NÚMERO ARQUIVO": "Sem Número",
            "CODIGO BARRAS ORIGINAL": "Sem Código",
            "CODIGO BARRAS": "Sem Código",
            "TOMADOR": "Aguardando Conciliação",
            "DATA PROCESSAMENTO": "agora",
            **{campo: "" for campo in AL_CAMPOS_PLANILHA},
        }
    ]
    assert progresso == [(1, 1)]


def test_carrega_excel_de_multiplas_abas_alinha_colunas_e_remove_duplicatas(tmp_path):
    if not spreadsheet_import_service.HAS_OPENPYXL:
        pytest.skip("openpyxl não está disponível")

    caminho = tmp_path / "multiplas_abas.xlsx"
    workbook = spreadsheet_import_service.openpyxl.Workbook()
    primeira = workbook.active
    primeira.append(["TERMO/CONTROLE", "UF", "TICKET", "CTE / REMESSA"])
    primeira.append(["123", "AL", "456", "789"])
    segunda = workbook.create_sheet("Segunda")
    segunda.append(["CTE / REMESSA", "TERMO/CONTROLE", "UF", "TICKET"])
    segunda.append(["789", "123", "AL", "456"])
    segunda.append(["900", "124", "AP", "457"])
    workbook.save(caminho)
    workbook.close()

    resultado = spreadsheet_import_service.carregar_planilha_conferencia(
        caminho,
        campos_al=AL_CAMPOS_PLANILHA,
        limpar_texto=lambda valor: str(valor).strip(),
        padronizar_data=lambda valor: valor,
        timestamp=lambda: "agora",
        ao_progresso=lambda *_: None,
    )

    assert resultado.abas_lidas == 2
    assert resultado.duplicados_ignorados == 1
    assert [(item["TERMO"], item["CTE / REMESSA"]) for item in resultado.dados] == [
        ("123", "789"),
        ("124", "900"),
    ]


def test_mescla_dados_importados_na_memoria_com_normalizacao_e_sem_sentinal():
    memoria = {}
    dados = [
        {
            "TERMO": "123",
            "TICKET": "456",
            "UF": "AL, AP",
            "CPF/CNPJ DA GUIA": "",
            "DATA": "09/11/2026, 10/11/2026",
            "VENCIMENTO": "Não informado",
            "VALOR": "1,00; 2,00",
            "CTE / REMESSA": "789 790",
            "CHAVE ARQUIVO": "Sem Arquivo Válido",
            "DACTE": "Sem DACTE",
            "NÚMERO ARQUIVO": "Sem Número",
            "CODIGO BARRAS ORIGINAL": "Sem Código",
            "CODIGO BARRAS": "Sem Código",
            "STATUS CONFERÊNCIA": "OK",
            "TOMADOR": "Aguardando Conciliação",
            "DATA PROCESSAMENTO": "agora",
            **{campo: "" for campo in AL_CAMPOS_PLANILHA},
        }
    ]

    spreadsheet_import_service.mesclar_dados_conferencia(
        dados,
        memoria,
        campos_al=AL_CAMPOS_PLANILHA,
        padronizar_data=lambda valor: f"data:{valor}",
        normalizar_valor=lambda valor: f"valor:{valor}",
        separar_valores=lambda valor: [parte.strip() for parte in valor.split(";")],
    )

    registro = memoria["123"]
    assert registro["UF"] == ["AL", "AP"]
    assert registro["DATA"] == ["data:09/11/2026", "data:10/11/2026"]
    assert registro["VALOR"] == ["valor:1,00", "valor:2,00"]
    assert registro["CTE / REMESSA"] == ["789", "790"]
    assert registro["CHAVE ARQUIVO"] == ["Sem", "Arquivo", "Válido"]
    assert registro["TOMADOR"] == "Aguardando Conciliação"
