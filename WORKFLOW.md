# Fluxo de Geração de Vídeo-Aulas — Unitran

## INPUT

```
assunto + estilo visual + duração
ex: "aula sobre CLT, quadro branco com maozinha escrevendo, 3 minutos"
```

## ETAPA 1 — Roteiro (Claude)

- Gerado por Claude e enviado para aprovação antes de qualquer geração
- Define quantos takes (cada take = 10 segundos de vídeo)
- Para cada take define:
  - Conteúdo visual (o que aparece na imagem final)
  - Prompt de geração de imagem (para Nano Banana 2, 16:9)
  - Prompt de geração de vídeo (animação do take)
  - Texto de narração (áudio daquele take)
- Define também a **imagem coringa** do estilo escolhido (primeiro frame fixo de todos os takes)
  - Exemplo quadro branco com mão: quadro em branco, sem elementos, sem mão

---

## ETAPA 2 — Imagens + Vídeos no Google Flow (Computer Use)

Acesso via: `https://flow.google.com/`

### Configuração
- Criar novo projeto nomeado com o nome do vídeo
  - ex: `Automação - Aula sobre Transporte`
- NÃO usar modo agente — gerar direto
- Modelo de imagem: **Nano Banana 2**, proporção **16:9**
- Modelo de vídeo: **Omni 1.1 Flash**, 720p, 10s, frames, 16:9, **1x geração**

### Por take
1. Gerar **4 imagens** com o prompt do take (Nano Banana 2, 16:9)
2. Selecionar a melhor das 4
3. Gerar **1 vídeo** com:
   - Primeiro frame: imagem coringa
   - Último frame: imagem selecionada do take
   - Prompt: conforme definido no roteiro (ex: animação da mão escrevendo)
4. Repetir para todos os takes

---

## ETAPA 3 — Narração no ElevenLabs (MCP)

- Um áudio por take, usando o texto do roteiro
- Duração esperada: ~12–16s (maior que os 10s do vídeo — normal)
- Ajuste feito na edição (etapa 4)

---

## ETAPA 4 — Edição com FFmpeg

Para cada take:
1. Remover o áudio original do vídeo gerado no Flow
2. Detectar a duração do áudio do ElevenLabs
3. **Estender o último frame** do vídeo até cobrir a duração do áudio (não desacelerar)
4. Sincronizar o áudio do ElevenLabs no vídeo estendido

Ao final: concatenar todos os takes em sequência → arquivo final

---

## ORGANIZAÇÃO DOS ARQUIVOS

Pasta local no computador (fora do repositório), nomeada com o título do vídeo:

```
~/unitran-aulas/nome-do-video/
├── roteiro.json
├── take_1.mp4
├── take_2.mp4
├── ...
├── imagem_final_take_1.png
├── imagem_final_take_2.png
├── ...
├── audio_take_1.mp3
├── audio_take_2.mp3
├── ...
└── video_final.mp4
```

---

## FERRAMENTAS

| Etapa | Ferramenta | Acesso |
|---|---|---|
| Roteiro | Claude | Direto |
| Imagens + Vídeos | Google Flow | Computer Use (desktop app) |
| Narração | ElevenLabs | MCP |
| Edição | FFmpeg | Terminal |
