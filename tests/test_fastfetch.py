from finscrape.scrapers import fastfetch


def test_connection_drop_falls_back_to_plain_client(monkeypatch):
    def dropped(*args, **kwargs):
        raise fastfetch.curl_requests.exceptions.ConnectionError(
            "curl: (56) Connection closed abruptly"
        )

    class Resp:
        content = b"<rss/>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(fastfetch.curl_requests, "get", dropped)
    monkeypatch.setattr(fastfetch.requests, "get", lambda url, timeout: Resp())
    assert fastfetch.fast_get("https://example.org/rss", use_cache=False) == b"<rss/>"
