"""Public creative metadata must survive refresh, storage, and API serialization."""

from sqlalchemy import select

from adwatch.api import ads
from adwatch.models import Ad, Competitor
from adwatch.public_data import combine, extract_records
from adwatch.service import enqueue, finish_scan


def test_rescan_enriches_existing_ad_with_media_and_date(db_session):
    competitor = Competitor(name="Print Studio", page_id="123", country="ALL")
    db_session.add(competitor)
    db_session.commit()
    legacy = {"library_id": "111", "creative_image": "https://scontent.xx.fbcdn.net/one.jpg"}
    scan = enqueue(db_session, competitor.id)
    finish_scan(db_session, scan, {"success": True, "ads": [legacy]})
    db_session.commit()
    ad = db_session.scalar(select(Ad))
    first_seen = ad.first_seen
    ad.saved = True
    ad.notes = "Keep this example"
    db_session.commit()

    payload = {
        "ad_archive_id": "111",
        "page_id": "123",
        "start_date": 1789628400,
        "snapshot": {
            "body": {"text": "Personalized gifts"},
            "images": [
                {"original_image_url": "https://scontent.xx.fbcdn.net/one.jpg"},
                {"original_image_url": "https://scontent.xx.fbcdn.net/two.jpg"},
            ],
            "videos": [
                {
                    "video_hd_url": "https://video.xx.fbcdn.net/ad.mp4",
                    "video_preview_image_url": "https://scontent.xx.fbcdn.net/preview.jpg",
                }
            ],
        },
    }
    structured = {record["library_id"]: record for record in extract_records(payload)}
    records, excluded = combine([legacy], structured, "123")
    assert excluded == 0
    scan = enqueue(db_session, competitor.id)
    finish_scan(db_session, scan, {"success": True, "ads": records})
    db_session.commit()
    db_session.expire_all()

    response = ads(session=db_session, limit=60, offset=0)
    assert response["total"] == 1
    stored = response["items"][0]
    assert stored["saved"] is True
    assert stored["notes"] == "Keep this example"
    assert db_session.get(Ad, ad.id).first_seen == first_seen
    assert stored["data"]["creative_images"] == [
        "https://scontent.xx.fbcdn.net/one.jpg",
        "https://scontent.xx.fbcdn.net/two.jpg",
    ]
    assert stored["data"]["creative_video"] == "https://video.xx.fbcdn.net/ad.mp4"
    assert stored["data"]["creative_videos"] == ["https://video.xx.fbcdn.net/ad.mp4"]
    assert stored["data"]["started_running"] == "Sep 17, 2026"
