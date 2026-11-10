"""Leitura e gravacao do estado diario da aplicacao."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


def carregar_memoria_diaria(caminho: str | Path) -> Any:
    """Carrega o JSON de memoria e preserva o formato legado em lista."""
    try:
        with open(caminho, "r", encoding="utf-8") as arquivo:
            return json.load(arquivo)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    except Exception as erro:  # noqa: BLE001
        print(f"[Erro] Falha ao carregar memória diária: {erro}")
        return None


def salvar_memoria_diaria(
    caminho: str | Path,
    dados_em_memoria: list[dict[str, Any]],
    memoria_termos: dict[str, Any],
    tickets_processados: dict[str, Any],
    ctes_consultados_cache: dict[str, Any],
) -> None:
    """Salva o estado com o mesmo formato JSON usado pelo aplicativo."""
    payload = {
        "dados_em_memoria": dados_em_memoria,
        "memoria_termos": memoria_termos,
        "tickets_processados": tickets_processados,
        "ctes_consultados_cache": ctes_consultados_cache,
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        with open(caminho, "w", encoding="utf-8") as arquivo:
            json.dump(payload, arquivo, ensure_ascii=False, indent=2)
    except Exception as erro:  # noqa: BLE001
        print(f"[Erro] Falha ao salvar memória diária: {erro}")


def salvar_checkpoint(
    pasta_checkpoint: str | Path,
    motivo: str,
    dados_em_memoria: list[dict[str, Any]],
    memoria_termos: dict[str, Any],
    tickets_processados: dict[str, Any],
    ctes_consultados_cache: dict[str, Any],
) -> None:
    """Cria um checkpoint JSON do estado atual da aplicacao."""
    try:
        nome_base = (
            re.sub(r"[^A-Za-z0-9._-]+", "_", (motivo or "lote").strip())[:40]
            or "lote"
        )
        data_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pasta = Path(pasta_checkpoint)
        pasta.mkdir(parents=True, exist_ok=True)
        caminho = pasta / f"checkpoint_{data_stamp}_{nome_base}.json"

        payload = {
            "motivo": motivo,
            "salvo_em": datetime.now().isoformat(timespec="seconds"),
            "dados_em_memoria": dados_em_memoria,
            "memoria_termos": memoria_termos,
            "tickets_processados": tickets_processados,
            "ctes_consultados_cache": ctes_consultados_cache,
        }
        with open(caminho, "w", encoding="utf-8") as arquivo:
            json.dump(payload, arquivo, ensure_ascii=False, indent=2)
    except Exception as erro:  # noqa: BLE001
        print(f"[Erro] Falha ao salvar checkpoint: {erro}")
