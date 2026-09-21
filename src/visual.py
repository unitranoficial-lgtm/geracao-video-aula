"""Etapa 3: Geração dos vídeos visuais via Kairogen (Google Veo/Flow)."""

import os
import time
import requests
from pathlib import Path
from rich.console import Console

from .models import Roteiro, Segmento, EstiloVisual, ESTILO_DESCRICAO

console = Console()

KAIROGEN_BASE = "https://api.kairogen.com"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['KAIROGEN_API_KEY']}",
        "Content-Type": "application/json",
    }


def _prompt_com_estilo(segmento: Segmento, estilo: EstiloVisual) -> str:
    """Combina o prompt_visual do segmento com a instrução de estilo."""
    estilo_desc = ESTILO_DESCRICAO[estilo]
    return f"{segmento.prompt_visual}. Style: {estilo_desc}. No humans, no faces, educational content only. High quality, smooth animation."


def gerar_video_segmento(
    segmento: Segmento,
    estilo: EstiloVisual,
    pasta_output: str,
    prefixo: str,
    duracao: int = 10,
    modelo: str = "veo-3",
) -> str:
    """
    Gera o vídeo de um segmento via Kairogen.
    Retorna o caminho do arquivo baixado.
    """
    prompt = _prompt_com_estilo(segmento, estilo)

    payload = {
        "prompt": prompt,
        "model": modelo,
        "duration_seconds": min(duracao, 30),
        "aspect_ratio": "16:9",
    }

    resp = requests.post(
        f"{KAIROGEN_BASE}/v1/generate/video",
        json=payload,
        headers=_headers(),
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    job_id = data.get("job_id") or data.get("id")

    # Aguarda conclusão
    video_url = _aguardar_job(job_id)

    # Baixa o arquivo
    nome_arquivo = f"{prefixo}_seg{segmento.id:02d}_visual.mp4"
    caminho = os.path.join(pasta_output, nome_arquivo)
    _baixar_arquivo(video_url, caminho)

    return caminho


def _aguardar_job(job_id: str, timeout: int = 300) -> str:
    """Polling do status do job até concluir. Retorna a URL do vídeo."""
    inicio = time.time()
    while time.time() - inicio < timeout:
        resp = requests.get(
            f"{KAIROGEN_BASE}/v1/jobs/{job_id}",
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status", "").lower()

        if status in ("completed", "done", "succeeded"):
            return data.get("output_url") or data["result"]["url"]
        if status in ("failed", "error"):
            raise RuntimeError(f"Geração falhou: {data.get('error', 'erro desconhecido')}")

        time.sleep(10)

    raise TimeoutError(f"Job {job_id} não concluiu em {timeout}s")


def _baixar_arquivo(url: str, caminho: str) -> None:
    """Baixa um arquivo de uma URL para o caminho local."""
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(caminho, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)


def gerar_videos_completo(
    roteiro: Roteiro,
    pasta_output: str,
    modelo: str = "veo-3",
) -> list[dict]:
    """
    Gera o vídeo de todos os segmentos.
    Retorna lista de dicts com id, titulo, caminho_video.
    """
    pasta_video = os.path.join(pasta_output, "video")
    Path(pasta_video).mkdir(parents=True, exist_ok=True)

    prefixo = roteiro.assunto.lower().replace(" ", "_")[:30]
    resultados = []

    console.print(f"\n[bold cyan]Etapa 3 — Geração de Vídeos[/bold cyan] ({len(roteiro.segmentos)} segmentos, modelo: {modelo})")

    for segmento in roteiro.segmentos:
        console.print(f"  → Segmento {segmento.id}: {segmento.titulo}")
        with console.status(f"Gerando vídeo (pode levar 1-3 min)..."):
            caminho = gerar_video_segmento(
                segmento=segmento,
                estilo=roteiro.estilo,
                pasta_output=pasta_video,
                prefixo=prefixo,
                duracao=segmento.duracao_estimada_segundos,
                modelo=modelo,
            )

        console.print(f"[green]✓[/green] Segmento {segmento.id}: [cyan]{caminho}[/cyan]")
        resultados.append({
            "id": segmento.id,
            "titulo": segmento.titulo,
            "caminho_video": caminho,
            "duracao_estimada": segmento.duracao_estimada_segundos,
            "prompt_usado": _prompt_com_estilo(segmento, roteiro.estilo),
        })

    return resultados
