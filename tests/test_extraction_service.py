import pytest

from src.services.extraction_service import extrair_documento


@pytest.mark.parametrize(
    ("uf", "texto", "termo", "vencimento", "valor", "uf_resultado"),
    [
        (
            "AC",
            "NOTIFICAÇÃO DO ICMS Número: 123456 Data de Vencimento: 09/11/2026",
            "123456",
            "09/11/2026",
            "Não informado",
            "AC",
        ),
        (
            "AL",
            "DOCUMENTO DE ARRECADACAO Vencimento do DAR: 09/11/2026 "
            "Valor Total (R$): 1.234,56",
            "Não localizado",
            "09/11/2026",
            "1.234,56",
            "AL",
        ),
        (
            "AM",
            "Controle: 1234567890123 Válido até 09/11/2026 "
            "TOTAL 18 VALOR R$ 1.234,56",
            "1234567890123",
            "09/11/2026",
            "1.234,56",
            "AM",
        ),
        (
            "AP",
            "GOVERNO DO ESTADO DO AMAPÁ N Controle 12345678",
            "12345678",
            "Não informado",
            "Não informado",
            "AP",
        ),
        (
            "MS",
            "DAEMS POSTO: 1 TA: 123456 02 - VENCIMENTO: 09/11/2026 "
            "10 - TOTAL R$ 1.234,56",
            "123456",
            "09/11/2026",
            "1.234,56",
            "MS",
        ),
    ],
)
def test_extrair_documento_preserva_resultados_por_uf(
    uf, texto, termo, vencimento, valor, uf_resultado
):
    resultado = extrair_documento(uf, texto, "amostra.pdf", {})

    assert len(resultado) == 7
    assert resultado[0] == termo
    assert resultado[4] == vencimento
    assert resultado[5] == valor
    assert resultado[6] == uf_resultado


@pytest.mark.parametrize("uf", ["ZZ", ""])
def test_extrair_documento_usa_regra_geral_para_uf_sem_regra_propria(uf):
    resultado = extrair_documento(
        uf,
        "TERMO DE AVERIGUACAO 123456",
        "amostra.pdf",
        {},
    )

    assert resultado[0] == "123456"
    assert resultado[6] == "GERAL"
