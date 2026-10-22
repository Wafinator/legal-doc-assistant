"""Integration tests for the streamed /ask endpoint."""

import json
import re

import pytest

from app.llm.client import TextDelta
from tests.fakes import FakeLLMClient, make_status_error, text_turn, tool_turn


def parse_events(response):
    return [
        (event_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: ")))
        for frame in response.text.strip().split("\n\n")
        for event_line, data_line in [frame.splitlines()]
    ]


def test_ask_streams_tool_answer_and_summed_usage(client_with_llm, make_document):
    doc = make_document(title="Services Agreement", content="1. TERM\nThe term is one year.")
    fake = FakeLLMClient(
        [
            tool_turn(
                "get_section",
                {"document_id": doc.id, "heading": "1. TERM"},
                tool_use_id="toolu_ask",
                input_tokens=7,
                output_tokens=3,
            ),
            text_turn(
                "The term ",
                "is one year.",
                input_tokens=11,
                output_tokens=5,
            ),
        ]
    )
    client = client_with_llm(fake)

    response = client.post("/ask", json={"question": "How long is the term?"})

    assert response.status_code == 200
    events = parse_events(response)
    assert [name for name, _ in events] == [
        "tool_call",
        "tool_result",
        "token",
        "token",
        "done",
    ]
    done = events[-1][1]
    assert done["steps"] == 2
    assert done["usage"] == {"input_tokens": 18, "output_tokens": 8}


def test_ask_unknown_document_returns_404_before_streaming(client_with_llm):
    fake = FakeLLMClient([])
    client = client_with_llm(fake)

    response = client.post("/ask", json={"question": "What does this say?", "document_id": 999_999})

    assert response.status_code == 404
    assert fake.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"question": "   "}, id="blank_question"),
        pytest.param({"question": "a" * 2001}, id="question_too_long"),
        pytest.param({}, id="missing_question"),
        pytest.param({"question": "Valid question", "unknown": True}, id="extra_field"),
    ],
)
def test_ask_invalid_input_returns_422(client, payload):
    response = client.post("/ask", json=payload)

    assert response.status_code == 422


def test_ask_streams_error_when_llm_fails_mid_stream(client_with_llm):
    fake = FakeLLMClient([[TextDelta("Partial "), make_status_error(500)]])
    client = client_with_llm(fake)

    response = client.post("/ask", json={"question": "What does this say?"})

    assert response.status_code == 200
    events = parse_events(response)
    assert [name for name, _ in events] == ["token", "error"]
    assert events[-1][1]["code"] == "llm_unavailable"


def test_ask_preserves_valid_request_id(client_with_llm, make_document):
    doc = make_document()
    request_id = "ask.test-123"
    fake = FakeLLMClient([text_turn("Done.")])
    client = client_with_llm(fake)

    response = client.post(
        "/ask",
        json={"question": "What does this say?", "document_id": doc.id},
        headers={"X-Request-ID": request_id},
    )

    assert response.headers["x-request-id"] == request_id


def test_ask_replaces_invalid_request_id(client_with_llm):
    fake = FakeLLMClient([text_turn("Done.")])
    client = client_with_llm(fake)

    response = client.post(
        "/ask",
        json={"question": "What does this say?"},
        headers={"X-Request-ID": "not a valid id"},
    )

    request_id = response.headers["x-request-id"]
    assert request_id != "not a valid id"
    assert re.fullmatch(r"[A-Za-z0-9._-]{1,64}", request_id)
