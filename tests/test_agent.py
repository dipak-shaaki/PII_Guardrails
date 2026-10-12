import json

from pydantic import BaseModel

from pii_shield import PIIShield, TokenVault
from pii_shield.agent import PIIAgent, Tool, ToolRegistry
from pii_shield.agent.graph import LIMIT_REPLY
from pii_shield.providers.base import LLMProvider, LLMResponse, ToolCall
from tests.helpers import StubDetector

CARD = "4111 1111 1111 1111"
KNOWN = {"Dipak": "PERSON", "dipak@example.com": "EMAIL_ADDRESS", CARD: "CREDIT_CARD"}


class EmailArgs(BaseModel):
    to_email: str
    body: str


class ScriptedProvider(LLMProvider):
    name = "scripted"

    def __init__(self, responses):
        self._responses = list(responses)
        self.seen = []

    async def generate(self, messages, tools=None):
        self.seen.append(list(messages))
        return self._responses.pop(0)


def reply(text):
    return LLMResponse(text=text, provider="scripted", model="fake")


def wants(**args):
    call = ToolCall(id="c1", name="send_email", arguments=args)
    return LLMResponse(text="", provider="scripted", model="fake", tool_calls=(call,))


def make_agent(responses, max_rounds=5):
    received = []

    async def send(args: EmailArgs):
        received.append(args)
        return {"status": "sent", "to": args.to_email}

    tools = ToolRegistry([Tool("send_email", "Send an email", EmailArgs, send)])
    provider = ScriptedProvider(responses)
    agent = PIIAgent(
        PIIShield(StubDetector(KNOWN)), provider, tools, max_tool_rounds=max_rounds
    )
    return agent, provider, received


def everything_llm_saw(provider) -> str:
    chunks = []
    for messages in provider.seen:
        for m in messages:
            chunks.append(m.content)
            chunks.extend(json.dumps(c.arguments) for c in m.tool_calls)
    return "\n".join(chunks)


async def test_tool_gets_real_values_and_llm_sees_only_tokens():
    agent, provider, received = make_agent(
        [
            wants(to_email="<EMAIL_ADDRESS_1>", body="Hi <PERSON_1>"),
            reply("Sent to <EMAIL_ADDRESS_1>, <PERSON_1>."),
        ]
    )
    result = await agent.run("I'm Dipak, email me at dipak@example.com", TokenVault())

    # the tool executed with real values
    assert received[0].to_email == "dipak@example.com"
    assert received[0].body == "Hi Dipak"
    # the user sees real values
    assert result.reply == "Sent to dipak@example.com, Dipak."
    # the LLM never saw any (including the tool result, which was re-tokenized)
    seen = everything_llm_saw(provider)
    assert "Dipak" not in seen and "dipak@example.com" not in seen
    # and the persisted history is tokens only
    stored = "\n".join(m.content for m in result.history)
    assert "Dipak" not in stored and "dipak@example.com" not in stored
    assert result.llm_query == "I'm <PERSON_1>, email me at <EMAIL_ADDRESS_1>"


async def test_credit_card_never_reaches_llm_or_history():
    agent, provider, _ = make_agent([])
    result = await agent.run(f"my card is {CARD}", TokenVault())
    assert result.blocked
    assert provider.seen == []
    assert result.history == []
    assert CARD not in result.reply


async def test_unresolved_placeholder_does_not_run_the_tool():
    agent, provider, received = make_agent(
        [
            wants(to_email="<EMAIL_ADDRESS_9>", body="hi"),
            reply("Sorry, I need your email."),
        ]
    )
    result = await agent.run("hello", TokenVault())
    assert received == []
    assert result.reply == "Sorry, I need your email."
    assert "unknown placeholder" in provider.seen[1][-1].content


async def test_invalid_arguments_are_reported_not_raised():
    agent, provider, received = make_agent(
        [wants(wrong_field=1), reply("Let me retry.")]
    )
    await agent.run("hello", TokenVault())
    assert received == []
    assert "invalid arguments" in provider.seen[1][-1].content


async def test_tool_round_limit_ends_the_loop_cleanly():
    agent, _, received = make_agent(
        [
            wants(to_email="<EMAIL_ADDRESS_1>", body="a"),
            wants(to_email="<EMAIL_ADDRESS_1>", body="b"),
        ],
        max_rounds=1,
    )
    result = await agent.run("email me at dipak@example.com", TokenVault())
    assert len(received) == 1
    assert result.reply == LIMIT_REPLY
    assert result.history[-1].role == "assistant"


async def test_leaked_pii_in_final_reply_is_retokenized_in_history():
    agent, _, _ = make_agent([reply("Your email dipak@example.com is saved")])
    result = await agent.run("hello", TokenVault())
    assert "dipak@example.com" not in result.history[-1].content
    assert "dipak@example.com" in result.reply  # restored for display only
    assert any(e.kind == "leak_retokenized" for e in result.trace)
