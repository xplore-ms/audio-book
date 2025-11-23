import os, logging, time
from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors

load_dotenv()
logger = logging.getLogger(__name__)

GENAI_KEY = os.getenv("GENAI_API_KEY")
CLEAN_MODEL = os.getenv("GENAI_CLEAN_MODEL", "gemini-2.5-flash")
GENAI_MAX_WORDS = int(os.getenv("GENAI_MAX_WORDS", "3000"))

if not GENAI_KEY:
    raise RuntimeError("GENAI_API_KEY must be set in .env")

def _chunk_text_by_words(text: str, max_words: int):
    words = text.split()
    for i in range(0, len(words), max_words):
        yield " ".join(words[i:i + max_words])

def clean_text_with_gemini(text: str) -> str:
    client = genai.Client(api_key=GENAI_KEY)
    prompt_template = (
        "Clean and rewrite this text so it can be read naturally by a text-to-speech engine.\n"
        "Remove line breaks, page numbers, headers, footers, watermarks, and PDF artifacts.\n"
        "Produce a smooth, natural, audiobook-ready script.\n"
        "DO NOT ADD ANY INTRO OR OUTRO. Keep ONLY the cleaned text.\n\n"
        "TEXT:\n{chunk}\n"
    )
    cleaned_parts = []
    for chunk in _chunk_text_by_words(text, GENAI_MAX_WORDS):
        prompt = prompt_template.format(chunk=chunk)
        retries = 3
        for attempt in range(retries):
            try:
                res = client.models.generate_content(model=CLEAN_MODEL, contents=prompt)
                if hasattr(res, "text"): cleaned_parts.append(res.text.strip())
                elif isinstance(res, dict) and "text" in res: cleaned_parts.append(res["text"].strip())
                else: cleaned_parts.append(str(res).strip())
                break
            except genai_errors.ClientError as e:
                logger.error(f"[GenAI] Client error: {e}")
                raise
            except Exception as e:
                logger.warning(f"[GenAI] Chunk retry {attempt+1}/{retries} failed: {e}")
                time.sleep(2 ** attempt)
                if attempt == retries - 1:
                    cleaned_parts.append(chunk.strip())
    return "\n\n".join([p for p in cleaned_parts if p])