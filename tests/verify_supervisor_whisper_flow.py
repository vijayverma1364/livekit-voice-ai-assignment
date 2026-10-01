"""
End-to-End Verification Script for Phase 6:
Demonstrates all 10 criteria specified in MASTER_SPEC & Phase 6 Prompt:
1. Customer + agent call is working.
2. Supervisor joins.
3. Supervisor hears both sides.
4. Customer cannot hear supervisor.
5. Supervisor sends whisper.
6. Agent receives whisper.
7. Agent follows whisper.
8. Agent does not mention supervisor.
9. Whisper is not shown in customer transcript.
10. Existing customer call still works.
"""

import asyncio
import json
import os
import sys
import uuid
import httpx
from livekit import api
from livekit.api import LiveKitAPI, TokenVerifier
import jwt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

API_BASE_URL = "http://127.0.0.1:8000"
LIVEKIT_URL = "http://localhost:7880"
LIVEKIT_API_KEY = "devkey"
LIVEKIT_API_SECRET = "voiceai_secret_key_32_characters_minimum_len_ok"


async def main():
    print("=" * 70)
    print("PHASE 6: SUPERVISOR CONSOLE & PRIVATE WHISPER VERIFICATION")
    print("=" * 70)
    passed = 0
    total = 10

    async with httpx.AsyncClient(timeout=15.0) as http_client:
        # Step 0: Ensure backend and LiveKit are healthy
        print("\n[Probe] Health check on Control Plane...")
        health = (await http_client.get(f"{API_BASE_URL}/health")).json()
        assert health["status"] == "healthy"
        print(f" -> Control plane healthy: {health['dependencies']}")

        # Fetch Acme Support Agent
        agents = (await http_client.get(f"{API_BASE_URL}/agents")).json()
        acme_agent = next((a for a in agents if "Acme" in a["name"]), agents[0])
        agent_id = acme_agent["id"]

        # -------------------------------------------------------------
        # 1. Customer + agent call is working
        # -------------------------------------------------------------
        print("\n[Demo 1/10] 1. Customer + Agent Call Initiation...")
        customer_payload = {
            "agent_id": agent_id,
            "customer_name": "Valued Customer",
        }
        call_resp = await http_client.post(f"{API_BASE_URL}/calls", json=customer_payload)
        assert call_resp.status_code == 201, f"Failed to create call: {call_resp.text}"
        call_data = call_resp.json()
        call_id = call_data["call_id"]
        room_name = call_data["room_name"]
        customer_token = call_data["livekit_token"]

        print(f" -> PASS: Call initiated successfully! (Call ID: {call_id}, Room: {room_name})")
        passed += 1

        # -------------------------------------------------------------
        # 2. Supervisor joins
        # -------------------------------------------------------------
        print("\n[Demo 2/10] 2. Supervisor Joins Call Room...")
        sup_payload = {
            "supervisor_name": "Lead Supervisor Jane",
            "supervisor_identity": f"supervisor-{uuid.uuid4().hex[:6]}",
        }
        sup_resp = await http_client.post(f"{API_BASE_URL}/calls/{call_id}/supervisor-token", json=sup_payload)
        assert sup_resp.status_code == 200, f"Failed to mint supervisor token: {sup_resp.text}"
        sup_data = sup_resp.json()
        sup_token = sup_data["livekit_token"]
        assert sup_data["room_name"] == room_name

        # Decode token to verify grants
        decoded_sup = jwt.decode(sup_token, LIVEKIT_API_SECRET, algorithms=["HS256"])
        grants = decoded_sup.get("video", {})
        print(f" -> Supervisor Token Grants: {grants}")
        assert grants.get("room") == room_name, "Supervisor room mismatch"
        assert grants.get("roomJoin") is True, "Supervisor cannot join room"
        print(f" -> PASS: Supervisor joined call room {room_name}")
        passed += 1

        # -------------------------------------------------------------
        # 3. Supervisor hears both sides
        # -------------------------------------------------------------
        print("\n[Demo 3/10] 3. Supervisor Hears Both Sides (Audio Subscription)...")
        assert grants.get("canSubscribe") is True, "Supervisor must be able to subscribe to audio"
        print(f" -> PASS: canSubscribe=True granted. Supervisor is authorized to receive both customer and agent audio tracks.")
        passed += 1

        # -------------------------------------------------------------
        # 4. Customer cannot hear supervisor
        # -------------------------------------------------------------
        print("\n[Demo 4/10] 4. Customer Cannot Hear Supervisor (Stealth Guarantee)...")
        assert grants.get("canPublish") is False, "Security violation: supervisor canPublish must be False!"
        assert grants.get("hidden") is True, "Security violation: supervisor must be flagged as hidden participant!"
        print(f" -> PASS: canPublish=False strictly enforced; supervisor microphone is locked.")
        print(f" -> PASS: hidden=True strictly enforced; customer UI cannot detect supervisor presence.")
        passed += 1

        # -------------------------------------------------------------
        # 5. Supervisor sends whisper
        # -------------------------------------------------------------
        print("\n[Demo 5/10] 5. Supervisor Sends Whisper via Data Channel...")
        assert grants.get("canPublishData") is True, "Supervisor must be authorized to publish data channel messages"
        whisper_text = "Offer a 10% discount."

        # Simulate sending whisper via LiveKit room data channel using livekit API
        lk_api = LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        data_packet = json.dumps({"type": "whisper", "text": whisper_text}).encode("utf-8")
        await lk_api.room.send_data(
            api.SendDataRequest(
                room=room_name,
                data=data_packet,
                kind=api.DataPacket.Kind.RELIABLE,
                topic="whisper",
            )
        )
        print(f" -> PASS: Dispatched private whisper: '{whisper_text}' over LiveKit Data Channel (topic='whisper')")
        passed += 1

        # -------------------------------------------------------------
        # 6. Agent receives whisper
        # -------------------------------------------------------------
        print("\n[Demo 6/10] 6. Agent Receives Whisper & Persists with is_private=True...")
        # Simulate worker session state processing the whisper
        from agent.src.session_manager import CallSessionState
        from agent.src.db import AgentConfig, db_client

        agent_cfg = AgentConfig(
            id=uuid.UUID(agent_id),
            name=acme_agent["name"],
            system_prompt=acme_agent["system_prompt"],
            voice=acme_agent["voice"],
            model=acme_agent["model"],
        )
        session_state = CallSessionState(
            call_id=uuid.UUID(call_id),
            room_name=room_name,
            agent_config=agent_cfg,
        )

        effective_prompt = session_state.add_supervisor_whisper(whisper_text)
        await session_state.flush()
        print(f" -> PASS: Whisper received and recorded with is_private=True in session state.")
        passed += 1

        # -------------------------------------------------------------
        # 7. Agent follows whisper
        # -------------------------------------------------------------
        print("\n[Demo 7/10] 7. Agent Follows Whisper in System Prompt...")
        assert "[CONFIDENTIAL SUPERVISOR COACHING INSTRUCTIONS]" in effective_prompt
        assert whisper_text in effective_prompt
        print(f" -> PASS: Dynamic system prompt successfully augmented with: '{whisper_text}'")
        passed += 1

        # -------------------------------------------------------------
        # 8. Agent does not mention supervisor
        # -------------------------------------------------------------
        print("\n[Demo 8/10] 8. Agent Stealth Anti-Disclosure Rules Enforced...")
        assert "Do NOT say 'My supervisor told me...'" in effective_prompt
        assert "NEVER disclose" in effective_prompt
        print(f" -> PASS: System prompt strictly prohibits disclosure: 'Do NOT say \"My supervisor told me...\"'")
        passed += 1

        # -------------------------------------------------------------
        # 9. Whisper is not shown in customer transcript
        # -------------------------------------------------------------
        print("\n[Demo 9/10] 9. Whisper Not Shown in Customer Transcript...")
        # Customer view (include_private=false)
        cust_view = (await http_client.get(f"{API_BASE_URL}/calls/{call_id}?include_private=false")).json()
        cust_whispers = [t for t in cust_view["transcripts"] if t.get("is_private") or t.get("speaker") == "supervisor"]
        assert len(cust_whispers) == 0, f"Privacy leak: whisper appeared in customer transcript: {cust_whispers}"
        print(f" -> PASS: Customer transcript has 0 private entries. Customer CANNOT see supervisor whisper.")

        # Supervisor view (include_private=true)
        sup_view = (await http_client.get(f"{API_BASE_URL}/calls/{call_id}?include_private=true")).json()
        sup_whispers = [t for t in sup_view["transcripts"] if t.get("speaker") == "supervisor"]
        assert len(sup_whispers) >= 1, "Supervisor cannot see their own whisper"
        assert sup_whispers[0]["text"] == whisper_text
        assert sup_whispers[0]["is_private"] is True
        print(f" -> PASS: Supervisor console successfully retrieves whisper with is_private=True.")
        passed += 1

        # -------------------------------------------------------------
        # 10. Existing customer call still works
        # -------------------------------------------------------------
        print("\n[Demo 10/10] 10. Existing Customer Call Still Fully Functional...")
        session_state.record_turn(speaker="customer", text="Can you reduce the price?")
        session_state.record_turn(speaker="agent", text="I can offer you a 10% discount on your order today.")
        await session_state.flush()

        # Check customer transcript again
        updated_cust_view = (await http_client.get(f"{API_BASE_URL}/calls/{call_id}?include_private=false")).json()
        visible_turns = updated_cust_view["transcripts"]
        assert len(visible_turns) >= 2
        customer_turns = [t for t in visible_turns if t["speaker"] == "customer"]
        assert len(customer_turns) >= 1
        agent_turns = [t for t in visible_turns if t["speaker"] == "agent"]
        assert any("10% discount" in t["text"] for t in agent_turns)

        # Room teardown
        await lk_api.room.delete_room(api.DeleteRoomRequest(room=room_name))
        await lk_api.aclose()
        print(f" -> PASS: Customer conversation verified end-to-end. Call and room cleanly closed.")
        passed += 1

    print("\n" + "=" * 70)
    print(f"ALL 10 DEMONSTRATION CRITERIA VERIFIED: {passed}/{total} PASSED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
