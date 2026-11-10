import hashlib

from src.services import local_report_service
from src.services.local_pdf_service import ResultadoLotePDFLocal
from src.services.local_report_service import (
    montar_mapa_relatorio_local,
    processar_pasta_local_para_relatorio,
)
from src.services.ufs.al import AL_CAMPOS_PLANILHA
from src.utils.text_mono import (
    formatar_numero_arquivo,
    limpar_texto_excel,
    padronizar_data_ddmmyyyy,
)

NF_1 = "33260913121476000122550010001447611862291617"
CTE_1 = "35260904884082000135570020093542021093542025"


def test_processa_pasta_e_monta_relatorio_com_resultados_da_extracao(monkeypatch):
    chamadas = []
    lote_pdf = ResultadoLotePDFLocal(
        quantidade_arquivos=1,
        registros=[],
        nfe_map={"nf": "valor"},
        doc_ap05_por_chave={"chave": "doc"},
        ap_total=0,
        ap_ok=0,
        ap_quarentena=0,
        ap_corrigidas=0,
    )
    termos_map = {"termo": {"UF": ["AL"]}}

    def processar(pasta, **opcoes):
        chamadas.append(("processar", pasta, opcoes))
        return lote_pdf

    def montar(registros, nfe_map, documentos, memoria, **opcoes):
        chamadas.append(
            ("montar", registros, nfe_map, documentos, memoria, opcoes)
        )
        return termos_map

    monkeypatch.setattr(local_report_service, "processar_pdfs_locais", processar)
    monkeypatch.setattr(local_report_service, "montar_mapa_relatorio_local", montar)
    historico = {"termo": {"UF": ["AL"]}}
    callbacks = {"cancelado": lambda: False}
    limpar_texto = str
    formatar_numero = str
    padronizar_data = str

    resultado = processar_pasta_local_para_relatorio(
        "pasta",
        historico,
        limpar_texto=limpar_texto,
        formatar_numero_relatorio=formatar_numero,
        padronizar_data_relatorio=padronizar_data,
        **callbacks,
    )

    assert resultado.lote_pdf is lote_pdf
    assert resultado.termos_map is termos_map
    assert chamadas[0] == ("processar", "pasta", callbacks)
    assert chamadas[1] == (
        "montar",
        lote_pdf.registros,
        lote_pdf.nfe_map,
        lote_pdf.doc_ap05_por_chave,
        historico,
        {
            "limpar_texto": limpar_texto,
            "formatar_numero": formatar_numero,
            "padronizar_data": padronizar_data,
        },
    )


def _montar(registros, *, nfe_map=None, documentos=None, memoria=None):
    return montar_mapa_relatorio_local(
        registros,
        nfe_map or {},
        documentos or {},
        memoria or {},
        limpar_texto=limpar_texto_excel,
        formatar_numero=formatar_numero_arquivo,
        padronizar_data=padronizar_data_ddmmyyyy,
        data_atual="09/11/2026",
    )


def test_agrupa_guia_e_danfe_ap_pela_chave_e_aplica_documento_do_campo_05():
    registros = [
        (
            "12345678",
            [(NF_1, "000000001")],
            "Sem Código",
            "Sem Código",
            "09/11/2026",
            "1,00",
            "AP",
            "C:\\pdfs\\guia.pdf",
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
            "C:\\pdfs\\danfe.pdf",
            "",
        ),
    ]

    resultado = _montar(
        registros,
        documentos={NF_1: "86890247272"},
    )

    assert list(resultado) == [NF_1]
    assert resultado[NF_1]["TERMO_REAL"] == "12345678"
    assert resultado[NF_1]["CPF/CNPJ DA GUIA"] == ["86890247272"]
    assert resultado[NF_1]["CHAVE ARQUIVO"] == [NF_1]
    assert resultado[NF_1]["NÚMERO ARQUIVO"] == ["000000001"]
    assert resultado[NF_1]["DATA"] == ["09/11/2026"]


def test_agregacao_al_preserva_campos_da_guia_e_status_incompleto():
    campos_al = {campo: f"valor {indice}" for indice, campo in enumerate(AL_CAMPOS_PLANILHA)}
    registros = [
        (
            "7654321",
            [(CTE_1, "123")],
            "Sem Código",
            "Sem Código",
            "Não informado",
            "Não informado",
            "AL",
            "C:\\pdfs\\guia-al.pdf",
            "",
        )
    ]

    resultado = _montar(
        registros,
        nfe_map={"DOC_MS_7654321": "12.345.678/0001-90", "AL_CAMPOS_7654321": campos_al},
    )

    item = resultado[CTE_1]
    assert item["STATUS CONFERÊNCIA"] == "INCOMPLETO: Falta Guia (DAR)"
    assert item["CPF/CNPJ DA GUIA"] == ["12345678000190"]
    assert item["DACTE"] == [CTE_1]
    assert item["NÚMERO ARQUIVO"] == ["000000123"]
    for campo, valor in campos_al.items():
        assert item[campo] == [valor]


def test_registro_sem_termo_usa_chave_deterministica_por_caminho():
    registro = (
        "Não localizado",
        [],
        "Sem Código",
        "Sem Código",
        "Não informado",
        "Não informado",
        "GERAL",
        "C:\\pdfs\\sem-termo.pdf",
        "",
    )

    resultado = _montar([registro])

    chave_esperada = f"ARQ_{hashlib.md5(registro[7].encode('utf-8')).hexdigest()[:10]}"
    assert list(resultado) == [chave_esperada]
    assert resultado[chave_esperada]["STATUS CONFERÊNCIA"] == "OK"
