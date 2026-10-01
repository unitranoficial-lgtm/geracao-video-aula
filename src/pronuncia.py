"""Normalização fonética do texto enviado ao sintetizador de voz."""

from __future__ import annotations

import json
import re
from pathlib import Path


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "pronunciation_config.json"


def carregar_aliases(caminho: Path = DEFAULT_CONFIG) -> dict[str, str]:
    """Carrega pronúncias explícitas sem modificar o roteiro editorial."""
    data = json.loads(caminho.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.get("aliases", {}).items()}


def normalizar_pronuncia(
    texto: str | None,
    aliases: dict[str, str] | None = None,
) -> str | None:
    """Adapta somente siglas pronunciadas como palavras.

    Siglas soletradas permanecem em caixa alta e são enviadas ao ElevenLabs
    exatamente como aparecem no roteiro. Os aliases existem apenas para
    acrônimos falados como uma palavra, como ``CIOT`` → ``cioti``.
    """
    if texto is None:
        return None

    aliases = aliases or carregar_aliases()
    resultado = texto
    # Termos maiores primeiro evita que TRC altere o trecho interno de RNTRC.
    for termo in sorted(aliases, key=len, reverse=True):
        padrao = re.compile(
            rf"(?<![\w-]){re.escape(termo)}(?![\w-])",
            flags=re.IGNORECASE,
        )
        resultado = padrao.sub(aliases[termo], resultado)
    return resultado
