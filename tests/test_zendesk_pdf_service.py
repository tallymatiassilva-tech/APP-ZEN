import pytest

from src.services.ufs.al import AL_CAMPOS_PLANILHA
from src.services.zendesk_pdf_service import (
    agregar_registros_ticket,
    analisar_anexo_baixado,
    determinar_uf_ticket,
    extrair_pdfs_dos_comentarios,
    mapear_chaves_nfe_pdf,
    mapear_termo_cte_ticket,
    ordenar_pdfs_nota_primeiro,
    processar_guias_ap_ticket,
    processar_pdfs_ticket,
)

NF_1 = "33260913121476000122550010001447611862291617"
CTE_1 = "35260904884082000135570020093542021093542025"


def test_extrai_pdfs_dos_comentarios_e_ignora_nao_pdf_ou_download_vazio():
    comentarios = [
        {
            "attachments": [
                {"file_name": "nota.PDF", "content_url": "url-nota"},
                {"file_name": "imagem.png", "content_url": "url-imagem"},
                {"file_name": "falha.pdf", "content_url": "url-falha"},
            ]
        },
        {"attachments": [{"file_name": "guia.pdf", "content_url": "url-guia"}]},
    ]
    chamadas_download = []
    conteudos = {
        "url-nota": b"pdf-nota",
        "url-falha": None,
        "url-guia": b"pdf-guia",
    }

    def baixar(url):
        chamadas_download.append(url)
        return conteudos[url], "OK" if conteudos[url] else "falha"

    resultado = extrair_pdfs_dos_comentarios(
        comentarios,
        baixar,
        lambda conteudo: (f"texto-{conteudo.decode()}", "OK"),
    )

    assert chamadas_download == ["url-nota", "url-falha", "url-guia"]
    assert resultado == [
        ("nota.pdf", "texto-pdf-nota", b"pdf-nota"),
        ("guia.pdf", "texto-pdf-guia", b"pdf-guia"),
    ]


def test_mapeia_chaves_nfe_com_numero_do_padrao_principal():
    conteudo = b"conteudo"
    chaves = ["chave-1", "chave-2"]
    chamada = []

    resultado = mapear_chaves_nfe_pdf(
        "NF-e Nº 123.456.789",
        conteudo,
        lambda texto, pdf: chamada.append((texto, pdf)) or chaves,
        lambda numero: f"formatado-{numero}",
    )

    assert chamada == [("NF-e Nº 123.456.789", conteudo)]
    assert resultado == {
        "chave-1": "formatado-123.456.789",
        "chave-2": "formatado-123.456.789",
    }


def test_mapeia_chaves_nfe_com_fallback_de_numero_ou_sem_numero():
    def obter_chaves(_texto, _pdf):
        return ["chave"]

    assert mapear_chaves_nfe_pdf(
        "Documento Nº 123456789",
        b"pdf",
        obter_chaves,
        lambda numero: numero.zfill(9),
    ) == {"chave": "123456789"}
    assert mapear_chaves_nfe_pdf(
        "Documento sem número",
        b"pdf",
        obter_chaves,
        lambda numero: numero,
    ) == {"chave": ""}


def test_ordena_notas_antes_dos_demais_mantendo_ordem():
    pdfs = [
        ("guia.pdf", "texto guia", b"guia"),
        ("nota-1.pdf", "texto nota 1", b"nota1"),
        ("nota-2.pdf", "texto nota 2", b"nota2"),
    ]

    ordenados = ordenar_pdfs_nota_primeiro(
        pdfs, lambda texto, _nome: texto.startswith("texto nota")
    )

    assert [pdf[0] for pdf in ordenados] == ["nota-1.pdf", "nota-2.pdf", "guia.pdf"]


def _analisar_anexo_com_callbacks(conteudo, *, uf_ticket="GERAL", **overrides):
    callbacks = {
        "extrair_texto": lambda _conteudo: (conteudo.decode(), "OK"),
        "identificar_uf": lambda _texto: "GERAL",
        "identificar_layout": lambda *_args, **_kwargs: None,
        "eh_dar": lambda texto: "DAR" in texto,
        "eh_termo": lambda texto: "TERMO" in texto,
        "eh_nota_fiscal": lambda texto, _nome: "DANFE" in texto,
        "extrair_vencimento_valor": lambda _texto: ("09/11/2026", "10,00"),
        "padronizar_data": lambda data: data,
        "documento_vencido": lambda _data: False,
        "extrair_vencimento_nota": lambda _texto: "Não informado",
    }
    callbacks.update(overrides)
    return analisar_anexo_baixado(
        "123",
        "arquivo.pdf",
        conteudo,
        uf_ticket,
        False,
        **callbacks,
    )


def test_classifica_danfe_ap_sem_marcar_guia_ou_vencimento():
    vencimentos_consultados = []

    resultado = _analisar_anexo_com_callbacks(
        "DANFE AMAPÁ".encode(),
        identificar_uf=lambda _texto: "AP",
        eh_dar=lambda _texto: True,
        eh_termo=lambda _texto: True,
        eh_nota_fiscal=lambda _texto, _nome: False,
        documento_vencido=lambda data: vencimentos_consultados.append(data) or True,
    )

    assert resultado["uf_final"] == "AP"
    assert resultado["subpasta"] == "NOTAS"
    assert resultado["is_nota"] is True
    assert resultado["is_dar"] is False
    assert resultado["is_termo"] is False
    assert resultado["is_vencido"] is False
    assert vencimentos_consultados == []


def test_classifica_dar_ap_usa_vencimento_do_layout():
    chamadas_layout = []
    vencimentos_consultados = []

    def identificar_layout(_texto, _nome, **_kwargs):
        chamadas_layout.append(True)
        return {"uf": "AP", "vencimento": "01/01/2020"}

    resultado = _analisar_anexo_com_callbacks(
        "DAR do Amapá".encode(),
        uf_ticket="GERAL",
        identificar_uf=lambda _texto: "GERAL",
        identificar_layout=identificar_layout,
        eh_dar=lambda _texto: True,
        padronizar_data=lambda data: f"data:{data}",
        documento_vencido=lambda data: vencimentos_consultados.append(data) or True,
    )

    assert len(chamadas_layout) == 2
    assert resultado["uf_final"] == "AP"
    assert resultado["subpasta"] == "DAR"
    assert resultado["is_dar"] is True
    assert resultado["vencimento_dar"] == "data:01/01/2020"
    assert resultado["is_vencido"] is True
    assert vencimentos_consultados == ["data:01/01/2020"]


def test_classifica_anexo_nao_pdf_com_estado_do_ticket_e_marca_duplicado():
    resultado = analisar_anexo_baixado(
        "456",
        r"arquivo:final.txt",
        b"conteudo",
        "MS",
        True,
        extrair_texto=lambda _conteudo: pytest.fail("não deve extrair texto"),
        identificar_uf=lambda _texto: pytest.fail("não deve identificar UF"),
        identificar_layout=lambda *_args, **_kwargs: pytest.fail(
            "não deve consultar layout"
        ),
        eh_dar=lambda _texto: pytest.fail("não deve classificar DAR"),
        eh_termo=lambda _texto: pytest.fail("não deve classificar termo"),
        eh_nota_fiscal=lambda *_args: pytest.fail("não deve classificar nota"),
        extrair_vencimento_valor=lambda _texto: pytest.fail(
            "não deve extrair vencimento"
        ),
        padronizar_data=lambda data: data,
        documento_vencido=lambda _data: pytest.fail("não deve validar vencimento"),
        extrair_vencimento_nota=lambda _texto: pytest.fail(
            "não deve extrair vencimento de nota"
        ),
    )

    assert resultado == {
        "tid": "456",
        "nome_limpo": "arquivo_final.txt",
        "conteudo": b"conteudo",
        "uf_final": "MS",
        "subpasta": "OUTROS",
        "is_dar": False,
        "is_termo": False,
        "is_nota": False,
        "is_duplicado": True,
        "is_vencido": False,
        "vencimento_dar": "Não informado",
    }


def test_determina_uf_por_pdf_com_fallback_para_tag_ou_al():
    pdfs = [
        ("geral.pdf", "texto geral", b"1"),
        ("ap.pdf", "texto amapa", b"2"),
    ]

    def identificar(texto):
        return "AP" if texto == "texto amapa" else "GERAL"

    assert determinar_uf_ticket(pdfs, "MS", identificar) == "AP"
    assert determinar_uf_ticket(pdfs[:1], "MS", identificar) == "MS"
    assert determinar_uf_ticket(pdfs[:1], "GERAL", identificar) == "AL"


def test_mapeia_termos_e_ctes_de_ticket_geral():
    texto = "Termo 123456 CTe 35260904884082000135570020093542021093542025"

    mapa, ctes = mapear_termo_cte_ticket(texto, "MS", lambda _: [])

    assert mapa == {"123456": ["35260904884082000135570020093542021093542025"]}
    assert ctes == ["35260904884082000135570020093542021093542025"]


def test_mapeia_remessas_ap_por_linha_e_lista_unica_ordenada():
    chamadas = {
        "12345678 remessa 111": ["111"],
        "87654321 remessa 222": ["222"],
        "12345678 remessa 111\n87654321 remessa 222": ["111", "222"],
    }

    mapa, ctes = mapear_termo_cte_ticket(
        "12345678 remessa 111\n87654321 remessa 222",
        "AP",
        lambda texto: chamadas[texto],
    )

    assert mapa == {"12345678": ["111"], "87654321": ["222"]}
    assert ctes == ["111", "222"]


def test_processa_guia_ap_com_multiplos_pares_e_marca_historico():
    registros = []
    ids = set()
    indices = {}
    logs = []

    processar_guias_ap_ticket(
        "guia",
        "guia.pdf",
        {"nfe": "123"},
        registros,
        ids,
        indices,
        {"12345678": {"UF": ["AP"]}},
        separar_guias=lambda _: [("12345678", "bloco")],
        extrair_documento=lambda *args: (
            "12345678",
            [("chave1", "1"), ("chave2", "2")],
            "original",
            "barras",
            "09/11/2026",
            "10,00",
            "AP",
        ),
        validar_guia=lambda *_: (True, "DOC OK"),
        marcar_processada=lambda status: f"{status} | processada",
        padronizar_data=lambda data: f"data:{data}",
        resumir_nfe_map=lambda _: "nfe-map",
        ao_log=lambda nivel, mensagem: logs.append((nivel, mensagem)),
    )

    assert len(registros) == 2
    assert registros[0] == (
        "12345678",
        [("chave1", "1")],
        "original",
        "barras",
        "data:09/11/2026",
        "10,00",
        "AP",
        "DOC OK | processada",
    )
    assert ids == {"12345678"}
    assert indices == {"12345678": [0, 1]}
    assert logs == [("INFO", "AP-guia: ok=True motivo=DOC OK nfe_map=nfe-map")]


def test_repeticao_de_guia_ap_marca_registros_anteriores_sem_reextrair():
    registros = [
        (
            "12345678",
            [("chave", "1")],
            "original",
            "barras",
            "09/11/2026",
            "1,00",
            "AP",
            "OK",
        )
    ]
    ids = {"12345678"}
    indices = {"12345678": [0]}
    extracoes = []

    processar_guias_ap_ticket(
        "guia repetida",
        "guia.pdf",
        {},
        registros,
        ids,
        indices,
        {},
        separar_guias=lambda _: [("12345678", "bloco")],
        extrair_documento=lambda *args: extracoes.append(args),
        validar_guia=lambda *_: (True, "OK"),
        marcar_processada=lambda status: f"{status} | processada",
        padronizar_data=str,
        resumir_nfe_map=str,
        ao_log=lambda *_: None,
    )

    assert registros[0][-1] == "OK | processada"
    assert extracoes == []


def test_guia_ap_sem_pares_cria_registro_de_fallback():
    registros = []

    processar_guias_ap_ticket(
        "guia sem par",
        "guia.pdf",
        {},
        registros,
        set(),
        {},
        {},
        separar_guias=lambda _: [(None, "bloco")],
        extrair_documento=lambda *_: (
            "Não localizado",
            [],
            "Sem Código",
            "Sem Código",
            "Não informado",
            "Não informado",
            "AP",
        ),
        validar_guia=lambda *_: (False, "INCOMPLETO"),
        marcar_processada=lambda status: status,
        padronizar_data=lambda data: data,
        resumir_nfe_map=lambda _: "{}",
        ao_log=lambda *_: None,
    )

    assert registros[0][1] == [("Sem Arquivo Válido", "Sem Número")]
    assert registros[0][-1] == "INCOMPLETO"


def test_processa_nfe_e_layout_dinamico_e_atualiza_cte_do_termo():
    pdfs = [
        ("nota.pdf", "DANFE NF-e Nº 123", b"nota"),
        ("layout.pdf", "DAR", b"layout"),
    ]
    nfe_map = {}
    registros = []
    mapa_cte = {}
    ctes = []
    resultado = processar_pdfs_ticket(
        pdfs,
        "ZZ",
        nfe_map,
        registros,
        mapa_cte,
        ctes,
        set(),
        {},
        {},
        identificar_uf=lambda _: "ZZ",
        eh_nota_fiscal=lambda _texto, nome: nome == "nota.pdf",
        eh_dar=lambda texto: texto == "DAR",
        eh_termo=lambda texto: texto == "TERMO",
        obter_chaves_nfe=lambda _texto, _pdf: ["chave-nfe"],
        formatar_numero=lambda numero: f"num-{numero}",
        separar_guias_ap=lambda _: [],
        extrair_documento=lambda *_: ("fallback", [], "", "", "", "", "MS"),
        validar_guia_ap=lambda *_: (True, "OK"),
        marcar_ap_processada=str,
        padronizar_data=lambda data: f"data:{data}",
        resumir_nfe_map=lambda _: "{}",
        ao_log=lambda *_: None,
        identificar_layout=lambda _texto, _nome, **_kwargs: {
            "termo": "123456",
            "cod_barras_orig": "original",
            "cod_barras": "barra",
            "vencimento": "10/11/2026",
            "valor": "15,00",
            "pares_documento": [("chave", "1")],
            "uf": "MS",
            "cte": "789",
        },
    )

    assert nfe_map == {"chave-nfe": "num-123"}
    assert resultado.tem_dar_pdf is True
    assert resultado.tem_termo_pdf is False
    assert len(registros) == 1
    assert registros[0] == (
        "123456",
        [("chave", "1")],
        "original",
        "barra",
        "data:10/11/2026",
        "15,00",
        "MS",
        "OK",
    )
    assert mapa_cte == {"123456": ["789"]}
    assert ctes == ["789"]


def test_processa_pdf_sem_layout_delega_extracao_padrao():
    registros = []
    chamadas = []

    resultado = processar_pdfs_ticket(
        [("guia.pdf", "conteudo", b"pdf")],
        "AC",
        {},
        registros,
        {},
        [],
        set(),
        {},
        {},
        identificar_uf=lambda _: "GERAL",
        eh_nota_fiscal=lambda *_: False,
        eh_dar=lambda _: False,
        eh_termo=lambda _: False,
        obter_chaves_nfe=lambda *_: [],
        formatar_numero=str,
        separar_guias_ap=lambda _: [],
        extrair_documento=lambda *args: (
            chamadas.append(args)
            or ("123", [("chave", "1")], "original", "barra", "venc", "valor", "AC")
        ),
        validar_guia_ap=lambda *_: (True, "OK"),
        marcar_ap_processada=str,
        padronizar_data=lambda data: f"data:{data}",
        resumir_nfe_map=lambda _: "{}",
        ao_log=lambda *_: None,
        identificar_layout=lambda *_args, **_kwargs: None,
    )

    assert resultado.tem_dar_pdf is False
    assert resultado.tem_termo_pdf is False
    assert chamadas == [("AC", "conteudo", "guia.pdf", {}, b"pdf")]
    assert registros == [
        ("123", [("chave", "1")], "original", "barra", "data:venc", "valor", "AC", "OK")
    ]


def test_agrega_registros_ap_por_chave_da_nfe_e_associa_cte_e_documento():
    registros = [
        (
            "12345678",
            [(NF_1, "000000001")],
            "original",
            "barra",
            "10/11/2026",
            "5,00",
            "AP",
            "DOC OK",
        ),
        (
            "Não localizado",
            [(NF_1, "000000001")],
            "Sem Código",
            "Sem Código",
            "Não informado",
            "Não informado",
            "AP",
            "DOC OK",
        ),
    ]
    termos_map = {}

    agregar_registros_ticket(
        "ticket-1",
        "09/11/2026",
        registros,
        termos_map,
        {"12345678": ["remessa-1"]},
        ["remessa-1"],
        {"DOC_MS_12345678": "12345678000190"},
        "OK",
        campos_al=AL_CAMPOS_PLANILHA,
        limpar_texto=lambda valor: str(valor or "").strip(),
        formatar_numero=lambda valor: f"fmt-{valor}",
        padronizar_data=lambda valor: f"data:{valor}",
        marcar_ap_processada=lambda status: f"{status} | processada",
    )

    item = termos_map[f"AP::12345678::{NF_1}"]
    assert item["TERMO_REAL"] == "12345678"
    assert item["TICKET"] == ["ticket-1", "ticket-1"]
    assert item["CTE"] == ["remessa-1"]
    assert item["CPF/CNPJ DA GUIA"] == ["12345678000190"]
    assert item["CHAVE ARQUIVO"] == [NF_1]
    assert item["NÚMERO ARQUIVO"] == ["fmt-000000001"]
    assert item["VENCIMENTO"] == ["data:10/11/2026"]
    assert item["STATUS CONFERÊNCIA"] == "DOC OK"


def test_agrega_registros_al_preserva_campos_e_ordena_ctes_do_ticket():
    campos_al = {campo: f"valor-{indice}" for indice, campo in enumerate(AL_CAMPOS_PLANILHA)}
    termo_map = {}

    agregar_registros_ticket(
        "ticket-al",
        "09/11/2026",
        [("123456", [(CTE_1, "123")], "orig", "barra", "10/11/2026", "2,00", "AL", "OK")],
        termo_map,
        {},
        ["cte-2", "cte-1"],
        {"DOC_MS_123456": "12.345.678/0001-90", "AL_CAMPOS_123456": campos_al},
        "OK",
        campos_al=AL_CAMPOS_PLANILHA,
        limpar_texto=lambda valor: str(valor or "").strip(),
        formatar_numero=lambda valor: f"fmt-{valor}",
        padronizar_data=str,
        marcar_ap_processada=str,
    )

    item = termo_map["123456"]
    assert item["CTE"] == ["cte-2", "cte-1"]
    assert item["CPF/CNPJ DA GUIA"] == ["12.345.678/0001-90"]
    assert item["DACTE"] == [CTE_1]
    assert item["NÚMERO ARQUIVO"] == ["fmt-123"]
    for campo, valor in campos_al.items():
        assert item[campo] == [valor]


def test_agrega_registro_ap_sem_termo_usa_chave_por_ticket():
    termos_map = {}

    agregar_registros_ticket(
        "ticket-s/termo",
        "09/11/2026",
        [
            (
                "Não localizado",
                [],
                "Sem Código",
                "Sem Código",
                "Não informado",
                "Não informado",
                "AP",
                "INCOMPLETO",
            )
        ],
        termos_map,
        {},
        [],
        {},
        "OK",
        campos_al=AL_CAMPOS_PLANILHA,
        limpar_texto=lambda valor: str(valor or "").strip(),
        formatar_numero=lambda valor: valor,
        padronizar_data=str,
        marcar_ap_processada=str,
    )

    assert "AP::ticket-s/termo::Linha_0" in termos_map
    assert termos_map["AP::ticket-s/termo::Linha_0"]["TERMO_REAL"] == "Não localizado"
