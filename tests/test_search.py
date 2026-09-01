from facechain.search import _parse_social_candidates, is_social_url, sanitize_search_payload


def test_social_domain_filter_uses_hostname_boundaries() -> None:
    assert is_social_url("https://www.instagram.com/p/abc")
    assert is_social_url("https://mobile.x.com/user/status/1")
    assert not is_social_url("https://x.com.attacker.example/post")
    assert not is_social_url("https://example.com/x.com/post")


def test_parses_and_deduplicates_social_results() -> None:
    payload = {
        "visual_matches": [
            {
                "position": 1,
                "title": "A post",
                "link": "https://x.com/person/status/1",
                "source": "X",
                "image": "https://cdn.example/a.jpg",
                "thumbnail": "https://cdn.example/a-small.jpg",
                "exact_matches": True,
            },
            {
                "position": 2,
                "title": "Duplicate",
                "link": "https://x.com/person/status/1",
                "image": "https://cdn.example/a2.jpg",
            },
            {
                "position": 3,
                "title": "Not social",
                "link": "https://example.com/article",
                "image": "https://example.com/image.jpg",
            },
        ]
    }
    candidates = list(_parse_social_candidates(payload))
    assert len(candidates) == 1
    assert candidates[0].exact_match is True
    assert candidates[0].source_url == "https://x.com/person/status/1"


def test_search_sanitization_drops_private_endpoints() -> None:
    payload = {
        "search_parameters": {"api_key": "secret"},
        "search_metadata": {
            "id": "search-1",
            "status": "Success",
            "json_endpoint": "https://example.invalid?api_key=secret",
        },
        "visual_matches": [],
    }
    sanitized = sanitize_search_payload(payload)
    assert "search_parameters" not in sanitized
    assert sanitized["search_metadata"] == {"id": "search-1", "status": "Success"}
