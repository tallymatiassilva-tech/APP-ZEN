import io, json, os
from pathlib import Path
from services import spreadsheet_import_service as s, memory_storage_service as m, pdf_service as p, layout_service as l

limpar = lambda v: str(v)

def test_csv_salvo_pelo_excel_em_cp1252_le_acentos(tmp_path):
    f = tmp_path / "a.csv"; f.write_bytes("NOME;VALOR\nJoão;1,50\n".encode("cp1252"))
    cab, linhas, *_ = s._carregar_linhas(f, limpar)
    assert cab == ["NOME", "VALOR"] and linhas == [["João", "1,50"]]

def test_csv_separado_por_virgula(tmp_path):
    f = tmp_path / "b.csv"; f.write_text("NOME,VALOR\nJosé,2\n", encoding="utf-8")
    cab, linhas, *_ = s._carregar_linhas(f, limpar)
    assert cab == ["NOME", "VALOR"] and linhas == [["José", "2"]]

def test_csv_vazio(tmp_path):
    f = tmp_path / "c.csv"; f.write_text("", encoding="utf-8")
    assert s._carregar_linhas(f, limpar) == ([], [], 0, 0)

def test_memoria_com_acentos(tmp_path):
    f = tmp_path / "m.json"; f.write_text('{"a": "ação"}', encoding="utf-8")
    assert m.carregar_memoria_diaria(f) == {"a": "ação"}

def test_memoria_corrompida_guarda_copia(tmp_path):
    f = tmp_path / "m.json"; f.write_text("{quebrado", encoding="utf-8")
    assert m.carregar_memoria_diaria(f) is None
    copias = list(tmp_path.glob("m.corrompido_*.json"))
    assert len(copias) == 1 and copias[0].read_text(encoding="utf-8") == "{quebrado"

def test_layouts_em_formato_invalido_usam_padrao(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(l.ARQUIVO_LAYOUTS).write_text("[1, 2]", encoding="utf-8")
    svc = l.GerenciadorLayouts()
    assert set(l.LAYOUTS_PADRAO_SISTEMA) <= set(svc.carregar_layouts())

def test_pdf_danificado_nao_trava():
    assert p.extrair_texto_pdf(b"nao e pdf")[0] == ""

def test_pdf_varias_paginas_com_acentos():
    from reportlab.pdfgen import canvas
    b = io.BytesIO(); c = canvas.Canvas(b)
    c.drawString(50, 800, "Pagina um ação"); c.showPage(); c.drawString(50, 800, "Pagina dois"); c.save()
    texto, status = p.extrair_texto_pdf(b.getvalue())
    assert status == "OK" and "ação" in texto and "dois" in texto
