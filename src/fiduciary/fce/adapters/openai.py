"""
OpenAI-backed baseline adapter for FCE baseline arms.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional, Sequence

from fiduciary.fce.adapters.base import (
    BaselineArmRequest,
    HTTPJSONTransport,
    LiveBaselineAdapter,
    LiveProviderConfig,
)


class OpenAIBaselineAdapter(LiveBaselineAdapter):
    adapter_name = "openai_baseline_adapter"

    def __init__(
        self,
        *,
        model: str,
        api_key_env_var: str = "OPENAI_API_KEY",
        api_url: str = "https://api.openai.com/v1/chat/completions",
        temperature: float = 0.0,
        max_output_tokens: int = 512,
        timeout_seconds: float = 60.0,
        transport: HTTPJSONTransport | None = None,
    ) -> None:
        super().__init__(
            config=LiveProviderConfig(
                provider_name="openai",
                provider_model=model,
                api_key_env_var=api_key_env_var,
                api_url=api_url,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                timeout_seconds=timeout_seconds,
            ),
            transport=transport,
        )

    def build_headers(self, api_key: str) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        organization = os.getenv("OPENAI_ORG_ID", "").strip()
        if organization:
            headers["OpenAI-Organization"] = organization
        project = os.getenv("OPENAI_PROJECT_ID", "").strip()
        if project:
            headers["OpenAI-Project"] = project
        return headers

    def build_payload(
        self,
        *,
        request: BaselineArmRequest,
        system_prompt: Optional[str],
        messages: Sequence[Mapping[str, str]],
    ) -> Dict[str, Any]:
        request_messages = []
        if system_prompt:
            request_messages.append({"role": "system", "content": system_prompt})
        for message in messages:
            request_messages.append({"role": message["role"], "content": message["content"]})
        return {
            "model": self.config.provider_model,
            "messages": request_messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_output_tokens,
        }

    def extract_response_text(self, payload: Mapping[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("OpenAI response did not include choices")
        first_choice = choices[0]
        if not isinstance(first_choice, Mapping):
            raise RuntimeError("OpenAI choice payload is malformed")
        message = first_choice.get("message")
        if not isinstance(message, Mapping):
            raise RuntimeError("OpenAI response did not include a message object")
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(_coerce_text_block(item) for item in content).strip()
        raise RuntimeError("OpenAI message content is not text-compatible")


def _coerce_text_block(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, Mapping):
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            return item["text"]
        if isinstance(item.get("content"), str):
            return item["content"]
    return ""
