# src/services/zendesk_api.py
"""Cliente Zendesk API. Copiado 1:1 do backup, sem alterar regra."""

from __future__ import annotations

import re
import threading
import time

import requests
from requests.adapters import HTTPAdapter


class ZendeskAPI:
    def __init__(self, subdomain: str, cookie: str):
        self.subdomain = subdomain
        self.base_url = f"https://{subdomain}.zendesk.com/api/v2"

        cookie_limpo = cookie.strip()
        if cookie_limpo.lower().startswith("cookie:"):
            cookie_limpo = cookie_limpo[7:].strip()
        self.cookie_limpo = re.sub(r"[\r\n]+", "", cookie_limpo)
        self._local = threading.local()

    @property
    def session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            s = requests.Session()
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
            s.mount("https://", adapter)
            s.mount("http://", adapter)
            s.headers.update(
                {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Cookie": self.cookie_limpo,
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                }
            )
            self._local.session = s
        return self._local.session

    def validar_autenticacao(self) -> tuple[bool, str]:
        try:
            resp = self.session.get(
                f"{self.base_url}/users/me.json", timeout=10, allow_redirects=False
            )
            if resp.status_code == 200 and "user" in resp.json():
                return True, resp.json().get("user", {}).get("name", "Agente")
            elif resp.status_code in (301, 302, 401, 403):
                return False, "Sessão expirada. Atualize o Cookie do Zendesk."
            return False, f"Status HTTP: {resp.status_code}"
        except Exception as e:
            return False, str(e)

    def obter_ticket(self, ticket_id: str) -> dict | None:
        try:
            resp = self.session.get(
                f"{self.base_url}/tickets/{ticket_id}.json", timeout=15, allow_redirects=False
            )
            if resp.status_code == 200 and "ticket" in resp.json():
                return resp.json().get("ticket")
        except Exception:
            pass
        return None

    def obter_comentarios(self, ticket_id: str) -> list:
        try:
            resp = self.session.get(
                f"{self.base_url}/tickets/{ticket_id}/comments.json",
                timeout=15,
                allow_redirects=False,
            )
            if resp.status_code == 200 and "comments" in resp.json():
                return resp.json().get("comments", [])
        except Exception:
            pass
        return []

    def baixar_conteudo(self, url: str, retries: int = 3) -> tuple[bytes | None, str]:
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.get(url, allow_redirects=False, timeout=(10, 45))
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location")
                    if location:
                        req_s3 = requests.get(
                            location, timeout=(10, 60), headers={"User-Agent": "Mozilla/5.0"}
                        )
                        if req_s3.status_code == 200:
                            return req_s3.content, "OK"
                        return None, f"Erro S3 HTTP {req_s3.status_code}"
                elif resp.status_code == 200:
                    return resp.content, "OK"
                return None, f"Erro HTTP {resp.status_code}"
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                if attempt == retries:
                    return None, f"Timeout na rede após {retries} tentativas: {e}"
                time.sleep(1.5 * attempt)
            except Exception as e:
                return None, str(e)
        return None, "Falha no download"

    def responder_ticket(self, ticket_id: str, mensagem: str, status: str = "solved") -> bool:
        try:
            payload = {"ticket": {"comment": {"body": mensagem, "public": True}, "status": status}}
            resp = self.session.put(
                f"{self.base_url}/tickets/{ticket_id}.json", json=payload, timeout=15
            )
            return resp.status_code == 200
        except Exception:
            return False
