"""Etapa 1: Geração do roteiro estruturado a partir do assunto da aula."""

import json
import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.progress import track

from .models import Roteiro, EstiloVisual, ESTILO_DESCRICAO

console = Console()

SYSTEM_PROMPT = """Você é um especialista em educação a distância e criação de conteúdo didático para o ensino superior.
Sua função é criar roteiros detalhados para vídeo-aulas da Unitran (União das Faculdades do Norte Paulista).

As aulas devem ser:
- Claras e objetivas, adequadas ao nível superior
- Divididas em segmentos de 30 a 90 segundos cada
- Com linguagem formal mas acessível
- Focadas no aprendizado prático e teórico

Para cada segmento, gere também um prompt visual detalhado em inglês para geração de vídeo por IA,
descrevendo exatamente o que deve aparecer na tela (textos, diagramas, símbolos, cores).
O prompt visual deve ser específico o suficiente para que um modelo de IA de vídeo entenda o conteúdo."""


def gerar_roteiro(assunto: str, estilo: EstiloVisual, num_segmentos: int = 6) -> Roteiro:
    """Gera um roteiro completo para a vídeo-aula usando Claude."""
    client = anthropic.Anthropic()

    estilo_desc = ESTILO_DESCRICAO[estilo]

    console.print(Panel(
        f"[bold cyan]Gerando roteiro para:[/bold cyan] {assunto}\n"
        f"[bold cyan]Estilo visual:[/bold cyan] {estilo.value}",
        title="Etapa 1 — Roteiro"
    ))

    user_prompt = f"""Crie um roteiro completo para uma vídeo-aula sobre: **{assunto}**

Requisitos:
- Aproximadamente {num_segmentos} segmentos
- Cada segmento deve ter entre 30 e 90 segundos de narração
- Tom: professoral, claro, ensino superior
- Estilo visual para geração de vídeo: {estilo_desc}

Responda APENAS com um JSON válido seguindo exatamente este schema:

{{
  "assunto": "{assunto}",
  "titulo_aula": "<título da aula>",
  "estilo": "{estilo.value}",
  "duracao_total_estimada_segundos": <número>,
  "objetivos_aprendizagem": ["objetivo 1", "objetivo 2", "objetivo 3"],
  "segmentos": [
    {{
      "id": 1,
      "titulo": "<título do segmento>",
      "narracao": "<texto completo que será narrado em voz alta, sem marcações>",
      "duracao_estimada_segundos": <número entre 30 e 90>,
      "prompt_visual": "<prompt em inglês para gerar o vídeo, descrevendo o visual com estilo: {estilo_desc}>",
      "elementos_visuais": ["elemento 1", "elemento 2"]
    }}
  ]
}}

Importante no prompt_visual: descreva o conteúdo específico (textos, fórmulas, diagramas) que deve aparecer.
Por exemplo: 'Whiteboard animation showing the text "Art. 484 CLT" appearing, with a hand drawing an arrow to a bullet list of 3 items...'"""

    with console.status("[bold green]Claude está gerando o roteiro..."):
        message = client.messages.create(
            model="claude-opus-5",
            max_tokens=8096,
            messages=[
                {"role": "user", "content": user_prompt}
            ],
            system=SYSTEM_PROMPT,
        )

    raw = message.content[0].text.strip()

    # Remove markdown code block se presente
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    data = json.loads(raw)
    roteiro = Roteiro(**data)

    console.print(f"[green]✓[/green] Roteiro gerado: {len(roteiro.segmentos)} segmentos, ~{roteiro.duracao_total_estimada_segundos}s")

    return roteiro


def salvar_roteiro(roteiro: Roteiro, pasta_output: str) -> str:
    """Salva o roteiro como JSON e retorna o caminho."""
    import os
    nome_arquivo = roteiro.assunto.lower().replace(" ", "_").replace("/", "-")[:50]
    caminho = os.path.join(pasta_output, f"{nome_arquivo}_roteiro.json")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(roteiro.model_dump_json(indent=2, ensure_ascii=False))
    console.print(f"[green]✓[/green] Roteiro salvo em: [cyan]{caminho}[/cyan]")
    return caminho
