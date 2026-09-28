"""Minimal Ollama client that returns validated Pydantic objects."""
import logging
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .config import Settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# JSON-schema keywords that local grammar engines may not support. Pydantic still enforces them afterwards.
_DROP = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "title", "default"}


class LLMError(RuntimeError):
    pass


def _clean_schema(node):
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "properties":
                out[k] = {name: _clean_schema(sub) for name, sub in v.items()}
            elif k not in _DROP:
                out[k] = _clean_schema(v)
        return out
    if isinstance(node, list):
        return [_clean_schema(x) for x in node]
    return node


def structured(settings: Settings, system: str, user: str, model_cls: type[T], retries: int = 2) -> T:
    """Ask the local model for JSON matching model_cls; on validation failure, show it the error and retry."""
    schema = _clean_schema(model_cls.model_json_schema())
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            resp = httpx.post(
                f"{settings.ollama_url}/api/chat",
                json={
                    "model": settings.ollama_model,
                    "messages": messages,
                    "format": schema,
                    "stream": False,
                    "options": {"temperature": 0, "num_ctx": settings.llm_num_ctx},
                },
                timeout=settings.llm_timeout_s,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama request failed ({settings.ollama_url}, model {settings.ollama_model}): {e}") from e

        content = resp.json()["message"]["content"]
        try:
            return model_cls.model_validate_json(content)
        except ValidationError as e:
            last_error = e
            log.warning("LLM output failed validation (attempt %d): %s", attempt + 1, e.errors()[:3])
            messages += [
                {"role": "assistant", "content": content},
                {"role": "user", "content": f"That JSON failed validation:\n{e}\nReturn the corrected JSON only."},
            ]
    raise LLMError(f"LLM output invalid after {retries + 1} attempts: {last_error}")
