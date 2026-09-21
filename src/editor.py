"""Etapa 4: Geração do manifesto de edição e instruções de sincronização."""

import json
import os
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def gerar_manifesto(
    roteiro_path: str,
    audios: list[dict],
    videos: list[dict],
    pasta_output: str,
) -> str:
    """
    Gera um manifesto JSON com a ordem de edição:
    cada segmento com seu arquivo de vídeo, arquivo de áudio e duração.
    """
    segmentos_edicao = []

    audio_map = {a["id"]: a for a in audios}
    video_map = {v["id"]: v for v in videos}

    for seg_id in sorted(audio_map.keys()):
        audio = audio_map.get(seg_id, {})
        video = video_map.get(seg_id, {})
        segmentos_edicao.append({
            "ordem": seg_id,
            "titulo": audio.get("titulo", video.get("titulo", f"Segmento {seg_id}")),
            "audio": audio.get("caminho_audio", ""),
            "video": video.get("caminho_video", ""),
            "duracao_segundos": audio.get("duracao_estimada", video.get("duracao_estimada", 60)),
        })

    manifesto = {
        "roteiro": roteiro_path,
        "total_segmentos": len(segmentos_edicao),
        "duracao_total_estimada": sum(s["duracao_segundos"] for s in segmentos_edicao),
        "segmentos": segmentos_edicao,
        "instrucoes_edicao": [
            "1. Importe todos os arquivos de vídeo e áudio no editor",
            "2. Para cada segmento: coloque o vídeo na track de vídeo e o áudio na track de áudio",
            "3. Ajuste o tempo do vídeo para corresponder à duração do áudio",
            "4. Se necessário, adicione transições entre segmentos (fade recomendado)",
            "5. Adicione intro e outro da Unitran no início e final",
            "6. Exporte em MP4 H.264, resolução 1920x1080, 30fps",
        ],
    }

    caminho = os.path.join(pasta_output, "manifesto_edicao.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(manifesto, f, indent=2, ensure_ascii=False)

    _exibir_manifesto(manifesto)
    console.print(f"\n[green]✓[/green] Manifesto salvo: [cyan]{caminho}[/cyan]")

    return caminho


def _exibir_manifesto(manifesto: dict) -> None:
    table = Table(title="Manifesto de Edição", show_lines=True)
    table.add_column("#", style="cyan", width=3)
    table.add_column("Segmento", style="bold")
    table.add_column("Áudio", style="green")
    table.add_column("Vídeo", style="blue")
    table.add_column("Duração", justify="right")

    for s in manifesto["segmentos"]:
        table.add_row(
            str(s["ordem"]),
            s["titulo"],
            os.path.basename(s["audio"]) if s["audio"] else "—",
            os.path.basename(s["video"]) if s["video"] else "—",
            f"{s['duracao_segundos']}s",
        )

    console.print(table)
    console.print(Panel(
        "\n".join(manifesto["instrucoes_edicao"]),
        title="Instruções de Edição",
        style="yellow",
    ))
