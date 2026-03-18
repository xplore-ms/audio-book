import os
from google import genai
from dotenv import load_dotenv

load_dotenv()


def generate_summary(text: str) -> str:
    """
    Generates a summary of the provided text using Gemini.
    """
    api_key = os.environ.get("GENAI_API_KEY")
    if not api_key:
        raise ValueError("GENAI_API_KEY is not set")

    client = genai.Client(api_key=api_key)
    model = os.environ.get("GENAI_CLEAN_MODEL", "gemini-1.5-flash")

    # Simple limit to 2M characters (~500k tokens) to prevent payload max out just in case
    # This should be plenty for most typical books.
    max_chars = 2_000_000
    if len(text) > max_chars:
        text = text[:max_chars]

    prompt = f"Please provide a comprehensive and detailed summary of the following material:\n\n{text}"

    response = client.models.generate_content(model=model, contents=prompt)
    return response.text


def chat_with_document(text: str, message: str, history: list) -> str:
    """
    Allows a user to chat with the document content.
    """
    api_key = os.environ.get("GENAI_API_KEY")
    if not api_key:
        raise ValueError("GENAI_API_KEY is not set")

    client = genai.Client(api_key=api_key)
    model = os.environ.get("GENAI_CLEAN_MODEL", "gemini-1.5-flash")

    max_chars = 2_000_000
    if len(text) > max_chars:
        text = text[:max_chars]

    # Build history context
    history_str = ""
    if history:
        for entry in history:
            role = "User" if entry.get("role") == "user" else "Assistant"
            history_str += f"{role}: {entry.get('content')}\n\n"

    prompt = (
        f"You are a helpful AI assistant helping a user understand a book or document.\n"
        f"Here is the context of the document:\n\n{text}\n\n"
        f"Conversation History:\n{history_str}\n"
        f"User: {message}\n"
        f"Please provide a helpful and accurate response based primarily on the document. If you explain something, be clear."
    )

    response = client.models.generate_content(model=model, contents=prompt)
    return response.text
