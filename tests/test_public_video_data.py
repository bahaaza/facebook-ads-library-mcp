import json

from bs4 import BeautifulSoup

from adwatch.public_data import combine, extract_records, from_soup, parse_payload


def record(snapshot):
    return {"ad_archive_id": "111", "page_id": "123", "snapshot": snapshot}


def test_video_sources_survive_public_payload_and_markup_merge():
    video = {
        "video_hd_url": "https://video.xx.fbcdn.net/hd.mp4?token=public",
        "video_sd_url": "https://video.xx.fbcdn.net/sd.mp4?token=public",
        "video_preview_image_url": "https://scontent.xx.fbcdn.net/preview.jpg",
    }
    payload = record({"videos": [video, {"video_sd_url": "https://video.xx.fbcdn.net/second.mp4"}]})
    data = extract_records(payload)[0]
    assert data["creative_video"] == video["video_hd_url"]
    assert data["creative_videos"] == [
        video["video_hd_url"],
        "https://video.xx.fbcdn.net/second.mp4",
    ]
    for key, value in video.items():
        assert data[key] == value
        assert data["videos"][0][key] == value
    assert data["creative_image"] == video["video_preview_image_url"]
    merged, excluded = combine(
        [{"library_id": "111", "creative_image": "https://example.com/rendered.jpg"}],
        {"111": data},
        "123",
    )
    assert excluded == 0
    assert merged[0]["creative_video"] == video["video_hd_url"]
    assert merged[0]["video_preview_image_url"] == video["video_preview_image_url"]
    text = json.dumps(payload)
    assert parse_payload("for (;;);" + text)[0]["creative_videos"] == data["creative_videos"]
    soup = BeautifulSoup(f'<script type="application/json">{text}</script>', "html.parser")
    assert from_soup(soup)[0]["creative_video"] == video["video_hd_url"]


def test_carousel_sources_and_per_variant_video_preserved():
    cards = [
        {"original_image_url": "https://example.com/still.jpg"},
        {
            "video_hd_url": "https://video.xx.fbcdn.net/card-hd.mp4",
            "video_sd_url": "https://video.xx.fbcdn.net/card-sd.mp4",
            "video_preview_image_url": "https://scontent.xx.fbcdn.net/card.jpg",
        },
        {"video_sd_url": "https://video.xx.fbcdn.net/second-card.mp4"},
    ]
    data = extract_records(record({"cards": cards}))[0]
    assert data["creative_video"] == cards[1]["video_hd_url"]
    assert data["creative_videos"] == [cards[1]["video_hd_url"], cards[2]["video_sd_url"]]
    assert data["variants"][0]["creative_video"] == ""
    assert data["variants"][1]["creative_video"] == cards[1]["video_hd_url"]
    assert data["variants"][1]["video_sd_url"] == cards[1]["video_sd_url"]
    assert data["variants"][2]["creative_video"] == cards[2]["video_sd_url"]


def test_preview_is_not_a_playable_source_and_duplicate_creatives_are_deduplicated():
    preview = {"video_preview_image_url": "https://example.com/poster.jpg"}
    data = extract_records(record({"videos": [None, preview]}))[0]
    assert data["creative_video"] == ""
    assert data["creative_videos"] == []
    assert data["video_preview_image_url"] == preview["video_preview_image_url"]
    assert data["creative_image"] == preview["video_preview_image_url"]
    video = {"video_sd_url": "https://video.xx.fbcdn.net/shared.mp4"}
    data = extract_records(record({"videos": [video, video], "cards": [video]}))[0]
    assert data["creative_videos"] == [video["video_sd_url"]]
    assert (
        extract_records(record({"images": [{"original_image_url": "https://example.com/a.jpg"}]}))[
            0
        ]["creative_videos"]
        == []
    )


def test_video_on_snapshot_and_all_carousel_urls_even_after_variant_display_limit():
    cards = [{"video_sd_url": f"https://video.xx.fbcdn.net/{index}.mp4"} for index in range(23)]
    data = extract_records(record({"cards": cards}))[0]
    assert data["variant_count"] == 23
    assert len(data["variants"]) == 20
    assert len(data["creative_videos"]) == 23
    assert data["videos"][-1]["video_sd_url"] == cards[-1]["video_sd_url"]
    direct = extract_records(record({"video_sd_url": "https://example.com/direct.mp4"}))[0]
    assert direct["creative_video"] == "https://example.com/direct.mp4"
