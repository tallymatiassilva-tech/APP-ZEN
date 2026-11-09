import pytest

from src.services import zendesk_pdf_service
from src.services.ufs.al import AL_CAMPOS_PLANILHA
from src.services.zendesk_pdf_service import (
    ResultadoTicketPlanilha,
    agregar_registros_ticket,
    analisar_anexo_baixado,
    baixar_e_analisar_anexos_ticket,
    coletar_anexos_ticket,
    determinar_uf_ticket,
    extrair_pdfs_dos_comentarios,
    identificar_uf_ticket,
    mapear_chaves_nfe_pdf,
    mapear_termo_cte_ticket,
    ordenar_pdfs_nota_primeiro,
    processar_anexos_ticket,
    processar_e_agregar_ticket_para_planilha,
    processar_e_salvar_anexos_ticket,
    processar_guias_ap_ticket,
    processar_pdfs_ticket,
    processar_ticket_para_planilha,
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


def test_coleta_anexos_de_descricao_e_comentarios_preservando_ordem():
    comentario_anexos = [
        {"file_name": "nota.pdf", "content_url": "url-nota"},
        {"file_name": "imagem.png", "content_url": "url-imagem"},
    ]

    anexos = coletar_anexos_ticket(
        {
            "description": (
                "Veja https://example.com/attachments/first.pdf e "
                "https://example.com/attachment/second?download=1"
            )
        },
        [{"attachments": comentario_anexos}, {"attachments": [{"file_name": "guia.pdf"}]}],
        "789",
    )

    assert anexos == [
        {
            "file_name": "anexo_789.pdf",
            "content_url": "https://example.com/attachments/first.pdf",
        },
        {
            "file_name": "anexo_789.pdf",
            "content_url": "https://example.com/attachment/second?download=1",
        },
        *comentario_anexos,
        {"file_name": "guia.pdf"},
    ]
    assert anexos[2] is comentario_anexos[0]


def test_coleta_anexos_sem_descricao_retorna_anexos_dos_comentarios():
    comentario = {"attachments": [{"file_name": "guia.pdf", "content_url": "url"}]}

    assert coletar_anexos_ticket({}, [comentario], "789") == comentario["attachments"]


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


def test_baixa_anexos_em_paralelo_e_detecta_duplicatas_entre_lotes():
    downloads = {
        "url-1": (b"conteudo-repetido", "OK"),
        "url-2": (b"conteudo-repetido", "OK"),
        "url-falha": (None, "HTTP 404"),
    }
    erros = []
    duplicados = []
    analisados = []
    hashes_baixados = set()

    def analisar(ticket_id, nome, conteudo, uf, duplicado):
        resultado = (ticket_id, nome, conteudo, uf, duplicado)
        analisados.append(resultado)
        return resultado

    primeiro_lote = baixar_e_analisar_anexos_ticket(
        [
            {"file_name": "a.pdf", "content_url": "url-1"},
            {"file_name": "b.pdf", "content_url": "url-2"},
            {"file_name": "falha.pdf", "content_url": "url-falha"},
        ],
        "ticket-1",
        "AP",
        hashes_baixados,
        cancelar=lambda: False,
        baixar_conteudo=lambda url: downloads[url],
        analisar_anexo=analisar,
        ao_erro_download=lambda nome, ticket, status: erros.append((nome, ticket, status)),
        ao_detectar_duplicado=lambda nome, ticket: duplicados.append((nome, ticket)),
        max_workers=3,
    )

    segundo_lote = baixar_e_analisar_anexos_ticket(
        [{"file_name": "c.pdf", "content_url": "url-1"}],
        "ticket-2",
        "AP",
        hashes_baixados,
        cancelar=lambda: False,
        baixar_conteudo=lambda url: downloads[url],
        analisar_anexo=analisar,
        ao_erro_download=lambda nome, ticket, status: erros.append((nome, ticket, status)),
        ao_detectar_duplicado=lambda nome, ticket: duplicados.append((nome, ticket)),
    )

    assert len(primeiro_lote) == 2
    assert sorted(resultado[4] for resultado in primeiro_lote) == [False, True]
    assert segundo_lote == [("ticket-2", "c.pdf", b"conteudo-repetido", "AP", True)]
    assert erros == [("falha.pdf", "ticket-1", "HTTP 404")]
    assert len(duplicados) == 2
    assert len(analisados) == 3


def test_baixa_anexos_cancelados_sem_iniciar_download():
    chamadas_download = []
    resultado = baixar_e_analisar_anexos_ticket(
        [{"file_name": "a.pdf", "content_url": "url"}],
        "ticket-1",
        "AL",
        set(),
        cancelar=lambda: True,
        baixar_conteudo=lambda url: chamadas_download.append(url) or (b"pdf", "OK"),
        analisar_anexo=lambda *_args: pytest.fail("não deve analisar anexo cancelado"),
        ao_erro_download=lambda *_args: pytest.fail("não deve registrar erro de download"),
        ao_detectar_duplicado=lambda *_args: pytest.fail("não deve detectar duplicata"),
    )

    assert resultado == []
    assert chamadas_download == []


def test_processa_anexos_ticket_coleta_classifica_e_define_quarentena():
    downloads = {
        "https://example.com/attachment/guia.pdf": (b"dar", "OK"),
        "url-comentario": (b"outro", "OK"),
    }

    resultado = processar_anexos_ticket(
        "ticket-123",
        {"description": "Comprovante: https://example.com/attachment/guia.pdf"},
        [
            {
                "attachments": [
                    {"file_name": "outro.pdf", "content_url": "url-comentario"}
                ]
            }
        ],
        "AL",
        set(),
        cancelar=lambda: False,
        baixar_conteudo=lambda url: downloads[url],
        analisar_anexo=lambda ticket_id, nome, conteudo, uf, duplicado: {
            "tid": ticket_id,
            "nome": nome,
            "uf_final": uf,
            "is_dar": nome == "anexo_ticket-123.pdf",
            "is_termo": False,
            "is_nota": False,
            "is_duplicado": duplicado,
            "is_vencido": False,
        },
        ao_erro_download=lambda *_args: pytest.fail("download deveria ter sucesso"),
        ao_detectar_duplicado=lambda *_args: pytest.fail("anexos são únicos"),
    )

    assert {anexo["nome"] for anexo in resultado.anexos} == {
        "anexo_ticket-123.pdf",
        "outro.pdf",
    }
    assert resultado.em_quarentena is True
    assert resultado.motivo_quarentena == "Falta Termo"


def test_processa_e_salva_anexos_do_ticket_mantendo_ordem_da_quarentena(monkeypatch):
    eventos = []
    ticket = {"tags": ["ap"]}
    resultado_anexos = zendesk_pdf_service.ResultadoAnexosTicket(
        anexos=[{"nome_limpo": "guia.pdf"}],
        em_quarentena=True,
        motivo_quarentena="Falta Termo",
    )
    monkeypatch.setattr(
        zendesk_pdf_service,
        "processar_anexos_ticket",
        lambda *args, **kwargs: eventos.append(("processar", args, kwargs))
        or resultado_anexos,
    )
    monkeypatch.setattr(
        zendesk_pdf_service,
        "salvar_anexos_processados",
        lambda *args: eventos.append(("salvar", args)),
    )
    resultado = processar_e_salvar_anexos_ticket(
        "ticket-123",
        "destino",
        set(),
        obter_ticket=lambda ticket_id: eventos.append(("ticket", ticket_id)) or ticket,
        obter_comentarios=lambda ticket_id: eventos.append(("comentarios", ticket_id))
        or [],
        identificar_uf=lambda dados: eventos.append(("uf", dados)) or "AP",
        cancelar=lambda: False,
        baixar_conteudo=lambda _url: (b"pdf", "OK"),
        analisar_anexo=lambda *_args: None,
        ao_erro_download=lambda *_args: None,
        ao_detectar_duplicado=lambda *_args: None,
        ao_entrar_quarentena=lambda ticket_id, _resultado: eventos.append(
            ("quarentena", ticket_id)
        ),
    )

    assert resultado == ("AP", resultado_anexos)
    assert [evento[0] for evento in eventos] == [
        "ticket",
        "uf",
        "comentarios",
        "processar",
        "quarentena",
        "salvar",
    ]
    assert eventos[-1][1] == ("destino", resultado_anexos.anexos, True)


def test_processa_ticket_de_anexos_ausente_sem_buscar_comentarios_ou_salvar():
    chamadas = []

    resultado = processar_e_salvar_anexos_ticket(
        "ticket-ausente",
        "destino",
        set(),
        obter_ticket=lambda _ticket_id: None,
        obter_comentarios=lambda _ticket_id: chamadas.append("comentarios") or [],
        identificar_uf=lambda _ticket: chamadas.append("uf") or "AL",
        cancelar=lambda: False,
        baixar_conteudo=lambda _url: (None, "HTTP 404"),
        analisar_anexo=lambda *_args: None,
        ao_erro_download=lambda *_args: None,
        ao_detectar_duplicado=lambda *_args: None,
        ao_entrar_quarentena=lambda *_args: None,
    )

    assert resultado is None
    assert chamadas == []


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


@pytest.mark.parametrize(
    ("ticket", "texto_pdf", "esperado"),
    [
        ({"tags": ["ms"]}, "GOVERNO DO ESTADO DO AMAPÁ", "AP"),
        (None, "SEFAZ/SP", "SP"),
        (None, "SEFAZ/XX UF=MG", "MG"),
        ({"tags": ["sp", "pa"]}, "", "PA"),
        ({"tags": ["estado_invalido"]}, "", "GERAL"),
        (None, "SEFAZ/XX UF=XX", "GERAL"),
    ],
)
def test_identifica_uf_por_texto_pdf_e_tags_do_ticket(ticket, texto_pdf, esperado):
    assert identificar_uf_ticket(ticket, texto_pdf) == esperado


def test_mapeia_termos_e_ctes_de_ticket_geral():
    texto = "Termo 123456 CTe 35260904884082000135570020093542021093542025"

    mapa, ctes = mapear_termo_cte_ticket(texto, "MS", lambda _: [])

    assert mapa == {"123456": ["35260904884082000135570020093542021093542025"]}
    assert ctes == ["35260904884082000135570020093542021093542025"]


def test_processa_ticket_para_planilha_e_define_status_al_incompleto():
    ticket = {
        "created_at": "2026-11-09T12:00:00Z",
        "description": f"123456 {CTE_1}",
        "tags": ["al"],
    }

    resultado = processar_ticket_para_planilha(
        "ticket-123",
        ticket,
        [{"attachments": [{"file_name": "guia.pdf", "content_url": "url-guia"}]}],
        {},
        padronizar_data=lambda data: f"data:{data}",
        identificar_uf=lambda dados, texto: (
            "AL" if dados and "al" in dados.get("tags", []) else "GERAL"
        ),
        baixar_conteudo=lambda url: (b"pdf-guia", "OK"),
        extrair_texto=lambda _conteudo: ("DAR estadual", "OK"),
        eh_nota_fiscal=lambda _texto, _nome: False,
        eh_dar=lambda texto: "DAR" in texto,
        eh_termo=lambda texto: "TERMO" in texto,
        extrair_remessas_ap=lambda _texto: [],
        obter_chaves_nfe=lambda _texto, _pdf: [],
        formatar_numero=lambda numero: numero,
        separar_guias_ap=lambda _texto: [],
        extrair_documento=lambda *_args: (
            "123456",
            [],
            "Sem Código",
            "Sem Código",
            "Não informado",
            "Não informado",
            "AL",
        ),
        validar_guia_ap=lambda *_args: (True, "OK"),
        marcar_ap_processada=str,
        resumir_nfe_map=lambda _mapa: "{}",
        ao_log=lambda *_args: None,
        identificar_layout=lambda *_args, **_kwargs: None,
    )

    assert resultado.data_ticket == "data:2026-11-09"
    assert resultado.uf_ticket == "AL"
    assert resultado.status_conf == "INCOMPLETO: Falta Termo"
    assert len(resultado.registros) == 1
    assert resultado.registros[0][0] == "123456"
    assert resultado.mapa_termo_cte == {"123456": [CTE_1]}
    assert resultado.lista_ctes_ordenada == [CTE_1]


def test_processa_e_agrega_ticket_sob_lock_compartilhado(monkeypatch):
    chamadas = []
    lock_ativo = []
    resultado = ResultadoTicketPlanilha(
        data_ticket="09/11/2026",
        uf_ticket="AL",
        registros=[("termo", [], "orig", "barra", "10/11/2026", "2,00", "AL", "OK")],
        status_conf="OK",
        mapa_termo_cte={"termo": [CTE_1]},
        lista_ctes_ordenada=[CTE_1],
        nfe_map={"chave": "123"},
    )

    class LockVerificavel:
        def __enter__(self):
            lock_ativo.append(True)

        def __exit__(self, *_args):
            lock_ativo.pop()

    def processar(*args, **kwargs):
        chamadas.append(("processar", args, kwargs))
        return resultado

    def agregar(*args, **kwargs):
        assert lock_ativo == [True]
        chamadas.append(("agregar", args, kwargs))

    monkeypatch.setattr(
        zendesk_pdf_service, "processar_ticket_para_planilha", processar
    )
    monkeypatch.setattr(zendesk_pdf_service, "agregar_registros_ticket", agregar)
    termos_map = {}
    historico = {"termo": {"UF": ["AL"]}}
    opcoes = {"ao_log": lambda *_args: None}

    processar_e_agregar_ticket_para_planilha(
        "ticket-123",
        {"created_at": "2026-11-09"},
        [{"attachments": []}],
        historico,
        termos_map,
        opcoes_processamento=opcoes,
        lock_termos=LockVerificavel(),
        campos_al=AL_CAMPOS_PLANILHA,
        limpar_texto=str,
        formatar_numero=str,
        padronizar_data=str,
        marcar_ap_processada=str,
    )

    assert chamadas[0] == (
        "processar",
        (
            "ticket-123",
            {"created_at": "2026-11-09"},
            [{"attachments": []}],
            historico,
        ),
        opcoes,
    )
    assert chamadas[1][0] == "agregar"
    assert chamadas[1][1] == (
        "ticket-123",
        "09/11/2026",
        resultado.registros,
        termos_map,
        resultado.mapa_termo_cte,
        resultado.lista_ctes_ordenada,
        resultado.nfe_map,
        "OK",
    )
    assert chamadas[1][2]["campos_al"] == AL_CAMPOS_PLANILHA
    assert lock_ativo == []


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
