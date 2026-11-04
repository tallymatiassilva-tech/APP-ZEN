"""Leitura e validacao de DAR por UF, com separacao por origem dos campos de 44 digitos."""

import re
from dataclasses import dataclass

MODELO_NFE = "55"
MODELO_CTE = "57"

# Campos do DAR. Cada valor de 44 digitos tem uma unica origem possivel.
CAMPO_CHAVE_NFE = 24      # Informacoes Complementares
CAMPO_CODIGO_BARRAS = 26  # Autenticacao Mecanica
CAMPO_IDENTIFICADOR = 5   # Inscricao Estadual / CGC / CPF


def so_digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def modelo(chave) -> str:
    """Modelo do documento fiscal: posicoes 21 e 22 da chave de 44 digitos."""
    d = so_digitos(chave)
    return d[20:22] if len(d) == 44 else ""


# ---------------------------------------------------------------------------
# Campo 26: codigo de barras. Lido e gravado, NUNCA validado.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CodigoBarras:
    original: str    # 55 caracteres, com espacos e tracos, como impresso na guia
    digitos48: str   # 48 digitos, incluindo os 4 digitos verificadores
    codigo44: str    # 44 digitos, sem os DVs. Coluna de 44 na planilha

    @property
    def blocos(self) -> list[str]:
        return self.original.split()


def ler_codigo_barras(campo26: str) -> CodigoBarras:
    """Le exclusivamente o campo 26. Nunca varre o documento.

    Layout: 4 blocos de 12 digitos + 1 DV cada, separados por espaco.
    4 x 13 caracteres + 3 espacos = 55 caracteres impressos.
    """
    original = str(campo26 or "").strip()
    blocos = original.split()
    if len(blocos) != 4:
        raise ValueError(f"campo 26: esperados 4 blocos, encontrados {len(blocos)}")

    limpos = [so_digitos(b) for b in blocos]
    for i, b in enumerate(limpos, start=1):
        if len(b) != 12:
            raise ValueError(f"campo 26, bloco {i}: {len(b)} digitos, esperados 12")

    return CodigoBarras(
        original=original,
        digitos48="".join(limpos),
        codigo44="".join(b[:-1] for b in limpos),  # b[:-1] descarta o DV
    )


# ---------------------------------------------------------------------------
# Campo 24: chave da NF-e. Unico valor comparavel da remessa.
# ---------------------------------------------------------------------------

def _candidatos_44(texto: str) -> list[str]:
    """Sequencias de digitos com separadores que, normalizadas, dao 44 digitos."""
    achados = re.findall(r"\d[\d\s.\-/]{40,80}\d", str(texto or ""))
    saida = []
    for bruto in achados:
        d = so_digitos(bruto)
        if len(d) == 44:
            saida.append(d)
    return saida


def ler_chave_nfe(campo24: str) -> str:
    """Le exclusivamente o campo 24 e filtra por modelo 55.

    Aceita apenas chave de NF-e. DACTE (modelo 57) e qualquer outro modelo
    caem fora pelo proprio filtro, sem lista de excecao.
    """
    for d in _candidatos_44(campo24):
        if modelo(d) == MODELO_NFE:
            return d
    return ""


# ---------------------------------------------------------------------------
# Guarda: garante que um valor nunca foi lido do campo errado.
# ---------------------------------------------------------------------------

def conferir_origens(codigo: CodigoBarras, chave: str) -> None:
    """Falha cedo se os dois campos de 44 digitos se confundirem."""
    if len(codigo.codigo44) != 44:
        raise ValueError(f"codigo de barras com {len(codigo.codigo44)} digitos")
    if len(chave) != 44:
        raise ValueError(f"chave NF-e com {len(chave)} digitos")
    if codigo.codigo44 == chave:
        raise ValueError("codigo de barras e chave NF-e iguais: leitura cruzada")
    if modelo(chave) != MODELO_NFE:
        raise ValueError(f"chave com modelo {modelo(chave)}, esperado {MODELO_NFE}")


# ---------------------------------------------------------------------------
# Validacao: duas verificacoes, nenhuma delas usa o codigo de barras.
# ---------------------------------------------------------------------------

def validar_guia(
    campo05: str,
    chave_guia: str,
    remetente: str,
    destinatario: str,
    chaves_remessa: list[str],
) -> tuple[bool, str]:
    ident = so_digitos(campo05)
    if not ident:
        return False, "INCOMPLETO: identificador ausente no campo 05"

    papeis = {
        "remetente": so_digitos(remetente),
        "destinatario": so_digitos(destinatario),
    }
    papeis = {k: v for k, v in papeis.items() if v}

    lado = next((k for k, v in papeis.items() if v == ident), None)
    if not lado:
        return False, "QUARENTENA: identificador nao consta na remessa"

    chave = so_digitos(chave_guia)
    if len(chave) != 44:
        return False, "INCOMPLETO: chave da guia nao localizada no campo 24"

    notas = {so_digitos(c) for c in chaves_remessa if modelo(c) == MODELO_NFE}
    if chave not in notas:
        return False, "QUARENTENA: chave da guia nao e de NF-e desta remessa"

    return True, f"OK: identificador ({lado}) e chave NF-e conferem"