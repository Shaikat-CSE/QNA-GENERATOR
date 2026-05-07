from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError
from dataclasses import dataclass
from typing import Any, Callable


def env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


@dataclass(frozen=True)
class MiniMaxConfig:
    api_key: str
    base_url: str
    model: str
    timeout_ms: int = 60000
    anthropic_version: str = "2023-06-01"

    @classmethod
    def from_sources(
        cls,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_ms: int | None = None,
    ) -> "MiniMaxConfig":
        resolved_api_key = api_key or env_first("MINIMAX_API_KEY", "ANTHROPIC_AUTH_TOKEN")
        resolved_base_url = base_url or env_first("MINIMAX_BASE_URL", "ANTHROPIC_BASE_URL")
        resolved_model = model or env_first("MINIMAX_MODEL", "ANTHROPIC_MODEL", "MODEL")
        resolved_timeout_ms = timeout_ms
        if resolved_timeout_ms is None:
            timeout_raw = env_first("MINIMAX_TIMEOUT_MS", "API_TIMEOUT_MS")
            resolved_timeout_ms = int(timeout_raw) if timeout_raw else 60000

        missing = [
            name
            for name, value in (
                ("api_key", resolved_api_key),
                ("base_url", resolved_base_url),
                ("model", resolved_model),
            )
            if not value
        ]
        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(
                "MiniMax configuration is incomplete. Missing "
                f"{missing_text}. Set MINIMAX_* env vars or provide CLI overrides."
            )

        return cls(
            api_key=resolved_api_key,
            base_url=resolved_base_url.rstrip("/") + "/",
            model=resolved_model,
            timeout_ms=resolved_timeout_ms,
        )


class MiniMaxClient:
    def __init__(self, config: MiniMaxConfig, logger: Callable[[str], None] | None = None) -> None:
        self.config = config
        self.logger = logger

    def _expanded_max_tokens(self, max_tokens: int) -> int:
        return max(max_tokens + 400, int(max_tokens * 1.5))

    def _send_messages_request(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        self._log(
            f"[llm] request start | model={self.config.model} | max_tokens={max_tokens} | temperature={temperature}"
        )

        # Auto-detect API format based on base_url
        is_openai_format = "chat/completions" in self.config.base_url

        if is_openai_format:
            # OpenAI format: system message in messages array
            payload = {
                "model": self.config.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
            }
            endpoint = ""  # Already in base_url
        else:
            # Anthropic format: system at root level
            payload = {
                "model": self.config.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            }
            endpoint = "v1/messages"

        response_json = self._post_json(endpoint, payload)

        # Handle both OpenAI and Anthropic response formats
        if "choices" in response_json:
            # OpenAI format
            usage = response_json.get("usage", {})
            input_tokens = usage.get("prompt_tokens", "?")
            output_tokens = usage.get("completion_tokens", "?")
            stop_reason = response_json.get("choices", [{}])[0].get("finish_reason", "?")
        else:
            # Anthropic format
            usage = response_json.get("usage", {})
            input_tokens = usage.get("input_tokens", "?")
            output_tokens = usage.get("output_tokens", "?")
            stop_reason = response_json.get("stop_reason", "?")

        self._log(
            f"[llm] response received | stop_reason={stop_reason} | input_tokens={input_tokens} | output_tokens={output_tokens}"
        )
        return response_json

    def _request_messages(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        response_json = self._send_messages_request(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if response_json.get("stop_reason") == "max_tokens":
            retry_max_tokens = self._expanded_max_tokens(max_tokens)
            self._log(
                f"[llm] retrying after max_tokens | previous_max_tokens={max_tokens} | retry_max_tokens={retry_max_tokens}"
            )
            response_json = self._send_messages_request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=retry_max_tokens,
                temperature=temperature,
            )
        return response_json

    def create_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 2500,
        temperature: float = 0.0,
    ) -> str:
        response_json = self._request_messages(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        try:
            text = extract_text_content(response_json)
        except ValueError as exc:
            if response_json.get("stop_reason") == "max_tokens":
                raise ValueError(
                    "MiniMax response remained truncated after one retry. Increase max_tokens or shorten the prompt."
                ) from exc
            raise
        if response_json.get("stop_reason") == "max_tokens":
            raise ValueError("MiniMax response remained truncated after one retry. Increase max_tokens or shorten the prompt.")
        return text

    def create_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 2500,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        response_json = self._request_messages(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        try:
            text = extract_text_content(response_json)
        except ValueError as exc:
            if response_json.get("stop_reason") == "max_tokens":
                raise ValueError(
                    "MiniMax response remained truncated after one retry. "
                    "Increase max_tokens or shorten the prompt."
                ) from exc
            raise
        try:
            parsed = extract_json_object(text)
        except ValueError as exc:
            if response_json.get("stop_reason") == "max_tokens":
                raise ValueError(
                    "MiniMax response remained truncated after one retry. "
                    "Increase max_tokens or shorten the prompt."
                ) from exc
            raise
        if response_json.get("stop_reason") == "max_tokens":
            raise ValueError(
                "MiniMax response remained truncated after one retry. "
                "Increase max_tokens or shorten the prompt."
            )
        return parsed

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        # If path is empty, use base_url directly (for OpenAI format where endpoint is in base_url)
        if path:
            url = urllib.parse.urljoin(self.config.base_url, path)
        else:
            url = self.config.base_url.rstrip('/')

        self._log(f"[llm] http POST {url}")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "x-api-key": self.config.api_key,
            "anthropic-version": self.config.anthropic_version,
        }

        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            request = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers=headers,
            )
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout_ms / 1000) as response:
                    raw = response.read().decode("utf-8", "replace")
                    self._log(f"[llm] http {response.status}")
                return json.loads(raw)
            except HTTPError as exc:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                raw_error = exc.read().decode("utf-8", "replace")
                self._log(f"[llm] http error {exc.code} | body={raw_error[:300]}")
                if exc.code in {408, 409, 425, 429, 500, 502, 503, 504} and attempt < max_attempts:
                    delay = self._retry_delay_seconds(attempt, retry_after)
                    self._log(f"[llm] retrying after {delay:.1f}s | attempt={attempt}/{max_attempts}")
                    time.sleep(delay)
                    continue
                raise
            except URLError as exc:
                self._log(f"[llm] url error | reason={exc.reason}")
                if attempt < max_attempts:
                    delay = self._retry_delay_seconds(attempt)
                    self._log(f"[llm] retrying after {delay:.1f}s | attempt={attempt}/{max_attempts}")
                    time.sleep(delay)
                    continue
                raise

        raise RuntimeError("MiniMax request failed after retries")

    def _retry_delay_seconds(self, attempt: int, retry_after: str | None = None) -> float:
        if retry_after:
            try:
                return max(1.0, min(30.0, float(retry_after)))
            except ValueError:
                pass
        return min(30.0, 1.5 * (2 ** (attempt - 1)))

    def _log(self, message: str) -> None:
        if self.logger is not None:
            self.logger(message)


def extract_text_content(response_json: dict[str, Any]) -> str:
    if isinstance(response_json.get("content"), list):
        chunks: list[str] = []
        for item in response_json["content"]:
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(item.get("text", ""))
        if chunks:
            return "\n".join(chunks).strip()

    choices = response_json.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, dict):
            message = choice.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content.strip()
                reasoning = message.get("reasoning_content")
                if isinstance(reasoning, str):
                    return reasoning.strip()
            if isinstance(choice.get("text"), str):
                return choice["text"].strip()

    if isinstance(response_json.get("output_text"), str):
        return response_json["output_text"].strip()

    raise ValueError("Could not extract text content from MiniMax response.")


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise ValueError("MiniMax returned an empty response.")

    direct = _try_json_load(stripped)
    if isinstance(direct, dict):
        return direct

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fenced_match:
        fenced = _try_json_load(fenced_match.group(1))
        if isinstance(fenced, dict):
            return fenced

    balanced = _find_balanced_json_object(stripped)
    if balanced is not None:
        parsed = _try_json_load(balanced)
        if isinstance(parsed, dict):
            return parsed

    raise ValueError(f"MiniMax did not return a valid JSON object: {text[:400]}")


def _try_json_load(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _find_balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        start = text.find("{", start + 1)
    return None
