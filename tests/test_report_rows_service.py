from src.services.report_rows_service import (
    cabecalho_relatorio,
    linhas_relatorio_conciliacao,
    linhas_relatorio_final,
)
from src.services.ufs.al import AL_CAMPOS_PLANILHA


def _formatar_texto(valor):
    return f"excel:{valor}" if valor else ""


def _padronizar_data(valor):
    return f"data:{valor}" if valor else "Não informado"


def _item():
    return {
        "TERMO": "123",
        "UF": "AL",
        "CPF/CNPJ DA GUIA": "12345678000190",
        "TICKET": "456",
        "STATUS CONFERÊNCIA": "OK",
        "CODIGO BARRAS ORIGINAL": "8" * 44,
        "CODIGO BARRAS": "8" * 44,
        "DATA": "09/11/2026",
        "VENCIMENTO": "15/11/2026",
        "VALOR": "10,00",
        "CTE": "789",
        "CTE / REMESSA": "Sem CTE",
        "CHAVE ARQUIVO": "1" * 44,
        "DACTE": "2" * 44,
        "NÚMERO ARQUIVO": "000000123",
        **{campo: f"campo:{indice}" for indice, campo in enumerate(AL_CAMPOS_PLANILHA)},
    }


def test_cabecalho_preserva_colunas_al_e_ordem():
    cabecalho = cabecalho_relatorio()

    assert cabecalho[:16] == [
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
    ]
    assert cabecalho[16:] == list(AL_CAMPOS_PLANILHA)


def test_linhas_conciliacao_aplica_fallbacks_e_formata_dados():
    item = _item()
    item.pop("DATA PROCESSAMENTO", None)

    linha = linhas_relatorio_conciliacao(
        [item],
        limpar_texto=lambda valor: str(valor).strip(),
        formatar_texto=_formatar_texto,
        padronizar_data=_padronizar_data,
        timestamp=lambda: "timestamp-fallback",
    )[0]

    assert len(linha) == len(cabecalho_relatorio())
    assert linha[2] == "excel:12345678000190"
    assert linha[7:9] == ["data:09/11/2026", "data:15/11/2026"]
    assert linha[10] == "789"
    assert linha[11] == "Aguardando Conciliação"
    assert linha[15] == "timestamp-fallback"
    assert linha[16:] == [f"campo:{i}" for i in range(len(AL_CAMPOS_PLANILHA))]


def test_linhas_relatorio_final_prefere_campos_de_exportacao():
    item = _item()
    item.update(
        {
            "TOMADOR": None,
            "CHAVE ARQUIVO (55)": "chave exportada",
            "DACTE (57)": "dacte exportado",
        }
    )

    linha = linhas_relatorio_final(
        [item],
        limpar_texto=lambda valor: str(valor).strip(),
        formatar_texto=_formatar_texto,
        padronizar_data=_padronizar_data,
        timestamp=lambda: "timestamp-fallback",
    )[0]

    assert len(linha) == len(cabecalho_relatorio())
    assert linha[10] == "789"
    assert linha[11] is None
    assert linha[13:15] == ["chave exportada", "dacte exportado"]
