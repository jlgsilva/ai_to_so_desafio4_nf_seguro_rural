"""
Configuracao central de logging da aplicacao.

Grava em logs/app.log (arquivo rotacionado, ate 5 arquivos de 2 MB
cada) e tambem imprime no console (util quando rodando via `streamlit
run`, onde o console e o terminal do usuario).

Registra: parametros de ingestao (encoding/delimitador detectados),
familia de dados reconhecida, cada chamada de agente (com duracao),
planos e SQL gerados, tentativas de auto-correcao, e qualquer excecao
com stack trace completo. Isso permite diagnosticar problemas (ex.:
erro 413 de limite de tokens da API) sem depender apenas da mensagem
resumida mostrada na interface.

Uso em qualquer modulo:
    from src.logging_config import get_logger
    log = get_logger(__name__)
    log.info("mensagem")
    log.exception("erro ao processar X")   # dentro de um except
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "app.log")
MAX_BYTES = 2_000_000
BACKUP_COUNT = 5

_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return

    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger("insurminds")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    console_handler.setLevel(logging.INFO)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure()
    return logging.getLogger(f"insurminds.{name}")


def read_recent_logs(n_lines: int = 300) -> str:
    """Le as ultimas n linhas do arquivo de log atual, para exibicao na
    interface (aba Historico > Log)."""
    if not os.path.exists(LOG_FILE):
        return "Nenhum log gravado ainda nesta instalacao."
    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return "".join(lines[-n_lines:])
