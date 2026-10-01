import asyncio
import httpx
import uuid
from livekit import rtc

API_BASE_URL = "http://127.0.0.1:8000"
LIVEKIT_URL = "ws://localhost:7880"

async def test():
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Get Acme Support Agent
        resp = await client.get(f"{API_BASE_URL}/agents")
        agents = resp.json()
        agent = next((a for a in agents if "Acme" in a["name"]), agents[0])
        print("Using Agent:", agent["name"], agent["id"])

        # Create Call
        call_resp = await client.post(f"{API_BASE_URL}/calls", json={
            "agent_id": agent["id"],
            "customer_name": "Test Customer",
        })
        call_data = call_resp.json()
        print("Created Call:", call_data)
        call_id = call_data["call_id"]
        token = call_data["livekit_token"]

        # Connect customer to LiveKit room
        room = rtc.Room()
        print("Connecting customer to room...")
        await room.connect(LIVEKIT_URL, token)
        print("Customer connected! Remote participants:", [p.identity for p in room.remote_participants.values()])

        # Wait a few seconds to let worker connect
        for _ in range(10):
            await asyncio.sleep(1)
            remotes = [p.identity for p in room.remote_participants.values()]
            print("Current remotes in room:", remotes)
            if any("agent" in r.lower() or "worker" in r.lower() for r in remotes):
                print("Worker joined room!")
                break

        await asyncio.sleep(3)
        await room.disconnect()
        print("Customer disconnected.")

if __name__ == "__main__":
    asyncio.run(test())
