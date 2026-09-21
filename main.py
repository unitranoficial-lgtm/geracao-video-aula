#!/usr/bin/env python3
"""
Gerador de Vídeo-Aulas — Unitran

Uso:
  # Gerar roteiro para aprovação
  python main.py "aula sobre CLT rescisão de contrato, quadro branco com maozinha, 3 minutos, voz: Rachel"

  # Editar takes já gerados (após baixar do Flow e ElevenLabs)
  python main.py --editar "C:/Users/UNITRAN/Documents/Geracao video aula/nome-do-video"
"""

import argparse
import os
import sys
from dotenv import load_dotenv
from rich.console import Console
from rich.prompt import Confirm

load_dotenv()

console = Console()


def cmd_gerar_roteiro(input_texto: str) -> None:
    from src.roteiro import gerar_roteiro, exibir_roteiro, salvar_roteiro

    roteiro = gerar_roteiro(input_texto)
    exibir_roteiro(roteiro)

    if not Confirm.ask("\n[bold yellow]Aprovar este roteiro?[/bold yellow]"):
        console.print("[red]Roteiro não aprovado. Rode novamente para gerar outro.[/red]")
        sys.exit(0)

    # Salva na pasta local do projeto
    nome_pasta = roteiro.titulo.lower().replace(" ", "_").replace("/", "-")[:50]
    base = os.environ.get("PASTA_PROJETOS", os.path.expanduser("~"))
    pasta = os.path.join(base, "Geracao video aula", nome_pasta)

    caminho = salvar_roteiro(roteiro, pasta)
    console.print(f"\n[green]✓[/green] Roteiro aprovado e salvo em: [cyan]{caminho}[/cyan]")
    console.print("\n[bold]Próximos passos:[/bold]")
    console.print(f"  1. Abra o Google Flow e crie o projeto: [cyan]{roteiro.titulo}[/cyan]")
    console.print(f"  2. Gere a imagem coringa: [dim]{roteiro.prompt_imagem_coringa[:80]}...[/dim]")
    console.print(f"  3. Para cada take, gere 4 imagens → selecione a melhor → gere o vídeo")
    console.print(f"  4. Gere os áudios no ElevenLabs com a voz [cyan]{roteiro.voz_elevenlabs}[/cyan]")
    console.print(f"  5. Salve tudo em: [cyan]{pasta}[/cyan]")
    console.print(f"  6. Rode: [bold]python main.py --editar \"{pasta}\"[/bold]")


def cmd_editar(pasta_projeto: str) -> None:
    from src.editor import editar_projeto

    console.print(f"[bold cyan]Editando projeto:[/bold cyan] {pasta_projeto}")

    # Instala ffmpeg se necessário
    import shutil
    if not shutil.which("ffmpeg"):
        console.print("[yellow]FFmpeg não encontrado. Instalando...[/yellow]")
        import subprocess
        subprocess.run(["apt-get", "install", "-y", "-q", "ffmpeg"], check=True)

    video_final = editar_projeto(pasta_projeto)
    console.print(f"\n[bold green]Concluído![/bold green] Vídeo final: [cyan]{video_final}[/cyan]")


def main():
    parser = argparse.ArgumentParser(description="Gerador de Vídeo-Aulas Unitran")
    parser.add_argument("input", nargs="?", help="Descrição da aula (assunto, estilo, duração, voz)")
    parser.add_argument("--editar", metavar="PASTA", help="Edita os takes de um projeto já gerado")
    args = parser.parse_args()

    if args.editar:
        cmd_editar(args.editar)
    elif args.input:
        cmd_gerar_roteiro(args.input)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
