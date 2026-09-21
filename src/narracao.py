"""Etapa 2: Geração da narração em áudio via ElevenLabs."""

import os
import time
from pathlib import Path
from elevenlabs import ElevenLabs
from rich.console import Console
from rich.table import Table

from .models import Roteiro, Segmento

console = Console()


def listar_vozes(client: ElevenLabs) -> list[dict]:
    """Lista vozes disponíveis no ElevenLabs."""
    resposta = client.voices.get_all()
    vozes = []
    for voz in resposta.voices:
        vozes.append({
            "id": voz.voice_id,
            "nome": voz.name,
            "categoria": getattr(voz, "category", "—"),
        })
    return vozes


def exibir_vozes(vozes: list[dict]) -> None:
    """Exibe tabela de vozes disponíveis."""
    table = Table(title="Vozes disponíveis no ElevenLabs")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Nome", style="bold")
    table.add_column("Categoria")
    for v in vozes:
        table.add_row(v["id"], v["nome"], v["categoria"])
    console.print(table)


def gerar_audio_segmento(
    client: ElevenLabs,
    segmento: Segmento,
    voice_id: str,
    pasta_output: str,
    prefixo: str,
) -> str:
    """Gera o áudio de um segmento e salva o arquivo. Retorna o caminho."""
    nome_arquivo = f"{prefixo}_seg{segmento.id:02d}_{segmento.titulo[:30].replace(' ', '_')}.mp3"
    caminho = os.path.join(pasta_output, nome_arquivo)

    audio = client.text_to_speech.convert(
        voice_id=voice_id,
        text=segmento.narracao,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )

    with open(caminho, "wb") as f:
        for chunk in audio:
            f.write(chunk)

    return caminho


def gerar_narracao_completa(
    roteiro: Roteiro,
    voice_id: str,
    pasta_output: str,
) -> list[dict]:
    """
    Gera o áudio de todos os segmentos do roteiro.
    Retorna lista de dicts com id, titulo, caminho_audio.
    """
    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])

    pasta_audio = os.path.join(pasta_output, "audio")
    Path(pasta_audio).mkdir(parents=True, exist_ok=True)

    prefixo = roteiro.assunto.lower().replace(" ", "_")[:30]
    resultados = []

    console.print(f"\n[bold cyan]Etapa 2 — Narração[/bold cyan] ({len(roteiro.segmentos)} segmentos)")

    for segmento in roteiro.segmentos:
        with console.status(f"Gerando áudio: segmento {segmento.id} — {segmento.titulo}"):
            caminho = gerar_audio_segmento(client, segmento, voice_id, pasta_audio, prefixo)
            time.sleep(0.5)  # respeitar rate limit

        console.print(f"[green]✓[/green] Segmento {segmento.id}: [cyan]{caminho}[/cyan]")
        resultados.append({
            "id": segmento.id,
            "titulo": segmento.titulo,
            "caminho_audio": caminho,
            "duracao_estimada": segmento.duracao_estimada_segundos,
        })

    return resultados
