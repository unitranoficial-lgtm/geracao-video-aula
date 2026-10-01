# Fluxo vertical 9:16

Este fluxo é a entrada separada para vídeos verticais, mantendo o fluxo principal em 16:9.

## Execução

Para gerar um roteiro planejado desde o início para tela vertical:

```powershell
python .\main_9x16.py "aula sobre o assunto, animação 2D, 1 minuto, voz: Davi Andrei"
```

## Vozes padrão

- Principal: Davi Andrei (`2CECaLAGTS5NRGxgbcxr`). Usar por padrão em todos os vídeos.
- Secundária: Elvis (`zNEsdgTUa3ndwKry8Xcq`). Usar somente quando solicitado explicitamente.
- A configuração persistente e consumida por `gerar_audios.py` fica em `voice_config.json`.

## Pronúncia de siglas

Antes de enviar a narração ao ElevenLabs, `gerar_audios.py` aplica as regras de
`pronunciation_config.json`. O roteiro original não é alterado. Siglas faladas
como palavra usam escrita fonética (`CIOT` → `cioti`). Siglas soletradas são
enviadas normalmente, em caixa alta, sem adaptação (`ANTT`, `RNTRC`, `IBS`,
`CBS`, `TRC`, `CT-e`, `MDF-e`, `NF-e`). Uma nova regra só deve ser adicionada
quando a sigla for pronunciada popularmente como uma palavra.

Depois, para executar a automação vertical no Flow:

```powershell
python .\flow_automation_9x16.py --roteiro .\output\meu_projeto\roteiro.json --auto
```

Se a sessão do perfil dedicado tiver expirado, feche todas as janelas do
Chrome e reutilize diretamente o perfil autenticado:

```powershell
python .\flow_automation_9x16.py --roteiro .\output\meu_projeto\roteiro.json --auto --usar-chrome-logado
```

O script valida o login antes de criar projetos ou consumir créditos.

As demais opções são iguais às de `flow_automation.py`, incluindo `--project-id`,
`--so-download`, `--download-take`, `--apenas-videos` e `--refazer-videos`.

## Garantias do modo vertical

- Imagens do Nano Banana configuradas em 9:16.
- Vídeos por frames configurados em 9:16.
- Menções de 16:9 ou 9:16 nos prompts são normalizadas automaticamente para 9:16.
- Fundo uniforme, coringa genérica, textos obrigatoriamente em português e downloads
  validados usam as mesmas regras do fluxo principal.
- Nos estilos com mão escrevendo, a imagem final de cada take mostra apenas o conteúdo concluído,
  sem mão, dedos, braço, pessoa ou marcador. A mão existe somente na animação e sai totalmente
  de cena antes do último frame.
- A edição com FFmpeg preserva a resolução vertical recebida do Flow.

O script original continua sendo usado para horizontal:

```powershell
python .\flow_automation.py --roteiro .\output\meu_projeto\roteiro.json --auto
```
