from pydantic import BaseModel, Field
from enum import Enum


class EstiloVisual(str, Enum):
    QUADRO_BRANCO_MAO = "quadro_branco_mao"
    QUADRO_BRANCO = "quadro_branco"
    QUADRO_NEGRO = "quadro_negro"
    ANIMACAO_2D = "animacao_2d"


class Take(BaseModel):
    numero: int
    conteudo_visual: str = Field(description="O que deve aparecer na imagem final deste take")
    prompt_imagem: str = Field(description="Prompt em inglês para gerar a imagem no Nano Banana 2 (16:9)")
    prompt_video: str = Field(description="Prompt em inglês para animar o take no Omni 1.1 Flash")
    narracao: str = Field(description="Texto da narração para este take no ElevenLabs")


class Roteiro(BaseModel):
    titulo: str
    assunto: str
    estilo: EstiloVisual
    voz_elevenlabs: str
    duracao_estimada_minutos: float
    num_takes: int
    descricao_imagem_coringa: str = Field(description="Descrição da imagem coringa do estilo (primeiro frame de todos os takes)")
    prompt_imagem_coringa: str = Field(description="Prompt em inglês para gerar a imagem coringa no Nano Banana 2")
    takes: list[Take]
