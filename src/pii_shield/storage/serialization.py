from typing import Any

from pii_shield.providers.base import Message, ToolCall


def message_to_dict(m: Message) -> dict[str, Any]:
    return {
        "role": m.role,
        "content": m.content,
        "tool_calls": [
            {"id": c.id, "name": c.name, "arguments": c.arguments} for c in m.tool_calls
        ],
        "tool_call_id": m.tool_call_id,
        "name": m.name,
    }


def message_from_dict(d: dict[str, Any]) -> Message:
    return Message(
        role=d["role"],
        content=d["content"],
        tool_calls=tuple(
            ToolCall(id=c["id"], name=c["name"], arguments=c["arguments"])
            for c in d.get("tool_calls", [])
        ),
        tool_call_id=d.get("tool_call_id"),
        name=d.get("name"),
    )