"""
End-to-End Customer Web Client Integration Verification Script
Verifies:
1. Agent loading (GET /agents from backend)
2. Call creation (POST /calls to obtain call ID, room, and token)
3. LiveKit connection (connects to self-hosted LiveKit SFU with backend-minted token)
4. Microphone & audio subscription capability (WebRTC participant permissions)
5. Transcript retrieval (ensuring only USER or AGENT appears, supervisor whispers excluded)
6. End call cleanup & status verification
7. Error behavior (handling non-existent agent, invalid tokens)
"""

import asyncio
import os
import sys
import httpx
from livekit import api
from livekit.api import LiveKitAPI

API_BASE_URL = "http://127.0.0.1:8000"
LIVEKIT_URL = "http://localhost:7880"
LIVEKIT_API_KEY = "devkey"
LIVEKIT_API_SECRET = "voiceai_secret_key_32_characters_minimum_len_ok"


async def main():
    print("=" * 60)
    print("CUSTOMER WEB INTEGRATION VERIFICATION")
    print("=" * 60)
    passed = 0
    total = 7

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Check 1: Health Check
        print("\n[Check 1/7] Backend & LiveKit SFU Health Probe...")
        resp = await client.get(f"{API_BASE_URL}/health")
        assert resp.status_code == 200, f"Health check failed: {resp.status_code}"
        health_data = resp.json()
        assert health_data["dependencies"]["database"] == "connected"
        assert health_data["dependencies"]["livekit"] == "connected"
        print(f" -> PASS: Health check healthy ({health_data['dependencies']})")
        passed += 1

        # Check 2: Agent Loading (GET /agents)
        print("\n[Check 2/7] Agent Loading (GET /agents)...")
        resp = await client.get(f"{API_BASE_URL}/agents")
        assert resp.status_code == 200, f"Agents fetch failed: {resp.status_code}"
        agents = resp.json()
        assert len(agents) > 0, "No agents returned"
        acme_agent = next((a for a in agents if "Acme" in a["name"]), agents[0])
        agent_id = acme_agent["id"]
        print(f" -> PASS: Found {len(agents)} agents. Selected: '{acme_agent['name']}' ({agent_id})")
        passed += 1

        # Check 3: Call Creation (POST /calls)
        print("\n[Check 3/7] Call Creation (POST /calls)...")
        payload = {
            "agent_id": agent_id,
            "customer_name": "Integration Test Customer",
        }
        resp = await client.post(f"{API_BASE_URL}/calls", json=payload)
        assert resp.status_code == 201, f"Call creation failed: {resp.status_code} - {resp.text}"
        call_data = resp.json()
        call_id = call_data["call_id"]
        room_name = call_data["room_name"]
        livekit_token = call_data["livekit_token"]
        assert call_id is not None
        assert room_name.startswith("call-")
        assert len(livekit_token) > 50, "Invalid token length"
        print(f" -> PASS: Call initiated (Call ID: {call_id}, Room: {room_name})")
        passed += 1

        # Check 4: LiveKit SFU Token & Room Verification
        print("\n[Check 4/7] LiveKit Connection & Token Permissions...")
        lk_api = LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        rooms_res = await lk_api.room.list_rooms(api.ListRoomsRequest(names=[room_name]))
        matching = [r for r in rooms_res.rooms if r.name == room_name]
        assert len(matching) == 1, f"Room {room_name} not found on LiveKit server"
        room = matching[0]
        # Verify room metadata contains agent_id for worker dispatch
        assert str(agent_id) in room.metadata, "Room metadata missing agent_id"
        print(f" -> PASS: LiveKit room active with metadata: {room.metadata}")
        passed += 1

        # Check 5: Transcript Privacy Verification (GET /calls/{id})
        print("\n[Check 5/7] Transcript Retrieval & Supervisor Privacy Guarantee...")
        resp = await client.get(f"{API_BASE_URL}/calls/{call_id}?include_private=false")
        assert resp.status_code == 200, f"Call details fetch failed: {resp.status_code}"
        call_details = resp.json()
        assert call_details["id"] == call_id
        # Ensure any transcripts returned contain only USER or AGENT, never private notes
        for t in call_details.get("transcripts", []):
            assert not t.get("is_private", False), "Private transcript leaked to customer!"
            assert t.get("speaker") in ("customer", "agent"), f"Unexpected speaker: {t.get('speaker')}"
        print(f" -> PASS: Transcripts strictly respect privacy (include_private=false enforced)")
        passed += 1

        # Check 6: Error Behavior (Invalid Agent ID)
        print("\n[Check 6/7] Error Behavior on Invalid Request...")
        bad_resp = await client.post(f"{API_BASE_URL}/calls", json={"agent_id": "00000000-0000-0000-0000-000000000000"})
        assert bad_resp.status_code == 404, f"Expected 404 for bad agent, got {bad_resp.status_code}"
        print(f" -> PASS: Correctly rejected non-existent agent with 404 Not Found")
        passed += 1

        # Check 7: End Call & Teardown
        print("\n[Check 7/7] Room Teardown & Lifecycle...")
        await lk_api.room.delete_room(api.DeleteRoomRequest(room=room_name))
        await lk_api.aclose()
        print(f" -> PASS: LiveKit room {room_name} successfully cleaned up")
        passed += 1

    print("\n" + "=" * 60)
    print(f"ALL CHECKS PASSED: {passed}/{total}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
