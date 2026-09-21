"""Etapa 4: Edição com FFmpeg — sincroniza vídeos e áudios de cada take e concatena tudo."""

import os
import subprocess
from pathlib import Path
from rich.console import Console

console = Console()


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error:\n{result.stderr}")


def get_duracao(arquivo: str) -> float:
    """Retorna a duração de um arquivo de áudio ou vídeo em segundos."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", arquivo],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())


def processar_take(
    video_path: str,
    audio_path: str,
    output_path: str,
    pasta_temp: str,
) -> None:
    """
    Para um take:
    1. Remove o áudio original do vídeo
    2. Estende o último frame até cobrir a duração do áudio
    3. Sincroniza o áudio do ElevenLabs
    """
    Path(pasta_temp).mkdir(parents=True, exist_ok=True)

    duracao_video = get_duracao(video_path)
    duracao_audio = get_duracao(audio_path)

    nome_base = Path(video_path).stem
    video_sem_audio = os.path.join(pasta_temp, f"{nome_base}_mudo.mp4")
    ultimo_frame = os.path.join(pasta_temp, f"{nome_base}_last_frame.png")
    extensao = os.path.join(pasta_temp, f"{nome_base}_extensao.mp4")
    video_estendido = os.path.join(pasta_temp, f"{nome_base}_estendido.mp4")
    lista_concat = os.path.join(pasta_temp, f"{nome_base}_concat.txt")

    # Remove áudio original
    _run(["ffmpeg", "-y", "-i", video_path, "-an", "-c:v", "copy", video_sem_audio])

    if duracao_audio > duracao_video:
        extensao_segundos = duracao_audio - duracao_video

        # Extrai último frame
        _run(["ffmpeg", "-y", "-sseof", "-0.5", "-i", video_sem_audio,
              "-frames:v", "1", "-q:v", "2", ultimo_frame])

        # Cria vídeo estático do último frame com a duração da extensão
        _run(["ffmpeg", "-y", "-loop", "1", "-i", ultimo_frame,
              "-t", str(extensao_segundos),
              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24", extensao])

        # Concatena vídeo original + extensão
        with open(lista_concat, "w") as f:
            f.write(f"file '{os.path.abspath(video_sem_audio)}'\n")
            f.write(f"file '{os.path.abspath(extensao)}'\n")

        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
              "-i", lista_concat, "-c:v", "libx264", "-pix_fmt", "yuv420p", video_estendido])

        video_para_usar = video_estendido
    else:
        video_para_usar = video_sem_audio

    # Sincroniza áudio do ElevenLabs
    _run(["ffmpeg", "-y", "-i", video_para_usar, "-i", audio_path,
          "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
          "-shortest", output_path])


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
