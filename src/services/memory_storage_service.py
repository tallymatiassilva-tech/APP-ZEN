"""Leitura e gravacao do estado diario da aplicacao."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _salvar_json_atomico(caminho: str | Path, payload: dict[str, Any]) -> None:
    """Preserva o arquivo anterior se a serialização ou gravação falhar."""
    conteudo = json.dumps(payload, ensure_ascii=False, indent=2)
    destino = Path(caminho)
    temporario = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destino.parent,
            prefix=f".{destino.name}.", suffix=".tmp", delete=False,
        ) as arquivo:
            temporario = Path(arquivo.name)
            arquivo.write(conteudo)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, destino)
    finally:
        if temporario is not None:
            temporario.unlink(missing_ok=True)


def _guardar_copia_corrompida(caminho: str | Path, erro: Exception) -> None:
    """Preserva o arquivo danificado para que o proximo salvamento nao o apague."""
    import shutil
    from datetime import datetime
    origem = Path(caminho)
    destino = origem.with_name(
        f"{origem.stem}.corrompido_{datetime.now():%Y%m%d_%H%M%S_%f}{origem.suffix}"
    )
    try:
        shutil.copy2(origem, destino)
        print(f"[Aviso] Memória danificada ({erro}); cópia guardada em {destino}")
    except OSError as falha:
        print(f"[Erro] Não foi possível guardar cópia da memória danificada: {falha}")


def carregar_memoria_diaria(caminho: str | Path) -> Any:
    """Carrega o JSON de memoria e preserva o formato legado em lista."""
    try:
        with open(caminho, "r", encoding="utf-8") as arquivo:
            return json.load(arquivo)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeDecodeError) as erro:
        _guardar_copia_corrompida(caminho, erro)
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
        _salvar_json_atomico(caminho, payload)
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
        caminho = pasta / f"checkpoint_{data_stamp}_{uuid4().hex}_{nome_base}.json"

        payload = {
            "motivo": motivo,
            "salvo_em": datetime.now().isoformat(timespec="seconds"),
            "dados_em_memoria": dados_em_memoria,
            "memoria_termos": memoria_termos,
            "tickets_processados": tickets_processados,
            "ctes_consultados_cache": ctes_consultados_cache,
        }
        _salvar_json_atomico(caminho, payload)
    except Exception as erro:  # noqa: BLE001
        print(f"[Erro] Falha ao salvar checkpoint: {erro}")
