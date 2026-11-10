from src.app_legacy import (
    formatar_numero_arquivo,
    formatar_texto_excel,
    limpar_texto_excel,
    normalizar_valor_monetario,
    padronizar_data_ddmmyyyy,
    separar_valores_monetarios,
)
from src.services import report_compilation_service
from src.services.report_compilation_service import (
    RelatorioCompilado,
    atualizar_memoria_termos,
    compilar_relatorio_e_atualizar_dados,
    preparar_dados_relatorio,
)
from src.services.ufs.al import AL_CAMPOS_PLANILHA


def _compilar(termos_map, memoria=None):
    memoria = memoria if memoria is not None else {}
    atualizar_memoria_termos(
        termos_map,
        memoria,
        "10/11/2026 12:00:00",
        limpar_texto=limpar_texto_excel,
        formatar_numero=formatar_numero_arquivo,
        padronizar_data=padronizar_data_ddmmyyyy,
        normalizar_valor=normalizar_valor_monetario,
        separar_valores=separar_valores_monetarios,
    )
    resultado = preparar_dados_relatorio(
        termos_map,
        memoria,
        "10/11/2026 12:00:00",
        limpar_texto=limpar_texto_excel,
        formatar_texto=formatar_texto_excel,
        formatar_numero=formatar_numero_arquivo,
        padronizar_data=padronizar_data_ddmmyyyy,
        normalizar_valor=normalizar_valor_monetario,
        separar_valores=separar_valores_monetarios,
    )
    return resultado, memoria


def _termo(uf="GERAL"):
    return {
        "TERMO_REAL": "123456789",
        "TICKET": ["Local"],
        "UF": [uf],
        "DATA": ["09/11/2026"],
        "VENCIMENTO": ["15/11/2026"],
        "VALOR": ["10,50"],
        "CTE": ["123456789"],
        "CHAVE ARQUIVO": ["1" * 44],
        "DACTE": [],
        "NÚMERO ARQUIVO": ["123"],
        "CODIGO BARRAS ORIGINAL": ["8" * 44],
        "CODIGO BARRAS": ["8" * 44],
        "CPF/CNPJ DA GUIA": ["12345678000190"],
        **{campo: [] for campo in AL_CAMPOS_PLANILHA},
        "STATUS CONFERÊNCIA": "OK",
    }


def test_compila_linhas_cabecalho_e_memoria_de_termo():
    termos_map = {"123456789": _termo("AL")}
    memoria = {
        "123456789": {
            "TICKET": ["456"],
            "TOMADOR": "Cliente",
            "VALOR": ["5,00"],
        }
    }

    resultado, memoria = _compilar(termos_map, memoria)

    item = resultado.itens[0]
    assert item["TICKET"] == "456"
    assert item["TOMADOR"] == "Cliente"
    assert item["VALOR"] == "5,00, 10,50"
    assert item["NÚMERO ARQUIVO"] == "123"
    assert item["DATA PROCESSAMENTO"] == "10/11/2026 12:00:00"
    assert memoria["123456789"]["TICKET"] == ["456"]
    assert len(resultado.cabecalho) == len(resultado.linhas[0])
    assert resultado.cabecalho[-len(AL_CAMPOS_PLANILHA) :] == list(AL_CAMPOS_PLANILHA)
    assert resultado.linhas[0][0] == item["TERMO"]


def test_compilacao_ap_substitui_valor_e_documento_historicos():
    termo = _termo("AP")
    termo["VALOR"] = ["25,00"]
    termo["CPF/CNPJ DA GUIA"] = ["98765432100"]
    memoria_anterior = {
        "123456789": {
            "VALOR": ["100,00"],
            "CPF/CNPJ DA GUIA": ["11111111111"],
        }
    }

    resultado, memoria = _compilar({"AP::guia.pdf::1::Não_localizado": termo}, memoria_anterior)

    assert memoria["123456789"]["VALOR"] == ["25,00"]
    assert memoria["123456789"]["CPF/CNPJ DA GUIA"] == ["98765432100"]
    assert resultado.itens[0]["VALOR"] == "25,00"
    assert resultado.itens[0]["CPF/CNPJ DA GUIA"] == "98765432100"


def test_compilacao_define_status_incompleto_quando_faltam_dados():
    termo = _termo()
    termo["CODIGO BARRAS"] = ["Sem Código"]
    termo["CODIGO BARRAS ORIGINAL"] = ["Sem Código"]
    termo["VENCIMENTO"] = ["Não informado"]
    termo["VALOR"] = ["Não informado"]

    resultado, _ = _compilar({"123456789": termo})

    assert resultado.itens[0]["STATUS CONFERÊNCIA"] == (
        "INCOMPLETO: Sem Código de Barras, Vencimento, Valor"
    )


def test_compilar_relatorio_preserva_ordem_de_persistencia_e_locks(monkeypatch):
    eventos = []
    lock_ativo = []
    resultado_esperado = RelatorioCompilado(
        cabecalho=["A"],
        itens=[{"TERMO": "123456789"}],
        linhas=[["123456789"]],
    )

    class LockVerificavel:
        def __enter__(self):
            lock_ativo.append(True)

        def __exit__(self, *_args):
            lock_ativo.pop()

    def atualizar(*_args, **_kwargs):
        assert lock_ativo == [True]
        eventos.append("atualizar")

    def preparar(*_args, **_kwargs):
        assert lock_ativo == [True]
        eventos.append("preparar")
        return resultado_esperado

    monkeypatch.setattr(
        report_compilation_service, "atualizar_memoria_termos", atualizar
    )
    monkeypatch.setattr(
        report_compilation_service, "preparar_dados_relatorio", preparar
    )
    dados = []
    memoria = {}

    resultado = compilar_relatorio_e_atualizar_dados(
        {},
        memoria,
        dados,
        "10/11/2026 12:00:00",
        lock=LockVerificavel(),
        persistir_memoria=lambda: eventos.append(
            "persistir" if not lock_ativo else "persistir_com_lock"
        ),
        limpar_texto=str,
        formatar_texto=str,
        formatar_numero=str,
        padronizar_data=str,
        normalizar_valor=str,
        separar_valores=lambda valor: [str(valor)],
    )

    assert resultado is resultado_esperado
    assert eventos == ["atualizar", "persistir", "preparar"]
    assert dados == resultado_esperado.itens
    assert lock_ativo == []
