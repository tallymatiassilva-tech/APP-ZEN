"""Regressões: preservação da memória e checkpoints sem sobrescrita."""
import json
from datetime import datetime

from src.services import memory_storage_service as storage


def test_falha_serializacao_preserva_memoria_anterior(tmp_path):
    path = tmp_path / 'memoria.json'
    previous = '{"dados_em_memoria": [{"TERMO": "123"}]}'
    path.write_text(previous, encoding='utf-8')
    storage.salvar_memoria_diaria(path, [{'valor': object()}], {}, {}, {})
    assert path.read_text(encoding='utf-8') == previous


def test_falha_substituicao_preserva_memoria_e_remove_temporario(tmp_path, monkeypatch):
    path = tmp_path / 'memoria.json'
    previous = '{"dados_em_memoria": []}'
    path.write_text(previous, encoding='utf-8')

    def fail_replace(*args):
        raise OSError('Falha de gravação simulada')

    monkeypatch.setattr(storage.os, 'replace', fail_replace)
    storage.salvar_memoria_diaria(path, [{'TERMO': '123'}], {}, {}, {})
    assert path.read_text(encoding='utf-8') == previous
    assert list(tmp_path.iterdir()) == [path]


def test_checkpoints_no_mesmo_segundo_preservam_ambos_estados(tmp_path, monkeypatch):
    class FixedDateTime:
        @staticmethod
        def now():
            return datetime(2026, 11, 11, 0, 0, 0)
    monkeypatch.setattr(storage, 'datetime', FixedDateTime)
    storage.salvar_checkpoint(tmp_path, 'lote', [{'TERMO': '123'}], {}, {}, {})
    storage.salvar_checkpoint(tmp_path, 'lote', [{'TERMO': '456'}], {}, {}, {})
    files = list(tmp_path.glob('checkpoint_*.json'))
    assert len(files) == 2
    assert {json.loads(p.read_text(encoding='utf-8'))['dados_em_memoria'][0]['TERMO'] for p in files} == {'123', '456'}
