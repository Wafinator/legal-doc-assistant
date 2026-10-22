import json

from app.agent.events import Done, ToolCall, ToolResultEvent, Token
from app.agent.loop import run_agent
from tests.fakes import FakeLLMClient, text_turn, tool_turn


def test_agent_search_then_section_then_answer(db, make_document):
    doc = make_document(
        title="Master Services Agreement",
        content=(
            "8. TERMINATION\n"
            "Either party may terminate this Agreement for convenience on sixty (60) days' written notice."
        ),
    )

    fake = FakeLLMClient(
        [
            tool_turn(
                "search_documents",
                {"query": "termination"},
                tool_use_id="toolu_1",
            ),
            tool_turn(
                "get_section",
                {"document_id": doc.id, "heading": "8. TERMINATION"},
                tool_use_id="toolu_2",
            ),
            text_turn("The agreement allows either party to terminate with 60 days' notice.")
            ,
        ]
    )

    events = list(run_agent("What does the agreement say about termination?", fake, db, max_steps=6))

    assert [type(event) for event in events] == [
        ToolCall,
        ToolResultEvent,
        ToolCall,
        ToolResultEvent,
        Token,
        Done,
    ]
    assert events[0].id == "toolu_1"
    assert events[1].id == "toolu_1"
    assert events[2].id == "toolu_2"
    assert events[3].id == "toolu_2"

    messages = fake.calls[-1]["messages"]
    roles = [message["role"] for message in messages]
    assert roles == ["user", "assistant", "user", "assistant", "user"]

    tool_use_ids = [
        block["id"]
        for message in messages
        if message["role"] == "assistant"
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]
    tool_result_ids = [
        block["tool_use_id"]
        for message in messages
        if message["role"] == "user"
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert tool_use_ids == ["toolu_1", "toolu_2"]
    assert tool_result_ids == ["toolu_1", "toolu_2"]

    assert events[-1].stop_reason == "answered"
    assert events[-1].steps == 3
    assert "termination" in events[-2].text.lower()


def test_agent_stops_after_max_steps(db, make_document):
    make_document(
        title="Services Agreement",
        content="8. TERMINATION\nEither party may terminate this Agreement.",
    )

    fake = FakeLLMClient(
        [
            tool_turn("search_documents", {"query": "termination"}, tool_use_id="toolu_1"),
            tool_turn("search_documents", {"query": "notice"}, tool_use_id="toolu_2"),
        ]
    )

    events = list(run_agent("What does the agreement say?", fake, db, max_steps=2))

    assert len(fake.calls) == 2
    assert events[-1].stop_reason == "max_steps"
    assert events[-1].steps == 2
    assert [type(event) for event in events[-2:]] == [ToolResultEvent, Done]
