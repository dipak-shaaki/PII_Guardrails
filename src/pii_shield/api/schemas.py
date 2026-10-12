from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints

MAX_MESSAGE_CHARS = 4000  # bounds spaCy/LLM cost per request

UserText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_CHARS
    ),
]


class ChatRequest(BaseModel):
    message: UserText
    session_id: str | None = Field(
        default=None,
        description="Omit on the first message. The server generates one and returns it.",
    )


class TraceEventOut(BaseModel):
    kind: str  # tool_call | tool_result | leak_retokenized
    name: str
    content: str  # always tokenized


class ChatResponse(BaseModel):
    session_id: str
    reply: str  # real values: what the end user sees
    llm_query: str  # tokenized: what the LLM saw
    llm_reply: str  # tokenized: what the LLM said (a fixed notice when blocked)
    blocked: bool
    provider: str | None
    trace: list[TraceEventOut]
    token_map: dict[str, str] | None = None  # only when EXPOSE_TOKEN_MAP=true


class ToolCallView(BaseModel):
    name: str
    arguments: dict[str, Any]


class MessageView(BaseModel):
    role: str
    content: str
    tool_calls: list[ToolCallView] = []


class SessionView(BaseModel):
    session_id: str
    history: list[MessageView]  # tokens only, exactly what is stored
    token_map: dict[str, str] | None = None


class DeleteResponse(BaseModel):
    deleted: bool


class HealthResponse(BaseModel):
    status: str
    redis: bool
