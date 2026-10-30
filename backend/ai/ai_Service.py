import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .prompts import build_assistant_prompt


class AIServiceError(RuntimeError):
    """Raised when Google Gemini API cannot provide a usable response."""


def generate_assistant_reply(
    messages: list[dict[str, str]],
    case_context: dict,
    api_key: str,
    model: str,
) -> str:
    prompt = build_assistant_prompt(case_context)
    contents = []
    for index, message in enumerate(messages):
        text = message["content"]
        if index == 0:
            text = f"{prompt}\n\nInvestigator: {text}"
        contents.append({
            "role": "model" if message["role"] == "model" else "user",
            "parts": [{"text": text}],
        })

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{quote(model, safe='')}:generateContent"
    )
    request = Request(
        url,
        data=json.dumps({
            "contents": contents,
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except HTTPError as error:
        try:
            body = json.loads(error.read(4096))
        except json.JSONDecodeError:
            body = {}
        error_body = body.get("error") if isinstance(body, dict) else None
        detail = error_body.get("message") if isinstance(error_body, dict) else None
        message = detail if isinstance(detail, str) else "No error details were provided."
        raise AIServiceError(
            f"Google Gemini API returned HTTP {error.code}: {message}"
        ) from error
    except (TimeoutError, URLError) as error:
        raise AIServiceError(f"Could not reach Google Gemini API: {error}") from error
    except json.JSONDecodeError as error:
        raise AIServiceError("Google Gemini API returned invalid JSON.") from error

    if not isinstance(payload, dict):
        raise AIServiceError("Google Gemini API returned an unexpected response.")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise AIServiceError("Google Gemini API returned no assistant response.")
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise AIServiceError("Google Gemini API returned an unexpected response.")
    content = candidate.get("content")
    parts = content.get("parts", []) if isinstance(content, dict) else []
    if not isinstance(parts, list):
        raise AIServiceError("Google Gemini API returned an unexpected response.")
    answer = "\n".join(
        part["text"]
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ).strip()
    if not answer:
        raise AIServiceError("Google Gemini API returned an empty assistant response.")
    return answer