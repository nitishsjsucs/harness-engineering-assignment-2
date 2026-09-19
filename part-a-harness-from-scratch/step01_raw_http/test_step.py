"""Offline test for step 01: httpx.post is replaced by a fake, so no key or network is needed."""
import httpx

import raw_call

FAKE_JSON = {
    "id": "gen-123",
    "model": "google/gemini-3.5-flash",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello from the fake model."}}],
    "usage": {
        "prompt_tokens": 12,
        "completion_tokens": 7,
        "prompt_tokens_details": {"cached_tokens": 4},
        "cost": 0.000042,
    },
}


def test_post_sends_json_and_openrouter_headers(monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, body=json)
        return httpx.Response(200, json=FAKE_JSON, request=httpx.Request("POST", url))

    monkeypatch.setattr(raw_call.httpx, "post", fake_post)

    assert raw_call.main(["hi", "there"]) == 0

    # The whole request is visible: URL, headers, JSON body. Nothing hidden.
    assert seen["url"].endswith("/chat/completions")
    assert seen["headers"]["Authorization"] == "Bearer sk-or-test"
    assert seen["headers"]["HTTP-Referer"].startswith("https://github.com/nitishsjsucs/")
    assert seen["headers"]["X-Title"] == "nanoharness"
    assert seen["body"]["messages"] == [{"role": "user", "content": "hi there"}]

    out = capsys.readouterr().out
    assert "Hello from the fake model." in out
    assert "cached=4" in out and "cost=$0.000042" in out
    assert "sk-or-test" not in out  # the key is masked when we print headers


def test_usage_line_without_openrouter_extras():
    line = raw_call.usage_line({"usage": {"prompt_tokens": 3, "completion_tokens": 1}})
    assert line == "usage: prompt=3 completion=1 cached=0 cost=n/a"


def test_http_error_is_reported_not_raised(monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-bad")
    monkeypatch.setattr(
        raw_call.httpx,
        "post",
        lambda url, **_: httpx.Response(401, text='{"error":"No auth credentials found"}',
                                        request=httpx.Request("POST", url)),
    )
    assert raw_call.main(["hi"]) == 1
    assert "HTTP 401" in capsys.readouterr().err


def test_missing_key_gives_clear_message(monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert raw_call.main(["hi"]) == 2
    assert "set OPENROUTER_API_KEY" in capsys.readouterr().err
