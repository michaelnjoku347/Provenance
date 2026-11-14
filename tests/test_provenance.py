import base64

import pytest
from fastapi.testclient import TestClient

from app import credentials, samples
from app.main import app


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    for name in (
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "YDC_API_KEY",
        "TREG_API_KEY",
        "XDC_AI_KEY",
        "XDC_PAYTO",
        "YDC_USE_RESEARCH",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("PROVENANCE_CACHE_DIR", str(tmp_path / "cache"))


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_and_homepage(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "Provenance" in page.text
    assert "Drop a viral image" in page.text
    health = client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["ok"] is True
    assert body["keys"]["youcom"] is False
    assert body["keys"]["xdc_ai"] is False


def test_demos_list_three_samples(client):
    body = client.get("/api/demos").json()
    assert [item["id"] for item in body["demos"]] == ["wire", "synthetic", "archive"]
    image = client.get("/api/demos/synthetic/image")
    assert image.status_code == 200
    assert image.content[:3] == b"\xff\xd8\xff"


def test_samples_fall_back_without_network(client, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("network should not be called without keys")

    monkeypatch.setattr("app.httputil.post_json", boom)
    archive = client.post("/api/check", json={"demo_id": "archive"})
    synthetic = client.post("/api/check", json={"demo_id": "synthetic"})
    wire = client.post("/api/check", json={"demo_id": "wire"})
    assert archive.status_code == 200
    assert archive.json()["verdict"] == "Out of Context"
    assert any("2011" in event["at"] for event in archive.json()["timeline"])
    assert synthetic.json()["verdict"] == "Likely AI or Fake"
    assert wire.json()["verdict"] == "Unverified"
    for response in (archive, synthetic, wire):
        payload = response.json()
        assert 3 <= len(payload["clues"]) <= 4
        assert payload["stages"]["youcom_search"]["status"] == "skipped"
        assert payload["stages"]["reverse_image"]["status"] == "skipped"
        assert payload["cache"]["hit"] is False


def test_second_check_is_cached(client, monkeypatch):
    calls = {"n": 0}

    def boom(*args, **kwargs):
        calls["n"] += 1
        raise AssertionError("network")

    monkeypatch.setattr("app.httputil.post_json", boom)
    first = client.post("/api/check", json={"demo_id": "synthetic"})
    second = client.post("/api/check", json={"demo_id": "synthetic"})
    assert first.json()["cache"]["hit"] is False
    assert second.json()["cache"]["hit"] is True
    assert second.json()["verdict"] == "Likely AI or Fake"
    assert calls["n"] == 0


def test_youcom_corroboration_and_json_upload(client, monkeypatch):
    monkeypatch.setenv("YDC_API_KEY", "test-key")

    def fake_post(url, headers, payload, timeout=30.0):
        assert headers["X-API-Key"] == "test-key"
        if url.endswith("/v1/search"):
            assert payload["count"] == 10
            assert payload["extraction"]["extraction_mode"] == "highlights"
            assert payload["knowledge"] == "core"
            return 200, {
                "results": {
                    "web": [
                        {
                            "url": "https://www.reuters.com/world/city-hall-crowd-2026-11-14/",
                            "title": "Crowd gathers at city hall after transit announcement",
                            "page_age": "2026-11-14T12:00:00",
                            "contents": {
                                "highlights": [
                                    "Reporters described a crowd outside city hall after the morning transit announcement."
                                ]
                            },
                        },
                        {
                            "url": "https://apnews.com/article/city-hall-transit",
                            "title": "AP: City hall crowd follows transit announcement",
                            "page_age": "2026-11-14T13:00:00",
                            "contents": {"highlights": ["The Associated Press reported the gathering this morning."]},
                        },
                    ]
                }
            }
        if url.endswith("/v1/contents"):
            assert payload["urls"]
            return 200, {
                "results": [
                    {
                        "url": "https://www.reuters.com/world/city-hall-crowd-2026-11-14/",
                        "markdown": "Reuters reported the crowd outside city hall this morning.",
                        "metadata": {"title": "Reuters"},
                    }
                ]
            }
        if url.endswith("/v1/answer"):
            return 200, {
                "answer": "Multiple news outlets are reporting a crowd outside city hall this morning.",
                "citations": [
                    {
                        "source": "https://www.reuters.com/world/city-hall-crowd-2026-11-14/",
                        "excerpts": ["Reuters reported the crowd this morning."],
                    }
                ],
            }
        raise AssertionError(url)

    monkeypatch.setattr("app.httputil.post_json", fake_post)
    samples.ensure()
    image = samples.get("wire")["bytes"]
    response = client.post(
        "/api/check",
        json={
            "image_base64": base64.b64encode(image).decode("ascii"),
            "claim": "A crowd gathered outside city hall this morning after a surprise transit announcement.",
            "filename": "wire.jpg",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "Likely Real"
    assert any(source["url"].startswith("https://www.reuters.com/") for source in body["sources"])
    assert any(clue["url"].startswith("https://") for clue in body["clues"])
    assert body["stages"]["youcom_search"]["status"] == "ok"
    assert body["stages"]["youcom_answer"]["status"] == "ok"


def test_treg_reverse_image_is_optional(client, monkeypatch):
    monkeypatch.setenv("TREG_API_KEY", "treg-test")

    def fake_post(url, headers, payload, timeout=30.0):
        assert url == "https://treg.to/call/serper.google.serp.lens"
        assert headers["X-Treg-Token"] == "treg-test"
        assert payload["url"].startswith("https://")
        return 200, {
            "organic": [
                {
                    "title": "Downtown flood, March 2011",
                    "link": "https://example.com/2011-flood",
                    "date": "2011-03-12",
                }
            ]
        }

    monkeypatch.setattr("app.httputil.post_json", fake_post)
    skipped = client.post("/api/check", json={"demo_id": "archive"})
    assert skipped.json()["stages"]["reverse_image"]["status"] == "skipped"
    found = client.post(
        "/api/check",
        json={"demo_id": "archive", "image_url": "https://cdn.example.com/flood.jpg"},
    )
    body = found.json()
    assert body["stages"]["reverse_image"]["status"] == "ok"
    assert any(source["url"] == "https://example.com/2011-flood" for source in body["sources"])
    assert body["verdict"] == "Out of Context"


def test_c2pa_marker_is_a_generative_clue():
    data = b"\xff\xd8\xff\xe0c2pa claim_generator OpenAI\xff\xd9"
    info = credentials.inspect(data)
    assert info["c2pa"]["present"] is True
    assert info["c2pa"]["generative"] is True


def test_x402_paywall(client, monkeypatch):
    open_gate = client.post("/api/x402/check", json={"demo_id": "synthetic"})
    assert open_gate.status_code == 200
    assert open_gate.json()["payment"]["status"] == "paywall_off"
    listing = client.get("/api/x402/listing").json()
    assert listing["method"] == "POST"
    assert listing["asset"] == "0xfA2958CB79b0491CC627c1557F441eF849Ca8eb1"
    assert listing["paywallReady"] is False

    monkeypatch.setenv("XDC_AI_KEY", "flag")
    monkeypatch.setenv("XDC_PAYTO", "0x1111111111111111111111111111111111111111")
    challenge = client.post("/api/x402/check", json={"demo_id": "synthetic"})
    assert challenge.status_code == 402
    body = challenge.json()
    assert body["accepts"][0]["scheme"] == "exact"
    assert body["accepts"][0]["network"] == "xdc"
    assert body["accepts"][0]["maxAmountRequired"] == "20000"
    assert body["accepts"][1]["network"] == "eip155:50"
    discover = client.get("/api/x402/check")
    assert discover.status_code == 402

    token = base64.b64encode(b'{"x402":"demo-authorization"}').decode("ascii")
    paid = client.post(
        "/api/x402/check",
        json={"demo_id": "synthetic"},
        headers={"X-PAYMENT": token},
    )
    assert paid.status_code == 200
    assert paid.json()["payment"]["status"] == "accepted_unsettled"
    assert paid.json()["verdict"] == "Likely AI or Fake"
    assert "does not settle" in paid.json()["payment"]["detail"]


def test_bad_requests(client):
    assert client.post("/api/check", json={}).status_code == 400
    assert client.post("/api/check", json={"demo_id": "nope"}).status_code == 400
    assert client.post("/api/check", json={"image_base64": "!!!!"}).status_code == 400
