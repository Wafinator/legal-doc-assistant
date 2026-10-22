"""Scaffolding smoke test: proves the app boots and the test database is reachable.

Your own document tests go in tests/integration/test_documents.py.
"""


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
