"""Etapa 4: Edição com FFmpeg — sincroniza vídeos e áudios de cada take e concatena tudo."""

import os
import re
import shutil
import subprocess
from pathlib import Path
from rich.console import Console

console = Console()


def _ffmpeg() -> str:
    return os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg") or "ffmpeg"


def _run(cmd: list[str]) -> None:
    if cmd and cmd[0] == "ffmpeg":
        cmd[0] = _ffmpeg()
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error:\n{result.stderr}")


def get_duracao(arquivo: str) -> float:
    """Retorna a duração de um arquivo de áudio ou vídeo em segundos."""
    ffprobe = os.environ.get("FFPROBE_BINARY") or shutil.which("ffprobe")
    if ffprobe:
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", arquivo],
            capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())

    # Distribuições compactas podem trazer apenas ffmpeg. O cabeçalho de
    # inspeção ainda informa Duration com precisão centesimal.
    result = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-i", arquivo],
        capture_output=True, text=True
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        raise RuntimeError(f"Não foi possível obter a duração de {arquivo}")
    horas, minutos, segundos = match.groups()
    return int(horas) * 3600 + int(minutos) * 60 + float(segundos)


def processar_take(
    video_path: str,
    audio_path: str,
    output_path: str,
    pasta_temp: str,
) -> None:
    """
    Para um take:
    1. Estende o último frame com tpad se audio > video (nunca corta o áudio)
    2. Substitui o áudio original pelo áudio do ElevenLabs
    O áudio sempre é preservado inteiro; só os frames de vídeo são estendidos.
    """
    Path(pasta_temp).mkdir(parents=True, exist_ok=True)

    duracao_video = get_duracao(video_path)
    duracao_audio = get_duracao(audio_path)

    extra = max(0.0, duracao_audio - duracao_video)

    # tpad estende o último frame se necessário (extra=0 é no-op para o vídeo)
    _run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-filter_complex", f"[0:v]tpad=stop_mode=clone:stop_duration={extra:.3f}[v]",
        "-map", "[v]",
        "-map", "1:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24",
        "-c:a", "aac",
        output_path,
    ])


def concatenar_takes(takes_paths: list[str], output_path: str, pasta_temp: str) -> None:
    """Concatena todos os takes em um único vídeo final."""
    lista = os.path.join(pasta_temp, "takes_finais.txt")
    with open(lista, "w") as f:
        for path in takes_paths:
            f.write(f"file '{os.path.abspath(path)}'\n")

    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
          "-i", lista, "-c", "copy", output_path])


def editar_projeto(pasta_projeto: str) -> str:
    """
    Processa todos os takes de um projeto e gera o vídeo final.

    Espera encontrar na pasta:
      take_1.mp4, take_2.mp4, ...
      audio_take_1.mp3, audio_take_2.mp3, ...

    Gera: video_final.mp4
    """
    pasta_temp = os.path.join(pasta_projeto, "_temp")
    takes_finais = []

    # Descobre quantos takes existem
    i = 1
    while True:
        video = os.path.join(pasta_projeto, f"take_{i}.mp4")
        audio = os.path.join(pasta_projeto, f"audio_take_{i}.mp3")
        if not os.path.exists(video):
            break
        if not os.path.exists(audio):
            raise FileNotFoundError(f"Áudio não encontrado: {audio}")

        output_take = os.path.join(pasta_projeto, f"take_{i}_editado.mp4")

        with console.status(f"Processando take {i}..."):
            processar_take(video, audio, output_take, pasta_temp)

        console.print(f"[green]✓[/green] Take {i} editado: [cyan]{output_take}[/cyan]")
        takes_finais.append(output_take)
        i += 1

    if not takes_finais:
        raise FileNotFoundError("Nenhum take encontrado na pasta.")

    video_final = os.path.join(pasta_projeto, "video_final.mp4")
    with console.status("Concatenando todos os takes..."):
        concatenar_takes(takes_finais, video_final, pasta_temp)

    console.print(f"\n[bold green]✓ Vídeo final:[/bold green] [cyan]{video_final}[/cyan]")
    return video_final
