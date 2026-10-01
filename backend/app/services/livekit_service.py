import json
import logging
import uuid
from typing import Optional
from livekit.api import (
    AccessToken,
    CreateRoomRequest,
    LiveKitAPI,
    VideoGrants,
)
from backend.app.core.config import settings

logger = logging.getLogger("livekit_service")


class LiveKitService:
    def __init__(
        self,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ):
        self.url = url or settings.LIVEKIT_URL
        self.ws_url = settings.LIVEKIT_WS_URL
        self.api_key = api_key or settings.LIVEKIT_API_KEY
        self.api_secret = api_secret or settings.LIVEKIT_API_SECRET

    def get_api_client(self) -> LiveKitAPI:
        return LiveKitAPI(
            url=self.url,
            api_key=self.api_key,
            api_secret=self.api_secret,
        )

    async def create_room(self, room_name: str, agent_id: uuid.UUID, empty_timeout: int = 300) -> None:
        """
        Creates a room on the self-hosted LiveKit SFU and attaches agent metadata
        so that an agent worker can discover and load the proper agent configuration upon joining.
        """
        api = self.get_api_client()
        try:
            metadata = json.dumps({"agent_id": str(agent_id)})
            request = CreateRoomRequest(
                name=room_name,
                empty_timeout=empty_timeout,
                metadata=metadata,
            )
            await api.room.create_room(request)
            logger.info("Created LiveKit room %s with agent_id %s", room_name, agent_id)

            # Explicitly dispatch voice agent worker to this room
            try:
                from livekit.protocol.agent_dispatch import CreateAgentDispatchRequest
                dispatch_req = CreateAgentDispatchRequest(
                    agent_name=getattr(settings, "WORKER_AGENT_NAME", "voice-agent-worker"),
                    room=room_name,
                    metadata=metadata,
                )
                await api.agent_dispatch.create_dispatch(dispatch_req)
                logger.info("Dispatched voice-agent-worker to room %s", room_name)
            except Exception as de:
                logger.debug("Agent dispatch note for room %s: %s", room_name, de)
        except Exception as e:
            logger.error("Failed to create room %s on LiveKit: %s", room_name, e)
            raise
        finally:
            await api.aclose()

    def generate_customer_token(
        self,
        room_name: str,
        identity: str,
        name: Optional[str] = None,
    ) -> str:
        """
        Generates a customer access token granting audio publish and subscribe privileges.
        """
        grant = VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )
        token = (
            AccessToken(self.api_key, self.api_secret)
            .with_identity(identity)
            .with_name(name or identity)
            .with_grants(grant)
            .to_jwt()
        )
        return token

    def generate_supervisor_token(
        self,
        room_name: str,
        identity: str,
        name: Optional[str] = None,
    ) -> str:
        """
        Generates a restricted supervisor token:
        - Audio Subscribe ONLY (cannot publish audio to customer mix)
        - Data Channel Publish ONLY (allows private whisper messages)
        - Hidden participant (stealth presence)
        """
        grant = VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=False,      # Strictly cannot publish audio/video
            can_subscribe=True,    # Can listen to all audio
            can_publish_data=True, # Can send whisper data messages
            hidden=True,           # Stealth participant
        )
        token = (
            AccessToken(self.api_key, self.api_secret)
            .with_identity(identity)
            .with_name(name or identity)
            .with_grants(grant)
            .to_jwt()
        )
        return token


livekit_service = LiveKitService()
