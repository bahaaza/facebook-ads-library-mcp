"""Image extraction preserves all public cards without duplicating previews."""

from adwatch.public_data import combine, extract_records


def record(snapshot):
    return {"ad_archive_id": "111", "page_id": "123", "snapshot": snapshot}


def test_collects_images_and_cards_in_order_with_legacy_preview():
    first = "https://images.test/first.jpg"
    second = "https://images.test/second.jpg"
    third = "https://images.test/third.jpg"
    data = extract_records(
        record(
            {
                "images": [
                    {
                        "resized_image_url": first,
                        "original_image_url": "https://images.test/original.jpg",
                    },
                    {"original_image_url": second},
                    None,
                    {},
                ],
                "cards": [
                    {"resized_image_url": first, "title": "First"},
                    {"original_image_url": third, "title": "Second"},
                    {"resized_image_url": second},
                ],
            }
        )
    )[0]
    assert data["creative_image"] == first
    assert data["creative_images"] == [first, second, third]
    assert data["variants"][1]["creative_images"] == [third]
    assert data["variant_count"] == 3


def test_keeps_all_card_images_past_displayed_variant_limit():
    urls = [f"https://images.test/{index}.jpg" for index in range(25)]
    data = extract_records(record({"cards": [{"original_image_url": url} for url in urls]}))[0]
    assert data["creative_images"] == urls
    assert len(data["variants"]) == 20
    assert data["variant_count"] == 25


def test_empty_media_and_video_preview_retain_legacy_behavior():
    data = extract_records(record({}))[0]
    assert data["creative_images"] == []
    assert data["creative_image"] == ""
    poster = "https://images.test/poster.jpg"
    data = extract_records(record({"videos": [{"video_preview_image_url": poster}]}))[0]
    assert data["creative_image"] == poster
    assert data["creative_images"] == []


def test_visible_preview_does_not_drop_structured_collection():
    urls = ["https://images.test/1.jpg", "https://images.test/2.jpg"]
    data = extract_records(record({"images": [{"original_image_url": url} for url in urls]}))[0]
    merged, _ = combine(
        [{"library_id": "111", "creative_image": "https://images.test/visible.jpg"}],
        {"111": data},
        "123",
    )
    assert merged[0]["creative_images"] == urls
    assert merged[0]["creative_image"].endswith("visible.jpg")


def test_collection_contains_url_strings_despite_malformed_media_values():
    url = "https://images.test/valid.jpg"
    data = extract_records(
        record(
            {
                "images": [
                    {"resized_image_url": {"bad": "value"}},
                    {"resized_image_url": 42, "original_image_url": url},
                ],
                "cards": [None, {}, {"original_image_url": ["invalid"]}],
            }
        )
    )[0]
    assert data["creative_images"] == [url]
    assert data["creative_image"] == url
