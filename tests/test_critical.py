from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src import app_legacy
from src.app_legacy import (
    _extrair_campos_al_pdf,
    chave_nfe_valida,
    documento_esta_vencido,
    e_dar_documento,
    e_nota_fiscal,
    e_termo_documento,
    extrair_chaves_nfe_pdf,
    extrair_codigo_barras_pdf,
    extrair_id_controle_ap,
    extrair_numero_termo_pdf,
    extrair_remessas_ap,
    extrair_vencimento_e_valor_pdf,
    extrair_vencimento_nota,
    formatar_texto_excel,
    limpar_texto_excel,
    linha_digitavel_para_codigo_barras,
    separar_guias_ap,
    validar_chaves_ap,
)
from src.app_legacy import (
    formatar_numero_arquivo as formatar_numero_arquivo_legado,
)
from src.app_legacy import (
    padronizar_data_ddmmyyyy as padronizar_data_ddmmyyyy_legado,
)
from src.services import pdf_service
from src.services.attachment_service import (
    calcular_hash_md5,
    determinar_caminho_arquivo_unico,
    determinar_diretorio_anexo,
    determinar_quarentena_al,
    limpar_nome_anexo,
    propagar_vencimento_dar_ap,
)
from src.services.document_classifier import normalizar_documento_fiscal
from src.services.fraction_service import (
    EvidenciasConferenciaFraction,
    armazenar_resultado_cache_fraction,
    atualizar_linha_fraction,
    atualizar_memoria_termo_fraction,
    campo_fraction_vazio,
    coletar_documentos_planilha_originais,
    comparar_evidencias_fraction,
    consultar_ctes_fraction_com_retentativas,
    detectar_rotulo_controle_fraction,
    determinar_status_conferencia_fraction,
    extrair_ctes_busca_fraction,
    extrair_ctes_unicos,
    extrair_dados_tabela_fraction,
    extrair_partes_fraction,
    extrair_resultado_consulta_fraction,
    extrair_texto_pagina_fraction,
    localizar_urls_detalhe_fraction,
    montar_dados_detalhe_fraction,
    montar_dados_fallback_fraction,
    montar_resultado_conferencia_fraction,
    obter_resultado_cache_fraction,
    preencher_campos_fraction,
    preparar_evidencias_conferencia_fraction,
    preparar_formulario_fraction,
    resposta_fraction_indica_login,
    selecionar_resultado_fraction,
)
from src.services.ufs import al as al_service
from src.services.ufs.al import ordenar_pares_documento_por_aparicao
from src.services.ufs.ap import extrair_valor_total_recolher_ap, preparar_codigos_barras_ap
from src.services.ufs.ap_validacao import (
    marcar_status_guia_ap_processada,
)
from src.services.ufs.ap_validacao import (
    validar_chaves_ap as validar_chaves_ap_servico,
)
from src.services.zendesk_auth_service import limpar_e_formatar_cookie
from src.utils.text_mono import (
    formatar_numero_arquivo,
    normalizar_valor_monetario,
    padronizar_data_ddmmyyyy,
    separar_valores_monetarios,
)


def test_valor():
    assert normalizar_valor_monetario("1.234,56") == "1234,56"
    assert normalizar_valor_monetario("R$ 12,00") == "12,00"


def test_extracao_campos_al_legada_usa_servico_com_pdf_sintetico(monkeypatch):
    class SyntheticPage:
        def extract_text(self, visitor_text):
            for texto, x, y in (
                ("Emitente", 20, 100),
                ("Empresa Alfa", 50, 90),
                ("12.345.678/0001-90", 300, 90),
            ):
                visitor_text(
                    texto,
                    None,
                    [0, 0, 0, 0, x, y],
                    None,
                    10,
                )

    monkeypatch.setattr(
        al_service.pypdf,
        "PdfReader",
        lambda *_args, **_kwargs: type(
            "SyntheticReader", (), {"pages": [SyntheticPage()]}
        )(),
    )

    assert _extrair_campos_al_pdf(b"synthetic-pdf") == {
        "EMITENTE - NOME/RAZÃO SOCIAL": "Empresa Alfa",
        "EMITENTE - CPF/CNPJ": "12345678000190",
    }


def test_regra_al_legada_delega_ao_extrator_oficial():
    from src.services.extraction_service import extrair_documento

    texto = (
        "DOCUMENTO DE ARRECADACAO Vencimento do DAR: 09/11/2026 "
        "Valor Total (R$): 1.234,56"
    )
    mapa_legado = {}
    mapa_oficial = {}

    resultado_legado = app_legacy._extrair_regras_al(
        texto, "amostra.pdf", mapa_legado
    )
    resultado_oficial = extrair_documento(
        "AL", texto, "amostra.pdf", mapa_oficial
    )

    assert resultado_legado == resultado_oficial
    assert mapa_legado == mapa_oficial


@pytest.mark.parametrize(
    "texto",
    [
        "DOCUMENTO DE ARRECADACAO Vencimento: 09/11/2026",
        "TERMO DE AVERIGUACAO 123456 Chave "
        "35261112345678000190550010000001231000001234",
    ],
)
def test_regra_geral_legada_delega_sem_alterar_resultado(texto):
    from src.services.extraction_service import extrair_documento

    mapa_legado = {}
    mapa_oficial = {}

    resultado_legado = app_legacy._extrair_regras_geral(
        texto, "amostra.pdf", mapa_legado
    )
    resultado_oficial = extrair_documento(
        "GERAL", texto, "amostra.pdf", mapa_oficial
    )

    assert resultado_legado == resultado_oficial
    assert mapa_legado == mapa_oficial


@pytest.mark.parametrize(
    ("uf", "regra_legada", "texto"),
    [
        (
            "AP",
            app_legacy._extrair_regras_ap,
            "GOVERNO DO ESTADO DO AMAPÁ N Controle 12345678",
        ),
        (
            "AC",
            app_legacy._extrair_regras_ac,
            "NOTIFICAÇÃO DO ICMS Número: 123456 Data de Vencimento: 09/11/2026",
        ),
        (
            "AM",
            app_legacy._extrair_regras_am,
            "Controle: 1234567890123 Válido até 09/11/2026 "
            "TOTAL 18 VALOR R$ 1.234,56",
        ),
        (
            "AM",
            app_legacy._extrair_regras_am,
            "DANFE Chave de acesso "
            "35261112345678000190550010000001231000001234",
        ),
    ],
)
def test_regras_uf_legadas_ap_ac_am_delegam_ao_servico(
    uf, regra_legada, texto
):
    from src.services.extraction_service import extrair_documento

    mapa_legado = {}
    mapa_oficial = {}

    resultado_legado = regra_legada(texto, "amostra.pdf", mapa_legado)
    resultado_oficial = extrair_documento(
        uf, texto, "amostra.pdf", mapa_oficial
    )

    assert resultado_legado == resultado_oficial
    assert mapa_legado == mapa_oficial


def test_dispatcher_legado_delega_extracao_para_servico(monkeypatch):
    chamadas = []
    resultado_esperado = ("123456", [], "", "", "", "", "AP")

    def extrair(uf, texto, nome, nfe_map, pdf_bytes):
        chamadas.append((uf, texto, nome, nfe_map, pdf_bytes))
        return resultado_esperado

    monkeypatch.setattr(app_legacy, "extrair_documento", extrair)
    nfe_map = {"chave": "dados"}
    pdf_bytes = b"synthetic-pdf"

    resultado = app_legacy.extrair_documento_legado(
        "AP", "texto sintético", "amostra.pdf", nfe_map, pdf_bytes
    )

    assert resultado == resultado_esperado
    assert chamadas == [
        ("AP", "texto sintético", "amostra.pdf", nfe_map, pdf_bytes)
    ]


def test_regra_ms_legada_usa_servico_oficial():
    from src.services.ufs.ms import _extrair_regras_ms as extrair_ms_servico

    texto = (
        "DAEMS POSTO: 1 TA: 123456 02 - VENCIMENTO: 09/11/2026 "
        "10 - TOTAL R$ 1.234,56"
    )
    mapa_legado = {}
    mapa_servico = {}

    assert app_legacy._extrair_regras_ms(
        texto, "amostra.pdf", mapa_legado
    ) == extrair_ms_servico(texto, "amostra.pdf", mapa_servico)
    assert mapa_legado == mapa_servico


def test_recorte_pdf_legado_usa_servico_com_pdf_sintetico(monkeypatch):
    class SyntheticCrop:
        def extract_text(self, layout):
            assert layout is True
            return "  trecho recortado  "

    class SyntheticPage:
        width = 200
        height = 100

        def crop(self, box):
            assert box == (20.0, 10.0, 180.0, 90.0)
            return SyntheticCrop()

    class SyntheticPdf:
        pages = [SyntheticPage()]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class SyntheticPdfPlumber:
        @staticmethod
        def open(_stream):
            return SyntheticPdf()

    monkeypatch.setattr(pdf_service, "HAS_PDFPLUMBER", True)
    monkeypatch.setattr(pdf_service, "pdfplumber", SyntheticPdfPlumber)

    assert app_legacy.extrair_texto_por_caixa(
        b"synthetic-pdf", (0.1, 0.1, 0.9, 0.9)
    ) == "trecho recortado"


def test_mesclagem_pdf_legada_delega_ao_servico(monkeypatch):
    class SyntheticReader:
        def __init__(self, stream):
            self.pages = [stream.read()]

    class SyntheticWriter:
        def __init__(self):
            self.pages = []

        def add_page(self, page):
            self.pages.append(page)

        def write(self, output):
            output.write(b"|".join(self.pages))

    monkeypatch.setattr(app_legacy, "log_terminal", lambda *_args: None)
    monkeypatch.setattr(pdf_service.pypdf, "PdfReader", SyntheticReader)
    monkeypatch.setattr(pdf_service.pypdf, "PdfWriter", SyntheticWriter)

    assert app_legacy.mesclar_pdfs([b"pdf-a", b"pdf-b"]) == b"pdf-a|pdf-b"


def test_extracao_pdf_registra_execucao_apenas_uma_vez(monkeypatch):
    class SyntheticPage:
        def extract_text(self, layout):
            assert layout is True
            return None

    class SyntheticPdf:
        pages = [SyntheticPage()]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class SyntheticPdfPlumber:
        @staticmethod
        def open(_stream):
            return SyntheticPdf()

    class SyntheticReader:
        pages = []

        def __init__(self, _stream):
            pass

    logs = []
    monkeypatch.setattr(app_legacy, "log_terminal", lambda *args: logs.append(args))
    monkeypatch.setattr(pdf_service, "HAS_PDFPLUMBER", True)
    monkeypatch.setattr(pdf_service, "pdfplumber", SyntheticPdfPlumber)
    monkeypatch.setattr(
        pdf_service.pypdf,
        "PdfReader",
        SyntheticReader,
    )
    monkeypatch.setattr(pdf_service, "HAS_OCR", False)

    assert app_legacy.extrair_texto_pdf(b"synthetic-pdf") == (
        "",
        "PDF sem texto extraível mesmo com OCR.",
    )
    assert [marcador for marcador, _ in logs] == [
        "INÍCIO",
        "SUCESSO",
        "CONCLUÍDO",
    ]


def test_separar_valores_monetarios_reconstroi_partes_e_remove_repetidos():
    assert separar_valores_monetarios("1.234,56, R$ 12, 34, 12,34") == [
        "1.234,56",
        "12,34",
    ]
    assert separar_valores_monetarios("Não informado") == []
    assert separar_valores_monetarios("") == []


def test_data():
    assert padronizar_data_ddmmyyyy("05/11/26") == "05/11/2026"
    assert padronizar_data_ddmmyyyy("") == "Nao informado"
    assert padronizar_data_ddmmyyyy_legado("") == "Não informado"
    assert padronizar_data_ddmmyyyy_legado("Não Informado") == "Não informado"


def test_documento_esta_vencido_com_datas_passadas_futuras_e_invalidas():
    assert documento_esta_vencido("01/01/2000") is True
    assert documento_esta_vencido("31/12/2999") is False
    assert documento_esta_vencido("data inválida") is False


def test_numero():
    assert formatar_numero_arquivo("320") == "000000320"
    assert formatar_numero_arquivo("") == "Sem Numero"
    assert formatar_numero_arquivo_legado("") == "Sem Número"
    assert formatar_numero_arquivo_legado("Sem Arquivo Válido") == "Sem Número"


def test_limpar_texto_excel_remove_formula_e_apostrofos():
    assert limpar_texto_excel(' = "valor" ') == "valor"
    assert limpar_texto_excel("''' 123 ") == "123"
    assert limpar_texto_excel(None) == ""


def test_formatar_texto_excel_protege_identificadores_numericos():
    assert formatar_texto_excel("001234") == '="001234"'
    assert formatar_texto_excel(" texto ") == "texto"
    assert formatar_texto_excel("Sem Número") == "Sem Número"


def test_limpar_e_formatar_cookie_aceita_cabecalho_comando_e_sessao():
    assert limpar_e_formatar_cookie('Cookie: a=b; Path=/') == "a=b"
    assert limpar_e_formatar_cookie('-H "Cookie: a=b; Path=/"') == "a=b"
    assert limpar_e_formatar_cookie("abcdefghijklm") == "JSESSIONID=abcdefghijklm"
    assert limpar_e_formatar_cookie("curto") == "curto"
    assert limpar_e_formatar_cookie("") == ""


def test_normaliza_cpf_cnpj_sem_validar_digitos_verificadores():
    assert normalizar_documento_fiscal("123.456.789-01") == "12345678901"
    assert normalizar_documento_fiscal("12.345.678/0001-90") == "12345678000190"
    assert normalizar_documento_fiscal("1234567890") == ""
    assert normalizar_documento_fiscal(None) == ""


def test_detecta_rotulo_de_controle_fraction_em_variantes_html():
    soup = BeautifulSoup(
        """
        <form>
          <label for="cte">Número do CTe</label>
          <input id="cte">
          <label>Remetente <input id="remetente"></label>
          <input id="destinatario"> Destinatário
          <table><tr><td>Conhecimento</td><td><input id="busca"></td></tr></table>
        </form>
        """,
        "html.parser",
    )
    form = soup.find("form")

    assert detectar_rotulo_controle_fraction(form, soup.find(id="cte")) == "Número do CTe"
    assert detectar_rotulo_controle_fraction(form, soup.find(id="remetente")) == "Remetente"
    assert detectar_rotulo_controle_fraction(form, soup.find(id="destinatario")) == (
        "Destinatário"
    )
    assert detectar_rotulo_controle_fraction(form, soup.find(id="busca")) == "Conhecimento"


def test_prepara_payload_de_busca_fraction_com_viewstate_radio_e_cte():
    soup = BeautifulSoup(
        """
        <form action="/FractionWeb/jad/pesquisar?execution=e2s1" method="post">
          <input type="hidden" name="frmPesquisa" value="">
          <textarea name="frmPesquisa:cte"></textarea>
          <input type="radio" name="frmPesquisa:tipo" id="tipo-nome" value="nome">
          <label for="tipo-nome">Nome</label>
          <input type="radio" name="frmPesquisa:tipo" id="tipo-cte" value="cte">
          <label for="tipo-cte">Conhecimento</label>
          <input type="hidden" name="javax.faces.ViewState" value="state-token">
          <button type="submit" name="frmPesquisa:id_enviar" value="buscar">Buscar</button>
        </form>
        """,
        "html.parser",
    )

    assert preparar_formulario_fraction(
        soup.find("form"), "https://fraction.example/app", "123456"
    ) == (
        "https://fraction.example/FractionWeb/jad/pesquisar?execution=e2s1",
        "post",
        [
            ("frmPesquisa", ""),
            ("frmPesquisa:cte", "123456"),
            ("frmPesquisa:tipo", "cte"),
            ("javax.faces.ViewState", "state-token"),
            ("frmPesquisa:id_enviar", "buscar"),
        ],
    )


def test_prepara_formulario_fraction_rejeita_login_e_viewstate_ausente():
    login = BeautifulSoup(
        '<form action="/login"><input name="user"></form>', "html.parser"
    ).find("form")
    sem_viewstate = BeautifulSoup(
        '<form><input name="cte"></form>', "html.parser"
    ).find("form")

    assert preparar_formulario_fraction(login, "https://fraction.example", "123") is None
    assert (
        preparar_formulario_fraction(sem_viewstate, "https://fraction.example", "123")
        is None
    )


def test_extrai_dados_fraction_de_tabela_e_filtra_documento_curto():
    soup = BeautifulSoup(
        """
        <table>
          <tr><th>CTE</th><th>Tomador</th><th>Remetente</th>
              <th>Destinatário</th><th>CPF/CNPJ</th></tr>
          <tr><td>999</td><td>Outro</td><td>Origem X</td><td>Destino X</td>
              <td>12.34</td></tr>
          <tr><td>123456</td><td>Cliente A</td><td>Origem A</td>
              <td>Destino A</td><td>12.345.678/0001-90</td></tr>
        </table>
        """,
        "html.parser",
    )

    assert extrair_dados_tabela_fraction(soup, "", "123456") == (
        "Cliente A",
        "Origem A",
        "Destino A",
        ["12345678000190"],
    )


def test_extrai_dados_fraction_por_texto_quando_nao_ha_tabela_correspondente():
    soup = BeautifulSoup(
        "<table><tr><th>CTE</th></tr><tr><td>987</td></tr></table>",
        "html.parser",
    )

    assert extrair_dados_tabela_fraction(
        soup,
        "Tomador: Cliente B Remetente: Origem B Destinatário: Destino B",
        "123456",
    ) == ("Cliente B", "Origem B", "Destino B", [])


def test_localiza_urls_de_detalhe_fraction_por_cte_e_rotulo():
    soup = BeautifulSoup(
        """
        <a href="/consulta/123456">Resultado</a>
        <a href="tracking/987">Acompanhar</a>
        <a href="/consulta">CTe 123456</a>
        <a href="/consulta">Outro link</a>
        """,
        "html.parser",
    )

    assert localizar_urls_detalhe_fraction(
        soup, "https://fraction.example/app/pesquisa", "123456"
    ) == [
        "https://fraction.example/consulta/123456",
        "https://fraction.example/app/tracking/987",
        "https://fraction.example/consulta",
    ]


def test_extrai_texto_pagina_fraction_com_whitespace_normalizado():
    soup, texto = extrair_texto_pagina_fraction(
        b"<html><body><p>Tomador</p><p>  Cliente   A </p></body></html>"
    )

    assert soup.find("p").get_text() == "Tomador"
    assert texto == "Tomador Cliente A "


def test_extrai_resultado_fraction_com_metadados_normais_ou_fallback():
    soup = BeautifulSoup(
        """
        <table>
          <tr><th>CTE</th><th>Tomador</th></tr>
          <tr><td>123456</td><td>Cliente A</td></tr>
        </table>
        """,
        "html.parser",
    )

    tomador, dados = extrair_resultado_consulta_fraction(
        soup, "Texto de detalhe", "123456"
    )
    assert tomador == "Cliente A"
    assert dados["texto_completo"] == "Texto de detalhe"
    assert dados["tomador"] == "Cliente A"

    tomador_fallback, dados_fallback = extrair_resultado_consulta_fraction(
        soup, "Texto tracking", "123456", fallback=True
    )
    assert tomador_fallback == "Cliente A"
    assert dados_fallback["texto_completo"] == "Texto tracking"
    assert dados_fallback["chaves_nfe"] == []


def test_extrai_resultado_fraction_rejeita_tomador_curto():
    soup = BeautifulSoup(
        "<table><tr><th>Tomador</th></tr><tr><td>AB</td></tr></table>",
        "html.parser",
    )

    assert extrair_resultado_consulta_fraction(soup, "", "123456") == (None, {})


def test_identifica_resposta_fraction_de_login_por_url_ou_corpo():
    assert resposta_fraction_indica_login("https://fraction.example/login")
    assert resposta_fraction_indica_login(
        "https://fraction.example/pesquisar", "j_spring_security_check"
    )
    assert not resposta_fraction_indica_login(
        "https://fraction.example/pesquisar", "resultado da pesquisa"
    )


def test_monta_metadados_detalhe_fraction_com_documentos_e_notas():
    def chave_com_modelo(modelo: str) -> str:
        prefixo = ("1" * 20 + modelo + "1" * 21)[:43]
        soma = 0
        peso = 2
        for digito in reversed(prefixo):
            soma += int(digito) * peso
            peso = 2 if peso == 9 else peso + 1
        verificador = 11 - (soma % 11)
        if verificador >= 10:
            verificador = 0
        return prefixo + str(verificador)

    chave_nfe = chave_com_modelo("55")
    chave_cte = chave_com_modelo("57")
    texto = (
        "Nome: Remetente X End.: Rua A Dest.: Destinatário Y Cidade/UF "
        "CNPJ: 12.345.678/0001-90 IE: 12345 "
        f"NF: 42 Dacte: {chave_cte} {chave_nfe}"
    )

    dados = montar_dados_detalhe_fraction(texto, "123456", "Tomador Z")

    assert dados["cte_consultado"] == "123456"
    assert dados["tomador"] == "Tomador Z"
    assert dados["remetente"] == "Remetente X"
    assert dados["destinatario"] == "Destinatário Y"
    assert dados["cnpjs"] == ["12345", "12345678000190"]
    assert dados["chaves_nfe"] == [chave_nfe]
    assert dados["dacte"] == chave_cte
    assert dados["dactes"] == [chave_cte]
    assert set(dados["numeros_notas"]) == {"42", "111111111"}
    assert dados["texto_completo"] == texto


def test_monta_metadados_fallback_fraction_com_campos_opcionais_vazios():
    assert montar_dados_fallback_fraction("Texto tracking", "123456", "Tomador") == {
        "cte_consultado": "123456",
        "tomador": "Tomador",
        "remetente": "",
        "destinatario": "",
        "cnpjs": [],
        "chaves_nfe": [],
        "dacte": "",
        "dactes": [],
        "numeros_notas": [],
        "texto_completo": "Texto tracking",
    }


def test_extrai_partes_fraction_com_fallbacks_dos_metadados():
    texto = (
        "Remetente Nome: Empresa A End.: Rua A CNPJ: 12.345.678/0001-90 "
        "IE: 123.456 Destinatário Dest.: Empresa B End.: Rua B "
        "CPF: 123.456.789-01 IE: 987-65 Nota Fiscal"
    )

    assert extrair_partes_fraction(texto, {}) == {
        "rem_nome": "Empresa A",
        "rem_cnpj": "12345678000190",
        "rem_ie": "123456",
        "dest_nome": "Empresa B",
        "dest_cnpj": "12345678901",
        "dest_ie": "98765",
    }
    assert extrair_partes_fraction(
        "",
        {
            "remetente": "Fallback rem",
            "rem_cnpj": "00123.45",
            "rem_ie": "IE 5",
            "destinatario": "Fallback dest",
            "dest_cnpj": "00987",
            "dest_ie": "IE 6",
        },
    ) == {
        "rem_nome": "Fallback rem",
        "rem_cnpj": "00123.45",
        "rem_ie": "IE 5",
        "dest_nome": "Fallback dest",
        "dest_cnpj": "00987",
        "dest_ie": "IE 6",
    }


def test_prepara_evidencias_de_conferencia_fraction_filtra_e_normaliza():
    chave_nfe = "1" * 6 + "12345678000190" + "55" + "000" + "000000123" + "1" * 10
    chave_cte = "2" * 20 + "57" + "2" * 22
    evidencias = preparar_evidencias_conferencia_fraction(
        {
            "cnpjs": ["12.345.678/0001-90", "inválido"],
            "chaves_nfe": [chave_nfe, chave_cte, "chave curta"],
            "numeros_notas": ["42", "NF 7", ""],
        },
        {
            "CPF/CNPJ DA GUIA": "12.345.678/0001-90",
            "TERMO": "42",
            "CHAVE ARQUIVO": f"{chave_nfe} e {chave_cte}",
            "NÚMERO ARQUIVO": "42, 123, 321",
        },
    )

    assert evidencias.documentos_fraction == {"12345678000190"}
    assert evidencias.documento_guia == "12345678000190"
    assert evidencias.chaves_fraction == {chave_nfe, chave_cte}
    assert evidencias.chaves_guia == {chave_nfe, chave_cte}
    assert evidencias.numeros_fraction == {7, 123}
    assert evidencias.numeros_guia == {123, 321}


def test_compara_evidencias_fraction_preserva_resultado_triestado():
    base = EvidenciasConferenciaFraction(
        documentos_fraction={"11111111111"},
        documento_guia="11111111111",
        chaves_fraction={"chave-fraction"},
        chaves_guia={"chave-guia"},
        numeros_fraction={1, 2},
        numeros_guia={2, 3},
    )
    assert comparar_evidencias_fraction(base, set()) == (True, False, True)

    sem_evidencia_fraction = EvidenciasConferenciaFraction(
        documentos_fraction=set(),
        documento_guia="22222222222",
        chaves_fraction=set(),
        chaves_guia=set(),
        numeros_fraction=set(),
        numeros_guia=set(),
    )
    assert comparar_evidencias_fraction(
        sem_evidencia_fraction, {"22222222222"}
    ) == (True, None, None)
    assert comparar_evidencias_fraction(sem_evidencia_fraction, set()) == (
        None,
        None,
        None,
    )


def test_monta_motivos_e_inconclusivos_de_conferencia_fraction():
    divergente = EvidenciasConferenciaFraction(
        documentos_fraction={"11111111111"},
        documento_guia="22222222222",
        chaves_fraction={"chave-fraction"},
        chaves_guia={"chave-guia"},
        numeros_fraction={1, 2},
        numeros_guia={3},
    )
    motivos, inconclusivos = montar_resultado_conferencia_fraction(divergente, set())
    assert motivos == [
        "Doc da guia (22222222222) não confere com o Fraction",
        "Chave NF-e divergente do CTe",
        "Número NF-e divergente (guia=[3] frac=[1, 2])",
    ]
    assert inconclusivos == []

    sem_evidencias = EvidenciasConferenciaFraction(
        documentos_fraction=set(),
        documento_guia="",
        chaves_fraction=set(),
        chaves_guia=set(),
        numeros_fraction=set(),
        numeros_guia=set(),
    )
    assert montar_resultado_conferencia_fraction(sem_evidencias, set()) == (
        [],
        ["documento", "chave NF-e", "número NF-e"],
    )


def test_determina_status_conferencia_preservando_status_existente():
    assert determinar_status_conferencia_fraction(
        "OK", ["divergência"], ["documento"]
    ) == ("DIVERGÊNCIA CTI (divergência)", True)
    assert determinar_status_conferencia_fraction(
        "OK", [], ["documento"]
    ) == ("CONCILIADO PARCIAL", True)
    for status in ("OK", "Aguardando Conciliação", ""):
        assert determinar_status_conferencia_fraction(status, [], []) == (
            "VALIDADO NO FRACTION",
            True,
        )
    assert determinar_status_conferencia_fraction(
        "REVISÃO MANUAL", [], []
    ) == ("REVISÃO MANUAL", False)


def test_extrai_ctes_de_valores_mistos_sem_repetir():
    assert extrair_ctes_unicos(
        [
            "Sem CTE 123456",
            "123456.0",
            "1.23456789e+8",
            "CTE: 987654321; 123456",
            None,
            "texto sem CTe",
        ]
    ) == ["123456", "123456789", "987654321"]


def test_extrai_ctes_de_busca_fraction_prioriza_coluna_e_remove_repetidos():
    assert extrair_ctes_busca_fraction(
        {
            "CTE / REMESSA": "123456, 123456 987654321",
            "CTE": "111111",
            "DACTE": f"{'1' * 20}57{'2' * 22}",
        }
    ) == ["123456", "987654321"]


def test_extrai_cte_de_chave_dacte_apenas_quando_nao_ha_cte_na_planilha():
    dacte = f"{'1' * 20}57{'2' * 22}"
    nfe = f"{'3' * 20}55{'4' * 22}"

    assert extrair_ctes_busca_fraction(
        {"CTE / REMESSA": "", "CTE": "", "DACTE": f"{dacte}, {dacte}, {nfe}"}
    ) == [dacte]


def test_obtem_resultado_cache_fraction_apenas_quando_tomador_existe():
    assert obter_resultado_cache_fraction(
        {"123456": ("Tomador", {"texto_completo": "dados"})}, "123456"
    ) == ("Tomador", {"texto_completo": "dados"})
    assert obter_resultado_cache_fraction({"123456": (None, {})}, "123456") is None
    assert obter_resultado_cache_fraction({"123456": "valor inválido"}, "123456") is None
    assert obter_resultado_cache_fraction({}, "123456") is None


def test_armazena_resultado_cache_fraction_no_formato_compartilhado():
    cache = {}
    metadados = {"texto_completo": "Resultado"}

    armazenar_resultado_cache_fraction(cache, "123456", "Tomador", metadados)

    assert cache == {"123456": ("Tomador", metadados)}


def test_seleciona_primeiro_resultado_fraction_preservando_prioridade():
    primeiro = ("123456", "Tomador A", {"texto_completo": "A"})
    segundo = ("987654", "Tomador B", {"texto_completo": "B"})

    assert selecionar_resultado_fraction([primeiro, segundo]) == primeiro
    assert selecionar_resultado_fraction([]) is None


def test_consulta_ctes_fraction_repete_duas_vezes_e_preserva_ordem():
    respostas = iter(
        [
            ("111111", None, {}),
            ("111111", "Tomador A", {"id": "A"}),
            ("222222", "Tomador B", {"id": "B"}),
        ]
    )
    consultas = []
    pausas = []

    def consultar(cte):
        consultas.append(cte)
        return next(respostas)

    cookie_expirado, resultados = consultar_ctes_fraction_com_retentativas(
        ["111111", "222222"],
        consultar,
        lambda: pausas.append("entre"),
        lambda: pausas.append("retry"),
    )

    assert not cookie_expirado
    assert consultas == ["111111", "111111", "222222"]
    assert pausas == ["entre", "retry", "entre"]
    assert resultados == [
        ("111111", "Tomador A", {"id": "A"}),
        ("222222", "Tomador B", {"id": "B"}),
    ]


def test_consulta_ctes_fraction_para_imediatamente_com_cookie_expirado():
    consultas = []

    def consultar(cte):
        consultas.append(cte)
        return cte, "COOKIE_EXPIRADO", {}

    cookie_expirado, resultados = consultar_ctes_fraction_com_retentativas(
        ["111111", "222222"],
        consultar,
        lambda: None,
        lambda: None,
    )

    assert cookie_expirado
    assert resultados == []
    assert consultas == ["111111"]


def test_identifica_placeholders_vazios_de_fraction_sem_sobrescrever_valores():
    for valor in (
        None,
        "",
        "  ",
        "None",
        " nan ",
        "Sem DACTE",
        "Sem Número",
        "Sem Arquivo Válido",
        "Sem Código",
        "Não informado",
        "Aguardando Conciliação",
    ):
        assert campo_fraction_vazio(valor) is True

    for valor in ("0", "Sem numero", "não informado", "Nome já preenchido"):
        assert campo_fraction_vazio(valor) is False


def test_coleta_documentos_originais_apenas_para_status_elegiveis():
    item = {
        "EMITENTE - CPF/CNPJ": "12.345.678/0001-90",
        "DESTINATÁRIO - CPF/CNPJ": "123.456.789-01",
    }
    esperados = {"12345678000190", "12345678901"}
    assert coletar_documentos_planilha_originais(item, "OK") == esperados
    assert coletar_documentos_planilha_originais(item, "Aguardando Conciliação") == esperados
    assert coletar_documentos_planilha_originais(item, "") == esperados
    assert coletar_documentos_planilha_originais(item, "DIVERGÊNCIA CTI") == set()
    assert coletar_documentos_planilha_originais({}, "OK") == set()


def test_atualiza_memoria_termo_fraction_apenas_quando_termo_existe():
    campos = {
        "EMITENTE - NOME/RAZÃO SOCIAL": "Empresa A",
        "EMITENTE - CPF/CNPJ": "12345678000190",
        "EMITENTE - IE": "",
        "DESTINATÁRIO - NOME/RAZÃO SOCIAL": "Empresa B",
        "DESTINATÁRIO - CPF/CNPJ": None,
        "DESTINATÁRIO - IE": "98765",
    }
    memoria = {"T-1": {"OUTRO": "mantido"}}

    atualizar_memoria_termo_fraction(memoria, "T-1", campos, "Tomador", "Dacte")
    assert memoria["T-1"] == {
        "OUTRO": "mantido",
        "TOMADOR": "Tomador",
        "DACTE": ["Dacte"],
        "EMITENTE - NOME/RAZÃO SOCIAL": ["Empresa A"],
        "EMITENTE - CPF/CNPJ": ["12345678000190"],
        "DESTINATÁRIO - NOME/RAZÃO SOCIAL": ["Empresa B"],
        "DESTINATÁRIO - IE": ["98765"],
    }

    antes = dict(memoria)
    atualizar_memoria_termo_fraction(memoria, "inexistente", campos, "Outro", "")
    assert memoria == antes


def test_preenche_campos_fraction_sem_sobrescrever_valores_existentes():
    item = {
        "TOMADOR": "Anterior",
        "DACTE": "Sem DACTE",
        "EMITENTE - NOME/RAZÃO SOCIAL": "Nome mantido",
        "EMITENTE - CPF/CNPJ": "",
        "EMITENTE - IE": None,
        "DESTINATÁRIO - NOME/RAZÃO SOCIAL": "Sem Número",
        "DESTINATÁRIO - CPF/CNPJ": "CNPJ existente",
        "DESTINATÁRIO - IE": "",
    }

    preencher_campos_fraction(
        item,
        "Tomador novo",
        "12345678901234567890123456789012345678901234",
        {
            "rem_nome": "Remetente novo",
            "rem_cnpj": "12.345.678/0001-90",
            "rem_ie": "IE 123-45",
            "dest_nome": "Destinatário novo",
            "dest_cnpj": "98.765.432/0001-10",
            "dest_ie": "98.765",
        },
    )

    assert item == {
        "TOMADOR": "Tomador novo",
        "DACTE": '="12345678901234567890123456789012345678901234"',
        "EMITENTE - NOME/RAZÃO SOCIAL": "Nome mantido",
        "EMITENTE - CPF/CNPJ": "12345678000190",
        "EMITENTE - IE": "12345",
        "DESTINATÁRIO - NOME/RAZÃO SOCIAL": "Destinatário novo",
        "DESTINATÁRIO - CPF/CNPJ": "CNPJ existente",
        "DESTINATÁRIO - IE": "98765",
    }


def test_atualiza_linha_fraction_coleta_documentos_antes_do_preenchimento():
    item = {
        "STATUS CONFERÊNCIA": "OK",
        "EMITENTE - CPF/CNPJ": "12.345.678/0001-90",
        "DESTINATÁRIO - CPF/CNPJ": "",
        "TOMADOR": "",
    }

    documentos_originais = atualizar_linha_fraction(
        item,
        item["STATUS CONFERÊNCIA"],
        "Tomador",
        "",
        {
            "rem_nome": "",
            "rem_cnpj": "",
            "rem_ie": "",
            "dest_nome": "",
            "dest_cnpj": "123.456.789-01",
            "dest_ie": "",
        },
    )

    assert documentos_originais == {"12345678000190"}
    assert item["DESTINATÁRIO - CPF/CNPJ"] == "12345678901"
    assert item["TOMADOR"] == "Tomador"


def test_dar_termo():
    assert e_dar_documento("DOCUMENTO DE ARRECADACAO ESTADUAL DARE 123") is True
    assert e_termo_documento("TERMO DE AVERIGUACAO 123456") is True


def test_classificacao_preserva_variantes_acentuadas():
    assert e_termo_documento("TERMO DE APREENSÃO") is True
    assert e_termo_documento("TERMO DE VERIFICAÇÃO FISCAL") is True
    assert e_nota_fiscal(
        "CHAVE DE ACESSO PROTOCOLO DE AUTORIZAÇÃO", "download.pdf"
    ) is True


def test_extrai_boleto_47_digitos_e_preserva_placeholders():
    linha = "12345.12345 12345.123456 12345.123456 1 12345678901234"

    original, codigo = extrair_codigo_barras_pdf(f"DARE {linha}")

    assert original == linha
    assert codigo == "12341123456789012345123412345123451234512345"
    assert linha_digitavel_para_codigo_barras("") == "Sem Código"
    assert extrair_codigo_barras_pdf("texto sem guia") == ("Sem Código", "Sem Código")


def test_extrai_vencimento_valor_e_numero_do_termo():
    texto_dar = (
        "DARE 07 - Data de Vencimento: 01/02/2026 "
        "14 - TOTAL A RECOLHER R$ 1.234,56"
    )

    assert extrair_vencimento_e_valor_pdf(texto_dar) == ("01/02/2026", "1.234,56")
    assert (
        extrair_numero_termo_pdf("TERMO DE APREENSÃO Nº 123456", "documento.pdf")
        == "123456"
    )


def test_extrai_vencimento_nota_com_barra_hifen_e_sem_data():
    assert extrair_vencimento_nota("Vencimento: 09/11/2026") == "09/11/2026"
    assert extrair_vencimento_nota("Validade até 09-11-26") == "09/11/2026"
    assert extrair_vencimento_nota("sem informação de validade") == "Não informado"


def test_extrai_valor_total_ap_com_padrao_alternativo_e_fallback():
    assert extrair_valor_total_recolher_ap("14 - TOTAL A RECOLHER R$ 1.234,56") == (
        "1234,56"
    )
    assert extrair_valor_total_recolher_ap("10 - Valor Principal: 45.67") == "45,67"
    assert extrair_valor_total_recolher_ap("taxa 10,00 e total 99,50") == "99,50"
    assert extrair_valor_total_recolher_ap("") == "Não informado"


def test_determina_diretorio_anexo_prioriza_regras_ap_e_quarentena():
    assert determinar_diretorio_anexo(
        "saida", "AP", "TERMO", True, True, True, True, True
    ) == Path("saida") / "AP" / "DUPLICADOS"
    assert determinar_diretorio_anexo(
        "saida", "AP", "DAR", True, False, False, True, False
    ) == Path("saida") / "AP" / "VENCIDAS"
    assert determinar_diretorio_anexo(
        "saida", "AL", "DAR", True, False, False, False, True
    ) == Path("saida") / "AL" / "QUARENTENA"
    assert determinar_diretorio_anexo(
        "saida", "AL", "ANEXOS", False, True, False, False, False
    ) == Path("saida") / "NOTAS"


def test_helpers_de_anexo_hash_e_sanitizacao_preservam_comportamento():
    assert calcular_hash_md5(b"abc") == "900150983cd24fb0d6963f7d28e17f72"
    assert limpar_nome_anexo(r"arquivo\ruim/:*?.pdf") == "arquivo_ruim____.pdf"


def test_determina_nome_de_arquivo_sem_sobrescrever(tmp_path):
    assert determinar_caminho_arquivo_unico(tmp_path, "anexo.pdf") == (
        tmp_path / "anexo.pdf"
    )

    (tmp_path / "anexo.pdf").touch()
    (tmp_path / "anexo_1.pdf").touch()
    assert determinar_caminho_arquivo_unico(tmp_path, "anexo.pdf") == (
        tmp_path / "anexo_2.pdf"
    )


def test_quarentena_al_considera_documentos_unicos_e_indica_falta():
    anexos = [
        {"is_dar": True, "is_termo": False, "is_duplicado": False},
        {"is_dar": False, "is_termo": True, "is_duplicado": True},
    ]

    assert determinar_quarentena_al("AL", anexos) == (True, "Falta Termo")
    assert determinar_quarentena_al("AP", anexos) == (False, None)
    assert determinar_quarentena_al("AL", []) == (False, None)
    assert determinar_quarentena_al(
        "AL",
        [
            {"is_dar": True, "is_termo": False, "is_duplicado": True},
            {"is_dar": False, "is_termo": True, "is_duplicado": True},
        ],
    ) == (False, None)
    assert determinar_quarentena_al(
        "AL", [{"is_dar": False, "is_termo": True, "is_duplicado": False}]
    ) == (True, "Falta Guia (DAR)")
    assert determinar_quarentena_al(
        "AL",
        [
            {"is_dar": True, "is_termo": False, "is_duplicado": False},
            {"is_dar": False, "is_termo": True, "is_duplicado": False},
        ],
    ) == (False, None)


def test_vencimento_dar_ap_se_propaga_para_guia_e_nota_apenas():
    anexos = [
        {
            "uf_final": "AP",
            "is_dar": True,
            "is_nota": False,
            "is_duplicado": False,
            "is_vencido": True,
        },
        {
            "uf_final": "AP",
            "is_dar": False,
            "is_nota": True,
            "is_duplicado": False,
            "is_vencido": False,
        },
        {
            "uf_final": "AP",
            "is_dar": True,
            "is_nota": False,
            "is_duplicado": True,
            "is_vencido": False,
        },
        {
            "uf_final": "AL",
            "is_dar": True,
            "is_nota": False,
            "is_duplicado": False,
            "is_vencido": False,
        },
    ]

    propagar_vencimento_dar_ap("AP", anexos)

    assert [item["is_vencido"] for item in anexos] == [True, True, True, False]

    anexos_sem_dar_vencido = [
        {
            "uf_final": "AP",
            "is_dar": True,
            "is_nota": False,
            "is_duplicado": False,
            "is_vencido": False,
        },
        {
            "uf_final": "AP",
            "is_dar": False,
            "is_nota": True,
            "is_duplicado": False,
            "is_vencido": True,
        },
    ]
    propagar_vencimento_dar_ap("AP", anexos_sem_dar_vencido)
    assert [item["is_vencido"] for item in anexos_sem_dar_vencido] == [False, False]


def test_ordena_pares_por_aparicao_deduplica_e_preserva_chaves_ausentes():
    pares = [
        ("chave-b", "2"),
        ("chave-a", "1"),
        ("chave-b", "2"),
        ("Sem Arquivo Válido", "Sem Número"),
    ]

    assert ordenar_pares_documento_por_aparicao(
        "chave-a primeiro, depois chave-b", pares
    ) == [
        ("chave-a", "1"),
        ("chave-b", "2"),
        ("Sem Arquivo Válido", "Sem Número"),
    ]


def test_prepara_codigo_barras_ap_preserva_original_e_converte_codigo():
    digitos48 = "85620000006" + "1" * 37
    original_formatado = (
        "85620000006-1 11111111111-1 11111111111-1 11111111111-1"
    )
    codigo44 = "85620000006" + "1" * 33

    assert preparar_codigos_barras_ap(digitos48, "") == (original_formatado, codigo44)
    assert preparar_codigos_barras_ap("  original  ", " 1234 ") == ("original", " 1234 ")


def test_chave_invalida():
    assert chave_nfe_valida("1" * 44) is False
    assert chave_nfe_valida("123") is False


def test_extrai_chave_nfe_valida_formatada_sem_duplicatas():
    chave = "35191111111111111111550010000000011000000012"
    texto = f"Chave: {chave[:4]} {chave[4:]} e repetida: {chave}"

    assert chave_nfe_valida(chave) is True
    assert extrair_chaves_nfe_pdf(texto) == [chave]


def test_ap_split_unico():
    guias = separar_guias_ap("N Controle 12345678 texto guia")
    assert len(guias) == 1 and guias[0][0] == "12345678"


def test_ap_split_multiplos_controles_e_remove_repetidos():
    texto = (
        "Cabeçalho\n18 - N Controle: 12345678\nGuia A\n"
        "18 - N Controle: 87654321\nGuia B\n"
        "18 - N Controle: 12345678\nDuplicata"
    )

    guias = separar_guias_ap(texto)

    assert [controle for controle, _ in guias] == ["12345678", "87654321"]
    assert "Guia A" in guias[0][1]
    assert "Guia B" in guias[1][1]
    assert extrair_id_controle_ap("Controle: 87654321") == "87654321"


def test_ap_extrai_remessas_sem_confundir_documento_fiscal():
    texto = (
        "CTE: 12345678901234\n"
        "Remessa 12345678901234\n"
        "CNPJ: 11222333000181\n"
        "Minuta: 87654321098765"
    )

    assert extrair_remessas_ap(texto) == ["12345678901234", "87654321098765"]


def test_ap_validacao_incompleta():
    assert validar_chaves_ap([], set()).startswith("INCOMPLETO")


def test_validacao_chaves_ap_correspondente_e_divergente():
    chave_guia = "35191111111111111111550010000000011000000012"
    outra_chave = "35191111111111111111550010000000011000000020"
    pares = [(chave_guia, "000000001")]

    assert validar_chaves_ap_servico(pares, {chave_guia}) == "DOC OK"
    assert validar_chaves_ap_servico(pares, {outra_chave}) == (
        "QUARENTENA: chave da guia diverge da NF-e"
    )


def test_ap_status_processada_e_idempotente():
    assert marcar_status_guia_ap_processada("OK") == "GUIA JÁ PROCESSADA"
    assert marcar_status_guia_ap_processada("QUARENTENA") == (
        "QUARENTENA | GUIA JÁ PROCESSADA"
    )
    assert marcar_status_guia_ap_processada("GUIA JÁ PROCESSADA") == (
        "GUIA JÁ PROCESSADA"
    )
