import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """
    Configuration settings for the LiveKit Voice AI Agent worker.
    Loads from environment variables or .env file.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LiveKit Connection Settings
    LIVEKIT_URL: str = "http://localhost:7880"
    LIVEKIT_WS_URL: str = "ws://localhost:7880"
    LIVEKIT_API_KEY: str = "devkey"
    LIVEKIT_API_SECRET: str = "voiceai_secret_key_32_characters_minimum_len_ok"

    # PostgreSQL Database Connection
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/voice_ai"

    # AI Provider Keys
    OPENAI_API_KEY: Optional[str] = None
    DEEPGRAM_API_KEY: Optional[str] = None
    CARTESIA_API_KEY: Optional[str] = None
    ELEVENLABS_API_KEY: Optional[str] = None

    # Worker Settings
    WORKER_AGENT_NAME: str = "voice-agent-worker"
    DEFAULT_AGENT_NAME: str = "Acme Support Agent"
    DEFAULT_VOICE: str = "alloy"
    DEFAULT_MODEL: str = "gpt-4o-mini"

    # Turn Detection & Interruption (Barge-In)
    INTERRUPTION_ENABLED: bool = True
    INTERRUPTION_MIN_DURATION: float = 0.2
    MIN_ENDPOINTING_DELAY: float = 0.5
    MAX_ENDPOINTING_DELAY: float = 3.0

    # Test / Mock Flags
    USE_MOCK_PROVIDERS: bool = False

    @property
    def async_database_url(self) -> str:
        """
        Ensures the SQLAlchemy database URL uses the asyncpg driver.
        """
        url = self.DATABASE_URL
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url

    @property
    def livekit_connection_url(self) -> str:
        """
        Returns WebSocket URL preferred for WebRTC signaling.
        """
        if self.LIVEKIT_WS_URL:
            return self.LIVEKIT_WS_URL
        if self.LIVEKIT_URL.startswith("http://"):
            return self.LIVEKIT_URL.replace("http://", "ws://", 1)
        elif self.LIVEKIT_URL.startswith("https://"):
            return self.LIVEKIT_URL.replace("https://", "wss://", 1)
        return self.LIVEKIT_URL


settings = AgentSettings()
