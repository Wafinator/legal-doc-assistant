import json

from app.agent.tools import execute_tool


def test_search_documents_stems_keyword_variants(db, make_document):
    doc = make_document(
        title="Termination Agreement",
        content=(
            "This agreement sets out the parties' rights. "
            "The terminating clause explains the termination procedure."
        ),
    )

    result = execute_tool("search_documents", {"query": "terminating"}, db)

    payload = json.loads(result.content)
    assert payload["results"]
    assert payload["results"][0]["document_id"] == doc.id


def test_search_documents_filters_by_document_id(db, make_document):
    first = make_document(title="First", content="Termination notice must be sent before suit.")
    second = make_document(title="Second", content="Termination notice must be sent before suit.")

    result = execute_tool(
        "search_documents",
        {"query": "termination", "document_id": first.id},
        db,
    )

    payload = json.loads(result.content)
    assert len(payload["results"]) == 1
    assert payload["results"][0]["document_id"] == first.id


def test_search_documents_returns_empty_list_when_no_hits(db):
    result = execute_tool("search_documents", {"query": "zzzz-not-a-real-term"}, db)

    payload = json.loads(result.content)
    assert payload["results"] == []


def test_search_documents_snippet_wraps_matches_in_markers(db, make_document):
    make_document(title="Services Agreement", content="The agreement requires notice before termination.")

    result = execute_tool("search_documents", {"query": "agreement"}, db)

    payload = json.loads(result.content)
    assert payload["results"]
    assert "**" in payload["results"][0]["snippet"]
