import os
import uuid
import pytest
import jwt
from dotenv import load_dotenv
from livekit.api import (
    AccessToken,
    CreateRoomRequest,
    DeleteRoomRequest,
    ListRoomsRequest,
    LiveKitAPI,
    VideoGrants,
)

load_dotenv()

LIVEKIT_URL = os.getenv("LIVEKIT_URL", "http://localhost:7880")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "devkey")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "voiceai_secret_key_32_characters_minimum_len_ok")


@pytest.mark.asyncio
async def test_livekit_credentials_configured():
    """
    Verify LiveKit environment credentials are present and meet minimum length requirements.
    """
    assert LIVEKIT_URL.startswith("http://") or LIVEKIT_URL.startswith("https://")
    assert len(LIVEKIT_API_KEY) > 0
    assert len(LIVEKIT_API_SECRET) >= 32, "LiveKit secret must be at least 32 characters for security"


@pytest.mark.asyncio
async def test_livekit_token_generation():
    """
    Verify generation and claims structure of LiveKit access tokens.
    """
    identity = f"user-{uuid.uuid4().hex[:6]}"
    room_name = f"room-{uuid.uuid4().hex[:6]}"

    grant = VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
    )
    token = (
        AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_name("Test User")
        .with_grants(grant)
        .to_jwt()
    )

    assert isinstance(token, str)
    assert len(token) > 20

    # Decode and verify payload
    decoded = jwt.decode(token, LIVEKIT_API_SECRET, algorithms=["HS256"])
    assert decoded["sub"] == identity
    assert decoded["name"] == "Test User"
    assert decoded["video"]["room"] == room_name
    assert decoded["video"]["roomJoin"] is True


@pytest.mark.asyncio
async def test_livekit_server_connection_and_room_lifecycle():
    """
    Verify that the self-hosted LiveKit server is reachable, accepts credentials,
    and supports room creation, listing, and deletion.
    """
    api = LiveKitAPI(
        url=LIVEKIT_URL,
        api_key=LIVEKIT_API_KEY,
        api_secret=LIVEKIT_API_SECRET,
    )

    test_room_name = f"phase1-test-{uuid.uuid4().hex[:8]}"

    try:
        # 1. Create Room
        create_req = CreateRoomRequest(name=test_room_name, empty_timeout=120)
        room = await api.room.create_room(create_req)
        assert room.name == test_room_name
        assert room.sid.startswith("RM_")

        # 2. List Rooms and verify presence
        list_req = ListRoomsRequest(names=[test_room_name])
        res = await api.room.list_rooms(list_req)
        matching_rooms = [r for r in res.rooms if r.name == test_room_name]
        assert len(matching_rooms) == 1
        assert matching_rooms[0].sid == room.sid

        # 3. Clean up (Delete Room)
        del_req = DeleteRoomRequest(room=test_room_name)
        await api.room.delete_room(del_req)

        # 4. Verify room deleted
        res_after = await api.room.list_rooms(ListRoomsRequest(names=[test_room_name]))
        assert len(res_after.rooms) == 0

    finally:
        await api.aclose()
