import azure.cognitiveservices.speech as speechsdk
from pydub import AudioSegment
import os

tmp_dir = "tmp"

# Função para converter texto em áudio .wav
def text_to_wav(text):
    subscription_key = os.getenv("azure_tts_api_key")
    region = os.getenv("azure_tts_region")

    # Configurar a autenticação e voz
    speech_config = speechsdk.SpeechConfig(subscription=subscription_key, region=region)
    speech_config.speech_synthesis_voice_name = "pt-BR-MacerioMultilingualNeural"

    # Caminho para salvar o arquivo WAV
    os.makedirs(tmp_dir, exist_ok=True)
    wav_audio_file_path = os.path.join(tmp_dir, "output_audio.wav")

    # Configurar a saída para o arquivo .wav
    audio_config = speechsdk.audio.AudioOutputConfig(filename=wav_audio_file_path)
    speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)

    # Gerar o áudio .wav
    result = speech_synthesizer.speak_text_async(text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return wav_audio_file_path
    else:
        return None

# Função para converter arquivo .wav em .mp3
def wav_to_mp3(wav_audio_path):
    os.makedirs(tmp_dir, exist_ok=True)
    mp3_audio_file_path = os.path.join(tmp_dir, "output_audio.mp3")

    # Carregar o arquivo .wav e exportar para .mp3
    audio = AudioSegment.from_wav(wav_audio_path)
    audio.export(mp3_audio_file_path, format="mp3", bitrate="192k")

    return mp3_audio_file_path
