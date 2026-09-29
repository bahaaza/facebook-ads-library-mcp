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
