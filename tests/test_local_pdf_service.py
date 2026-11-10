import pytest

from src.services import local_pdf_service

NF_1 = "33260913121476000122550010001447611862291617"


def test_listar_pdfs_locais_prioriza_danfe_e_ignora_outros_arquivos(tmp_path):
    recibo = tmp_path / "recibo.PDF"
    danfe_dir = tmp_path / "Notas"
    danfe_dir.mkdir()
    danfe = danfe_dir / "documento.pdf"
    outros = tmp_path / "leia.txt"
    for arquivo in (recibo, danfe, outros):
        arquivo.write_text("conteudo", encoding="utf-8")

    assert local_pdf_service.listar_pdfs_locais(tmp_path) == [
        str(danfe),
        str(recibo),
    ]


def test_carregar_pdf_local_retorna_conteudo_texto_status_e_uf(
    tmp_path, monkeypatch
):
    caminho = tmp_path / "guia.pdf"
    conteudo = b"conteudo pdf"
    caminho.write_bytes(conteudo)
    monkeypatch.setattr(
        local_pdf_service,
        "extrair_texto_pdf",
        lambda dados: ("GOVERNO DO ESTADO DO AMAPA", "OK"),
    )

    documento = local_pdf_service.carregar_pdf_local(
        caminho,
        lambda texto: "AP" if "AMAPA" in texto else "GERAL",
    )

    assert documento.caminho == str(caminho)
    assert documento.nome == "guia.pdf"
    assert documento.conteudo == conteudo
    assert documento.texto == "GOVERNO DO ESTADO DO AMAPA"
    assert documento.status_leitura == "OK"
    assert documento.uf == "AP"


def test_carregar_pdf_local_propaga_erro_de_leitura(tmp_path):
    caminho = tmp_path / "ausente.pdf"

    with pytest.raises(FileNotFoundError):
        local_pdf_service.carregar_pdf_local(caminho, lambda _: "GERAL")


def test_processar_pdfs_locais_le_nota_antes_e_valida_guia_ap(
    tmp_path, monkeypatch
):
    notas = tmp_path / "Notas"
    notas.mkdir()
    danfe = notas / "danfe.pdf"
    guia = tmp_path / "guia.pdf"
    danfe.write_bytes(b"danfe")
    guia.write_bytes(b"guia")
    textos = {
        b"danfe": "DANFE\nNF-e Nº 1",
        b"guia": (
            "05 - Inscricao Estadual/CGC/CPF: 868.902.472-72\n"
            "06 - Data de vencimento: 09/11/2026\n"
            f"Chave de Acesso: {NF_1}"
        ),
    }
    monkeypatch.setattr(
        local_pdf_service,
        "extrair_texto_pdf",
        lambda conteudo: (textos[conteudo], "OK"),
    )
    progresso = []
    inicio = []
    resultado = local_pdf_service.processar_pdfs_locais(
        tmp_path,
        identificar_uf=lambda _: "AP",
        eh_nota_fiscal=lambda _, nome: nome == "danfe.pdf",
        separar_guias_ap=lambda texto: [("12345678", texto)],
        identificar_layout=lambda *_args, **_kwargs: None,
        historico_termos={},
        marcar_ap_processada=lambda status: f"{status} | processada",
        cancelado=lambda: False,
        ao_inicio=inicio.append,
        ao_progresso=lambda atual, total: progresso.append((atual, total)),
        ao_log=lambda *_: None,
        ao_aviso=lambda _: None,
        ao_erro=lambda nome, erro: pytest.fail(f"{nome}: {erro}"),
        obter_chaves_nfe=lambda _texto, _pdf: [NF_1],
        extrair=lambda _uf, _texto, _nome, _mapa: (
            "12345678",
            [(NF_1, "000000001")],
            "Sem Código",
            "Sem Código",
            "09/11/2026",
            "1,00",
            "AP",
        ),
    )

    assert inicio == [2]
    assert progresso == [(1, 2), (2, 2)]
    assert resultado.nfe_map == {NF_1: "000000001"}
    assert resultado.doc_ap05_por_chave == {NF_1: "86890247272"}
    assert resultado.registros[0][0] == "12345678"
    assert resultado.registros[0][6] == "AP"
    assert resultado.registros[0][8].startswith("DOC OK")
    assert resultado.ap_total == 1
    assert resultado.ap_ok == 1
