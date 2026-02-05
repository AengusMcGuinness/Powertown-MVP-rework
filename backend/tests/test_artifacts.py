# backend/tests/test_artifacts.py
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_text_artifact_requires_association(client):
    r = client.post("/artifacts/text", data={"text_content": "hello"})
    assert r.status_code == 400

def test_create_text_artifact(client):
    # First create a park + building through your routes (if available),
    # or insert directly in DB if you prefer.
    # If you have park/building endpoints, use them here.

    # For now: assuming building_id=1 exists in seeded DB; adapt.
    r = client.post("/artifacts/text", data={"text_content": "hello", "building_id": 1})
    assert r.status_code in (200, 201)
    payload = r.json()
    assert payload["kind"] == "text"
    assert payload["text_content"] == "hello"
