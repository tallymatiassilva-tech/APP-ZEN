import json

from src.services.memory_storage_service import (
    carregar_memoria_diaria,
    salvar_checkpoint,
    salvar_memoria_diaria,
)


def test_carrega_formato_atual_da_memoria(tmp_path):
    caminho = tmp_path / "memoria.json"
    dados = {
        "dados_em_memoria": [{"TERMO": "123"}],
        "memoria_termos": {"123": {"UF": ["AL"]}},
        "tickets_processados": {"456": True},
        "ctes_consultados_cache": {"789": "cliente"},
    }
    caminho.write_text(json.dumps(dados), encoding="utf-8")

    assert carregar_memoria_diaria(caminho) == dados


def test_carrega_formato_legado_em_lista(tmp_path):
    caminho = tmp_path / "memoria.json"
    dados = [{"TERMO": "123"}]
    caminho.write_text(json.dumps(dados), encoding="utf-8")

    assert carregar_memoria_diaria(caminho) == dados


def test_arquivo_ausente_ou_json_invalido_retorna_none(tmp_path):
    assert carregar_memoria_diaria(tmp_path / "ausente.json") is None

    caminho = tmp_path / "invalido.json"
    caminho.write_text("{", encoding="utf-8")
    assert carregar_memoria_diaria(caminho) is None


def test_salva_estado_json_completo_e_timestamp(tmp_path):
    caminho = tmp_path / "memoria.json"
    dados = [{"TERMO": "123"}]
    memoria = {"123": {"UF": ["AL"]}}
    tickets = {"456": True}
    cache_ctes = {"789": "cliente"}

    salvar_memoria_diaria(caminho, dados, memoria, tickets, cache_ctes)

    resultado = json.loads(caminho.read_text(encoding="utf-8"))
    assert resultado["dados_em_memoria"] == dados
    assert resultado["memoria_termos"] == memoria
    assert resultado["tickets_processados"] == tickets
    assert resultado["ctes_consultados_cache"] == cache_ctes
    assert resultado["atualizado_em"]


def test_salva_checkpoint_com_motivo_sanitizado_e_estado_completo(tmp_path):
    dados = [{"TERMO": "123"}]
    memoria = {"123": {"UF": ["AL"]}}
    tickets = {"456": True}
    cache_ctes = {"789": "cliente"}

    salvar_checkpoint(
        tmp_path,
        "ticket de anexos #123",
        dados,
        memoria,
        tickets,
        cache_ctes,
    )

    arquivos = list(tmp_path.glob("checkpoint_*_ticket_de_anexos_123.json"))
    assert len(arquivos) == 1
    resultado = json.loads(arquivos[0].read_text(encoding="utf-8"))
    assert resultado["motivo"] == "ticket de anexos #123"
    assert resultado["dados_em_memoria"] == dados
    assert resultado["memoria_termos"] == memoria
    assert resultado["tickets_processados"] == tickets
    assert resultado["ctes_consultados_cache"] == cache_ctes
    assert resultado["salvo_em"]


def test_checkpoint_cria_pasta_de_destino(tmp_path):
    pasta = tmp_path / "subpasta" / "checkpoints"

    salvar_checkpoint(pasta, "", [], {}, {}, {})

    assert list(pasta.glob("checkpoint_*_lote.json"))
