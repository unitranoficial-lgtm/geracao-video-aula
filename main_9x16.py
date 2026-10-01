#!/usr/bin/env python3
"""Entrada separada para criar roteiros de vídeos verticais 9:16."""

import argparse

from main import cmd_editar, cmd_gerar_roteiro


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerador vertical 9:16 de Vídeo-Aulas Unitran")
    parser.add_argument("input", nargs="?", help="Descrição da aula")
    parser.add_argument("--editar", metavar="PASTA", help="Edita os takes de um projeto já gerado")
    args = parser.parse_args()

    if args.editar:
        cmd_editar(args.editar)
    elif args.input:
        cmd_gerar_roteiro(args.input, aspect_ratio="9:16")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
