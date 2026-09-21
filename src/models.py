from pydantic import BaseModel, Field
from typing import Literal
from enum import Enum


class EstiloVisual(str, Enum):
    QUADRO_BRANCO = "quadro_branco"
    QUADRO_BRANCO_MAO = "quadro_branco_mao"
    QUADRO_NEGRO = "quadro_negro"
    ANIMACAO_2D = "animacao_2d"


ESTILO_DESCRICAO = {
    EstiloVisual.QUADRO_BRANCO: "Whiteboard clean animation, text and diagrams appearing on white background, professional educational style",
    EstiloVisual.QUADRO_BRANCO_MAO: "Whiteboard with hand drawing and writing motion, stop-motion style, hand holding marker writing content",
    EstiloVisual.QUADRO_NEGRO: "Blackboard with chalk writing, dust particles, warm classroom atmosphere, chalk handwriting style",
    EstiloVisual.ANIMACAO_2D: "Clean 2D flat animation, colorful icons and text, modern explainer video style",
}


class Segmento(BaseModel):
    id: int
    titulo: str
    narracao: str = Field(description="Texto completo da narração deste segmento")
    duracao_estimada_segundos: int = Field(description="Duração estimada em segundos")
    prompt_visual: str = Field(description="Prompt descritivo para gerar o vídeo deste segmento")
    elementos_visuais: list[str] = Field(description="Lista de elementos que devem aparecer visualmente")


class Roteiro(BaseModel):
    assunto: str
    titulo_aula: str
    estilo: EstiloVisual
    duracao_total_estimada_segundos: int
    objetivos_aprendizagem: list[str]
    segmentos: list[Segmento]
