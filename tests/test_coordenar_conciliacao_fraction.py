"""Testes de regressão para coordenar_conciliacao_fraction."""

from threading import Lock
from unittest.mock import patch

from src.services.fraction_service import (
    PreparacaoItensFraction,
    ResultadoConciliacaoFraction,
    coordenar_conciliacao_fraction,
)


def _rodar(dados, *, cookie="cookie", cache=None, mock_preparacao=None, mock_consultar=None):
    """Utilitário: executa coordenar_conciliacao_fraction com mocks."""
    logs = []
    progresso = []
    cache = cache or {}
    lock = Lock()

    patches = []
    if mock_preparacao is not None:
        patches.append(
            patch(
                "src.services.fraction_service.preparar_itens_pendentes_fraction",
                return_value=mock_preparacao,
            )
        )
    if mock_consultar is not None:
        patches.append(
            patch(
                "src.services.fraction_service.consultar_ctes_fraction_com_retentativas",
                side_effect=mock_consultar,
            )
        )

    for p in patches:
        p.start()
    try:
        resultado = coordenar_conciliacao_fraction(
            dados,
            cookie,
            cache,
            lock,
            ao_log=logs.append,
            ao_progresso=lambda c, t: progresso.append((c, t)),
            deve_cancelar=lambda: False,
        )
    finally:
        for p in patches:
            p.stop()

    return resultado, logs, progresso


def test_base_vazia_sem_cte_retorna_zero():
    """Sem itens pendentes retorna estatísticas zeradas e loga aviso."""
    preparacao_vazia = PreparacaoItensFraction(
        itens_pendentes=[],
        guias_ap_chave_incompleta=[],
        itens_sem_cte=[],
    )
    resultado, logs, _ = _rodar([], mock_preparacao=preparacao_vazia)

    assert isinstance(resultado, ResultadoConciliacaoFraction)
    assert resultado.total == 0
    assert resultado.encontrados == 0
    assert resultado.cookie_expirado is False
    assert any("Nenhum CTe válido" in m for m in logs)


def test_loga_itens_sem_cte():
    """Itens sem CTe devem gerar uma mensagem de log por item."""
    sem_cte = [{"TERMO": "777"}, {"TERMO": "888"}]
    preparacao = PreparacaoItensFraction(
        itens_pendentes=[],
        guias_ap_chave_incompleta=[],
        itens_sem_cte=sem_cte,
    )
    _, logs, _ = _rodar([], mock_preparacao=preparacao)

    assert any("777" in m for m in logs)
    assert any("888" in m for m in logs)


def test_loga_guias_ap_chave_incompleta():
    """Guias AP com chave incompleta devem gerar aviso de conferência manual."""
    incompletas = [{"TERMO": "999", "STATUS CONFERÊNCIA": "chave incompleta"}]
    preparacao = PreparacaoItensFraction(
        itens_pendentes=[],
        guias_ap_chave_incompleta=incompletas,
        itens_sem_cte=[],
    )
    _, logs, _ = _rodar([], mock_preparacao=preparacao)

    assert any("999" in m and "CONFERÊNCIA MANUAL" in m for m in logs)


def test_sem_resultado_fraction_contabilizado():
    """Quando o Fraction não retorna resultado para um CTe, sem_resultado deve ser 1."""
    item_ref = {"TERMO": "111", "CTE / REMESSA": "123456", "TOMADOR": "EmpresaX"}
    preparacao = PreparacaoItensFraction(
        itens_pendentes=[(item_ref, ["123456"])],
        guias_ap_chave_incompleta=[],
        itens_sem_cte=[],
    )

    # consultar_ctes retorna lista vazia (sem resultado)
    def _sem_resultado(ctes, fn_consultar, fn_pausa, fn_pausa2):
        return False, []

    resultado, logs, progresso = _rodar(
        [],
        mock_preparacao=preparacao,
        mock_consultar=_sem_resultado,
    )

    assert resultado.total == 1
    assert resultado.encontrados == 0
    assert resultado.sem_resultado == 1
    assert any("RESUMO CONCILIAÇÃO" in m for m in logs)
    assert (100, 100) in progresso
