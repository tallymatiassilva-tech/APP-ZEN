# src/services/ufs/router.py
"""Dispatcher. Unico arquivo que pode citar varias UFs.
Espelha extrair_dados_por_uf do backup, linhas 1764-1785."""

from src.services.ufs.ac import _extrair_regras_ac
from src.services.ufs.al import _extrair_regras_al
from src.services.ufs.am import _extrair_regras_am
from src.services.ufs.ap import _extrair_regras_ap
from src.services.ufs.geral import _extrair_regras_geral
from src.services.ufs.ms import _extrair_regras_ms


def extrair_dados_por_uf(
    uf: str,
    txt_pdf: str,
    nome_anexo: str,
    nfe_map: dict,
    pdf_bytes: bytes | None = None,
) -> tuple[str, list, str, str, str, str, str]:
    uf_clean = (uf or "GERAL").upper()

    if uf_clean == "AL":
        return _extrair_regras_al(txt_pdf, nome_anexo, nfe_map, pdf_bytes)
    elif uf_clean == "AP":
        return _extrair_regras_ap(txt_pdf, nome_anexo, nfe_map)
    elif uf_clean == "AC":
        return _extrair_regras_ac(txt_pdf, nome_anexo, nfe_map)
    elif uf_clean == "MS":
        return _extrair_regras_ms(txt_pdf, nome_anexo, nfe_map)
    elif uf_clean == "AM":
        return _extrair_regras_am(txt_pdf, nome_anexo, nfe_map)
    else:
        return _extrair_regras_geral(txt_pdf, nome_anexo, nfe_map)
