import base64

import pytest
from fastapi.testclient import TestClient

from app import credentials, samples, sponsors
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
    sponsors.reset()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_and_homepage(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "Provenance" in page.text
    assert "Check a claim" in page.text
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
    assert archive.json()["verdict"] == "Misleading or Out of Context"
    assert any("2011" in event["at"] for event in archive.json()["timeline"])
    assert synthetic.json()["verdict"] == "Unverified"
    assert any(item["bucket"] == "weak" for item in synthetic.json()["contributions"])
    assert all(item["bucket"] != "fake" for item in synthetic.json()["contributions"])
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
    assert second.json()["verdict"] == "Unverified"
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
    assert body["verdict"] == "True"
    assert any(source["url"].startswith("https://www.reuters.com/") for source in body["sources"])
    assert any(clue["url"].startswith("https://") for clue in body["clues"])
    assert body["stages"]["youcom_search"]["status"] == "ok"
    assert body["stages"]["youcom_answer"]["status"] == "ok"


def test_treg_reverse_image_is_optional(client, monkeypatch):
    monkeypatch.setenv("TREG_API_KEY", "treg-test")

    def fake_get(url, headers=None, timeout=20.0):
        if "catalog/search" in url:
            return 200, {"tools": []}
        assert url.startswith("https://treg.to/call/serper.google.serp.lens?url=")
        assert headers["X-Treg-Token"] == "treg-test"
        assert "cdn.example.com" in url
        return 200, {
            "organic": [
                {
                    "title": "Downtown flood, March 2011",
                    "link": "https://example.com/2011-flood",
                    "date": "2011-03-12",
                }
            ]
        }

    monkeypatch.setattr("app.httputil.get_json", fake_get)
    monkeypatch.setattr("app.httputil.post_json", lambda *args, **kwargs: (200, {"output": {"results": []}}))
    skipped = client.post("/api/check", json={"demo_id": "archive"})
    assert skipped.json()["stages"]["reverse_image"]["status"] == "skipped"
    found = client.post(
        "/api/check",
        json={"demo_id": "archive", "image_url": "https://cdn.example.com/flood.jpg"},
    )
    body = found.json()
    assert body["stages"]["reverse_image"]["status"] == "ok"
    assert any(source["url"] == "https://example.com/2011-flood" for source in body["sources"])
    assert body["verdict"] == "Misleading or Out of Context"


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
    assert paid.json()["verdict"] == "Unverified"
    assert "does not settle" in paid.json()["payment"]["detail"]


def test_bad_requests(client):
    assert client.post("/api/check", json={}).status_code == 400
    assert client.post("/api/check", json={"demo_id": "nope"}).status_code == 400
    assert client.post("/api/check", json={"image_base64": "!!!!"}).status_code == 400


def test_old_exif_beats_generic_topical_news(client, monkeypatch):
    monkeypatch.setenv("YDC_API_KEY", "test-key")

    def fake_post(url, headers, payload, timeout=30.0):
        if url.endswith("/v1/search"):
            return 200, {
                "results": {
                    "web": [
                        {
                            "url": "https://apnews.com/article/georgia-flooding",
                            "title": "Storms cause flooding in Tennessee and Georgia",
                            "page_age": "2026-11-14T12:00:00",
                            "contents": {
                                "highlights": ["Severe flooding downtown after heavy rain."]
                            },
                        },
                        {
                            "url": "https://www.reuters.com/world/floods",
                            "title": "Flooding downtown after storms",
                            "page_age": "2026-11-14T13:00:00",
                            "contents": {
                                "highlights": ["Downtown flooding was reported this morning."]
                            },
                        },
                    ]
                }
            }
        if url.endswith("/v1/contents"):
            return 200, {"results": []}
        if url.endswith("/v1/answer"):
            return 200, {
                "answer": "Multiple outlets are reporting flooding downtown this morning.",
                "citations": [],
            }
        raise AssertionError(url)

    monkeypatch.setattr("app.httputil.post_json", fake_post)
    body = client.post("/api/check", json={"demo_id": "archive"}).json()
    assert body["verdict"] == "Misleading or Out of Context"
    titles = [item["title"] for item in body["contributions"]]
    assert "Capture date contradicts the claim" in titles
    assert "Topical news not counted as confirmation" in titles
    assert all(item["points"] != 40 or item["bucket"] != "real" for item in body["contributions"])


def test_meta_lists_accepted_types_and_domains(client):
    body = client.get("/api/meta").json()
    assert body["accepted"]["formats"] == ["JPEG", "PNG", "WebP"]
    assert body["accepted"]["max_mb"] == 8
    assert "reuters.com" in body["credible_domains"]
    assert "snopes.com" in body["factcheck_domains"]
    assert any("x.com" in item.lower() or "twitter" in item.lower() for item in body["accepted"]["links"])


def test_check_stream_emits_stages_and_result(client):
    with client.stream("POST", "/api/check/stream", json={"demo_id": "archive"}) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        raw = b"".join(response.iter_bytes()).decode("utf-8")
    assert "event: stage" in raw
    assert "event: result" in raw
    assert "Out of Context" in raw
    assert "Reading the file" in raw or "Read EXIF" in raw


def test_receipt_explains_limits_and_next_steps(client):
    body = client.post("/api/check", json={"demo_id": "archive"}).json()
    assert body["verdict"] == "Misleading or Out of Context"
    assert "image itself wasn't read" in body["confidence_note"]
    assert any(note["id"] == "no_vision" for note in body["caveats"])
    groups = body["evidence_groups"]
    assert any(item["title"] == "Capture date contradicts the claim" for item in groups["toward_fake_or_ooc"])
    assert any(item["title"] == "Reverse image search" for item in groups["couldnt_check"])
    titles = [step["title"] for step in body["next_steps"]]
    assert "Run a reverse image search" in titles
    assert "Compare the dates" in titles


def test_feedback_is_recorded(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROVENANCE_CACHE_DIR", str(tmp_path / "cache"))
    from app import config

    body = client.post("/api/check", json={"demo_id": "synthetic"}).json()
    response = client.post(
        "/api/feedback",
        json={
            "receipt_id": body["receipt_id"],
            "verdict": body["verdict"],
            "reason": "disagree",
            "expected": "True",
            "note": "This looks like a real photo to me.",
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    lines = (config.cache_dir() / "feedback.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert "This looks like a real photo to me." in lines[0]


def test_claim_without_image_is_checked(client, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("network should not be called without keys")

    monkeypatch.setattr("app.httputil.post_json", boom)
    monkeypatch.setattr("app.httputil.get_json", boom)
    body = client.post("/api/check", json={"claim": "The mayor resigned on live television this morning."}).json()
    assert body["verdict"] == "Unverified"
    assert body["claim"]["text"].startswith("The mayor resigned")
    assert body["stages"]["youcom_search"]["status"] == "skipped"


def test_sources_that_contradict_the_claim_are_false(client, monkeypatch):
    monkeypatch.setenv("YDC_API_KEY", "test-key")

    def fake_post(url, headers, payload, timeout=30.0):
        if url.endswith("/v1/search"):
            return 200, {
                "results": {
                    "web": [
                        {
                            "url": "https://www.reuters.com/world/mayor-did-not-resign",
                            "title": "Mayor did not resign",
                            "page_age": "2026-11-14T12:00:00",
                            "contents": {
                                "highlights": [
                                    "There is no evidence this happened. The resignation post was fabricated."
                                ]
                            },
                        }
                    ]
                }
            }
        if url.endswith("/v1/contents"):
            return 200, {"results": []}
        if url.endswith("/v1/answer"):
            return 200, {"answer": "", "citations": []}
        raise AssertionError(url)

    monkeypatch.setattr("app.httputil.post_json", fake_post)
    body = client.post(
        "/api/check",
        json={"claim": "The mayor resigned on live television this morning."},
    ).json()
    assert body["verdict"] == "False"
    assert any(item["title"] == "Coverage calls it false" for item in body["contributions"])


_TWEET_HTML = (
    '<blockquote class="twitter-tweet"><p lang="en" dir="ltr">'
    "This photo was taken this morning of flooding downtown. "
    '<a href="https://t.co/abc">pic.twitter.com/abc</a></p>'
    '&mdash; Metro Desk (@metro) '
    '<a href="https://twitter.com/metro/status/99">March 11, 2011</a></blockquote>'
    '<img src="https://pbs.twimg.com/media/flood.jpg" />'
)


def test_x_status_url_supplies_the_claim_and_date(client, monkeypatch):
    def fake_get(url, headers=None, timeout=20.0):
        assert url.startswith("https://publish.twitter.com/oembed?url=")
        assert "x.com" in url or "twitter.com" in url
        return 200, {
            "author_name": "Metro Desk",
            "author_url": "https://twitter.com/metro",
            "html": _TWEET_HTML,
            "url": "https://twitter.com/metro/status/99",
        }

    monkeypatch.setattr("app.httputil.get_json", fake_get)
    body = client.post("/api/check", json={"image_url": "https://x.com/metro/status/99"}).json()
    assert body["verdict"] == "Misleading or Out of Context"
    assert body["claim"]["text"].startswith("This photo was taken this morning")
    assert body["link"]["kind"] == "status"
    assert body["link"]["author"] == "Metro Desk"
    assert body["link"]["posted_at"].startswith("2011-03-11")
    assert body["link"]["image_url"] == "https://pbs.twimg.com/media/flood.jpg"
    assert any(item["title"] == "Post date contradicts the claim" for item in body["contributions"])
    assert body["stages"]["link"]["status"] == "ok"


def test_x_oembed_failure_still_returns_a_receipt(client, monkeypatch):
    def fake_get(url, headers=None, timeout=20.0):
        raise RuntimeError("oembed down")

    monkeypatch.setattr("app.httputil.get_json", fake_get)
    response = client.post(
        "/api/check",
        json={
            "image_url": "https://twitter.com/metro/status/99",
            "claim": "A crowd gathered outside city hall this morning.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "Unverified"
    assert body["link"]["status"] == "error"
    assert body["claim"]["text"].startswith("A crowd gathered")
    assert "oEmbed" in body["link"]["detail"] or "could not" in body["link"]["detail"].lower()


def test_article_link_uses_youcom_contents_as_the_claim(client, monkeypatch):
    monkeypatch.setenv("YDC_API_KEY", "test-key")
    seen = {"contents": []}

    def fake_post(url, headers, payload, timeout=30.0):
        if url.endswith("/v1/contents"):
            seen["contents"].append(list(payload.get("urls") or []))
            if payload.get("urls") == ["https://www.reuters.com/world/city-hall-crowd"]:
                return 200, {
                    "results": [
                        {
                            "url": "https://www.reuters.com/world/city-hall-crowd",
                            "markdown": "Reporters described a crowd outside city hall after the morning transit announcement.",
                            "metadata": {"title": "Crowd gathers at city hall"},
                        }
                    ]
                }
            return 200, {"results": []}
        if url.endswith("/v1/search"):
            return 200, {"results": {"web": []}}
        if url.endswith("/v1/answer"):
            return 200, {"answer": "", "citations": []}
        raise AssertionError(url)

    monkeypatch.setattr("app.httputil.post_json", fake_post)
    body = client.post(
        "/api/check",
        json={"image_url": "https://www.reuters.com/world/city-hall-crowd"},
    ).json()
    assert body["link"]["kind"] == "article"
    assert body["link"]["status"] == "ok"
    assert body["link"]["title"] == "Crowd gathers at city hall"
    assert body["claim"]["text"].startswith("Crowd gathers at city hall")
    assert ["https://www.reuters.com/world/city-hall-crowd"] in seen["contents"]


def test_article_link_falls_back_to_the_page_title(client, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("You.com should not be called without a key")

    def fake_text(url, timeout=15.0):
        assert url == "https://www.reuters.com/world/city-hall-crowd"
        return 200, "<html><head><title>Crowd gathers at city hall</title><meta name='description' content='Reporters described a crowd outside city hall.'></head></html>"

    monkeypatch.setattr("app.httputil.post_json", boom)
    monkeypatch.setattr("app.httputil.get_text", fake_text)
    body = client.post(
        "/api/check",
        json={"image_url": "https://www.reuters.com/world/city-hall-crowd"},
    ).json()
    assert body["link"]["status"] == "ok"
    assert body["claim"]["text"].startswith("Crowd gathers at city hall")
    assert "Reporters described a crowd" in body["claim"]["text"]


def test_sponsors_endpoint_lists_tools_and_test_mode(client):
    body = client.get("/api/sponsors").json()
    assert body["youcom"]["connected"] is False
    assert body["treg"]["connected"] is False
    assert body["treg"]["hint"] == "Treg: add key"
    assert body["x402"]["mode"] == "test"
    assert body["x402"]["price_usdc"] == "0.02"
    assert body["opencrawl"]["runtime"] is False
    assert "getopencrawl.com" in body["opencrawl"]["detail"]


def test_receipt_records_youcom_stats_and_source_tool(client, monkeypatch):
    monkeypatch.setenv("YDC_API_KEY", "test-key")

    def fake_post(url, headers, payload, timeout=30.0):
        if url.endswith("/v1/search"):
            return 200, {
                "results": {
                    "web": [
                        {
                            "url": "https://www.reuters.com/world/city-hall-crowd-2026-11-14/",
                            "title": "Crowd gathers at city hall",
                            "page_age": "2026-11-14T12:00:00",
                            "contents": {"highlights": ["Reporters described a crowd outside city hall this morning."]},
                        },
                        {
                            "url": "https://apnews.com/article/city-hall-transit",
                            "title": "AP: City hall crowd",
                            "page_age": "2026-11-14T13:00:00",
                            "contents": {"highlights": ["The Associated Press reported the gathering this morning."]},
                        },
                    ]
                }
            }
        if url.endswith("/v1/contents"):
            return 200, {
                "results": [
                    {
                        "url": "https://www.reuters.com/world/city-hall-crowd-2026-11-14/",
                        "markdown": "Reuters reported the crowd outside city hall this morning in detail.",
                        "metadata": {"title": "Reuters"},
                    }
                ]
            }
        if url.endswith("/v1/answer"):
            return 200, {
                "answer": "Multiple outlets are reporting the crowd this morning.",
                "citations": [{"source": "https://www.bbc.com/news/city-hall", "excerpts": ["BBC reported the crowd."]}],
            }
        raise AssertionError(url)

    monkeypatch.setattr("app.httputil.post_json", fake_post)
    body = client.post("/api/check", json={"claim": "A crowd gathered outside city hall this morning."}).json()
    search = body["sponsors"]["youcom_search"]
    assert search["status"] == "ok"
    assert search["results"] == 2
    assert isinstance(search["latency_ms"], int)
    assert body["sponsors"]["youcom_contents"]["pages"] == 1
    assert body["sponsors"]["youcom_answer"]["citations"] == 1
    assert body["sponsors"]["treg"]["detail"] == "Treg: add key"
    assert body["sponsors"]["x402"]["mode"] == "test"
    found = {source["url"]: source["found_by"] for source in body["sources"]}
    assert found["https://www.reuters.com/world/city-hall-crowd-2026-11-14/"] == "You.com Contents"
    assert found["https://apnews.com/article/city-hall-transit"] == "You.com Search"
    assert found["https://www.bbc.com/news/city-hall"] == "You.com Answer"
    session = client.get("/api/sponsors").json()
    assert session["youcom_search"]["calls"] == 1
    assert session["youcom_contents"]["calls"] == 1
    assert session["youcom_answer"]["calls"] == 1


def test_treg_match_is_tagged_and_timed(client, monkeypatch):
    monkeypatch.setenv("TREG_API_KEY", "treg-test")

    def fake_get(url, headers=None, timeout=20.0):
        if "catalog/search" in url:
            return 200, {"tools": []}
        assert "treg.to" in url
        return 200, {"organic": [{"title": "Downtown flood, March 2011", "link": "https://example.com/2011-flood", "date": "2011-03-12"}]}

    monkeypatch.setattr("app.httputil.get_json", fake_get)
    monkeypatch.setattr("app.httputil.post_json", lambda *args, **kwargs: (200, {"output": {"results": []}}))
    body = client.post(
        "/api/check",
        json={"demo_id": "archive", "image_url": "https://cdn.example.com/flood.jpg"},
    ).json()
    assert body["sponsors"]["treg"]["status"] == "ok"
    assert body["sponsors"]["treg"]["matches"] == 1
    assert isinstance(body["sponsors"]["treg"]["latency_ms"], int)
    assert any(source["found_by"] == "Treg Lens" for source in body["sources"])
    assert any(event["label"].startswith("Treg first seen") for event in body["timeline"])
    assert client.get("/api/sponsors").json()["treg"]["calls"] == 1


def test_question_splits_who_and_whether_they_are_divorced():
    from app.questions import split_questions

    parts = split_questions("Are these two divorce and who are these two?")
    kinds = {item["kind"] for item in parts}
    assert kinds == {"identity", "relationship"}


def test_image_question_uses_treg_names_then_youcom(client, monkeypatch):
    monkeypatch.setenv("TREG_API_KEY", "treg-test")
    monkeypatch.setenv("YDC_API_KEY", "test-key")
    seen = {}

    def fake_get(url, headers=None, timeout=20.0):
        if "catalog/search" in url:
            return 200, {"tools": [{"id": "fixture.vision.caption", "description": "image caption vision"}]}
        assert "cafefcdn.com" in url
        return 200, {
            "organic": [
                {
                    "title": "NVIDIA CEO Jensen Huang and his wife Lori Huang",
                    "link": "https://www.reuters.com/technology/jensen-huang-profile",
                    "snippet": "NVIDIA CEO Jensen Huang and his wife Lori Huang.",
                }
            ]
        }

    def fake_post(url, headers, payload, timeout=30.0):
        if "fixture.vision.caption" in url:
            return 200, {"caption": "NVIDIA CEO Jensen Huang standing beside his wife Lori Huang."}
        if url.endswith("/v1/search"):
            seen["query"] = payload["query"]
            return 200, {
                "results": {
                    "web": [
                        {
                            "url": "https://www.reuters.com/technology/jensen-huang-profile",
                            "title": "Jensen Huang, NVIDIA chief executive",
                            "contents": {"highlights": ["Jensen Huang is NVIDIA's CEO. His wife is Lori Huang."]},
                        },
                        {
                            "url": "https://www.bbc.com/news/technology-jensen-huang",
                            "title": "Who is Jensen Huang?",
                            "contents": {"highlights": ["Huang and his wife Lori have been married for decades."]},
                        },
                        {
                            "url": "https://gossip.example/huang-split",
                            "title": "Rumor: Huang divorce?",
                            "contents": {"highlights": ["A rumor says the couple might divorce."]},
                        },
                    ]
                }
            }
        if url.endswith("/v1/contents"):
            return 200, {"results": []}
        if url.endswith("/v1/research"):
            return 200, {
                "output": {
                    "content": '{"names":["Jensen Huang","Lori Huang"],"role":"NVIDIA CEO","relation":"wife","what":""}',
                    "sources": [],
                }
            }
        if url.endswith("/v1/answer"):
            assert len(payload.get("query") or "") <= 400
            return 200, {"answer": "", "citations": []}
        raise AssertionError(url)

    monkeypatch.setattr("app.httputil.get_json", fake_get)
    monkeypatch.setattr("app.httputil.post_json", fake_post)
    monkeypatch.setattr("app.httputil.get_bytes", lambda url, timeout=20.0: (404, b"", ""))
    body = client.post(
        "/api/check",
        json={
            "claim": "Are these two divorce and who are these two?",
            "image_url": "https://cafefcdn.com/thumb_w/1200/203337114487263232/2024/11/25/avatar1732525933296-1732525938744619592903.jpg",
        },
    ).json()
    assert "Jensen Huang" in seen["query"]
    assert "divorce" in seen["query"].lower()
    assert "Jensen Huang" in body["answer"]["text"]
    assert "Lori" in body["answer"]["text"]
    assert "no credible reports they are divorced" in body["answer"]["text"].lower()
    assert "No credible evidence they are divorced" in body["answer"]["line"]
    assert body["answer"]["verdict"] == "False"
    assert len(body["answer"]["why"]) <= 3
    assert 1 <= len(body["answer"]["sources"]) <= 3
    assert body["answer"]["sources"][0]["domain"] in {"reuters.com", "bbc.com"}
    assert body["stages"]["vision"]["status"] == "ok"
    assert "Jensen Huang" in body["claim"]["seen"]


def test_what_car_question_is_identity():
    from app.questions import split_questions

    kinds = {item["kind"] for item in split_questions("what car is this?")}
    assert "identity" in kinds


def test_see_failure_is_reported_and_the_check_continues(client, monkeypatch):
    monkeypatch.setenv("TREG_API_KEY", "treg-test")

    def boom(*args, **kwargs):
        raise RuntimeError("catalog down")

    monkeypatch.setattr("app.httputil.get_json", boom)
    monkeypatch.setattr("app.httputil.post_json", boom)
    monkeypatch.setattr("app.httputil.get_bytes", boom)
    response = client.post(
        "/api/check",
        json={"claim": "what car is this?", "image_url": "https://cdn.example.com/car.jpg"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["stages"]["vision"]["status"] in {"error", "skipped"}
    assert "continued" in body["stages"]["vision"]["detail"].lower()
    assert body["verdict"]


def test_treg_failure_still_returns_a_result(client, monkeypatch):
    monkeypatch.setenv("TREG_API_KEY", "treg-test")

    def boom(*args, **kwargs):
        raise RuntimeError("treg down")

    monkeypatch.setattr("app.httputil.get_json", boom)
    monkeypatch.setattr("app.httputil.post_json", boom)
    monkeypatch.setattr("app.httputil.get_bytes", boom)
    response = client.post(
        "/api/check",
        json={
            "claim": "Who are these two?",
            "image_url": "https://cdn.example.com/people.jpg",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["stages"]["reverse_image"]["status"] == "error"
    assert body["verdict"] == "Unverified"


def test_mojibake_repairs_to_utf8():
    from app.textutil import repair_text

    assert repair_text("Affair\u00e2\u0080\u0094Why") == "Affair\u2014Why"
    assert repair_text("Huang\u00e2\u0080\u0099s") == "Huang\u2019s"


def test_contents_accepts_a_top_level_list():
    from app.youcom import _parse_pages

    pages = _parse_pages(
        [
            {
                "url": "https://www.forbes.com/example",
                "title": "Affair\u00e2\u0080\u0094Why",
                "markdown": "Divorce speculation, not a filing.",
            }
        ]
    )
    assert pages[0]["title"] == "Affair\u2014Why"
    assert pages[0]["url"].endswith("/example")


def test_major_outlets_are_credible_and_gossip_is_not():
    from app.verdict import is_credible, is_rumor, tier

    for url in (
        "https://www.forbes.com/sites/example",
        "https://economictimes.indiatimes.com/news/example",
        "https://www.yahoo.com/lifestyle/example",
        "https://www.mensjournal.com/news/example",
        "https://en.ilsole24ore.com/art/example",
    ):
        assert is_credible(url), url
        assert tier(url) in {1, 2}
    assert is_rumor("https://www.celebitchy.com/example")
    assert not is_credible("https://www.celebitchy.com/example")


def test_frequency_names_skip_publication_fragments():
    from app.questions import frequency_names

    matches = [
        {
            "title": "New Oregon State supercomputer will be like a time machine, NVIDIA CEO Jensen Huang says",
            "snippet": "Oregon Live. He spoke beside his wife Lori Huang.",
        },
        {"title": "Jensen Huang and his wife Lori Huang", "snippet": "NVIDIA CEO Jensen Huang."},
        {"title": "Who is Lori Huang? Jensen Huang's wife", "snippet": ""},
    ]
    names = frequency_names(matches)
    assert names[0] == "Jensen Huang"
    assert "Lori Huang" in names
    assert "Oregon Live He" not in names
    assert "New Oregon State" not in names
    headlines = [
        {"title": "Spouse Helps Launch Nvidia Foundation at Oregon State University", "snippet": "Lori Mills Huang attended."},
        {"title": "nvidia ceo jensen huang and his wife lori huang", "snippet": ""},
        {"title": "Jensen Huang says the new machine is ready", "snippet": "Jensen Huang spoke."},
        {"title": "Who is Lori Huang? Jensen Huang's wife of 40 years", "snippet": ""},
    ]
    ranked = frequency_names(headlines)
    assert ranked[0] == "Jensen Huang"
    assert "Spouse Helps Launch" not in ranked
    assert "Helps Launch" not in ranked
    assert all("Foundation" not in name and "University" not in name and "Spouse" not in name for name in ranked)


def test_answer_queries_stay_within_400_characters(client, monkeypatch):
    monkeypatch.setenv("YDC_API_KEY", "test-key")
    monkeypatch.setenv("TREG_API_KEY", "treg-test")
    seen = {"answer": [], "research": 0}

    def fake_get(url, headers=None, timeout=20.0):
        if "catalog/search" in url:
            return 200, {"tools": []}
        return 200, {"organic": [{"title": "Jensen Huang and his wife Lori Huang", "link": "https://www.reuters.com/huang", "snippet": "Jensen Huang."}]}

    def fake_post(url, headers, payload, timeout=30.0):
        if url.endswith("/v1/search"):
            return 200, {"results": {"web": [{"url": "https://www.reuters.com/huang", "title": "Jensen Huang", "snippets": ["Jensen Huang is NVIDIA's CEO."]}]}}
        if url.endswith("/v1/contents"):
            return 200, []
        if url.endswith("/v1/answer"):
            query = payload.get("query") or ""
            assert len(query) <= 400
            seen["answer"].append(query)
            return 200, {"answer": "Unverified.", "citations": []}
        if url.endswith("/v1/research"):
            seen["research"] += 1
            assert len(payload.get("input") or "") > 400
            return 200, {"output": {"content": '{"people":["Jensen Huang","Lori Huang"]}', "sources": []}}
        raise AssertionError(url)

    monkeypatch.setattr("app.httputil.get_json", fake_get)
    monkeypatch.setattr("app.httputil.post_json", fake_post)
    monkeypatch.setattr("app.httputil.get_bytes", lambda url, timeout=20.0: (404, b"", ""))
    long_claim = "A crowd gathered outside city hall this morning. " + ("detail " * 120)
    statement = client.post("/api/check", json={"claim": long_claim}).json()
    assert statement["verdict"]
    assert seen["answer"]
    assert all(len(query) <= 400 for query in seen["answer"])
    question = client.post(
        "/api/check",
        json={"claim": "Are Jensen Huang and Lori Huang divorced?", "image_url": "https://cdn.example.com/huang.jpg"},
    ).json()
    assert question["sponsors"]["youcom_answer"]["label"] == "You.com Research"
    assert seen["research"] >= 1
    assert all(len(query) <= 400 for query in seen["answer"])


def test_huang_live_fixture_names_the_couple_and_the_speculation(client, monkeypatch):
    """The attached live receipt, replayed through mocked HTTP."""
    import hashlib
    import json
    from pathlib import Path

    live = json.loads(Path("tests/fixtures/huang_live.json").read_text(encoding="utf-8-sig"))
    jpeg = b"\xff\xd8\xff\xd9huang"
    monkeypatch.setenv("YDC_API_KEY", "test-key")
    monkeypatch.setenv("TREG_API_KEY", "treg-test")
    seen = {"catalog": 0, "prompts": []}

    lens = {
        "organic": [
            {
                "title": "New Oregon State supercomputer will be like 'a time machine' NVIDIA CEO Jensen Huang says",
                "link": "https://www.oregonlive.com/silicon-forest/2022/10/new-oregon-state-supercomputer-will-be-like-a-time-machine-nvidia-ceo-jesen-huang-says-qa.html",
                "snippet": "Oregon Live. He says the machine is a time machine. NVIDIA CEO Jensen Huang.",
            },
            {
                "title": "NVIDIA CEO Jensen Huang and his wife Lori Huang",
                "link": "https://www.reuters.com/technology/jensen-huang",
                "snippet": "Jensen Huang with his wife Lori Huang.",
            },
            {
                "title": "Jensen Huang, Nvidia CEO, and Lori Huang",
                "link": "https://www.forbes.com/sites/jensen",
                "snippet": "Lori Huang has been married to Jensen Huang since 1985.",
            },
            {
                "title": "Who is Lori Huang, wife of Jensen Huang?",
                "link": "https://www.bbc.com/news/lori-huang",
                "snippet": "Lori Huang and Jensen Huang.",
            },
            {
                "title": "Jensen Huang family photo with Lori Huang",
                "link": "https://www.bloomberg.com/news/huang",
                "snippet": "NVIDIA CEO Jensen Huang and Lori Huang.",
            },
            {
                "title": "Lori Huang beside Jensen Huang",
                "link": "https://www.cnbc.com/huang",
                "snippet": "Jensen Huang and his wife Lori Huang at an event.",
            },
        ]
    }

    def fake_get(url, headers=None, timeout=20.0):
        if "catalog/search" in url:
            seen["catalog"] += 1
            return 200, {"tools": []}
        assert "serper.google.serp.lens" in url
        return 200, lens

    def fake_post(url, headers, payload, timeout=30.0):
        if url.endswith("/v1/search"):
            seen["query"] = payload["query"]
            web = []
            for source in live["sources"]:
                web.append(
                    {
                        "url": source["url"],
                        "title": source["title"],
                        "page_age": source.get("page_age") or "",
                        "description": source.get("excerpt") or "",
                        "snippets": [source.get("excerpt") or ""],
                    }
                )
            return 200, {"results": {"web": web}}
        if url.endswith("/v1/contents"):
            forbes = live["sources"][1]
            return 200, [
                {
                    "url": forbes["url"],
                    "title": forbes["title"],
                    "markdown": forbes["excerpt"],
                    "metadata": {"site_name": "Forbes"},
                }
            ]
        if url.endswith("/v1/research"):
            prompt = payload.get("input") or ""
            seen["prompts"].append(prompt)
            if "Return one JSON object" in prompt or "people" in prompt:
                return 200, {
                    "output": {
                        "content": '{"people":["Jensen Huang","Lori Huang"],"role":"NVIDIA CEO","relation":"wife","what":""}',
                        "sources": [{"url": "https://www.forbes.com/sites/example", "title": "Forbes", "snippets": ["speculation"]}],
                    }
                }
            if "reverse-image page titles" in prompt:
                return 200, {"output": {"content": "NVIDIA CEO Jensen Huang standing with his wife Lori Huang.", "sources": []}}
            return 200, {"output": {"content": "They are not reported divorced.", "sources": []}}
        if url.endswith("/v1/answer"):
            prompt = payload.get("query") or ""
            assert len(prompt) <= 400
            seen["prompts"].append(prompt)
            return 200, {"answer": "", "citations": []}
        if "generativelanguage" in url:
            raise AssertionError("gemini should not run without a key")
        raise AssertionError(url)

    monkeypatch.setattr("app.httputil.get_json", fake_get)
    monkeypatch.setattr("app.httputil.post_json", fake_post)
    monkeypatch.setattr("app.httputil.get_bytes", lambda url, timeout=20.0: (200, jpeg, "image/jpeg"))
    body = client.post(
        "/api/check",
        json={
            "claim": live["claim"]["text"],
            "image_url": "https://cafefcdn.com/thumb_w/1200/203337114487263232/2024/11/25/avatar1732525933296-1732525938744619592903.jpg",
        },
    ).json()
    expected = (
        "This is NVIDIA CEO Jensen Huang and his wife Lori Huang. "
        "They are not reported divorced; Forbes reports divorce speculation after alleged affairs, "
        "but no filing or announcement."
    )
    assert body["summary"] == expected
    assert body["answer"]["text"] == expected
    assert body["verdict"] == "Unverified"
    assert "Oregon Live" not in body["summary"]
    assert "New Oregon" not in body["summary"]
    assert "Jensen Huang" in seen["query"] and "divorce" in seen["query"].lower()
    assert "Oregon" not in seen["query"]
    assert body["image_sha256"] == hashlib.sha256(jpeg).hexdigest()
    assert body["image_sha256"] != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert body["mode"] == "url"
    assert body["stages"]["youcom_contents"]["status"] == "ok"
    assert "HTTP 200" not in body["stages"]["youcom_contents"]["detail"]
    forbes = next(source for source in body["sources"] if "forbes.com" in source["url"])
    assert forbes["credible"] is True
    assert "\u2014" in forbes["title"]
    assert "\u00e2" not in forbes["title"]
    assert any("JSON" in prompt or "people" in prompt for prompt in seen["prompts"])
    assert body["sponsors"]["youcom_answer"]["label"] == "You.com Research"
    assert body["stages"]["vision"]["status"] == "ok"
    assert "continued" in body["stages"]["vision"]["detail"].lower()


def test_gemini_reads_the_image_when_treg_has_no_vision_tool(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")
    monkeypatch.setenv("TREG_API_KEY", "treg-test")

    def fake_get(url, headers=None, timeout=20.0):
        if "catalog/search" in url:
            return 200, {"tools": []}
        return 200, {"organic": []}

    def fake_post(url, headers, payload, timeout=30.0):
        assert "generativelanguage.googleapis.com" in url
        assert headers.get("x-goog-api-key") == "gemini-test"
        return 200, {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": '{"claim":"This is a Tesla Model S.","who":"","what":"Tesla Model S","where":"","when":"","search_query":"Tesla Model S"}'
                            }
                        ]
                    }
                }
            ]
        }

    monkeypatch.setattr("app.httputil.get_json", fake_get)
    monkeypatch.setattr("app.httputil.post_json", fake_post)
    body = client.post(
        "/api/check",
        json={"claim": "what car is this?", "image_base64": "data:image/jpeg;base64,/9j/4AAQ"},
    ).json()
    assert body["stages"]["vision"]["status"] == "ok"
    assert "Tesla Model S" in body["claim"]["seen"]


def test_treg_news_web_and_x_are_separate_rows(client, monkeypatch):
    monkeypatch.setenv("TREG_API_KEY", "treg-test")
    monkeypatch.setenv("YDC_API_KEY", "test-key")
    seen = {"tools": []}

    def fake_post(url, headers, payload, timeout=30.0):
        if "treg.to/call/" in url:
            tool = url.rsplit("/", 1)[-1]
            seen["tools"].append(tool)
            assert timeout <= 25
            if tool == "treg.google.serp.news":
                return 200, {"output": {"results": [{"title": "Fortune on Jensen Huang", "link": "https://fortune.com/huang", "published_at": "2026-11-14T09:37:00Z", "source": "Fortune"}]}}
            if tool == "treg.google.serp.organic":
                return 200, {"output": {"results": [
                    {"title": "Fortune on Jensen Huang", "url": "https://fortune.com/huang", "snippet": "duplicate"},
                    {"title": "A web page", "url": "https://www.reuters.com/huang-web", "snippet": "Jensen Huang", "date": "2026-11-12"},
                ]}}
            if tool == "treg.x.user.profile":
                assert payload["username"] == "Reuters"
                return 200, {"output": {"username": "Reuters", "name": "Reuters", "followers": 25000000, "is_verified": True, "description": "Top and breaking news."}}
            if tool == "treg.x.post.comments":
                if "tweet_id" not in payload:
                    return 422, {"error": "expected tweet_id"}
                return 200, {"output": {"comments": [{"text": "This claim leaves out the date.", "username": "reader"}]}}
            return 200, {"output": {"results": []}}
        if url.endswith("/v1/search"):
            return 200, {"results": {"web": [{"url": "https://www.reuters.com/huang", "title": "Reuters", "snippets": ["Jensen Huang."]}]}}
        if url.endswith("/v1/contents"):
            return 200, []
        if url.endswith("/v1/answer"):
            assert len(payload.get("query") or "") <= 400
            return 200, {"answer": "", "citations": []}
        if url.endswith("/v1/research"):
            return 200, {"output": {"content": "Noted.", "sources": []}}
        raise AssertionError(url)

    def fake_get(url, headers=None, timeout=20.0):
        if "oembed" in url:
            return 200, {
                "author_name": "Reuters",
                "author_url": "https://x.com/Reuters",
                "html": '<p>Trump tells advisers he may hold off.</p><img src="https://cdn.example.com/photo.jpg">',
            }
        return 200, {
            "output": {
                "knowledge_graph": {"title": "Jensen Huang"},
                "visual_matches": [{"title": "Jensen Huang on stage", "link": "https://www.reuters.com/photo"}],
            }
        }

    monkeypatch.setattr("app.httputil.post_json", fake_post)
    monkeypatch.setattr("app.httputil.get_json", fake_get)
    body = client.post(
        "/api/check",
        json={
            "claim": "Who is this?",
            "image_url": "https://x.com/Reuters/status/2121624210791440863",
        },
    ).json()
    assert "Identified by Treg Google Lens" in body["claim"]["seen"]
    assert "treg.google.serp.news" in seen["tools"]
    assert "treg.google.serp.organic" in seen["tools"]
    found = {source["url"]: source["found_by"] for source in body["sources"]}
    assert found["https://fortune.com/huang"] == "Treg News"
    assert found["https://www.reuters.com/huang-web"] == "Treg Web"
    assert found["https://fortune.com/huang"] != "Treg Web"
    assert body["stages"]["treg_news"]["status"] == "ok"
    assert body["stages"]["treg_web"]["results"] == 2
    assert body["poster"]["verified"] is True
    assert body["poster"]["followers"] == 25000000
    assert body["pushback"][0]["text"].startswith("This claim leaves out")
    assert body["stages"]["reverse_image"]["detail"].startswith("Identified by Treg Google Lens")
