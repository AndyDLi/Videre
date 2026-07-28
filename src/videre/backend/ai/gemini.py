"""
Turns a FailureContext into a parsed RootCauseAnalysis.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from ..settings import Settings
from .analysis import RootCauseAnalysis
from .context import FailureContext
from .prompt import SYSTEM_INSTRUCTION, build_prompt

logger = logging.getLogger("videre.backend.ai.gemini")

RETRY_BACKOFF_SECONDS = 0.5
RATE_LIMIT_STATUS_CODE = 429


class GeminiError(Exception):
    """Base class for Gemini failures the endpoint has to communicate."""


class GeminiRateLimitError(GeminiError):
    """Gemini rejected the call with 429. Never retried."""


class GeminiRequestError(GeminiError):
    """Gemini rejected with a 4xx that is not a rate limit."""


class GeminiUnavailableError(GeminiError):
    """A timeout, connection failure, or 5xx that outlived the retries."""


class GeminiResponseError(GeminiError):
    """The call succeeded but the structured output was missing or unparseable."""


class GeminiAnalyst:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._model = settings.gemini_model
        self._timeout_seconds = settings.gemini_timeout_seconds
        self._maximum_attempts = settings.gemini_maximum_attempts
        self._maximum_prompt_characters = settings.gemini_maximum_prompt_characters
        self._client = client if client is not None else genai.Client(
            api_key=settings.gemini_api_key.get_secret_value()
        )
        self._config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=RootCauseAnalysis,
            temperature=0.2
        )
    
    async def analyze(self, context: FailureContext) -> RootCauseAnalysis:
        prompt = build_prompt(context, maximum_characters=self._maximum_prompt_characters)
        logger.info(
            "gemini request",
            extra={
                "entity_type": context.entity_type.value,
                "entity_id": context.entity_id,
                "model": self._model,
                "prompt_characters": len(prompt),
                "degraded_sources": context.degraded_sources,
            }
        )
        return _parse(await self._generate(prompt))
    
    async def _generate(self, prompt: str) -> Any:
        last_error: Exception | None = None
        
        for attempt in range(1, self._maximum_attempts + 1):
            try:
                return await asyncio.wait_for(
                    self._client.aio.models.generate_content(
                        model=self._model, contents=prompt, config=self._config
                    ),
                    self._timeout_seconds,
                )
            except errors.ClientError as error:
                if error.code == RATE_LIMIT_STATUS_CODE:
                    raise GeminiRateLimitError("gemini rejected the request as rate limited") from error
                raise GeminiRequestError(
                    f"gemini rejected the request: {error.code} {error.message}"
                ) from error
            except (errors.ServerError, TimeoutError, ConnectionError) as error:
                last_error = error
                logger.warning(
                    "gemini call failed, retrying",
                    extra={"attempt": attempt, "attempts_allowed": self._maximum_attempts, "error": str(error)},
                )
                if attempt < self._maximum_attempts:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
        
        raise GeminiUnavailableError(
            f"gemini unreachable after {self._maximum_attempts} attempts"
        ) from last_error


def _parse(response: Any) -> RootCauseAnalysis:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, RootCauseAnalysis):
        return parsed
    
    text = getattr(response, "text", None)
    if text:
        try:
            return RootCauseAnalysis.model_validate_json(text)
        except ValidationError as error:
            raise GeminiResponseError("gemini returned unparseable structured output") from error
    
    raise GeminiResponseError("gemini returned no content")
