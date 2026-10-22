"""Integration tests for the document upload, list and get endpoints."""

from datetime import datetime

import pytest

MISSING_ID = 999_999


def make_doc(client, title="Sample Contract", content="This agreement is made between A and B."):
    """Small helper so each test does not repeat the POST boilerplate."""
    response = client.post("/documents", json={"title": title, "content": content})
    assert response.status_code == 201, response.text
    return response.json()


# Upload

def test_upload_returns_201_with_document(client):
    title = "Lease Agreement"
    content = "The tenant agrees to pay rent on the first of each month."

    response = client.post("/documents", json={"title": title, "content": content})

    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert body["title"] == title
    assert body["content"] == content
    assert body["char_count"] == len(content)
    # created_at must be present and parse as a real timestamp
    datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))


def test_upload_is_stored_and_readable(client):
    created = make_doc(client, title="NDA", content="Confidential information shall not be disclosed.")

    response = client.get(f"/documents/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


# Validation

@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"content": "some text"}, id="missing_title"),
        pytest.param({"title": "   ", "content": "some text"}, id="whitespace_title"),
        pytest.param({"title": "a" * 201, "content": "some text"}, id="title_too_long"),
        pytest.param({"title": "Valid", "content": ""}, id="empty_content"),
        pytest.param({"title": "Valid", "content": "a" * 500_001}, id="content_too_long"),
        pytest.param({"title": "Valid", "content": "some text", "author": "me"}, id="unknown_field"),
    ],
)
def test_upload_invalid_payload_returns_422(client, payload):
    response = client.post("/documents", json=payload)

    assert response.status_code == 422


# List

def test_list_leaves_out_content(client):
    make_doc(client, title="First")
    make_doc(client, title="Second")

    response = client.get("/documents")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    for item in items:
        assert "content" not in item


def test_list_is_newest_first_and_pages(client):
    first = make_doc(client, title="First")
    second = make_doc(client, title="Second")
    third = make_doc(client, title="Third")

    page_one = client.get("/documents", params={"limit": 2, "offset": 0})
    page_two = client.get("/documents", params={"limit": 2, "offset": 2})

    assert page_one.status_code == 200
    assert page_two.status_code == 200

    page_one_ids = [item["id"] for item in page_one.json()["items"]]
    page_two_ids = [item["id"] for item in page_two.json()["items"]]

    assert page_one_ids == [third["id"], second["id"]]
    assert page_two_ids == [first["id"]]
    assert page_one.json()["total"] == 3
    assert page_two.json()["total"] == 3


@pytest.mark.parametrize("limit", [0, 101])
def test_list_invalid_limit_returns_422(client, limit):
    response = client.get("/documents", params={"limit": limit})

    assert response.status_code == 422


# Get

def test_get_unknown_id_returns_404(client):
    response = client.get(f"/documents/{MISSING_ID}")

    assert response.status_code == 404


# Isolation
# Each test creates exactly one document. If the reset fixture stopped
# truncating between tests, whichever runs second would see total == 2.

def test_isolation_first(client):
    make_doc(client, title="Isolation A")

    response = client.get("/documents")

    assert response.json()["total"] == 1


def test_isolation_second(client):
    make_doc(client, title="Isolation B")

    response = client.get("/documents")

    assert response.json()["total"] == 1
