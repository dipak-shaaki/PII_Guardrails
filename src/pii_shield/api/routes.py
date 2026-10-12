import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from pii_shield.agent import PIIAgent
from pii_shield.api.schemas import (
    ChatRequest,
    ChatResponse,
    DeleteResponse,
    HealthResponse,
    MessageView,
    SessionView,
    ToolCallView,
    TraceEventOut,
)
from pii_shield.config import Settings
from pii_shield.exceptions import SessionNotFoundError
from pii_shield.storage import SessionStore

router = APIRouter()


def get_agent(request: Request) -> PIIAgent:
    return request.app.state.agent


def get_store(request: Request) -> SessionStore:
    return request.app.state.store


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


AgentDep = Annotated[PIIAgent, Depends(get_agent)]
StoreDep = Annotated[SessionStore, Depends(get_store)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest, agent: AgentDep, store: StoreDep, settings: SettingsDep
) -> ChatResponse:
    # Server-generated ids are unguessable (22 URL-safe chars from a CSPRNG).
    session_id = body.session_id or secrets.token_urlsafe(16)

    # load -> run -> save is a read-modify-write, so hold the per-session lock.
    async with store.lock(session_id):
        session = await store.load(session_id)
        result = await agent.run(body.message, session.vault, session.history)
        # Save only on success: a failed turn leaves the stored session untouched.
        if not result.blocked:
            await store.save(session_id, session.vault, result.history)

    return ChatResponse(
        session_id=session_id,
        reply=result.reply,
        llm_query=result.llm_query,
        llm_reply=result.llm_reply,
        blocked=result.blocked,
        provider=result.provider,
        trace=[
            TraceEventOut(kind=e.kind, name=e.name, content=e.content)
            for e in result.trace
        ],
        token_map=session.vault.token_to_value if settings.expose_token_map else None,
    )


@router.get("/sessions/{session_id}", response_model=SessionView)
async def get_session(
    session_id: str, store: StoreDep, settings: SettingsDep
) -> SessionView:
    session = await store.load(session_id)
    if not session.history and not session.vault.token_to_value:
        raise SessionNotFoundError()
    return SessionView(
        session_id=session_id,
        history=[
            MessageView(
                role=m.role,
                content=m.content,
                tool_calls=[
                    ToolCallView(name=c.name, arguments=c.arguments)
                    for c in m.tool_calls
                ],
            )
            for m in session.history
        ],
        token_map=session.vault.token_to_value if settings.expose_token_map else None,
    )


@router.delete("/sessions/{session_id}", response_model=DeleteResponse)
async def delete_session(session_id: str, store: StoreDep) -> DeleteResponse:
    return DeleteResponse(deleted=await store.delete(session_id))


@router.get("/health", response_model=HealthResponse)
async def health(store: StoreDep, response: Response) -> HealthResponse:
    ok = await store.ping()
    if not ok:
        response.status_code = 503
    return HealthResponse(status="ok" if ok else "degraded", redis=ok)
