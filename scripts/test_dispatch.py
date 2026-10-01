import asyncio
from livekit.api import LiveKitAPI
from livekit.protocol.agent_dispatch import CreateAgentDispatchRequest

async def main():
    api = LiveKitAPI("http://localhost:7880", "devkey", "voiceai_secret_key_32_characters_minimum_len_ok")
    req = CreateAgentDispatchRequest(agent_name="voice-agent-worker", room="test-room-disp")
    res = await api.agent_dispatch.create_dispatch(req)
    print("Dispatched successfully:", res)
    await api.aclose()

if __name__ == "__main__":
    asyncio.run(main())
