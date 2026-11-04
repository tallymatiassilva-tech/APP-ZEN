from src.services.document_classifier import (
    chave_nfe_valida,
    e_dar_documento,
    e_termo_documento,
)
from src.app_legacy import separar_guias_ap, validar_chaves_ap
from src.utils.text_mono import (
    formatar_numero_arquivo,
    normalizar_valor_monetario,
    padronizar_data_ddmmyyyy,
)


def test_valor():
    assert normalizar_valor_monetario("1.234,56") == "1234,56"
    assert normalizar_valor_monetario("R$ 12,00") == "12,00"


def test_data():
    assert padronizar_data_ddmmyyyy("05/11/26") == "05/11/2026"
    assert padronizar_data_ddmmyyyy("") == "Nao informado"


def test_numero():
    assert formatar_numero_arquivo("320") == "000000320"
    assert formatar_numero_arquivo("") == "Sem Numero"


def test_dar_termo():
    assert e_dar_documento("DOCUMENTO DE ARRECADACAO ESTADUAL DARE 123") is True
    assert e_termo_documento("TERMO DE AVERIGUACAO 123456") is True


def test_chave_invalida():
    assert chave_nfe_valida("1" * 44) is False
    assert chave_nfe_valida("123") is False


def test_ap_split_unico():
    guias = separar_guias_ap("N Controle 12345678 texto guia")
    assert len(guias) == 1 and guias[0][0] == "12345678"


def test_ap_validacao_incompleta():
    assert validar_chaves_ap([], set()).startswith("INCOMPLETO")
