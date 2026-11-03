from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppState:
    """Estado compartilhado da aplicação, separado da interface gráfica."""

    api: Any | None = None
    cookie_jadlog: str = ""
    cancelar_operacao: bool = False

    dados_em_memoria: list[dict[str, Any]] = field(default_factory=list)
    memoria_termos: dict[str, dict[str, Any]] = field(default_factory=dict)
    tickets_processados: dict[str, Any] = field(default_factory=dict)
    ctes_consultados_cache: dict[str, Any] = field(default_factory=dict)