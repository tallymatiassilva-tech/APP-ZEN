"""Helpers for extracting search fields from Jadlog Fraction forms."""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.services.document_classifier import (
    extrair_chaves_nfe_pdf,
    normalizar_documento_fiscal,
)
from src.utils.text_mono import formatar_texto_excel


@dataclass(frozen=True)
class EvidenciasConferenciaFraction:
    documentos_fraction: set[str]
    documento_guia: str
    chaves_fraction: set[str]
    chaves_guia: set[str]
    numeros_fraction: set[int]
    numeros_guia: set[int]


@dataclass(frozen=True)
class PreparacaoItensFraction:
    itens_pendentes: list[tuple[Mapping[str, Any], list[str]]]
    guias_ap_chave_incompleta: list[Mapping[str, Any]]
    itens_sem_cte: list[Mapping[str, Any]]


@dataclass(frozen=True)
class ResultadoAplicacaoFraction:
    motivos: list[str]
    inconclusivos: list[str]
    status: str
    status_atualizado: bool


def extrair_ctes_unicos(valores: list[Any]) -> list[str]:
    ctes_limpos = []
    for valor in valores:
        texto = str(valor or "").replace("Sem CTE", "").strip()
        if "e+" in texto.lower():
            try:
                texto = f"{Decimal(texto):.0f}"
            except (InvalidOperation, ValueError):
                pass
        if texto.endswith(".0"):
            texto = texto[:-2]
        for numero in re.findall(r"\b\d{6,15}\b", re.sub(r"[^\d\s]", " ", texto)):
            if numero not in ctes_limpos:
                ctes_limpos.append(numero)
    return ctes_limpos


def extrair_ctes_busca_fraction(item_ref: Mapping[str, Any]) -> list[str]:
    candidatos = []
    cte_raw = (
        str(item_ref.get("CTE / REMESSA") or item_ref.get("CTE") or "")
        .replace("Sem CTE", "")
        .strip()
    )
    for cte in re.findall(r"(?<!\d)\d{6,15}(?!\d)", cte_raw):
        if cte not in candidatos:
            candidatos.append(cte)

    if candidatos:
        return candidatos

    dacte_raw = str(item_ref.get("DACTE", "")).replace("Sem DACTE", "").strip()
    for dacte in re.split(r"[\s,]+", dacte_raw):
        dacte_limpo = re.sub(r"\D", "", dacte)
        if len(dacte_limpo) == 44 and dacte_limpo[20:22] == "57":
            if dacte_limpo not in candidatos:
                candidatos.append(dacte_limpo)
    return candidatos


def preparar_itens_pendentes_fraction(
    itens: Sequence[Mapping[str, Any]],
) -> PreparacaoItensFraction:
    """Separa linhas consultáveis pelo CT-e, casos de chave AP e itens sem CT-e."""
    pendentes = []
    guias_ap_chave_incompleta = []
    itens_sem_cte = []

    for item in itens:
        uf_item = str(item.get("UF", "")).strip().upper()
        status_item = str(item.get("STATUS CONFERÊNCIA", "")).strip().upper()
        if uf_item == "AP" and status_item.startswith("INCOMPLETO: CHAVE"):
            guias_ap_chave_incompleta.append(item)

        candidatos_cte = extrair_ctes_busca_fraction(item)
        if candidatos_cte:
            pendentes.append((item, candidatos_cte))
        else:
            itens_sem_cte.append(item)

    return PreparacaoItensFraction(
        pendentes,
        guias_ap_chave_incompleta,
        itens_sem_cte,
    )


def obter_resultado_cache_fraction(
    cache: dict[str, Any], cte_code: str
) -> tuple[Any, Any] | None:
    valor = cache.get(cte_code)
    if isinstance(valor, tuple) and valor[0] is not None:
        return valor[0], valor[1]
    return None


def armazenar_resultado_cache_fraction(
    cache: dict[str, Any],
    cte_code: str,
    tomador: Any,
    metadados: dict[str, Any],
) -> None:
    cache[cte_code] = (tomador, metadados)


def consultar_fraction_por_cte(
    cte_code: str,
    session: requests.Session,
    cache: dict[str, Any],
    cache_lock: Any,
    *,
    ao_cookie_expirado: Callable[[], None],
    ao_erro_consulta: Callable[[str], None],
    ao_formulario_ausente: Callable[[str], None],
) -> tuple[str, Any, dict[str, Any]]:
    """Consulta um CT-e pelo formulário Fraction e usa tracking como fallback."""
    with cache_lock:
        resultado_cache = obter_resultado_cache_fraction(cache, cte_code)
    if resultado_cache is not None:
        return cte_code, resultado_cache[0], resultado_cache[1]

    url_pesquisa = "https://jadlog.com.br/FractionWeb/jad/pesquisar"
    formulario_localizado = False

    for url in [url_pesquisa]:
        try:
            pagina = session.get(url, timeout=15)
            if resposta_fraction_indica_login(pagina.url, pagina.text):
                ao_cookie_expirado()
                return cte_code, "COOKIE_EXPIRADO", {}
            if pagina.status_code >= 400:
                continue

            soup_form = BeautifulSoup(pagina.content, "html.parser")
            for form in soup_form.find_all("form"):
                preparado = preparar_formulario_fraction(form, pagina.url, cte_code)
                if not preparado:
                    continue

                formulario_localizado = True
                action, method, campos = preparado
                if method == "post":
                    response = session.post(
                        action,
                        data=campos,
                        headers={"Referer": pagina.url},
                        timeout=15,
                    )
                else:
                    response = session.get(
                        action,
                        params=campos,
                        headers={"Referer": pagina.url},
                        timeout=15,
                    )

                if resposta_fraction_indica_login(response.url, response.text):
                    ao_cookie_expirado()
                    return cte_code, "COOKIE_EXPIRADO", {}
                if response.status_code >= 400:
                    continue

                soup, texto = extrair_texto_pagina_fraction(response.content)
                if "Tomador" not in texto:
                    for url_detalhe in localizar_urls_detalhe_fraction(
                        soup, str(response.url), cte_code
                    ):
                        try:
                            response_detalhe = session.get(url_detalhe, timeout=15)
                            soup_detalhe, texto_detalhe = extrair_texto_pagina_fraction(
                                response_detalhe.content
                            )
                            if "Tomador" in texto_detalhe:
                                soup, texto = soup_detalhe, texto_detalhe
                                break
                        except Exception:
                            continue

                tomador, dados_fraction = extrair_resultado_consulta_fraction(
                    soup, texto, cte_code
                )
                if tomador:
                    with cache_lock:
                        armazenar_resultado_cache_fraction(
                            cache, cte_code, tomador, dados_fraction
                        )
                    return cte_code, tomador, dados_fraction

        except requests.RequestException as erro:
            ao_erro_consulta(type(erro).__name__)

    try:
        response_tracking = session.post(
            "https://jadlog.com.br/FractionWeb/jad/tracking",
            data={
                "cte": cte_code,
                "conhecimento": cte_code,
                "remessa": cte_code,
            },
            headers={"Referer": "https://jadlog.com.br/FractionWeb/jad/"},
            timeout=12,
        )
        if response_tracking.status_code == 200 and not resposta_fraction_indica_login(
            response_tracking.url
        ):
            soup_tracking, texto_tracking = extrair_texto_pagina_fraction(
                response_tracking.content
            )
            tomador, dados_fraction = extrair_resultado_consulta_fraction(
                soup_tracking, texto_tracking, cte_code, fallback=True
            )
            if tomador:
                with cache_lock:
                    armazenar_resultado_cache_fraction(
                        cache, cte_code, tomador, dados_fraction
                    )
                return cte_code, tomador, dados_fraction
    except Exception:
        pass

    if not formulario_localizado:
        ao_formulario_ausente(cte_code)
    return cte_code, None, {}


def selecionar_resultado_fraction(
    resultados: list[tuple[str, Any, dict[str, Any]]],
) -> tuple[str, Any, dict[str, Any]] | None:
    return resultados[0] if resultados else None


def consultar_ctes_fraction_com_retentativas(
    ctes: list[str],
    consultar: Callable[[str], tuple[str, Any, dict[str, Any]]],
    aguardar_entre_ctes: Callable[[], None],
    aguardar_retentativa: Callable[[], None],
) -> tuple[bool, list[tuple[str, Any, dict[str, Any]]]]:
    resultados = []
    for cte_code in ctes:
        aguardar_entre_ctes()
        for _ in range(2):
            _, tomador, metadados = consultar(cte_code)
            if tomador == "COOKIE_EXPIRADO":
                return True, []
            if tomador:
                resultados.append((cte_code, tomador, metadados))
                break
            aguardar_retentativa()
    return False, resultados


def campo_fraction_vazio(valor: Any) -> bool:
    return str(valor or "").strip() in (
        "",
        "None",
        "nan",
        "Sem DACTE",
        "Sem Número",
        "Sem Arquivo Válido",
        "Sem Código",
        "Não informado",
        "Aguardando Conciliação",
    )


def coletar_documentos_planilha_originais(
    item_ref: dict[str, Any], status: str
) -> set[str]:
    if status not in ("OK", "Aguardando Conciliação", ""):
        return set()
    return {
        documento
        for campo in ("EMITENTE - CPF/CNPJ", "DESTINATÁRIO - CPF/CNPJ")
        if (documento := normalizar_documento_fiscal(item_ref.get(campo)))
    }


def atualizar_memoria_termo_fraction(
    memoria_termos: dict[str, dict[str, Any]],
    termo_chave: Any,
    item_ref: dict[str, Any],
    tomador: str,
    dacte: str,
) -> None:
    if termo_chave not in memoria_termos:
        return

    memoria = memoria_termos[termo_chave]
    memoria["TOMADOR"] = tomador
    if dacte:
        memoria["DACTE"] = [dacte]
    for campo in (
        "EMITENTE - NOME/RAZÃO SOCIAL",
        "EMITENTE - CPF/CNPJ",
        "EMITENTE - IE",
        "DESTINATÁRIO - NOME/RAZÃO SOCIAL",
        "DESTINATÁRIO - CPF/CNPJ",
        "DESTINATÁRIO - IE",
    ):
        if item_ref.get(campo):
            memoria[campo] = [item_ref[campo]]


def preencher_campos_fraction(
    item_ref: dict[str, Any],
    tomador: str,
    dacte: str,
    partes: dict[str, str],
) -> None:
    item_ref["TOMADOR"] = tomador
    campos = (
        ("DACTE", dacte, True),
        ("EMITENTE - NOME/RAZÃO SOCIAL", partes["rem_nome"], False),
        ("EMITENTE - CPF/CNPJ", partes["rem_cnpj"], True),
        ("EMITENTE - IE", partes["rem_ie"], True),
        ("DESTINATÁRIO - NOME/RAZÃO SOCIAL", partes["dest_nome"], False),
        ("DESTINATÁRIO - CPF/CNPJ", partes["dest_cnpj"], True),
        ("DESTINATÁRIO - IE", partes["dest_ie"], True),
    )
    for campo, valor, somente_digitos in campos:
        if campo_fraction_vazio(item_ref.get(campo, "")) and valor:
            if campo == "DACTE":
                item_ref[campo] = formatar_texto_excel(valor)
            elif somente_digitos:
                item_ref[campo] = re.sub(r"\D", "", str(valor))
            else:
                item_ref[campo] = valor


def atualizar_linha_fraction(
    item_ref: dict[str, Any],
    status_atual: str,
    tomador: str,
    dacte: str,
    partes: dict[str, str],
) -> set[str]:
    documentos_originais = coletar_documentos_planilha_originais(
        item_ref, status_atual
    )
    preencher_campos_fraction(item_ref, tomador, dacte, partes)
    return documentos_originais


def aplicar_resultado_conferencia_fraction(
    item_ref: dict[str, Any],
    memoria_termos: dict[str, dict[str, Any]],
    tomador: str,
    dacte: str,
    partes: dict[str, str],
    dados_fraction: dict[str, Any],
) -> ResultadoAplicacaoFraction:
    """Aplica dados de um resultado Fraction à linha, memória e status de conferência."""
    status_inicial = str(item_ref.get("STATUS CONFERÊNCIA", "OK"))
    documentos_originais = atualizar_linha_fraction(
        item_ref,
        status_inicial,
        tomador,
        dacte,
        partes,
    )
    atualizar_memoria_termo_fraction(
        memoria_termos,
        item_ref.get("TERMO"),
        item_ref,
        tomador,
        dacte,
    )

    evidencias = preparar_evidencias_conferencia_fraction(dados_fraction, item_ref)
    motivos, inconclusivos = montar_resultado_conferencia_fraction(
        evidencias, documentos_originais
    )
    status_atual = str(item_ref.get("STATUS CONFERÊNCIA", "OK"))
    novo_status, status_atualizado = determinar_status_conferencia_fraction(
        status_atual, motivos, inconclusivos
    )

    if motivos or inconclusivos or status_atualizado:
        item_ref["STATUS CONFERÊNCIA"] = novo_status

    return ResultadoAplicacaoFraction(
        motivos=motivos,
        inconclusivos=inconclusivos,
        status=novo_status,
        status_atualizado=status_atualizado,
    )


def comparar_evidencias_fraction(
    evidencias: EvidenciasConferenciaFraction,
    documentos_planilha_originais: set[str],
) -> tuple[bool | None, bool | None, bool | None]:
    if evidencias.documento_guia:
        if evidencias.documentos_fraction:
            documento_conferido = (
                evidencias.documento_guia in evidencias.documentos_fraction
            )
        elif documentos_planilha_originais:
            documento_conferido = (
                evidencias.documento_guia in documentos_planilha_originais
            )
        else:
            documento_conferido = None
    else:
        documento_conferido = None

    chave_bateu = (
        bool(evidencias.chaves_guia & evidencias.chaves_fraction)
        if evidencias.chaves_guia and evidencias.chaves_fraction
        else None
    )
    numero_bateu = (
        bool(evidencias.numeros_guia & evidencias.numeros_fraction)
        if evidencias.numeros_guia and evidencias.numeros_fraction
        else None
    )
    return documento_conferido, chave_bateu, numero_bateu


def montar_resultado_conferencia_fraction(
    evidencias: EvidenciasConferenciaFraction,
    documentos_planilha_originais: set[str],
) -> tuple[list[str], list[str]]:
    documento_conferido, chave_bateu, numero_bateu = comparar_evidencias_fraction(
        evidencias, documentos_planilha_originais
    )
    motivos = []
    if documento_conferido is False:
        motivos.append(
            f"Doc da guia ({evidencias.documento_guia}) não confere com o Fraction"
        )
    if chave_bateu is False:
        motivos.append("Chave NF-e divergente do CTe")
    if numero_bateu is False:
        motivos.append(
            "Número NF-e divergente "
            f"(guia={sorted(evidencias.numeros_guia)} "
            f"frac={sorted(evidencias.numeros_fraction)})"
        )

    inconclusivos = [
        nome
        for nome, resultado in (
            ("documento", documento_conferido),
            ("chave NF-e", chave_bateu),
            ("número NF-e", numero_bateu),
        )
        if resultado is None
    ]
    return motivos, inconclusivos


def determinar_status_conferencia_fraction(
    status_atual: str, motivos: list[str], inconclusivos: list[str]
) -> tuple[str, bool]:
    if motivos:
        return f"DIVERGÊNCIA CTI ({' | '.join(motivos)})", True
    if inconclusivos:
        return "CONCILIADO PARCIAL", True
    if status_atual in ("OK", "Aguardando Conciliação", ""):
        return "VALIDADO NO FRACTION", True
    return status_atual, False


def preparar_evidencias_conferencia_fraction(
    dados_fraction: dict[str, Any],
    item_ref: dict[str, Any],
) -> EvidenciasConferenciaFraction:
    documentos_fraction = {
        documento
        for valor in dados_fraction.get("cnpjs", [])
        if (documento := normalizar_documento_fiscal(valor))
    }

    chaves_fraction: set[str] = set()
    documentos_chave: set[str] = set()
    numeros_fraction: set[int] = set()

    for valor_chave in dados_fraction.get("chaves_nfe", []):
        chave = re.sub(r"\D", "", str(valor_chave))
        if len(chave) != 44:
            continue
        chaves_fraction.add(chave)
        if chave[20:22] == "55":
            documento_emitente = normalizar_documento_fiscal(chave[6:20])
            if documento_emitente:
                documentos_chave.add(documento_emitente)
            numeros_fraction.add(int(chave[25:34]))

    for valor_numero in dados_fraction.get("numeros_notas", []):
        digitos = re.sub(r"\D", "", str(valor_numero))
        if digitos:
            numeros_fraction.add(int(digitos))

    documentos_fraction |= documentos_chave
    documento_guia = normalizar_documento_fiscal(item_ref.get("CPF/CNPJ DA GUIA"))
    termo_numero = re.sub(r"\D", "", str(item_ref.get("TERMO", "")))

    chaves_guia = set(
        re.findall(
            r"\d{44}",
            re.sub(r"\D", "", str(item_ref.get("CHAVE ARQUIVO", ""))),
        )
    )
    numeros_guia = {
        int(digitos)
        for digitos in re.findall(
            r"\d{1,9}",
            re.sub(r"\D", " ", str(item_ref.get("NÚMERO ARQUIVO", ""))),
        )
        if digitos and digitos != termo_numero
    }

    if termo_numero.isdigit():
        numeros_fraction.discard(int(termo_numero))

    return EvidenciasConferenciaFraction(
        documentos_fraction=documentos_fraction,
        documento_guia=documento_guia,
        chaves_fraction=chaves_fraction,
        chaves_guia=chaves_guia,
        numeros_fraction=numeros_fraction,
        numeros_guia=numeros_guia,
    )


def detectar_rotulo_controle_fraction(form: Any, controle: Any) -> str:
    controle_id = controle.get("id")
    if controle_id:
        label = form.find("label", attrs={"for": controle_id})
        if label:
            return label.get_text(" ", strip=True)

    label = controle.find_parent("label")
    if label:
        return label.get_text(" ", strip=True)

    for proximo in controle.next_siblings:
        if (
            getattr(proximo, "name", None) == "input"
            and str(proximo.get("type", "")).lower() == "radio"
        ):
            break
        if hasattr(proximo, "get_text"):
            rotulo = proximo.get_text(" ", strip=True)
        else:
            rotulo = str(proximo).strip()
        if rotulo:
            return rotulo

    parent_td = controle.find_parent(["td", "th"])
    if parent_td:
        prev_td = parent_td.find_previous_sibling(["td", "th"])
        if prev_td:
            rotulo = prev_td.get_text(" ", strip=True)
            if rotulo:
                return rotulo
    return ""


def extrair_dados_tabela_fraction(soup: Any, txt: str, cte_code: str):
    tomador, remetente, destinatario = "", "", ""
    cnpjs = []

    for table in soup.find_all("table"):
        header_row = table.find("tr")
        if not header_row:
            continue
        headers = [
            th.get_text(" ", strip=True).upper()
            for th in header_row.find_all(["th", "td"])
        ]

        idx_tom = next(
            (i for i, h in enumerate(headers) if re.search(r"TOMADOR|PAGADOR|CLIENTE", h)),
            None,
        )
        idx_rem = next((i for i, h in enumerate(headers) if re.search(r"REMET", h)), None)
        idx_dest = next(
            (i for i, h in enumerate(headers) if re.search(r"DESTINAT", h)), None
        )
        idx_doc = next(
            (i for i, h in enumerate(headers) if re.search(r"CNPJ|CPF|DOC", h)), None
        )

        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if not cells:
                continue
            linha_txt = " ".join(cells)
            cte_na_linha = (cte_code in re.sub(r"\D", "", linha_txt)) or (
                len(table.find_all("tr")) == 2
            )
            if cte_na_linha:
                if idx_tom is not None and idx_tom < len(cells) and cells[idx_tom]:
                    tomador = cells[idx_tom].strip()
                if idx_rem is not None and idx_rem < len(cells) and cells[idx_rem]:
                    remetente = cells[idx_rem].strip()
                if idx_dest is not None and idx_dest < len(cells) and cells[idx_dest]:
                    destinatario = cells[idx_dest].strip()
                if idx_doc is not None and idx_doc < len(cells) and cells[idx_doc]:
                    doc_c = re.sub(r"\D", "", cells[idx_doc])
                    if len(doc_c) >= 5:
                        cnpjs.append(doc_c)
                break
        if tomador:
            break

    if not tomador:
        match_tomador = re.search(
            r"(?:Tomador|Pagador|Cliente)\s*[:\-]?\s*([^\n\r\|;]+?)(?=\s*Remetente|\s*Destinat|\s*Informa|\s*Volume|\s*CNPJ|\s*$)",
            txt,
            re.IGNORECASE,
        )
        if match_tomador:
            tomador = match_tomador.group(1).strip()

    if not remetente:
        match_remetente = re.search(
            r"Remetente\s*[:\-]?\s*([^\n\r\|;]+?)(?=\s*Destinat|\s*End|\s*Cidade|\s*CNPJ|\s*$)",
            txt,
            re.IGNORECASE,
        )
        if match_remetente:
            remetente = match_remetente.group(1).strip()

    if not destinatario:
        match_destinatario = re.search(
            r"Destinat[aá]rio\s*[:\-]?\s*([^\n\r\|;]+?)(?=\s*End|\s*Cidade|\s*CNPJ|\s*$)",
            txt,
            re.IGNORECASE,
        )
        if match_destinatario:
            destinatario = match_destinatario.group(1).strip()

    return tomador, remetente, destinatario, cnpjs


def montar_dados_detalhe_fraction(
    texto: str, cte_code: str, tomador: str
) -> dict[str, Any]:
    match_remetente = re.search(
        r"Nome\s*:\s*(.*?)(?=\s*End\.|\s*Cidade/UF|\s*CNPJ)",
        texto,
        re.IGNORECASE,
    )
    remetente = match_remetente.group(1).strip() if match_remetente else ""

    match_destinatario = re.search(
        r"Dest\.\s*:\s*(.*?)(?=\s*End\.|\s*Cidade/UF|\s*CNPJ)",
        texto,
        re.IGNORECASE,
    )
    destinatario = match_destinatario.group(1).strip() if match_destinatario else ""

    documentos_brutos = re.findall(
        r"(?:Inscri[çc][ãa]o\s+Estadual|IE|CNPJ|CPF)"
        r"(?:\s*/\s*(?:CNPJ|CPF))?\s*[:\-]?\s*([\d\.\/-]{5,25})",
        texto,
        re.IGNORECASE,
    )
    documentos_limpos = sorted(
        {
            re.sub(r"\D", "", documento)
            for documento in documentos_brutos
            if 5 <= len(re.sub(r"\D", "", documento)) <= 18
        }
    )

    chaves_fraction = extrair_chaves_nfe_pdf(texto)
    dactes_fraction = [chave for chave in chaves_fraction if chave[20:22] == "57"]
    match_dacte = re.search(r"Dacte\s*:\s*(\b\d{44}\b)", texto, re.IGNORECASE)
    dacte_rotulado = match_dacte.group(1).strip() if match_dacte else ""
    if dacte_rotulado and dacte_rotulado[20:22] == "57":
        dacte = dacte_rotulado
    else:
        dacte = dactes_fraction[0] if dactes_fraction else ""

    numeros_notas = [
        re.sub(r"\D", "", numero)
        for numero in re.findall(r"NF\s*:\s*(\d{1,9})", texto, re.IGNORECASE)
    ]
    chaves_nfe = [chave for chave in chaves_fraction if chave[20:22] == "55"]
    numeros_nota_por_chave = [
        chave[25:34].lstrip("0") or "0" for chave in chaves_nfe
    ]
    numeros_notas = list(dict.fromkeys(numeros_notas + numeros_nota_por_chave))

    return {
        "cte_consultado": cte_code,
        "tomador": tomador,
        "remetente": remetente,
        "destinatario": destinatario,
        "cnpjs": documentos_limpos,
        "chaves_nfe": list(set(chaves_nfe)),
        "dacte": dacte,
        "dactes": dactes_fraction,
        "numeros_notas": list(set(numeros_notas)),
        "texto_completo": texto,
    }


def montar_dados_fallback_fraction(
    texto: str, cte_code: str, tomador: str
) -> dict[str, Any]:
    return {
        "cte_consultado": cte_code,
        "tomador": tomador,
        "remetente": "",
        "destinatario": "",
        "cnpjs": [],
        "chaves_nfe": [],
        "dacte": "",
        "dactes": [],
        "numeros_notas": [],
        "texto_completo": texto,
    }


def extrair_resultado_consulta_fraction(
    soup: Any, texto: str, cte_code: str, fallback: bool = False
) -> tuple[str | None, dict[str, Any]]:
    tomador, _, _, _ = extrair_dados_tabela_fraction(soup, texto, cte_code)
    if not tomador or len(tomador) <= 2:
        return None, {}

    montar_dados = (
        montar_dados_fallback_fraction if fallback else montar_dados_detalhe_fraction
    )
    return tomador, montar_dados(texto, cte_code, tomador)


def localizar_urls_detalhe_fraction(
    soup: Any, page_url: str, cte_code: str
) -> list[str]:
    urls = []
    for link in soup.find_all("a", href=True):
        href = str(link.get("href", "") or "")
        texto_link = str(link.get_text()).strip()
        if (
            cte_code in href
            or cte_code in texto_link
            or re.search(r"detalhe|tracking|visualizar", href, re.IGNORECASE)
        ):
            urls.append(urljoin(page_url, href))
    return urls


def extrair_texto_pagina_fraction(conteudo: bytes) -> tuple[Any, str]:
    soup = BeautifulSoup(conteudo, "html.parser")
    texto = re.sub(r"\s+", " ", soup.get_text(separator=" "))
    return soup, texto


def resposta_fraction_indica_login(url: str, texto: str = "") -> bool:
    return "login" in url.lower() or "j_spring_security_check" in texto


def extrair_partes_fraction(texto: str, dados_fraction: dict[str, Any]) -> dict[str, str]:
    match_remetente = re.search(
        r"Remetente\b([\s\S]*?)(?:Destinat[áa]rio|Local\s+de\s+Coleta|Informa[çc][õo]es|$)",
        texto,
        re.IGNORECASE,
    )
    texto_remetente = match_remetente.group(1) if match_remetente else ""
    match_nome_remetente = re.search(
        r"Nome\s*:\s*(.*?)(?=\s*End\.|\s*Cidade|\s*Bairro|\s*Cep|\s*Telefone|\s*CNPJ|\s*CPF|\s*IE|$)",
        texto_remetente,
        re.IGNORECASE,
    )
    remetente_nome = (
        match_nome_remetente.group(1).strip()
        if match_nome_remetente
        else (dados_fraction.get("rem_nome") or dados_fraction.get("remetente", ""))
    )
    match_cnpj_remetente = re.search(
        r"(?:CNPJ|CPF)\s*:\s*([\d\.\/-]+)", texto_remetente, re.IGNORECASE
    )
    remetente_cnpj = (
        re.sub(r"\D", "", match_cnpj_remetente.group(1))
        if match_cnpj_remetente
        else dados_fraction.get("rem_cnpj", "")
    )
    match_ie_remetente = re.search(
        r"IE\s*:\s*([\d\.\/-]+)", texto_remetente, re.IGNORECASE
    )
    remetente_ie = (
        re.sub(r"\D", "", match_ie_remetente.group(1))
        if match_ie_remetente
        else dados_fraction.get("rem_ie", "")
    )

    match_destinatario = re.search(
        r"Destinat[áa]rio\b([\s\S]*?)(?:Local\s+de\s+Coleta|Informa[çc][õo]es|Nota\s+Fiscal|$)",
        texto,
        re.IGNORECASE,
    )
    texto_destinatario = match_destinatario.group(1) if match_destinatario else ""
    match_nome_destinatario = re.search(
        r"(?:Dest\.|Nome)\s*:\s*(.*?)(?=\s*End\.|\s*Cidade|\s*Bairro|\s*Cep|\s*Telefone|\s*CNPJ|\s*CPF|\s*IE|$)",
        texto_destinatario,
        re.IGNORECASE,
    )
    destinatario_nome = (
        match_nome_destinatario.group(1).strip()
        if match_nome_destinatario
        else (dados_fraction.get("dest_nome") or dados_fraction.get("destinatario", ""))
    )
    match_cnpj_destinatario = re.search(
        r"(?:CNPJ|CPF)\s*:\s*([\d\.\/-]+)", texto_destinatario, re.IGNORECASE
    )
    destinatario_cnpj = (
        re.sub(r"\D", "", match_cnpj_destinatario.group(1))
        if match_cnpj_destinatario
        else dados_fraction.get("dest_cnpj", "")
    )
    match_ie_destinatario = re.search(
        r"IE\s*:\s*([\d\.\/-]+)", texto_destinatario, re.IGNORECASE
    )
    destinatario_ie = (
        re.sub(r"\D", "", match_ie_destinatario.group(1))
        if match_ie_destinatario
        else dados_fraction.get("dest_ie", "")
    )

    return {
        "rem_nome": remetente_nome,
        "rem_cnpj": remetente_cnpj,
        "rem_ie": remetente_ie,
        "dest_nome": destinatario_nome,
        "dest_cnpj": destinatario_cnpj,
        "dest_ie": destinatario_ie,
    }


def preparar_formulario_fraction(form: Any, page_url: str, cte_code: str):
    controles = form.find_all(["input", "textarea", "select", "button"])
    if not controles:
        return None

    action_bruta = str(form.get("action", "") or "").strip()
    if "login" in action_bruta.lower():
        return None

    todos_os_nomes = " ".join(str(c.get("name", "") or "") for c in controles).lower()
    if re.search(
        r"codigomfa|atualizasenha|id_senha|id_usuario|botao_login"
        r"|form_notificacao|form_navegador",
        todos_os_nomes,
    ):
        return None

    padrao_cte = r"\bcte\b|conhecimento|nrcte|numcte|num_conhecimento"
    campo_cte = None

    for controle in controles:
        if controle.name not in ("input", "textarea"):
            continue
        tipo = str(controle.get("type", "text") or "text").lower()
        if tipo not in ("text", "search", ""):
            continue
        nome = str(controle.get("name", "") or "").lower()
        cid = str(controle.get("id", "") or "").lower()
        rotulo = (detectar_rotulo_controle_fraction(form, controle) or "").lower()
        if (
            re.search(padrao_cte, nome)
            or re.search(padrao_cte, cid)
            or re.search(padrao_cte, rotulo)
        ):
            campo_cte = controle
            break

    campo_codigo = None
    if campo_cte is None:
        for controle in controles:
            if controle.name not in ("input", "textarea"):
                continue
            tipo = str(controle.get("type", "text") or "text").lower()
            if tipo not in ("text", "textarea", ""):
                continue
            alvo = " ".join(
                [
                    str(controle.get("name", "") or ""),
                    str(controle.get("id", "") or ""),
                    detectar_rotulo_controle_fraction(form, controle) or "",
                ]
            ).lower()
            if re.search(r"c[oó]digo|pesquis|filtro", alvo):
                campo_codigo = controle
                break

    if campo_cte is None and campo_codigo is None:
        return None

    radios = [
        c for c in controles if c.name == "input" and str(c.get("type", "")).lower() == "radio"
    ]
    radio_escolhido = None

    if radios:
        for radio in radios:
            rotulo = (detectar_rotulo_controle_fraction(form, radio) or "").lower()
            valor = str(radio.get("value", "") or "").lower()
            radio_id = str(radio.get("id", "") or "").lower()
            if re.search(r"conhec|\bcte\b", " ".join([rotulo, valor, radio_id])):
                radio_escolhido = radio
                break

        if radio_escolhido is None:
            for radio in radios:
                radio_id = str(radio.get("id", "") or "")
                if not radio_id:
                    continue
                label = form.find("label", attrs={"for": radio_id})
                if label is not None and re.search(
                    r"conhec|\bcte\b", label.get_text(" ", strip=True).lower()
                ):
                    radio_escolhido = radio
                    break

        if radio_escolhido is None:
            radio_escolhido = radios[0]

    action = urljoin(page_url, action_bruta or page_url)
    method = str(form.get("method", "post") or "post").strip().lower()

    campos = []
    grupos_radio_enviados = set()

    for controle in controles:
        nome = str(controle.get("name", "") or "").strip()
        tipo = str(controle.get("type", "") or "").lower()

        if controle is campo_cte or controle is campo_codigo:
            campos.append((nome, str(cte_code)))
            continue

        if tipo == "radio":
            if controle is radio_escolhido and nome not in grupos_radio_enviados:
                campos.append((nome, str(controle.get("value", "on") or "on")))
                grupos_radio_enviados.add(nome)
            continue

        if tipo == "checkbox":
            if controle.has_attr("checked") and nome:
                campos.append((nome, str(controle.get("value", "on") or "on")))
            continue

        if tipo in ("submit", "button"):
            if nome:
                campos.append((nome, str(controle.get("value", "") or "")))
            continue

        if controle.name == "select":
            opcao = controle.find("option", selected=True) or controle.find("option")
            if opcao is not None and nome:
                campos.append((nome, str(opcao.get("value", "") or "")))
            continue

        if controle.name == "textarea" or tipo in ("hidden", "text", "search"):
            if not nome:
                continue
            campos.append((nome, str(controle.get("value", "") or "")))
            continue

    if not any(nome == "javax.faces.ViewState" for nome, _ in campos):
        return None

    return action, method, campos
