import re
import threading
from decimal import Decimal
from typing import Any
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter

from src.utils.logging_config import log_terminal


def limpar_e_formatar_cookie(valor: str) -> str:
    texto = str(valor or "").strip()
    if (texto.startswith('"') and texto.endswith('"')) or (
        texto.startswith("'") and texto.endswith("'")
    ):
        texto = texto[1:-1].strip()
    m_curl = re.search(
        r'(?:-H\s+["\']?Cookie:\s*|Cookie:\s*)([^;\r\n]+)', texto, re.IGNORECASE
    )
    if m_curl:
        texto = m_curl.group(1).strip()
    elif texto.lower().startswith("cookie:"):
        texto = texto[7:].strip()
    if "=" not in texto and len(texto) > 10:
        texto = f"JSESSIONID={texto}"
    return texto


class FractionService:
    URLS_PESQUISA = [
        "https://jadlog.com.br/FractionWeb/jad/pesquisar",
        "https://jadlog.com.br/FractionWeb/jad/consulta",
        "https://jadlog.com.br/FractionWeb/jad/consultaGeral",
        "https://jadlog.com.br/FractionWeb/jad/consultar",
        "https://jadlog.com.br/FractionWeb/jad/tracking",
        "https://jadlog.com.br/FractionWeb/jad/",
        "https://jadlog.com.br/FractionWeb/pesquisar.jad",
        "https://jadlog.com.br/FractionWeb/jad/tracking.jadlog",
    ]

    def __init__(self, cookie: str = ""):
        self.cookie = limpar_e_formatar_cookie(cookie)
        self._local = threading.local()

    def atualizar_cookie(self, novo_cookie: str):
        self.cookie = limpar_e_formatar_cookie(novo_cookie)
        if hasattr(self._local, "session"):
            delattr(self._local, "session")

    @property
    def session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            s = requests.Session()
            adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10)
            s.mount("https://", adapter)
            s.mount("http://", adapter)
            s.headers.update(
                {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Cookie": self.cookie,
                }
            )
            self._local.session = s
        return self._local.session

    def validar_conexao(self) -> tuple[bool, str]:
        if not self.cookie:
            return False, "Cookie Fraction não configurado."
        try:
            r = self.session.get("https://jadlog.com.br/FractionWeb/jad/pesquisar", timeout=10)
            if "login" in r.url.lower() or "j_spring_security_check" in r.text:
                return False, "Sessão expirada. Atualize o Cookie do Fraction."
            return True, "Sessão válida."
        except Exception as e:
            return False, f"Falha ao conectar no Fraction: {e}"

    @staticmethod
    def _detectar_rotulo_controle(form: Any, controle: Any) -> str:
        cid = controle.get("id")
        if cid:
            label = form.find("label", attrs={"for": cid})
            if label:
                return label.get_text(" ", strip=True)
        label = controle.find_parent("label")
        if label:
            return label.get_text(" ", strip=True)
        for proximo in controle.next_siblings:
            if getattr(proximo, "name", None) == "input" and str(proximo.get("type", "")).lower() == "radio":
                break
            if hasattr(proximo, "get_text"):
                rotulo = proximo.get_text(" ", strip=True)
                if rotulo:
                    return rotulo
        td = controle.find_parent(["td", "th"])
        if td:
            prev = td.find_previous_sibling(["td", "th"])
            if prev and prev.get_text(" ", strip=True):
                return prev.get_text(" ", strip=True)
        return ""

    def _preparar_formulario(self, form: Any, page_url: str, cte_code: str):
        controles = form.find_all(["input", "textarea", "select", "button"])
        if not controles:
            return None

        campo_cte_direto = None
        for c in controles:
            if c.name == "input" and str(c.get("type", "text")).lower() in ("text", "search", ""):
                rot = self._detectar_rotulo_controle(form, c).lower()
                nm = str(c.get("name", "")).lower()
                cid = str(c.get("id", "")).lower()
                if re.search(r"^\s*cte\b|\bcte\s*$|conhecimento|nrcte|numcte", rot) or \
                   re.search(r"\bcte\b|conhecimento|nrcte|numcte", nm) or \
                   re.search(r"\bcte\b|conhecimento|nrcte|numcte", cid):
                    campo_cte_direto = c
                    break

        campo_cod_generico = None
        if campo_cte_direto is None:
            for c in controles:
                if c.name in ("textarea", "input") and str(c.get("type", "text")).lower() in ("text", "textarea", ""):
                    rot = self._detectar_rotulo_controle(form, c).lower()
                    nm = str(c.get("name", "")).lower()
                    cid = str(c.get("id", "")).lower()
                    if re.search(r"c[oó]d|codigo", rot + " " + nm + " " + cid):
                        campo_cod_generico = c
                        break
            if campo_cod_generico is None:
                campo_cod_generico = next((c for c in controles if c.name == "textarea" and c.get("name")), None)

        if campo_cte_direto is None and campo_cod_generico is None:
            return None

        radios = [c for c in controles if c.name == "input" and str(c.get("type", "")).lower() == "radio"]
        radio_sel = None
        if radios:
            for r in radios:
                rot = self._detectar_rotulo_controle(form, r).lower()
                val = str(r.get("value", "")).lower()
                if re.search(r"conhec", rot) or re.search(r"conhec", val):
                    radio_sel = r
                    break
            if radio_sel is None:
                for r in radios:
                    if "remessa" in (self._detectar_rotulo_controle(form, r) + str(r.get("value", ""))).lower():
                        radio_sel = r
                        break
            radio_sel = radio_sel or radios[0]

        select_conhec = None
        if not radios:
            for sel in (c for c in controles if c.name == "select" and c.get("name")):
                op = next((o for o in sel.find_all("option") if re.search(r"conhec|remessa", o.get_text(" ", strip=True), re.IGNORECASE)), None)
                if op:
                    select_conhec = (sel, op)
                    break

        campos = []
        for c in controles:
            nome = c.get("name")
            if not nome:
                continue
            tipo = str(c.get("type", "")).lower()
            if c is campo_cte_direto or c is campo_cod_generico:
                campos.append((nome, cte_code))
            elif radios and c is radio_sel:
                campos.append((nome, str(c.get("value", "on"))))
            elif tipo == "radio":
                continue
            elif select_conhec and c is select_conhec[0]:
                campos.append((nome, str(select_conhec[1].get("value", ""))))
            elif tipo in ("hidden", "submit", "button"):
                val = str(c.get("value", ""))
                if re.search(r"cancel|voltar|limpar|sair", nome + " " + val, re.IGNORECASE):
                    continue
                campos.append((nome, val))
            elif tipo == "checkbox" and c.has_attr("checked"):
                campos.append((nome, str(c.get("value", "on"))))
            elif c.name == "input" and tipo in ("text", "search"):
                campos.append((nome, str(c.get("value", ""))))

        action = urljoin(page_url, str(form.get("action") or page_url))
        method = str(form.get("method", "get")).lower()
        return action, method, campos

    def extrair_dados_tabela(self, soup: Any, txt: str, cte_code: str) -> tuple[str, str, str, list[str]]:
        tomador, remetente, destinatario = "", "", ""
        cnpjs = []

        for table in soup.find_all("table"):
            header_row = table.find("tr")
            if not header_row:
                continue
            headers = [th.get_text(" ", strip=True).upper() for th in header_row.find_all(["th", "td"])]
            idx_tom = next((i for i, h in enumerate(headers) if re.search(r"TOMADOR|PAGADOR|CLIENTE", h)), None)
            idx_rem = next((i for i, h in enumerate(headers) if re.search(r"REMET", h)), None)
            idx_dest = next((i for i, h in enumerate(headers) if re.search(r"DESTINAT", h)), None)
            idx_doc = next((i for i, h in enumerate(headers) if re.search(r"CNPJ|CPF|DOC", h)), None)

            for tr in table.find_all("tr")[1:]:
                cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
                if not cells:
                    continue
                linha_txt = " ".join(cells)
                if (cte_code in re.sub(r"\D", "", linha_txt)) or (len(table.find_all("tr")) == 2):
                    if idx_tom is not None and idx_tom < len(cells):
                        tomador = cells[idx_tom].strip()
                    if idx_rem is not None and idx_rem < len(cells):
                        remetente = cells[idx_rem].strip()
                    if idx_dest is not None and idx_dest < len(cells):
                        destinatario = cells[idx_dest].strip()
                    if idx_doc is not None and idx_doc < len(cells):
                        doc_c = re.sub(r"\D", "", cells[idx_doc])
                        if len(doc_c) >= 5:
                            cnpjs.append(doc_c)
                    break
            if tomador:
                break

        if not tomador:
            m = re.search(r"(?:Tomador|Pagador|Cliente)\s*[:\-]?\s*([^\n\r\|;]+?)(?=\s*Remetente|\s*Destinat|\s*Informa|\s*Volume|\s*CNPJ|\s*$)", txt, re.IGNORECASE)
            if m:
                tomador = m.group(1).strip()
        if not remetente:
            m = re.search(r"Remetente\s*[:\-]?\s*([^\n\r\|;]+?)(?=\s*Destinat|\s*End|\s*Cidade|\s*CNPJ|\s*$)", txt, re.IGNORECASE)
            if m:
                remetente = m.group(1).strip()
        if not destinatario:
            m = re.search(r"Destinat[aá]rio\s*[:\-]?\s*([^\n\r\|;]+?)(?=\s*End|\s*Cidade|\s*CNPJ|\s*$)", txt, re.IGNORECASE)
            if m:
                destinatario = m.group(1).strip()

        return tomador, remetente, destinatario, cnpjs

    def consultar_cte(self, cte_code: str) -> tuple[str, str | None, dict]:
        cte_limpo = re.sub(r"\D", "", str(cte_code or ""))
        if not cte_limpo:
            return cte_code, None, {}

        for url in self.URLS_PESQUISA:
            try:
                pagina = self.session.get(url, timeout=12)
                if "login" in pagina.url.lower() or "j_spring_security_check" in pagina.text:
                    return cte_limpo, "COOKIE_EXPIRADO", {}
                if pagina.status_code >= 400:
                    continue

                soup = BeautifulSoup(pagina.content, "html.parser")
                for form in soup.find_all("form"):
                    prep = self._preparar_formulario(form, pagina.url, cte_limpo)
                    if not prep:
                        continue
                    action, method, campos = prep
                    req_func = self.session.post if method == "post" else self.session.get
                    resp = req_func(action, data=campos if method == "post" else None, params=campos if method == "get" else None, headers={"Referer": pagina.url}, timeout=15)
                    
                    if "login" in resp.url.lower():
                        return cte_limpo, "COOKIE_EXPIRADO", {}

                    soup_resp = BeautifulSoup(resp.content, "html.parser")
                    txt = re.sub(r"\s+", " ", soup_resp.get_text(separator=" "))
                    tomador, rem, dest, docs = self.extrair_dados_tabela(soup_resp, txt, cte_limpo)

                    if tomador and len(tomador) > 2:
                        docs_all = sorted({re.sub(r"\D", "", d) for d in re.findall(r"(?:CNPJ|CPF|IE)\s*[:\-]?\s*([\d\.\/-]{5,25})", txt, re.IGNORECASE) if len(re.sub(r"\D", "", d)) >= 5} | set(docs))
                        chaves_55 = [ch for ch in re.findall(r"\b\d{44}\b", txt) if ch[20:22] == "55"]
                        dactes_57 = [ch for ch in re.findall(r"\b\d{44}\b", txt) if ch[20:22] == "57"]
                        nfs = list(dict.fromkeys(re.findall(r"NF\s*:\s*(\d{1,9})", txt, re.IGNORECASE) + [ch[25:34].lstrip("0") for ch in chaves_55]))

                        return cte_limpo, tomador, {
                            "cte": cte_limpo,
                            "tomador": tomador,
                            "remetente": rem,
                            "destinatario": dest,
                            "cnpjs": docs_all,
                            "chaves_nfe": chaves_55,
                            "dacte": dactes_57[0] if dactes_57 else "",
                            "numeros_notas": nfs,
                            "texto_completo": txt,
                        }
            except Exception:
                continue

        return cte_limpo, None, {}