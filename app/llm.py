"""Anthropic adapter — single point of model swap.

Wraps the Anthropic SDK with:
- Two named tiers: `fast` (Haiku) and `smart` (Sonnet).
- Automatic prompt caching of the system prompt (saves ~90% on cached tokens).
- A typed JSON-output helper for structured agent results.
- A simple tool-use loop for agents that need to call functions.

If you ever swap providers (OpenAI, Bedrock, Ollama), reimplement this file
and nothing else needs to change.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Literal

from anthropic import Anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings

Tier = Literal["fast", "smart"]

_client: Anthropic | None = None


def client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=get_settings().anthropic_api_key)
    return _client


def _model(tier: Tier) -> str:
    s = get_settings()
    return s.llm_model_fast if tier == "fast" else s.llm_model_smart


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def chat(
    *,
    system: str,
    messages: list[dict[str, Any]],
    tier: Tier = "smart",
    max_tokens: int = 1024,
    temperature: float = 0.3,
    tools: list[dict[str, Any]] | None = None,
    cache_system: bool = True,
) -> dict[str, Any]:
    """Single-turn (or multi-turn) chat. Returns the raw Anthropic response as a dict."""
    system_blocks: list[dict[str, Any]] = [{"type": "text", "text": system}]
    if cache_system:
        # Mark the system prompt as cacheable. Anthropic prompt caching has a 5-min TTL.
        system_blocks[0]["cache_control"] = {"type": "ephemeral"}

    kwargs: dict[str, Any] = {
        "model": _model(tier),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system_blocks,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools

    resp = client().messages.create(**kwargs)
    return resp.model_dump()


def extract_text(response: dict[str, Any]) -> str:
    """Concatenate all text blocks from an Anthropic response."""
    parts = []
    for block in response.get("content", []):
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts).strip()


def extract_json(response: dict[str, Any]) -> dict[str, Any]:
    """Pull the first JSON object out of the response text. Tolerant of markdown fences."""
    text = extract_text(response)
    if not text:
        raise ValueError("empty response")
    # Strip code fences if present
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        # remove leading 'json\n' or similar
        if "\n" in t:
            t = t.split("\n", 1)[1]
    # Find the first '{' and last '}' to be tolerant
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object found in: {text[:200]}")
    return json.loads(t[start : end + 1])


def json_call(
    *,
    system: str,
    user: str,
    tier: Tier = "smart",
    max_tokens: int = 1024,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """Convenience: ask for a JSON object back. The system prompt should specify the schema."""
    resp = chat(
        system=system + "\n\nReply with a single JSON object and nothing else.",
        messages=[{"role": "user", "content": user}],
        tier=tier,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return extract_json(resp)


# ---------- Tool-use loop ----------

ToolFn = Callable[[dict[str, Any]], Any]


def run_tool_loop(
    *,
    system: str,
    user: str,
    tools: list[dict[str, Any]],
    tool_impls: dict[str, ToolFn],
    tier: Tier = "smart",
    max_tokens: int = 2048,
    max_turns: int = 8,
) -> dict[str, Any]:
    """Run an agent with tools until it stops calling them or hits max_turns.

    `tools` is the Anthropic tool schema list; `tool_impls` maps tool name -> Python fn.
    Returns the final response dict.
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]

    for _ in range(max_turns):
        resp = chat(
            system=system,
            messages=messages,
            tier=tier,
            max_tokens=max_tokens,
            tools=tools,
        )
        stop_reason = resp.get("stop_reason")
        # Append the assistant turn verbatim
        messages.append({"role": "assistant", "content": resp["content"]})

        if stop_reason != "tool_use":
            return resp

        # Resolve every tool_use block in this turn
        tool_results = []
        for block in resp["content"]:
            if block.get("type") != "tool_use":
                continue
            name = block["name"]
            tool_input = block.get("input", {})
            fn = tool_impls.get(name)
            if not fn:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": f"error: unknown tool {name}",
                        "is_error": True,
                    }
                )
                continue
            try:
                result = fn(tool_input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": json.dumps(result) if not isinstance(result, str) else result,
                    }
                )
            except Exception as e:  # noqa: BLE001
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": f"error: {e}",
                        "is_error": True,
                    }
                )

        messages.append({"role": "user", "content": tool_results})

    return resp  # last response after max_turns
