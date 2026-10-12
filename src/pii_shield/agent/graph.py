import asyncio
import json
import logging
import operator
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from pii_shield.agent.tools import ToolRegistry, has_unresolved_token, map_strings
from pii_shield.core.guardrails import OutputScan
from pii_shield.core.vault import TokenVault
from pii_shield.exceptions import InputBlockedError, ToolError
from pii_shield.pipeline import PIIShield
from pii_shield.providers.base import LLMProvider, Message, ToolCall

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a helpful customer support assistant.
Personal details in this conversation are replaced with placeholders such as \
<PERSON_1>, <EMAIL_ADDRESS_1> or <PHONE_NUMBER_1>. Each stands for a real value you cannot see.
- Use placeholders exactly as written, in replies and in tool arguments.
- Never invent, guess or alter a placeholder.
- Do not ask the user to repeat a detail that is already a placeholder.
- If you need a detail you don't have, ask for it.
- Never ask for payment card numbers."""

BLOCKED_REPLY = (
    "For your security I can't process payment card numbers in chat. "
    "Please remove it and try again."
)
LIMIT_REPLY = "I wasn't able to finish that request. Please try rephrasing it."


@dataclass(frozen=True, slots=True)
class TraceEvent:
    kind: str  # tool_call | tool_result | leak_retokenized
    name: str
    content: str  # always tokenized


@dataclass(frozen=True, slots=True)
class AgentResult:
    reply: str  # real values: show to the end user
    llm_query: str  # tokenized user message the LLM saw
    llm_reply: str  # tokenized reply the LLM produced
    history: list[Message]  # tokenized only: this is what you persist
    trace: list[TraceEvent]
    blocked: bool
    provider: str | None


class AgentState(TypedDict, total=False):
    vault: TokenVault
    user_input: str
    history: list[Message]
    llm_query: str
    rag_query: str  # retrieval hook: a RAG step would use this
    pending_calls: tuple[ToolCall, ...]
    reply: str
    display_reply: str
    blocked: bool
    tool_rounds: int
    provider: str
    trace: Annotated[list[TraceEvent], operator.add]


class PIIAgent:
    """sanitize -> LLM <-> tools (restore only at execution) -> scan -> restore."""

    def __init__(
        self,
        shield: PIIShield,
        provider: LLMProvider,
        tools: ToolRegistry,
        *,
        system_prompt: str = SYSTEM_PROMPT,
        max_tool_rounds: int = 5,
    ) -> None:
        self._shield = shield
        self._provider = provider
        self._tools = tools
        self._system_prompt = system_prompt
        self._max_tool_rounds = max_tool_rounds
        self._graph = self._build()

    async def run(
        self, user_input: str, vault: TokenVault, history: list[Message] | None = None
    ) -> AgentResult:
        state = await self._graph.ainvoke(
            {
                "vault": vault,
                "user_input": user_input,
                "history": list(history or []),
                "tool_rounds": 0,
                "trace": [],
            }
        )
        return AgentResult(
            reply=state["display_reply"],
            llm_query=state.get("llm_query", ""),
            llm_reply=state["reply"],
            history=state["history"],
            trace=state["trace"],
            blocked=state.get("blocked", False),
            provider=state.get("provider"),
        )

    # ---- helpers: Presidio/spaCy is CPU-bound, so keep it off the event loop ----

    async def _scan(self, text: str, vault: TokenVault) -> OutputScan:
        return await asyncio.to_thread(self._shield.sanitize_output, text, vault)

    async def _tokenize_args(self, args: dict[str, Any], vault: TokenVault) -> dict[str, Any]:
        # Real PII the model invents in tool arguments must not reach history.
        return await asyncio.to_thread(
            map_strings, args, lambda s: self._shield.sanitize_output(s, vault).text
        )

    # ---- nodes ----

    async def _sanitize(self, state: AgentState) -> dict[str, Any]:
        try:
            safe = await asyncio.to_thread(
                self._shield.sanitize, state["user_input"], state["vault"]
            )
        except InputBlockedError:
            # Stop here: nothing is stored, nothing reaches the LLM.
            return {"blocked": True, "reply": BLOCKED_REPLY, "display_reply": BLOCKED_REPLY}
        return {
            "history": [*state["history"], Message("user", safe.llm_query)],
            "llm_query": safe.llm_query,
            "rag_query": safe.rag_query,
        }

    async def _call_llm(self, state: AgentState) -> dict[str, Any]:
        vault = state["vault"]
        messages = [Message("system", self._system_prompt), *state["history"]]
        response = await self._provider.generate(messages, self._tools.specs())

        if response.tool_calls and state["tool_rounds"] >= self._max_tool_rounds:
            logger.warning("Tool round limit reached")
            return {"reply": LIMIT_REPLY, "pending_calls": (), "provider": response.provider}

        if not response.tool_calls:
            return {"reply": response.text, "pending_calls": (), "provider": response.provider}

        content = (await self._scan(response.text, vault)).text if response.text else ""
        calls = []
        for c in response.tool_calls:
            calls.append(ToolCall(c.id, c.name, await self._tokenize_args(c.arguments, vault)))
        return {
            "history": [
                *state["history"],
                Message("assistant", content, tool_calls=tuple(calls)),
            ],
            "pending_calls": tuple(calls),
            "provider": response.provider,
        }

    async def _execute_tools(self, state: AgentState) -> dict[str, Any]:
        vault = state["vault"]
        history = list(state["history"])
        trace: list[TraceEvent] = []

        for call in state["pending_calls"]:
            trace.append(TraceEvent("tool_call", call.name, json.dumps(call.arguments)))

            # The ONLY place real values come back, and they never go to the LLM.
            real_args = map_strings(call.arguments, vault.restore)
            if has_unresolved_token(real_args):
                result = json.dumps({"error": "arguments contain an unknown placeholder"})
            else:
                try:
                    result = await self._tools.execute(call.name, real_args)
                except ToolError as exc:
                    result = json.dumps({"error": str(exc)})

            # Results hold real values: re-tokenize before the LLM sees them.
            safe = (await self._scan(result, vault)).text
            trace.append(TraceEvent("tool_result", call.name, safe))
            history.append(Message("tool", safe, tool_call_id=call.id, name=call.name))

        return {
            "history": history,
            "pending_calls": (),
            "tool_rounds": state["tool_rounds"] + 1,
            "trace": trace,
        }

    async def _finalize(self, state: AgentState) -> dict[str, Any]:
        vault = state["vault"]
        scan = await self._scan(state["reply"], vault)
        trace = (
            [TraceEvent("leak_retokenized", "output", f"{scan.leaks_found} span(s)")]
            if scan.leaked
            else []
        )
        return {
            "history": [*state["history"], Message("assistant", scan.text)],
            "reply": scan.text,
            "display_reply": self._shield.restore(scan.text, vault),
            "trace": trace,
        }

    def _build(self):
        g = StateGraph(AgentState)
        g.add_node("sanitize", self._sanitize)
        g.add_node("call_llm", self._call_llm)
        g.add_node("execute_tools", self._execute_tools)
        g.add_node("finalize", self._finalize)

        g.add_edge(START, "sanitize")
        g.add_conditional_edges(
            "sanitize",
            lambda s: "end" if s.get("blocked") else "llm",
            {"end": END, "llm": "call_llm"},
        )
        g.add_conditional_edges(
            "call_llm",
            lambda s: "tools" if s.get("pending_calls") else "final",
            {"tools": "execute_tools", "final": "finalize"},
        )
        g.add_edge("execute_tools", "call_llm")
        g.add_edge("finalize", END)
        return g.compile()