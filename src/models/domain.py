"""Strongly typed domain models. Replaces loose dicts."""

from dataclasses import dataclass, field


@dataclass(slots=True)
class PdfDocument:
    nome_arquivo: str
    conteudo: bytes
    texto: str = ""
    uf: str = "GERAL"


@dataclass(slots=True)
class ExtractedDoc:
    termo: str = "Nao localizado"
    uf: str = "GERAL"
    vencimento: str = "Nao informado"
    valor: str = "Nao informado"
    cod_barras_orig: str = "Sem Codigo"
    cod_barras: str = "Sem Codigo"
    pares: list[tuple[str, str]] = field(default_factory=list)
    status: str = "OK"


@dataclass(slots=True)
class LayoutConfig:
    uf: str
    palavras_chave: list[str] = field(default_factory=list)
    regex_termo: str = ""
    regex_vencimento: str = ""
    regex_valor: str = ""
    regex_cod_barras: str = ""
    regex_cte: str = ""
    regex_num_arquivo: str = ""
    regex_chave_arquivo: str = ""
    bbox_vencimento: list[float] | None = None
    bbox_valor: list[float] | None = None


@dataclass(slots=True)
class DedicatedClient:
    nome: str
    documento: str = ""
    observacao: str = ""
    atualizado_em: str = ""
