from threading import Lock
import pytest
from src.services import fraction_service as fraction, layout_service as layout, spreadsheet_import_service as sheet


def test_importacao_preserva_cobrancas_distintas(tmp_path):
    path = tmp_path / 'cobrancas.xlsx'
    wb = sheet.openpyxl.Workbook()
    ws = wb.active
    ws.append(['TERMO/CONTROLE', 'VALOR (R$)', 'VENCIMENTO'])
    ws.append(['123456', '10,00', '01/12/2026'])
    ws.append(['123456', '20,00', '02/12/2026'])
    wb.save(path)
    wb.close()
    result = sheet.carregar_planilha_conferencia(path, campos_al=[], limpar_texto=str, padronizar_data=str, timestamp=lambda: '', ao_progresso=lambda *_: None)
    assert [(r['VALOR'], r['VENCIMENTO']) for r in result.dados] == [('10,00', '01/12/2026'), ('20,00', '02/12/2026')]
    assert result.duplicados_ignorados == 0


@pytest.mark.parametrize('field', ['regex_termo', 'regex_vencimento', 'regex_valor', 'regex_cod_barras', 'regex_cte', 'regex_num_arquivo', 'regex_chave_arquivo'])
def test_layout_captura_opcional_nao_interrompe_extracao(field):
    manager = object.__new__(layout.GerenciadorLayouts)
    manager.layouts = {'TESTE': {'uf': 'ZZ', 'palavras_chave': ['TAG'], 'regex_termo': r'TERM:(\d+)', field: r'TAG(?: VAL:(\d+))?'}}
    result = manager.identificar_e_extrair('TAG TERM:123456', 'arquivo.pdf')
    if field != 'regex_termo':
        assert result['termo'] == '123456'
    else:
        assert result is None


def test_coordenador_preserva_chave_dacte(monkeypatch):
    key = '1' * 20 + '57' + '2' * 22
    received = []
    def consult(ctes, *_):
        received.extend(ctes)
        return False, []
    monkeypatch.setattr(fraction, 'consultar_ctes_fraction_com_retentativas', consult)
    fraction.coordenar_conciliacao_fraction([{'TERMO': '123', 'CTE / REMESSA': 'Sem CTE', 'DACTE': key}], 'cookie-teste', {}, Lock(), ao_log=lambda *_: None, ao_progresso=lambda *_: None, deve_cancelar=lambda: False)
    assert received == [key]


@pytest.mark.parametrize('old', ['CONCILIADO PARCIAL', 'DIVERGÊNCIA CTI (Chave NF-e divergente do CTe)'])
def test_reconferencia_corrigida_substitui_status_fraction(old):
    assert fraction.determinar_status_conferencia_fraction(old, [], []) == ('VALIDADO NO FRACTION', True)


def test_reconferencia_preserva_status_manual():
    assert fraction.determinar_status_conferencia_fraction('CONFERÊNCIA MANUAL', [], []) == ('CONFERÊNCIA MANUAL', False)
