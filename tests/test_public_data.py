import json

from bs4 import BeautifulSoup

from adwatch.public_data import combine, extract_records, from_soup, parse_payload

RECORD = {
    "ad_archive_id": "111",
    "page_id": "123",
    "is_active": True,
    "start_date": 1789628400,
    "publisher_platform": ["INSTAGRAM"],
    "collation_count": None,
    "snapshot": {
        "page_name": "Print Studio",
        "page_profile_uri": "https://www.facebook.com/printstudio/",
        "body": {"text": "Personalized gifts for your team."},
        "cta_text": "Shop now",
        "cards": [
            {
                "title": "Custom keychains",
                "resized_image_url": "https://scontent.xx.fbcdn.net/creative.jpg",
                "link_url": "https://example.com/keychains",
                "body": "Personalized gifts for your team.",
            }
        ],
    },
}


def test_nested_public_data_and_variants():
    records = extract_records({"data": {"edges": [{"node": {"collated_results": [RECORD]}}]}})
    ad = records[0]
    assert ad["page_id"] == "123"
    assert ad["advertiser"] == "Print Studio"
    assert ad["platforms"] == ["Instagram"]
    assert ad["creative_image"].endswith("creative.jpg")
    assert ad["variant_count"] == 1
    assert ad["status"] == "active"
    assert ad["ads_using_creative"] is None
    soup = BeautifulSoup(
        '<script type="application/json">' + json.dumps({"payload": RECORD}) + "</script>",
        "html.parser",
    )
    assert from_soup(soup)[0]["library_id"] == "111"
    assert parse_payload("for (;;);" + json.dumps({"payload": RECORD}))[0]["library_id"] == "111"


def test_identity_filter_excludes_unknown_and_other_pages():
    structured = {ad["library_id"]: ad for ad in extract_records(RECORD)}
    visible = [
        {
            "library_id": "111",
            "body": "Personalized…",
            "creative_image": "https://scontent.xx.fbcdn.net/visible.jpg",
        },
        {"library_id": "222", "advertiser": "Other Page"},
    ]
    result, excluded = combine(visible, structured, "123")
    assert len(result) == 1 and excluded == 1
    assert result[0]["body"] == "Personalized gifts for your team."
    assert result[0]["creative_image"].endswith("visible.jpg")
    assert combine(visible, structured, "999")[0] == []


def test_invalid_payload_is_ignored():
    assert parse_payload("not JSON") == []
    assert extract_records({"ad_archive_id": "111", "snapshot": None}) == []


def empty_document(page_id="123", count=0, has_next=False, edges=None):
    payload = {
        "require": [
            {
                "__bbox": {
                    "result": {
                        "data": {
                            "page": {"id": page_id},
                            "ad_library_main": {
                                "search_results_connection": {
                                    "count": count,
                                    "edges": [] if edges is None else edges,
                                    "page_info": {"has_next_page": has_next},
                                }
                            },
                        }
                    },
                    "variables": {"viewAllPageID": page_id},
                }
            }
        ]
    }
    return BeautifulSoup(
        '<img src="/images/ads/politics/archive/empty-state_overfiltering_3x.png">'
        '<p>No ads match your search criteria</p><script type="application/json">'
        + json.dumps(payload)
        + "</script>",
        "html.parser",
    )


def test_empty_page_requires_identity_complete_search_and_empty_illustration():
    from adwatch.public_data import verified_empty_from_soup

    assert verified_empty_from_soup(empty_document(), "123")
    assert not verified_empty_from_soup(empty_document(), "999")
    assert not verified_empty_from_soup(empty_document(count=1), "123")
    assert not verified_empty_from_soup(empty_document(count=False), "123")
    assert not verified_empty_from_soup(empty_document(has_next=True), "123")
    assert not verified_empty_from_soup(empty_document(edges=[RECORD]), "123")
    missing_image = empty_document()
    missing_image.img.decompose()
    assert not verified_empty_from_soup(missing_image, "123")
    missing_query = empty_document()
    missing_query.script.string = missing_query.script.string.replace("viewAllPageID", "other")
    assert not verified_empty_from_soup(missing_query, "123")
    missing_identity = empty_document()
    missing_identity.script.string = missing_identity.script.string.replace(
        '"id": "123"', '"id": "999"'
    )
    assert not verified_empty_from_soup(missing_identity, "123")
    error = BeautifulSoup(
        '<script type="application/json">{"errors":[{"message":"blocked"}]}</script>', "html.parser"
    )
    document = empty_document()
    document.append(error.script)
    assert not verified_empty_from_soup(document, "123")
