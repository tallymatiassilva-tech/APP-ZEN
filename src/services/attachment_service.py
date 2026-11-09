"""Pure helpers for choosing Zendesk attachment destinations."""

import hashlib
import os
import re
from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any

AttachmentFlags = Mapping[str, object]
MutableAttachmentFlags = MutableMapping[str, object]


def calcular_hash_md5(conteudo: bytes) -> str:
    """Retorna o hash usado para detectar anexos duplicados."""
    return hashlib.md5(conteudo).hexdigest()


def limpar_nome_anexo(nome: str) -> str:
    return re.sub(r"[\\/*?:|<>]", "_", str(nome))


def determinar_caminho_arquivo_unico(
    diretorio: str | Path, nome_arquivo: str
) -> Path:
    caminho = Path(diretorio) / nome_arquivo
    if not caminho.exists():
        return caminho

    nome_base, extensao = os.path.splitext(nome_arquivo)
    contador = 1
    while True:
        caminho = Path(diretorio) / f"{nome_base}_{contador}{extensao}"
        if not caminho.exists():
            return caminho
        contador += 1


def determinar_quarentena_al(
    uf_ticket: str, anexos: Sequence[AttachmentFlags]
) -> tuple[bool, str | None]:
    if uf_ticket != "AL":
        return False, None

    anexos_validos = [item for item in anexos if not item["is_duplicado"]]
    tem_dar = any(item["is_dar"] for item in anexos_validos)
    tem_termo = any(item["is_termo"] for item in anexos_validos)
    if tem_dar and not tem_termo:
        return True, "Falta Termo"
    if tem_termo and not tem_dar:
        return True, "Falta Guia (DAR)"
    return False, None


def propagar_vencimento_dar_ap(
    uf_ticket: str, anexos: Sequence[MutableAttachmentFlags]
) -> None:
    if uf_ticket != "AP" and not any(item.get("uf_final") == "AP" for item in anexos):
        return

    tem_dar_vencido_ap = any(
        item.get("is_vencido")
        for item in anexos
        if item.get("uf_final") == "AP"
        and item.get("is_dar")
        and not item.get("is_duplicado")
    )
    for item in anexos:
        if item.get("uf_final") == "AP" and (item.get("is_dar") or item.get("is_nota")):
            item["is_vencido"] = tem_dar_vencido_ap


def determinar_diretorio_anexo(
    pasta_destino: str | Path,
    estado_dir: str,
    subpasta: str,
    is_dar: bool,
    is_nota: bool,
    is_duplicado: bool,
    is_vencido: bool,
    em_quarentena: bool,
) -> Path:
    raiz = Path(pasta_destino)

    if estado_dir == "AP":
        if is_duplicado:
            return raiz / "AP" / "DUPLICADOS"
        if is_vencido and (is_dar or is_nota):
            return raiz / "AP" / "VENCIDAS"
        if is_dar:
            return raiz / "AP" / "DAR"
        if is_nota:
            return raiz / "AP" / "NOTAS"
        return raiz / "AP" / subpasta

    if is_duplicado:
        return raiz / estado_dir / "DUPLICADOS"
    if is_vencido:
        return raiz / estado_dir / "VENCIDAS"
    if em_quarentena and subpasta in ("DAR", "TERMO"):
        return raiz / estado_dir / "QUARENTENA"
    if is_dar:
        return raiz / estado_dir / "DAR"
    if is_nota:
        return raiz / "NOTAS"
    return raiz / estado_dir / subpasta


def salvar_anexos_processados(
    pasta_destino: str | Path,
    anexos: Sequence[Mapping[str, Any]],
    em_quarentena: bool,
) -> list[Path]:
    """Grava anexos classificados na estrutura de pastas correspondente."""
    caminhos_salvos = []
    for anexo in anexos:
        caminho_dir = determinar_diretorio_anexo(
            pasta_destino,
            anexo["uf_final"],
            anexo["subpasta"],
            anexo["is_dar"],
            anexo["is_nota"],
            anexo["is_duplicado"],
            anexo["is_vencido"],
            em_quarentena,
        )
        caminho_dir.mkdir(parents=True, exist_ok=True)
        caminho_arquivo = determinar_caminho_arquivo_unico(
            caminho_dir, anexo["nome_limpo"]
        )
        caminho_arquivo.write_bytes(anexo["conteudo"])
        caminhos_salvos.append(caminho_arquivo)
    return caminhos_salvos
