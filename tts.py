import asyncio
import edge_tts

async def tts_to_bytes(text: str) -> bytes:
    communicate = edge_tts.Communicate(text, "en-US-AriaNeural")
    audio_chunks = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])
    return b"".join(audio_chunks)

def generate_tts_bytes(text: str) -> bytes:
    return asyncio.run(tts_to_bytes(text))
