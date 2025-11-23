# tts.py
import asyncio
import os
import logging
from pydub import AudioSegment
import edge_tts
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
VOICE = os.getenv("EDGE_TTS_VOICE", "en-US-AriaNeural")

async def _stream_to_file(text: str, out_path: str, voice: str):
    communicate = edge_tts.Communicate(text, voice=voice)
    with open(out_path, "wb") as f:
        async for message in communicate.stream():
            if message.get("type") == "audio" and message.get("data"):
                f.write(message["data"])

def generate_speech(text: str, out_path: str, voice: str = VOICE, max_words_per_chunk: int = 400):
    """Synchronous wrapper for Edge TTS with chunking and cleanup."""
    if not text.strip():
        AudioSegment.silent(duration=1000).export(out_path, format="mp3")
        return

    words = text.split()
    chunks = [" ".join(words[i:i + max_words_per_chunk]) for i in range(0, len(words), max_words_per_chunk)]
    part_files = []

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        for idx, chunk in enumerate(chunks):
            part_path = f"{out_path}.part{idx}.mp3"
            try:
                loop.run_until_complete(_stream_to_file(chunk, part_path, voice))
            except Exception as e:
                logger.warning(f"[EDGE_TTS] Chunk {idx} failed: {e}")
                AudioSegment.silent(duration=500).export(part_path, format="mp3")
            part_files.append(part_path)

        # merge
        combined = AudioSegment.empty()
        for p in part_files:
            try:
                combined += AudioSegment.from_mp3(p)
            except Exception as e:
                logger.warning(f"[EDGE_TTS] Failed reading {p}: {e}")
                combined += AudioSegment.silent(duration=500)
        combined.export(out_path, format="mp3")
    finally:
        loop.close()
        for p in part_files:
            try: os.remove(p)
            except Exception: pass