# src/services/ufs/base.py
"""Contrato das regras por UF."""

from typing import Protocol


class RegraUF(Protocol):
    def __call__(
        self,
        txt_pdf: str,
        nome_anexo: str,
        nfe_map: dict,
        pdf_bytes: bytes | None = None,
    ) -> tuple[str, list, str, str, str, str, str]: ...
