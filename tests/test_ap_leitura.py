from src.services.ufs.ap import (
    conferir_origens,
    ler_chave_nfe,
    ler_codigo_barras,
    modelo,
    validar_guia,
)

CAMPO_24 = (
    "NAO RECEBER APOS: 09/11/2026   "
    "Chave de Acesso: 33260913121476000122550010001447611862291617"
)
CAMPO_26 = "85670000003-2 07890463202-9 61109300516-7 50601415000-3"

DACTE = "35260904884082000135570020093542021093542025"
NF_1 = "33260913121476000122550010001447611862291617"
NF_2 = "33260903007331019837570010743112191210443038"


def test_codigo_barras_44_sem_dv():
    codigo = ler_codigo_barras(CAMPO_26)
    assert codigo.original == CAMPO_26
    assert len(codigo.digitos48) == 48
    assert codigo.codigo44 == "85670000003078904632026110930051650601415000"


def test_codigo_barras_bloco_invalido():
    import pytest
    with pytest.raises(ValueError):
        ler_codigo_barras("85670000003-2 07890463202-9")


def test_chave_nfe_ignora_data_do_campo_24():
    assert ler_chave_nfe(CAMPO_24) == NF_1


def test_chave_nfe_rejeita_dacte():
    assert ler_chave_nfe("Dacte: " + DACTE) == ""


def test_modelo_nas_posicoes_21_22():
    assert modelo(NF_1) == "55"
    assert modelo(DACTE) == "57"


def test_conferir_origens_pega_leitura_cruzada():
    import pytest
    codigo = ler_codigo_barras(CAMPO_26)
    with pytest.raises(ValueError):
        conferir_origens(codigo, codigo.codigo44)


def test_guia_aprovada_pelo_destinatario():
    ok, motivo = validar_guia(
        campo05="868.902.472-72",
        chave_guia=NF_1,
        remetente="13121476000122",
        destinatario="86890247272",
        chaves_remessa=[DACTE, NF_1, NF_2],
    )
    assert ok, motivo
    assert "destinatario" in motivo


def test_guia_reprovada_identificador_fora_da_remessa():
    ok, motivo = validar_guia(
        campo05="11122233344",
        chave_guia=NF_1,
        remetente="13121476000122",
        destinatario="86890247272",
        chaves_remessa=[DACTE, NF_1],
    )
    assert not ok
    assert motivo.startswith("QUARENTENA")


def test_remessa_sem_nfe_nao_culpa_a_guia():
    ok, motivo = validar_guia(
        campo05="86890247272",
        chave_guia=NF_1,
        remetente="13121476000122",
        destinatario="86890247272",
        chaves_remessa=[DACTE],
    )
    assert not ok
    assert motivo.startswith("INCOMPLETO")
