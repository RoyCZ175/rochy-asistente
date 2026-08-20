import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    groq_api_key: str
    groq_model: str
    whisper_model: str
    assistant_name: str
    wake_word: str
    voice_language: str
    edge_tts_voice: str
    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str
    university_base_url: str
    google_credentials_path: str
    ollama_model: str

    @classmethod
    def load(cls) -> "Config":
        key = os.getenv("GROQ_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "Falta GROQ_API_KEY. Copia .env.example a .env y añade tu clave "
                "gratuita de https://console.groq.com/keys"
            )
        return cls(
            groq_api_key=key,
            groq_model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            whisper_model=os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo"),
            assistant_name=os.getenv("ASSISTANT_NAME", "Rochy"),
            wake_word=os.getenv("WAKE_WORD", "rochy").strip().lower(),
            voice_language=os.getenv("VOICE_LANGUAGE", "es-ES"),
            edge_tts_voice=os.getenv("EDGE_TTS_VOICE", "es-ES-AlvaroNeural"),
            spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID", "").strip(),
            spotify_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET", "").strip(),
            spotify_redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"),
            university_base_url=os.getenv("UNIVERSITY_BASE_URL", "").strip(),
            google_credentials_path=os.getenv("GOOGLE_CREDENTIALS_PATH", "google_credentials.json").strip(),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2").strip(),
        )
