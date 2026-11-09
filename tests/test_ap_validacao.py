from src.services.ufs.ap_validacao import (
    chave_do_texto,
    doc_do_campo_05,
    documentos_dos_pares,
    validar_guia_ap,
)

TXT = (
    "NAO RECEBER APOS: 09/11/2026\n"
    "Chave de Acesso: 33260913121476000122550010001447611862291617\n"
    "Informacoes Complementares: 35260904884082000135570020093542021093542025\n"
)

DACTE = "35260904884082000135570020093542021093542025"
NF_1 = "33260913121476000122550010001447611862291617"

PARES_OK = [("868.902.472-72", "1")]

NFE_MAP = {
    NF_1: {"remetente": "13121476000122", "destinatario": "86890247272"},
    DACTE: {"remetente": "13121476000122", "destinatario": "86890247272"},
}


def test_documentos_dos_pares_pegam_o_par_zero():
    pares = [("868.902.472-72", "1"), ("Sem Arquivo Valido", "Sem Numero")]
    assert documentos_dos_pares(pares) == ["86890247272"]


def test_chave_do_texto_usa_o_rotulo():
    assert chave_do_texto(TXT) == NF_1


def test_chave_do_texto_ignora_dacte_sem_rotulo():
    so_dacte = "Informacoes Complementares: " + DACTE
    assert chave_do_texto(so_dacte) == ""


def test_doc_do_campo_05_para_no_inicio_do_campo_06():
    texto = (
        "05 - Inscricao Estadual/CGC/CPF: 868.902.472-72\n"
        "06 - Data de vencimento: 09/11/2026"
    )
    assert doc_do_campo_05(texto) == "86890247272"


def test_guia_aprovada_pelo_destinatario():
    texto_guia = (
        "05 - Inscricao Estadual/CGC/CPF: 868.902.472-72\n"
        "06 - Data de vencimento: 09/11/2026\n" + TXT
    )
    ok, motivo = validar_guia_ap([], texto_guia, NFE_MAP)
    assert ok, motivo
    assert "destinatario" in motivo


def test_guia_sem_campo_05_fica_incompleta():
    ok, motivo = validar_guia_ap([], TXT, NFE_MAP)
    assert not ok
    assert motivo.startswith("INCOMPLETO: nenhum CPF/CNPJ")


def test_guia_com_remessa_sem_dados_das_partes_informa_limite_da_validacao():
    texto_guia = (
        "05 - Inscricao Estadual/CGC/CPF: 868.902.472-72\n"
        "06 - Data de vencimento: 09/11/2026\n" + TXT
    )
    ok, motivo = validar_guia_ap([], texto_guia, {NF_1: "1"})
    assert ok
    assert "CPF/CNPJ nao validado" in motivo
