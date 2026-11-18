from pathlib import Path

from .config import VOICE_MODEL_DIR


class VoiceError(RuntimeError):
    """Raised when local speech input or output is unavailable."""


def listen_once(
    model_path: Path = VOICE_MODEL_DIR,
    duration_seconds: int = 7,
) -> str:
    if not 1 <= duration_seconds <= 30:
        raise ValueError("A duração de gravação deve estar entre 1 e 30 segundos.")
    if not model_path.is_dir():
        raise VoiceError(
            f"Modelo de voz não encontrado em '{model_path}'. "
            "Consulte o README para instalar o modelo Vosk em português."
        )
    try:
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model
    except ImportError as error:
        raise VoiceError(
            "Voz opcional ausente. Instale com "
            "'.venv\\Scripts\\python.exe -m pip install -r requirements-voice.txt'."
        ) from error

    try:
        model = Model(str(model_path))
        sample_rate = 16000
        audio = sd.rec(
            int(duration_seconds * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
        )
        sd.wait()
        recognizer = KaldiRecognizer(model, sample_rate)
        recognizer.AcceptWaveform(audio.tobytes())
        import json

        text = json.loads(recognizer.FinalResult()).get("text", "").strip()
    except Exception as error:
        raise VoiceError(f"Falha ao capturar ou reconhecer áudio: {error}") from error
    if not text:
        raise VoiceError("Nenhuma fala inteligível foi reconhecida.")
    return text


def speak(text: str) -> None:
    try:
        import pyttsx3
    except ImportError as error:
        raise VoiceError(
            "Síntese de voz opcional ausente. Instale com "
            "'.venv\\Scripts\\python.exe -m pip install -r requirements-voice.txt'."
        ) from error
    try:
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
    except Exception as error:
        raise VoiceError(f"Falha na síntese de voz local: {error}") from error
