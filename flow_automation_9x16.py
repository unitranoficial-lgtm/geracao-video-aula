#!/usr/bin/env python3
"""Entrypoint separado para vídeos verticais 9:16.

Aceita os mesmos argumentos de flow_automation.py, mas configura imagens,
frames e prompts para 9:16. Toda a lógica robusta permanece compartilhada.
"""

import flow_automation as fluxo


if __name__ == "__main__":
    fluxo.ASPECT_RATIO = "9:16"
    fluxo.main()
