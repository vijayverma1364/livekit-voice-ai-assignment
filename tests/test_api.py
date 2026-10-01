import os
import uuid
import pytest
import jwt
from dotenv import load_dotenv

load_dotenv()
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "voiceai_secret_key_32_characters_minimum_len_ok")


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """
    Test GET /health returns 200 and healthy upstream dependencies.
    """
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["dependencies"]["database"] == "connected"
    assert data["dependencies"]["livekit"] == "connected"


@pytest.mark.asyncio
async def test_create_agent_valid(client):
    """
    Test POST /agents creates and returns a valid agent profile.
    """
    payload = {
        "name": f"Support Tier 2 - {uuid.uuid4().hex[:6]}",
        "system_prompt": "You are a Tier 2 technical support agent.",
        "voice": "shimmer",
        "model": "gpt-4o",
    }
    response = await client.post("/agents", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["name"] == payload["name"]
    assert data["system_prompt"] == payload["system_prompt"]
    assert data["voice"] == "shimmer"
    assert data["model"] == "gpt-4o"
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_create_agent_invalid_input(client):
    """
    Test POST /agents with invalid payload returns 422 Unprocessable Entity.
    """
    # Missing required name field
    response = await client.post(
        "/agents",
        json={"system_prompt": "Prompt with no name", "voice": "alloy"},
    )
    assert response.status_code == 422

    # Empty name
    response_empty = await client.post(
        "/agents",
        json={"name": "", "system_prompt": "Valid prompt"},
    )
    assert response_empty.status_code == 422


@pytest.mark.asyncio
async def test_get_agent_existing(client):
    """
    Test GET /agents/{id} returns the agent profile.
    """
    # Create agent first
    create_res = await client.post(
        "/agents",
        json={
            "name": "Lookup Agent",
            "system_prompt": "Lookup prompt",
            "voice": "alloy",
            "model": "gpt-4o-mini",
        },
    )
    agent_id = create_res.json()["id"]

    # Fetch agent
    get_res = await client.get(f"/agents/{agent_id}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["id"] == agent_id
    assert data["name"] == "Lookup Agent"


@pytest.mark.asyncio
async def test_get_agent_missing(client):
    """
    Test GET /agents/{id} with non-existent UUID returns 404.
    """
    missing_id = uuid.uuid4()
    response = await client.get(f"/agents/{missing_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Agent not found"


@pytest.mark.asyncio
async def test_create_call_valid(client):
    """
    Test POST /calls successfully initiates a call and returns LiveKit connection info.
    """
    # Create agent
    agent_res = await client.post(
        "/agents",
        json={
            "name": "Call Flow Agent",
            "system_prompt": "You are a friendly voice agent.",
            "voice": "alloy",
            "model": "gpt-4o-mini",
        },
    )
    agent_id = agent_res.json()["id"]

    # Create call
    call_payload = {
        "agent_id": agent_id,
        "customer_identity": "customer-alice-123",
        "customer_name": "Alice Cooper",
    }
    call_res = await client.post("/calls", json=call_payload)
    assert call_res.status_code == 201
    data = call_res.json()

    assert "call_id" in data
    assert data["agent_id"] == agent_id
    assert data["status"] == "CREATED"
    assert data["customer_identity"] == "customer-alice-123"
    assert "livekit_url" in data
    assert "livekit_token" in data
    assert data["room_name"].startswith("call-")

    # Verify customer token claims
    token = data["livekit_token"]
    decoded = jwt.decode(token, LIVEKIT_API_SECRET, algorithms=["HS256"])
    assert decoded["sub"] == "customer-alice-123"
    assert decoded["video"]["room"] == data["room_name"]
    assert decoded["video"]["roomJoin"] is True
    assert decoded["video"]["canPublish"] is True
    assert decoded["video"]["canSubscribe"] is True


@pytest.mark.asyncio
async def test_create_call_missing_agent(client):
    """
    Test POST /calls with a non-existent agent_id returns 404.
    """
    missing_agent_id = str(uuid.uuid4())
    response = await client.post(
        "/calls",
        json={"agent_id": missing_agent_id},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Agent not found"


@pytest.mark.asyncio
async def test_get_call_details(client):
    """
    Test GET /calls/{id} returns comprehensive call session details.
    """
    # Create agent and call
    agent_res = await client.post(
        "/agents",
        json={"name": "Detail Agent", "system_prompt": "Detail prompt"},
    )
    agent_id = agent_res.json()["id"]

    call_res = await client.post("/calls", json={"agent_id": agent_id})
    call_id = call_res.json()["call_id"]

    # Retrieve call
    detail_res = await client.get(f"/calls/{call_id}")
    assert detail_res.status_code == 200
    data = detail_res.json()
    assert data["id"] == call_id
    assert data["agent_id"] == agent_id
    assert data["status"] == "CREATED"
    assert isinstance(data["transcripts"], list)
    assert isinstance(data["latency_measurements"], list)
    assert data["compliance_result"] is None


@pytest.mark.asyncio
async def test_get_call_missing(client):
    """
    Test GET /calls/{id} with non-existent UUID returns 404.
    """
    missing_id = uuid.uuid4()
    response = await client.get(f"/calls/{missing_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Call not found"


@pytest.mark.asyncio
async def test_supervisor_token_generation(client):
    """
    Test POST /calls/{id}/supervisor-token returns restricted listen-only access token.
    """
    # Create agent and call
    agent_res = await client.post(
        "/agents",
        json={"name": "Supervisor Test Agent", "system_prompt": "Prompt"},
    )
    agent_id = agent_res.json()["id"]
    call_res = await client.post("/calls", json={"agent_id": agent_id})
    call_id = call_res.json()["call_id"]

    # Generate supervisor token
    token_res = await client.post(
        f"/calls/{call_id}/supervisor-token",
        json={"supervisor_identity": "sup-john-456", "supervisor_name": "Supervisor John"},
    )
    assert token_res.status_code == 200
    data = token_res.json()
    assert data["call_id"] == call_id
    assert data["supervisor_identity"] == "sup-john-456"

    # Decode and verify supervisor privacy privileges (canPublish == False, hidden == True)
    token = data["livekit_token"]
    decoded = jwt.decode(token, LIVEKIT_API_SECRET, algorithms=["HS256"])
    assert decoded["sub"] == "sup-john-456"
    assert decoded["video"]["canPublish"] is False
    assert decoded["video"]["canSubscribe"] is True
    assert decoded["video"]["canPublishData"] is True
    assert decoded["video"]["hidden"] is True
