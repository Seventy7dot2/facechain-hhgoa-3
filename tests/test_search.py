from facechain.search import (
    _parse_social_candidates,
    extract_identity_hint,
    extract_social_profiles,
    is_social_url,
    sanitize_search_payload,
)


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


def test_extracts_entity_and_associated_social_profiles() -> None:
    lens_payload = {
        "related_content": [
            {
                "query": "Barack Obama",
                "serpapi_link": (
                    "https://serpapi.com/search.json?engine=google&"
                    "kgmid=%2Fm%2F02mjmr&q=Barack+Obama"
                ),
            }
        ]
    }
    assert extract_identity_hint(lens_payload) == {
        "name": "Barack Obama",
        "kgmid": "/m/02mjmr",
        "source": "google_lens_related_content",
    }

    results = {
        "knowledge_graph": {
            "profiles": [
                {"name": "Twitter", "link": "https://x.com/BarackObama"},
                {
                    "name": "Instagram",
                    "link": "https://instagram.com/barackobama/?hl\\u003den",
                },
                {"name": "Facebook", "link": "https://facebook.com/barackobama"},
            ]
        },
        "organic_results": [
            {"source": "X", "link": "https://x.com/reposter/status/123"},
            {"source": "Medium", "link": "https://barackobama.medium.com/"},
        ],
    }
    profiles = extract_social_profiles(results)
    assert [(item.platform, item.handle, item.confidence) for item in profiles] == [
        ("x", "@BarackObama", "knowledge_graph"),
        ("instagram", "@barackobama", "knowledge_graph"),
        ("facebook", "barackobama", "knowledge_graph"),
        ("medium", "barackobama", "search_result"),
    ]
    assert profiles[1].profile_url == "https://instagram.com/barackobama/?hl=en"
