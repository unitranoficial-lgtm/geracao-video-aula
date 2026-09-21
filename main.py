#!/usr/bin/env python3
"""
Gerador de Vídeo-Aulas — Unitran
---------------------------------
Uso:
  python main.py "Direito Trabalhista - Rescisão de Contrato"
  python main.py "Cálculo - Derivadas" --estilo quadro_negro
  python main.py "Marketing Digital" --so-roteiro
  python main.py "Contabilidade Básica" --listar-vozes
"""

import argparse
import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv()

from src.models import EstiloVisual
from src.roteiro import gerar_roteiro, salvar_roteiro
from src.narracao import listar_vozes, exibir_vozes, gerar_narracao_completa
from src.visual import gerar_videos_completo
from src.editor import gerar_manifesto

console = Console()

ESTILOS_DISPONIVEIS = {
    "quadro_branco": EstiloVisual.QUADRO_BRANCO,
    "quadro_branco_mao": EstiloVisual.QUADRO_BRANCO_MAO,
    "quadro_negro": EstiloVisual.QUADRO_NEGRO,
    "animacao_2d": EstiloVisual.ANIMACAO_2D,
}


def main():
    parser = argparse.ArgumentParser(
        description="Gera vídeo-aulas completas para a Unitran",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("assunto", nargs="?", help="Assunto da aula")
    parser.add_argument(
        "--estilo",
        choices=list(ESTILOS_DISPONIVEIS.keys()),
        default="quadro_branco",
        help="Estilo visual do vídeo (padrão: quadro_branco)",
    )
    parser.add_argument(
        "--segmentos",
        type=int,
        default=6,
        help="Número aproximado de segmentos (padrão: 6)",
    )
    parser.add_argument(
        "--voice-id",
        default=os.getenv("ELEVENLABS_VOICE_ID", ""),
        help="ID da voz ElevenLabs",
    )
    parser.add_argument(
        "--modelo-video",
        default="veo-3",
        help="Modelo de vídeo no Kairogen (padrão: veo-3)",
    )
    parser.add_argument(
        "--output",
        default="output",
        help="Pasta de saída (padrão: output/)",
    )
    parser.add_argument("--so-roteiro", action="store_true", help="Gera apenas o roteiro, sem áudio e vídeo")
    parser.add_argument("--so-narracao", action="store_true", help="Gera roteiro + narração, sem vídeo")
    parser.add_argument("--listar-vozes", action="store_true", help="Lista vozes disponíveis no ElevenLabs e sai")
    parser.add_argument("--roteiro-json", help="Usa um roteiro já gerado (pula etapa 1)")

    args = parser.parse_args()

    # --- Listar vozes ---
    if args.listar_vozes:
        from elevenlabs import ElevenLabs
        client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
        vozes = listar_vozes(client)
        exibir_vozes(vozes)
        sys.exit(0)

    if not args.assunto and not args.roteiro_json:
        parser.print_help()
        sys.exit(1)

    pasta_output = args.output
    Path(pasta_output).mkdir(parents=True, exist_ok=True)

    console.print(Panel(
        f"[bold]Gerador de Vídeo-Aulas Unitran[/bold]\n"
        f"Assunto: [cyan]{args.assunto or 'do roteiro existente'}[/cyan]\n"
        f"Estilo:  [cyan]{args.estilo}[/cyan]",
        style="bold blue",
    ))

    # --- Etapa 1: Roteiro ---
    if args.roteiro_json:
        with open(args.roteiro_json, encoding="utf-8") as f:
            from src.models import Roteiro
            roteiro = Roteiro.model_validate_json(f.read())
        roteiro_path = args.roteiro_json
        console.print(f"[green]✓[/green] Roteiro carregado de: {roteiro_path}")
    else:
        estilo = ESTILOS_DISPONIVEIS[args.estilo]
        roteiro = gerar_roteiro(args.assunto, estilo, args.segmentos)
        roteiro_path = salvar_roteiro(roteiro, pasta_output)

    if args.so_roteiro:
        console.print("\n[bold green]Roteiro gerado com sucesso![/bold green]")
        _imprimir_roteiro(roteiro)
        sys.exit(0)

    # --- Etapa 2: Narração ---
    if not args.voice_id:
        console.print("\n[yellow]⚠ Nenhum ELEVENLABS_VOICE_ID definido.[/yellow]")
        console.print("Use [bold]--listar-vozes[/bold] para ver as disponíveis, depois:")
        console.print("  export ELEVENLABS_VOICE_ID=<id>  ou defina no .env\n")
        sys.exit(1)

    audios = gerar_narracao_completa(roteiro, args.voice_id, pasta_output)

    if args.so_narracao:
        gerar_manifesto(roteiro_path, audios, [], pasta_output)
        console.print("\n[bold green]Narração gerada com sucesso![/bold green]")
        sys.exit(0)

    # --- Etapa 3: Vídeos visuais ---
    videos = gerar_videos_completo(roteiro, pasta_output, args.modelo_video)

    # --- Etapa 4: Manifesto de edição ---
    gerar_manifesto(roteiro_path, audios, videos, pasta_output)

    console.print("\n[bold green]✓ Fluxo completo concluído![/bold green]")
    console.print(f"Arquivos em: [cyan]{os.path.abspath(pasta_output)}[/cyan]")


def _imprimir_roteiro(roteiro) -> None:
    from rich.table import Table
    console.print(f"\n[bold]{roteiro.titulo_aula}[/bold]")
    console.print(f"Objetivos: {', '.join(roteiro.objetivos_aprendizagem)}\n")
    table = Table(show_lines=True)
    table.add_column("#", width=3)
    table.add_column("Segmento")
    table.add_column("Duração")
    table.add_column("Narração (início)", width=50)
    for s in roteiro.segmentos:
        table.add_row(
            str(s.id),
            s.titulo,
            f"{s.duracao_estimada_segundos}s",
            s.narracao[:80] + "...",
        )
    console.print(table)


if __name__ == "__main__":
    main()
