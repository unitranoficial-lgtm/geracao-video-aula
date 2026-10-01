#!/usr/bin/env python3
"""Gera um MP3 por take de um roteiro usando ElevenLabs."""

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from elevenlabs import ElevenLabs, VoiceSettings
from src.pronuncia import normalizar_pronuncia


VOICE_CONFIG_PATH = Path(__file__).with_name("voice_config.json")


def default_voice_id() -> str:
    """Retorna a voz principal persistida para o fluxo de vídeos."""
    config = json.loads(VOICE_CONFIG_PATH.read_text(encoding="utf-8"))
    return config["primary"]["voice_id"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("roteiro", type=Path)
    parser.add_argument(
        "--voice-id",
        default=default_voice_id(),
        help="ID da voz ElevenLabs (padrão: voz principal de voice_config.json)",
    )
    args = parser.parse_args()

    load_dotenv(Path(__file__).with_name(".env"))
    roteiro = json.loads(args.roteiro.read_text(encoding="utf-8"))
    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    output = args.roteiro.parent

    for index, take in enumerate(roteiro["takes"]):
        number = int(take["numero"])
        destination = output / f"audio_take_{number}.mp3"
        texto_original = take["narracao"]
        texto_falado = normalizar_pronuncia(texto_original)
        previous_text = normalizar_pronuncia(
            roteiro["takes"][index - 1]["narracao"] if index else None
        )
        next_text = normalizar_pronuncia(
            roteiro["takes"][index + 1]["narracao"]
            if index + 1 < len(roteiro["takes"])
            else None
        )
        if texto_falado != texto_original:
            print(f"take {number}: pronúncia adaptada → {texto_falado}")
        stream = client.text_to_speech.convert(
            voice_id=args.voice_id,
            text=texto_falado,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
            previous_text=previous_text,
            next_text=next_text,
            voice_settings=VoiceSettings(
                stability=0.55,
                similarity_boost=0.8,
                style=0.25,
                speed=1.0,
                use_speaker_boost=True,
            ),
        )
        with destination.open("wb") as audio_file:
            for chunk in stream:
                audio_file.write(chunk)
        print(f"take {number}: {destination.name} ({destination.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
