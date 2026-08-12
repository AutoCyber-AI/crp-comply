"""Content-based tool-call normalization for llama.cpp server.

llama.cpp's OpenAI-compatible server does not reliably emit native
``message.tool_calls`` for instruct models (e.g. Llama 3.1). Instead,
with a small prompt nudge it returns the tool JSON inside ``content``.
This module parses that JSON and converts it to the standard OpenAI
``tool_calls`` shape so the rest of CRP Comply can consume it unchanged.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("crp_comply.worker")


def _strip_code_fences(text: str) -> str:
    """Remove markdown JSON fences if present."""
    text = text.strip()
    if text.startswith("```"):
        # Drop the opening fence and any language tag.
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _extract_json_candidates(text: str) -> list[dict[str, Any]]:
    """Return a list of JSON objects found in *text*.

    Tries the whole string first, then falls back to balanced-brace
    extraction so a little surrounding prose does not break parsing.
    """
    text = _strip_code_fences(text)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return [p for p in parsed if isinstance(p, dict)]
        return []
    except json.JSONDecodeError:
        pass

    # Fallback: find outermost balanced braces / brackets.
    candidates: list[dict[str, Any]] = []
    for start_char, end_char in (("{", "}"), ("[", "]")):
        depth = 0
        start: int | None = None
        for i, ch in enumerate(text):
            if ch == start_char and depth == 0:
                start = i
                depth = 1
            elif ch == start_char:
                depth += 1
            elif ch == end_char and depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        parsed = json.loads(text[start : i + 1])
                        if isinstance(parsed, dict):
                            candidates.append(parsed)
                        elif isinstance(parsed, list):
                            candidates.extend(p for p in parsed if isinstance(p, dict))
                    except json.JSONDecodeError:
                        pass
                    start = None
    return candidates


def _known_tool_names(tools: list[dict[str, Any]]) -> set[str]:
    """Extract the set of tool names from OpenAI-style tool schemas."""
    names: set[str] = set()
    for tool in tools:
        if isinstance(tool, dict):
            fn = tool.get("function") or tool
            name = fn.get("name") if isinstance(fn, dict) else None
            if isinstance(name, str):
                names.add(name)
    return names


def _candidate_to_tool_call(
    candidate: dict[str, Any],
    known_names: set[str],
    call_id_prefix: str = "call_llamacpp",
) -> dict[str, Any] | None:
    """Convert a parsed JSON dict into an OpenAI ``tool_calls`` entry.

    Accepts either:
      {"name": "...", "arguments": {...}}
      {"name": "...", "parameters": {...}}
      {"function": {"name": "...", "arguments": {...}}}
    """
    if not isinstance(candidate, dict):
        return None

    name: str | None = None
    args: dict[str, Any] | None = None

    # Nested OpenAI-style inside the JSON itself.
    nested_fn = candidate.get("function")
    if isinstance(nested_fn, dict):
        name = nested_fn.get("name")
        args = nested_fn.get("arguments") or nested_fn.get("parameters")

    # Flat name + arguments/parameters.
    if name is None:
        name = candidate.get("name")
    if args is None:
        args = candidate.get("arguments") or candidate.get("parameters")

    if not isinstance(name, str) or name not in known_names:
        return None
    if not isinstance(args, dict):
        args = {}

    return {
        "id": f"{call_id_prefix}_{name}",
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(args, ensure_ascii=False),
        },
    }


def normalize_content_tool_calls(
    response: dict[str, Any],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    """If *response* has no ``tool_calls`` but ``content`` looks like tool
    JSON, rewrite it to include standard ``message.tool_calls``.

    The original content is replaced with an empty string when a tool call
    is successfully extracted, mirroring OpenAI's behaviour for native
    tool-use responses.
    """
    if not tools:
        return response

    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return response
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return response

    # Already has native tool_calls — leave it alone.
    if message.get("tool_calls"):
        return response

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        return response

    known_names = _known_tool_names(tools)
    candidates = _extract_json_candidates(content)
    tool_calls: list[dict[str, Any]] = []
    for candidate in candidates:
        tc = _candidate_to_tool_call(candidate, known_names)
        if tc is not None:
            tool_calls.append(tc)

    if not tool_calls:
        return response

    message["tool_calls"] = tool_calls
    message["content"] = ""
    choices[0]["message"] = message
    response["choices"] = choices
    logger.debug(
        "llama.cpp content-tool normalization: extracted %d call(s) from content",
        len(tool_calls),
    )
    return response


def inject_llamacpp_tool_instruction(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Append a lightweight instruction that makes generic instruct models
    emit tool calls as JSON inside ``content``.

    llama.cpp server does not attach the model's native tool template for
    generic instruct checkpoints. We therefore tell the model explicitly
    what shape to produce, then ``normalize_content_tool_calls`` parses it
    back into OpenAI ``tool_calls`` on the return path.
    """
    if not tools:
        return messages

    names = sorted(_known_tool_names(tools))
    if not names:
        return messages

    instruction = (
        "If you need to call a tool, output ONLY a JSON object of the form "
        '{"name": "TOOL_NAME", "arguments": {"arg": "value"}} '
        "and no other text. Available tools: " + ", ".join(names) + "."
    )
    return list(messages) + [{"role": "system", "content": instruction}]
