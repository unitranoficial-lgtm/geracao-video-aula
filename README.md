# Gerador de Vídeo-Aulas — Unitran

Fluxo automatizado para criação de vídeo-aulas a partir de um assunto.

## Fluxo

```
INPUT: Assunto da aula
    │
    ▼
[Etapa 1] Roteiro (Claude)
  Gera narração por segmento + prompts visuais
    │
    ├─────────────────────────────┐
    ▼                             ▼
[Etapa 2] Narração          [Etapa 3] Vídeos visuais
  ElevenLabs → .mp3            Kairogen/Veo → .mp4
    │                             │
    └──────────────┬──────────────┘
                   ▼
        [Etapa 4] Manifesto de edição
          JSON com ordem de sincronização
                   │
                   ▼
        OUTPUT: Pasta com audios/ + video/ + manifesto
```

## Instalação

```bash
pip install -r requirements.txt
cp .env.example .env
# Preencha as chaves no .env
```

## Uso

```bash
# Gerar fluxo completo
python main.py "Direito Trabalhista - Rescisão de Contrato"

# Escolher estilo visual
python main.py "Cálculo - Derivadas" --estilo quadro_negro

# Só o roteiro (sem gastar créditos de API)
python main.py "Marketing Digital" --so-roteiro

# Ver vozes disponíveis no ElevenLabs
python main.py --listar-vozes

# Usar roteiro já gerado (pula etapa 1)
python main.py --roteiro-json output/meu_roteiro.json
```

## Estilos Visuais

| Opção | Descrição |
|-------|-----------|
| `quadro_branco` | Animação em quadro branco limpo |
| `quadro_branco_mao` | Quadro branco com mão desenhando |
| `quadro_negro` | Quadro negro com giz |
| `animacao_2d` | Animação 2D flat moderna |

## Saída

```
output/
├── assunto_roteiro.json         # Roteiro estruturado
├── manifesto_edicao.json        # Guia de sincronização
├── audio/
│   ├── seg01_introducao.mp3
│   ├── seg02_conceito.mp3
│   └── ...
└── video/
    ├── seg01_introducao_visual.mp4
    ├── seg02_conceito_visual.mp4
    └── ...
```

Após a geração, importe os arquivos no seu editor de vídeo (DaVinci Resolve, Premiere, CapCut)
e siga as instruções do `manifesto_edicao.json`.
