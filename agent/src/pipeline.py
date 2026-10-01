import logging
import os
from dataclasses import dataclass
from typing import Optional

from livekit.agents import llm, stt, tts, vad
from livekit.plugins import silero
try:
    from livekit.plugins import openai
except Exception:
    openai = None
try:
    from livekit.plugins import deepgram
except Exception:
    deepgram = None

from agent.src.config import settings
from agent.src.db import AgentConfig

logger = logging.getLogger("agent.pipeline")


class PipelineError(Exception):
    """Base exception for pipeline failures."""
    pass


class ProviderConfigurationError(PipelineError):
    """Raised when required provider credentials or configurations are missing."""
    pass


class STTFailureError(PipelineError):
    """Raised when speech-to-text processing fails."""
    pass


class LLMFailureError(PipelineError):
    """Raised when language model generation fails."""
    pass


class TTSFailureError(PipelineError):
    """Raised when text-to-speech audio synthesis fails."""
    pass


@dataclass
class VoicePipeline:
    """
    Holds the instantiated pipeline components:
    Customer Audio -> VAD -> Turn Detection -> STT -> LLM -> TTS -> LiveKit Audio -> Customer
    """
    vad: vad.VAD
    stt: stt.STT
    llm: llm.LLM
    tts: tts.TTS
    provider_name: str


def create_pipeline(
    agent_config: AgentConfig,
    vad_instance: Optional[vad.VAD] = None,
) -> VoicePipeline:
    """
    Factory creating the voice AI processing pipeline based on database agent config
    and environment credentials.

    Pipeline:
    Customer Audio -> Silero VAD -> Turn Detection -> STT -> LLM -> TTS -> LiveKit Audio
    """
    # 1. Voice Activity Detection (Silero VAD)
    if vad_instance is None:
        try:
            vad_instance = silero.VAD.load()
            logger.info("Initialized Silero VAD successfully.")
        except Exception as e:
            logger.error("Failed to load Silero VAD: %s", e)
            raise PipelineError(f"Silero VAD initialization failed: {e}") from e

    # 2. Check for mock provider mode (for offline tests)
    if settings.USE_MOCK_PROVIDERS:
        logger.info("Creating mock voice pipeline for automated testing.")
        from livekit.agents.tts import StreamAdapter
        from agent.src.mock_providers import MockLLM, MockSTT, MockTTS
        return VoicePipeline(
            vad=vad_instance,
            stt=MockSTT(),
            llm=MockLLM(model=agent_config.model),
            tts=StreamAdapter(tts=MockTTS(voice=agent_config.voice)),
            provider_name="mock",
        )

    # 3. Check provider credentials
    openai_key = settings.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY")
    deepgram_key = settings.DEEPGRAM_API_KEY or os.environ.get("DEEPGRAM_API_KEY")

    if not openai_key and not deepgram_key:
        error_msg = (
            "No AI provider API key found. OPENAI_API_KEY (or DEEPGRAM_API_KEY) "
            "must be configured in environment variables or .env file."
        )
        logger.error(error_msg)
        raise ProviderConfigurationError(error_msg)

    # 4. Initialize STT, LLM, TTS using OpenAI or Deepgram
    try:
        # LLM
        model_name = agent_config.model or settings.DEFAULT_MODEL
        llm_instance = openai.LLM(
            model=model_name,
            api_key=openai_key,
        )

        # STT (Deepgram if available and configured, otherwise OpenAI Whisper)
        if deepgram_key and deepgram is not None:
            stt_instance = deepgram.STT(
                model="nova-3",
                api_key=deepgram_key,
            )
            provider_name = "deepgram+openai"
        else:
            # OpenAI Whisper STT
            stt_instance = openai.STT(
                model="whisper-1",
                api_key=openai_key,
            )
            provider_name = "openai"

        # TTS (OpenAI TTS with voice from database agent config)
        voice_name = agent_config.voice or settings.DEFAULT_VOICE
        tts_instance = openai.TTS(
            voice=voice_name,
            api_key=openai_key,
        )

        # If TTS is not natively streaming (such as OpenAI TTS), adapt it
        if not tts_instance.capabilities.streaming:
            from livekit.agents.tts import StreamAdapter
            tts_instance = StreamAdapter(tts=tts_instance)

        logger.info(
            "Created %s pipeline for agent '%s' (model=%s, voice=%s)",
            provider_name, agent_config.name, model_name, voice_name,
        )

        return VoicePipeline(
            vad=vad_instance,
            stt=stt_instance,
            llm=llm_instance,
            tts=tts_instance,
            provider_name=provider_name,
        )

    except Exception as e:
        logger.error("Failed to construct voice pipeline components: %s", e)
        raise ProviderConfigurationError(f"Failed to configure pipeline components: {e}") from e
