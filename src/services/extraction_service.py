# src/services/extraction_service.py
"""Ponto único de extração usado pelos orquestradores.
Sem regra fiscal aqui, só delega para o router.
Espelha backup extrair_dados_por_uf linhas 1764-1785.
"""
from __future__ import annotations
from src.services.ufs.router import extrair_dados_por_uf
from src.utils.logging_config import get_logger

logger = get_logger("jadlog.extraction")

def extrair_documento(
    uf: str,
    txt_pdf: str,
    nome_anexo: str,
    nfe_map: dict,
    pdf_bytes: bytes | None = None,
) -> tuple[str, list, str, str, str, str, str]:
    try:
        return extrair_dados_por_uf(uf, txt_pdf, nome_anexo, nfe_map, pdf_bytes)
    except Exception:
        logger.exception(f"falha extrair_documento uf={uf} anexo={nome_anexo}")
        raise