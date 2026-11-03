# src/services/uf_rules.py
"""Compat shim. Não colocar regra fiscal aqui."""

from src.services.ufs.router import extrair_dados_por_uf


def extrair_regras_uf(uf, txt_pdf, nome_anexo, nfe_map, pdf_bytes=None):
    return extrair_dados_por_uf(uf, txt_pdf, nome_anexo, nfe_map, pdf_bytes)
