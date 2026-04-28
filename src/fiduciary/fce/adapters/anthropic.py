"""
Anthropic-backed baseline adapter for FCE baseline arms.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from fiduciary.fce.adapters.base import (
    BaselineArmRequest,
    HTTPJSONTransport,
    LiveBaselineAdapter,
    LiveProviderConfig,
)


class AnthropicBaselineAdapter(LiveBaselineAdapter):
    adapter_name = "anthropic_baseline_adapter"

    def __init__(
        self,
        *,
        model: str,
        api_key_env_var: str = "ANTHROPIC_API_KEY",
        api_url: str = "https://api.anthropic.com/v1/messages",
        temperature: float = 0.0,
        max_output_tokens: int = 512,
        timeout_seconds: float = 60.0,
        transport: HTTPJSONTransport | None = None,
    ) -> None:
        super().__init__(
            config=LiveProviderConfig(
                provider_name="anthropic",
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
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def build_payload(
        self,
        *,
        request: BaselineArmRequest,
        system_prompt: Optional[str],
        messages: Sequence[Mapping[str, str]],
    ) -> Dict[str, Any]:
        payload = {
            "model": self.config.provider_model,
            "max_tokens": self.config.max_output_tokens,
            "temperature": self.config.temperature,
            "messages": [
                {"role": message["role"], "content": message["content"]}
                for message in messages
            ],
        }
        if system_prompt:
            payload["system"] = system_prompt
        return payload

    def extract_response_text(self, payload: Mapping[str, Any]) -> str:
        content = payload.get("content")
        if not isinstance(content, list):
            raise RuntimeError("Anthropic response did not include content blocks")
        text = "".join(_coerce_text_block(item) for item in content).strip()
        if not text:
            raise RuntimeError("Anthropic response did not include any text content")
        return text


def _coerce_text_block(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, Mapping) and item.get("type") == "text" and isinstance(item.get("text"), str):
        return item["text"]
    return ""
