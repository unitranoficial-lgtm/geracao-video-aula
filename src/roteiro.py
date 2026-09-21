"""Etapa 1: Geração e exibição do roteiro para aprovação."""

import re
import json
import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .models import Roteiro, EstiloVisual

console = Console()

SYSTEM_PROMPT = """Você é especialista em criação de vídeo-aulas para ensino superior.
Cria roteiros para vídeos educacionais gerados por IA, sem presença humana.

Cada take tem exatamente 10 segundos de vídeo. O áudio de narração ficará entre 12-16 segundos
(o vídeo será estendido na edição para cobrir o áudio — isso é esperado).

Para os prompts de imagem (Nano Banana 2, 16:9): descreva o conteúdo específico que deve aparecer
na imagem final do take — textos, diagramas, fórmulas, listas, títulos — de forma visual e clara.

Para os prompts de vídeo (Omni 1.1 Flash): descreva como animar a imagem coringa → imagem final,
conforme o estilo escolhido. O vídeo vai do primeiro frame (imagem coringa) ao último (imagem do take).

A imagem coringa é o ponto de partida de todos os takes — para quadro branco com mão: quadro limpo,
sem elementos, sem mão. A animação traz a mão escrevendo até chegar na imagem final do take."""

ESTILO_INSTRUCOES = {
    EstiloVisual.QUADRO_BRANCO_MAO: (
        "quadro branco com mão animada escrevendo",
        "Coringa: clean white whiteboard, empty, no hand, no text, no elements, pure white surface, educational setting.",
        "animate with a hand holding a marker in motion, drawing and writing the content onto the whiteboard, "
        "smooth motion animation, the whiteboard background stays fixed, only the hand moves writing the content"
    ),
    EstiloVisual.QUADRO_BRANCO: (
        "quadro branco com elementos aparecendo",
        "Clean white whiteboard, empty, no text, no elements, pure white background.",
        "animate the content appearing smoothly on the whiteboard, text and elements fade or draw in progressively"
    ),
    EstiloVisual.QUADRO_NEGRO: (
        "quadro negro com escrita a giz",
        "Black chalkboard, empty, clean surface, no chalk marks, no text, dark educational background.",
        "animate a chalk hand writing the content on the blackboard, white chalk dust particles, "
        "smooth chalk writing motion, blackboard stays fixed"
    ),
    EstiloVisual.ANIMACAO_2D: (
        "animação 2D flat moderna",
        "Clean white background, empty canvas, no elements, flat design style.",
        "animate flat 2D icons and text appearing with smooth transitions, modern explainer video style, "
        "elements slide and fade in progressively"
    ),
}


def _parse_input(texto: str) -> dict:
    """Extrai assunto, estilo, duração e voz do texto de input livre."""
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-opus-5",
        max_tokens=512,
        messages=[{"role": "user", "content": f"""Extraia do texto abaixo: assunto, estilo visual, duração em minutos e voz ElevenLabs.
Responda APENAS com JSON:
{{"assunto": "...", "estilo_raw": "...", "duracao_minutos": 3.0, "voz": "..."}}

Mapeie o estilo para um destes valores exatos:
- "quadro_branco_mao" (quadro branco com mão/maozinha escrevendo)
- "quadro_branco" (quadro branco sem mão)
- "quadro_negro" (quadro negro com giz)
- "animacao_2d" (animação 2D flat)

Texto: {texto}"""}]
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def gerar_roteiro(input_texto: str) -> Roteiro:
    """Gera o roteiro completo a partir do input livre do usuário."""
    client = anthropic.Anthropic()

    parsed = _parse_input(input_texto)
    assunto = parsed["assunto"]
    estilo = EstiloVisual(parsed["estilo_raw"])
    duracao_min = float(parsed["duracao_minutos"])
    voz = parsed.get("voz", "")

    # Calcula número de takes (média de 13s de áudio por take)
    duracao_seg = duracao_min * 60
    num_takes = max(3, round(duracao_seg / 13))

    estilo_nome, prompt_coringa, instrucao_animacao = ESTILO_INSTRUCOES[estilo]

    console.print(Panel(
        f"[bold cyan]Assunto:[/bold cyan] {assunto}\n"
        f"[bold cyan]Estilo:[/bold cyan] {estilo_nome}\n"
        f"[bold cyan]Duração:[/bold cyan] {duracao_min} min → {num_takes} takes\n"
        f"[bold cyan]Voz:[/bold cyan] {voz}",
        title="Gerando Roteiro"
    ))

    user_prompt = f"""Crie um roteiro para vídeo-aula sobre: **{assunto}**

Especificações:
- {num_takes} takes de 10 segundos cada
- Estilo visual: {estilo_nome}
- Voz ElevenLabs: {voz}
- Instrução de animação dos vídeos: {instrucao_animacao}

Responda APENAS com JSON válido:

{{
  "titulo": "<título da aula>",
  "assunto": "{assunto}",
  "estilo": "{estilo.value}",
  "voz_elevenlabs": "{voz}",
  "duracao_estimada_minutos": {duracao_min},
  "num_takes": {num_takes},
  "descricao_imagem_coringa": "<descrição em português do que é a imagem coringa>",
  "prompt_imagem_coringa": "{prompt_coringa}",
  "takes": [
    {{
      "numero": 1,
      "conteudo_visual": "<descrição em português do que aparece na imagem final>",
      "prompt_imagem": "<prompt em inglês para Nano Banana 2, descreve o conteúdo visual específico, estilo: {estilo_nome}, 16:9, educational>",
      "prompt_video": "<prompt em inglês para Omni 1.1 Flash: {instrucao_animacao}, [descreve o conteúdo do take]>",
      "narracao": "<texto da narração em português, entre 12-16 segundos de fala>"
    }}
  ]
}}"""

    with console.status("[bold green]Claude está gerando o roteiro..."):
        msg = client.messages.create(
            model="claude-opus-5",
            max_tokens=8096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}]
        )

    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    roteiro = Roteiro(**json.loads(raw.strip()))
    return roteiro


def exibir_roteiro(roteiro: Roteiro) -> None:
    """Exibe o roteiro completo para aprovação."""
    console.print(f"\n[bold white on blue] {roteiro.titulo} [/bold white on blue]")
    console.print(f"[dim]Estilo: {roteiro.estilo.value} | Voz: {roteiro.voz_elevenlabs} | "
                  f"{roteiro.num_takes} takes | ~{roteiro.duracao_estimada_minutos} min[/dim]\n")

    console.print(Panel(
        f"[bold]Imagem Coringa ({roteiro.estilo.value}):[/bold]\n"
        f"{roteiro.descricao_imagem_coringa}\n\n"
        f"[dim]Prompt:[/dim] {roteiro.prompt_imagem_coringa}",
        title="Frame Inicial de Todos os Takes",
        style="yellow"
    ))

    table = Table(show_lines=True, expand=True)
    table.add_column("Take", width=5, justify="center")
    table.add_column("Conteúdo Visual", width=25)
    table.add_column("Narração", width=35)
    table.add_column("Prompt Imagem", width=35)
    table.add_column("Prompt Vídeo", width=35)

    for t in roteiro.takes:
        table.add_row(
            str(t.numero),
            t.conteudo_visual,
            t.narracao[:120] + ("..." if len(t.narracao) > 120 else ""),
            t.prompt_imagem[:100] + "...",
            t.prompt_video[:100] + "...",
        )

    console.print(table)


def salvar_roteiro(roteiro: Roteiro, pasta: str) -> str:
    """Salva o roteiro como JSON na pasta do projeto."""
    import os
    from pathlib import Path
    Path(pasta).mkdir(parents=True, exist_ok=True)
    caminho = os.path.join(pasta, "roteiro.json")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(roteiro.model_dump_json(indent=2, ensure_ascii=False))
    return caminho
