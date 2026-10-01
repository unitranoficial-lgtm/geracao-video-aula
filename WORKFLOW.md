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
  - Exemplo quadro negro com giz: quadro em branco, sem elementos, sem mão

### Regras para prompt de vídeo

- **Idioma visual obrigatório:** todo texto renderizado dentro de imagens e vídeos deve estar em português do Brasil, com acentuação correta. O prompt pode ser escrito em inglês, mas títulos, rótulos, placas, fórmulas explicadas e demais palavras visíveis devem ser PT-BR. Traduzir rótulos como `BUY`, `SELL`, `SHARES` e `INVESTORS` para `COMPRAR`, `VENDER`, `AÇÕES` e `INVESTIDORES`.
- **Fundo puro não é objeto:** quando o pedido for "fundo totalmente branco" (ou outra cor uniforme), a coringa deve ser somente a cor preenchendo todos os pixels, de ponta a ponta. Não gerar quadro branco, placa, folha, tela, canvas, slide, moldura, parede, sombra, textura, perspectiva ou cenário. Um quadro branco físico só deve aparecer quando o usuário pedir explicitamente quadro/lousa/whiteboard.

- **Mão só quando explicitamente pedido**: se o estilo for "quadro negro com giz" sem mencionar mão, os elementos devem se formar sozinhos — sem ninguém escrevendo. Exemplo correto: "os elementos aparecem progressivamente como se fossem desenhados por giz". Só coloque mão se o usuário descrever "com maozinha", "mão escrevendo", etc.
- **Stop motion quando houver mão**: se o estilo incluir uma mão animando, o prompt deve especificar movimento em stop motion (ex: "stop motion chalk hand animation, frame-by-frame hand movement"). Sem isso a mão fica com movimentos artificiais.
- **A mão nunca pertence ao frame final:** em estilos com mão/maozinha, a imagem final contém somente a ilustração e os textos já concluídos. `prompt_imagem` deve proibir explicitamente mão, dedos, braço, pessoa, marcador e caneta. A mão aparece exclusivamente no `prompt_video`, desenha os elementos e sai completamente da tela antes do último frame. Assim, o slot **Fim** sempre recebe uma arte limpa, sem a mão.
- O roteiro **não define a voz** — isso fica para a Etapa 3 (ElevenLabs).

---

## ETAPA 2 — Imagens + Vídeos no Google Flow (Computer Use)

Acesso via: `https://flow.google.com/`

### Configuração
- Criar novo projeto nomeado com o nome do vídeo
  - ex: `Automação - Aula sobre Transporte`
- NÃO usar modo agente — gerar direto
- Modelo de imagem: **Nano Banana 2**, proporção **16:9**
- Modelo de vídeo: **Omni 1.1 Flash**, 720p, 10s, frames, 16:9, **1x geração**

### Regra fundamental do vídeo — container idêntico entre Início e Fim

> ⚠️ **O primeiro frame (Início) e o último frame (Fim) de cada take devem ter o MESMO container visual** — mesma moldura do quadro, mesmo ângulo, mesma iluminação, mesmo fundo de sala. **A única diferença permitida é o conteúdo escrito/desenhado dentro do quadro.** Se o container mudar (enquadramento diferente, estilo diferente), o Flow vai animar a transição do próprio quadro em vez de animar apenas o conteúdo — o resultado fica distorcido.
>
> É por isso que a imagem coringa é usada como Início **e** como referência ao gerar a imagem do take: a coringa ancora o container visualmente. A imagem do take gerada com essa referência deve ter o mesmo quadro — com conteúdo adicionado, mas sem alterar o entorno.

### Por take — Imagens
1. Gerar **4 imagens** com o prompt do take (Nano Banana 2, 16:9)
   - Sempre usar a **imagem coringa como referência** ao gerar as imagens do take (arrastar para o campo de referência), para garantir que o container (moldura do quadro, fundo) seja idêntico ao Início
   - O prompt de imagem nunca deve alterar a moldura, o ângulo ou o ambiente — só o conteúdo dentro do quadro
2. Selecionar a melhor das 4 (preferir a primeira/mais simples quando equivalentes)

### Por take — Vídeos (fazer todos em sequência, sem esperar cada geração)
Para cada take, configurar e submeter o vídeo **sem esperar o anterior terminar** — o Flow faz fila automaticamente. Isso economiza ~2 minutos por take.

Para cada vídeo:
- **Primeiro frame (Início): sempre a imagem coringa** — arrastar o thumbnail da coringa direto para o slot Início, sem abrir o picker
- **Último frame (Fim)**: arrastar o thumbnail da imagem do take direto para o slot Fim, sem abrir o picker
- O par Início/Fim deve ter container idêntico (ver regra acima)
- Prompt: usar `form_input` no campo de texto (mais rápido que digitar caractere por caractere)
- Submeter e já configurar o próximo take sem aguardar

> ⚠️ **Erros comuns:**
> - Usar uma imagem de take como Início em vez da coringa → corte visual no início do vídeo
> - Gerar a imagem do take sem a coringa como referência → container diferente → animação distorcida

### Dicas de automação (Computer Use / Claude in Chrome)
- **Drag direto** para os slots Início/Fim — arrastar thumbnail do gallery para o slot evita o picker dialog (5+ passos → 1 ação)
- **Não tirar screenshot após cada clique** — só capturar quando há erro ou ambiguidade; usar `find`/`read_page` para verificar estado
- **`form_input`** em campos de texto para prompts longos — evita digitação caractere por caractere
- **Submeter em fila** — configurar take 1, 2 e 3 em sequência sem esperar conclusão; o Flow processa na fila enquanto você configura o próximo
- Usar **`ref`** de elementos ao clicar (não coordenadas) — mais estável e não depende de posição do elemento na tela

---

## ETAPA 3 — Narração no ElevenLabs (MCP)

- Ferramenta: **ElevenLabs via MCP** (`mcp__elevenlabs__*`) — não usar Kairogen nem outro TTS
- Voz definida no roteiro (campo `voz_elevenlabs`)
- Um áudio por take, usando o texto de narração do roteiro
- Salvar como `audio_take_N.mp3` na pasta do projeto
- Duração esperada: ~12–16s (maior que os 10s do vídeo — normal, ajuste feito na Etapa 4)

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
