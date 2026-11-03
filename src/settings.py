"""Central configuration. Single source of truth for paths, timeouts and UI."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str = "Automacao Total JadLog"
    version: str = "1.3"
    base_dir: Path = Path(__file__).resolve().parent.parent
    icone_app: str = "icons8-coordenada-z-48.ico"
    arquivo_layouts: str = "layouts_custom.json"
    arquivo_dedicados: str = "base_clientes_dedicados.json"
    arquivo_memoria: str = "memoria_diaria_jadlog.json"
    pasta_checkpoints: str = "checkpoints"
    timeout_api: int = 15
    max_workers: int = 8
    subdomain_padrao: str = "jadloglogsticahelp"


SETTINGS = Settings()
