"""Testes unitários dedicados às regras de extração do Estado do Acre (AC)."""

from src.services.extraction_service import extrair_documento
from src.services.ufs.ac import _extrair_regras_ac


def test_extracao_ac_notificacao_padrao():
    texto = """
    ESTADO DO ACRE
    SECRETARIA DE ESTADO DA FAZENDA - SEFAZ
    NOTIFICAÇÃO DO ICMS Número: 133905
    CNPJ: 11.389.858/0001-06
    Data de Vencimento: 31/10/2026
    Total do ICMS a recolher: R$ 270,00
    858300000025 700000012631 041001822060 093411000004
    Chave de Acesso: 31260911389858000106550080000892171157365591
    """
    nfe_map = {}
    termo, pares, orig, b44, venc, valor, uf = _extrair_regras_ac(texto, "notificacao.pdf", nfe_map)

    assert termo == "133905"
    assert uf == "AC"
    assert venc == "31/10/2026"
    assert valor == "270,00"
    assert "858300000025700000012631041001822060093411000004" in b44
    assert pares == [("31260911389858000106550080000892171157365591", "000089217")]
    assert nfe_map.get("DOC_MS_133905") == "11389858000106"


def test_extracao_ac_processo_ativo_e_ano_dois_digitos():
    texto = """
    GOVERNO DO ESTADO DO ACRE
    Processo Ativo 778899/2026
    Inscrição Estadual: 01.999.888/777-66
    Válido para pagamento até: 15/12/26
    Total: R$ 1.450,50
    858300000012 345678901234 567890123456 789012345678
    Chave NF-e: 12260911389858000106550080000123451157365599
    """
    nfe_map = {}
    termo, pares, orig, b44, venc, valor, uf = _extrair_regras_ac(texto, "guia_ac.pdf", nfe_map)

    assert termo == "778899/2026"
    assert uf == "AC"
    assert venc == "15/12/2026"  # expansão de 26 para 2026
    assert valor == "1.450,50"
    assert pares == [("12260911389858000106550080000123451157365599", "000012345")]
    assert nfe_map.get("DOC_MS_778899/2026") == "0199988877766"


def test_extracao_ac_sem_chave_valida_gera_fallback():
    texto = """
    ESTADO DO ACRE
    VIA BANCO
    Número: 998877
    Data de Vencimento: 05/11/2026
    Total do ICMS a recolher: R$ 500,00
    858300000025 700000012631 041001822060 093411000004
    """
    nfe_map = {}
    termo, pares, _, _, _, _, uf = _extrair_regras_ac(texto, "guia.pdf", nfe_map)

    assert termo == "998877"
    assert uf == "AC"
    assert pares == [("Sem Arquivo Válido", "Sem Número")]


def test_dispatcher_extrair_documento_para_ac():
    texto = """
    GOVERNO DO ESTADO DO ACRE
    NOTIFICAÇÃO DO ICMS Número: 554433
    Data de Vencimento: 20/11/2026
    Total do ICMS a recolher: R$ 320,00
    858300000025 700000012631 041001822060 093411000004
    Chave de Acesso: 31260911389858000106550080000892171157365591
    """
    resultado = extrair_documento("AC", texto, "anexo_ac.pdf", {})
    termo, pares, orig, b44, venc, valor, uf = resultado

    assert uf == "AC"
    assert termo == "554433"
    assert venc == "20/11/2026"
    assert valor == "320,00"
    assert len(pares) == 1
