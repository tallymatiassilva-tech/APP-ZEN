import json

from src import app_legacy
from src.services import layout_service


def test_legacy_layout_manager_reexports_service_and_keeps_execution_logs(monkeypatch, tmp_path):
    monkeypatch.setattr(layout_service, "ARQUIVO_LAYOUTS", str(tmp_path / "layouts.json"))
    logs = []
    monkeypatch.setattr(app_legacy, "log_terminal", lambda *args: logs.append(args))

    manager = app_legacy.GerenciadorLayouts()

    assert isinstance(manager, layout_service.GerenciadorLayouts)
    assert "SEFAZ_ALAGOAS" in manager.layouts
    result = manager.identificar_e_extrair(
        "DOCUMENTO ARRECADAÇÃO TERMO:123456", "guia.pdf"
    )

    assert result is not None
    assert result["layout"] == "PADRAO_GERAL"
    assert result["termo"] == "123456"
    assert [marker for marker, _ in logs] == ["INÍCIO", "SUCESSO", "CONCLUÍDO"]


def test_manager_merges_defaults_preserves_history_and_restores_layout(monkeypatch, tmp_path):
    path = tmp_path / "layouts.json"
    path.write_text(
        json.dumps(
            {
                "_historico": [{"data": "ontem", "acao": "CADASTRO", "layout": "CUSTOM"}],
                "CUSTOM": {"uf": "ZZ", "palavras_chave": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(layout_service, "ARQUIVO_LAYOUTS", str(path))

    manager = layout_service.GerenciadorLayouts()

    assert manager.historico == [{"data": "ontem", "acao": "CADASTRO", "layout": "CUSTOM"}]
    assert "CUSTOM" in manager.layouts
    assert "SEFAZ_ALAGOAS" in manager.layouts
    assert manager.restaurar_padrao("SEFAZ_ALAGOAS") is True
    assert manager.layouts["SEFAZ_ALAGOAS"] == layout_service.LAYOUTS_PADRAO_SISTEMA[
        "SEFAZ_ALAGOAS"
    ]
    assert manager.restaurar_padrao("CUSTOM") is False
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["_historico"][-1]["acao"] == "RESTAURADO PADRÃO"


def test_manager_validates_regex_and_extracts_using_layout_configuration(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(layout_service, "ARQUIVO_LAYOUTS", str(tmp_path / "layouts.json"))
    manager = layout_service.GerenciadorLayouts()
    manager.layouts = {
        "CUSTOM": {
            "uf": "ZZ",
            "palavras_chave": ["TAG"],
            "regex_termo": r"TERM:(\d+)",
            "regex_vencimento": r"DATE:(\d{2}/\d{2}/\d{4})",
            "regex_valor": r"VALUE:(\d+,\d{2})",
            "regex_cod_barras": "",
            "regex_cte": r"CTE:(\d+)",
            "regex_num_arquivo": r"DOC:(\d+)",
            "regex_chave_arquivo": "",
        }
    }
    monkeypatch.setattr(layout_service, "padronizar_data_ddmmyyyy", lambda value: value)
    monkeypatch.setattr(layout_service, "formatar_numero_arquivo", lambda value: f"doc-{value}")
    monkeypatch.setattr(
        layout_service,
        "extrair_numero_termo_pdf",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        layout_service,
        "extrair_vencimento_e_valor_pdf",
        lambda _text: ("Não informado", "Não informado"),
    )
    monkeypatch.setattr(
        layout_service,
        "extrair_codigo_barras_pdf",
        lambda _text: ("Sem Código", "Sem Código"),
    )

    result = manager.identificar_e_extrair(
        "TAG TERM:123456 DATE:09/11/2026 VALUE:12,34 CTE:555 DOC:42",
        "synthetic.pdf",
    )

    assert result == {
        "layout": "CUSTOM",
        "uf": "ZZ",
        "termo": "123456",
        "vencimento": "09/11/2026",
        "valor": "12,34",
        "cod_barras_orig": "Sem Código",
        "cod_barras": "Sem Código",
        "cte": "555",
        "num_arquivo": "doc-42",
        "chave_arquivo": None,
        "pares_documento": [],
    }
    assert manager.validar_layout("BAD", {"uf": "ZZ", "regex_termo": "("}) == [
        "regex_termo: missing ), unterminated subpattern at position 0"
    ]


def test_manager_extracts_vencimento_and_valor_from_synthetic_crops(monkeypatch, tmp_path):
    monkeypatch.setattr(layout_service, "ARQUIVO_LAYOUTS", str(tmp_path / "layouts.json"))
    manager = layout_service.GerenciadorLayouts()
    manager.layouts = {
        "MS_CUSTOM": {
            "uf": "MS",
            "palavras_chave": ["TAG"],
            "regex_termo": "",
            "regex_vencimento": r"DATE:(\d{2}/\d{2}/\d{4})",
            "regex_valor": r"VALUE:(\d+,\d{2})",
            "regex_cod_barras": "",
            "regex_cte": "",
            "regex_num_arquivo": "",
            "regex_chave_arquivo": "",
            "bbox_vencimento": [0.1, 0.1, 0.9, 0.3],
            "bbox_valor": [0.1, 0.3, 0.9, 0.5],
        }
    }
    crops = []

    def fake_crop(pdf_bytes, bbox):
        crops.append((pdf_bytes, bbox))
        if bbox == [0.1, 0.1, 0.9, 0.3]:
            return "DATE:08/11/2026"
        return "VALUE:99,50"

    monkeypatch.setattr(layout_service, "extrair_texto_por_caixa", fake_crop)
    monkeypatch.setattr(
        layout_service,
        "extrair_numero_termo_pdf",
        lambda *_args: "Não localizado",
    )
    monkeypatch.setattr(
        layout_service,
        "extrair_vencimento_e_valor_pdf",
        lambda _text: ("Não informado", "Não informado"),
    )
    monkeypatch.setattr(
        layout_service,
        "extrair_codigo_barras_pdf",
        lambda _text: ("Sem Código", "Sem Código"),
    )

    result = manager.identificar_e_extrair("TAG sem campos no texto", "synthetic.pdf", b"pdf")

    assert result["vencimento"] == "08/11/2026"
    assert result["valor"] == "99,50"
    assert len(crops) == 2
    assert all(pdf_bytes == b"pdf" for pdf_bytes, _ in crops)
