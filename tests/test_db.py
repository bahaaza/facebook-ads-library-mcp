from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker

import adwatch.db as db
from adwatch.models import Ad, Competitor, IgnoredAd


def test_startup_adds_ignore_table_to_existing_database(tmp_path, monkeypatch):
    engine = db.make_engine(f"sqlite:///{tmp_path}/existing.db")
    # Reproduce the schema of installations created before ignore support.
    db.Base.metadata.create_all(
        engine,
        tables=[table for table in db.Base.metadata.sorted_tables if table != IgnoredAd.__table__],
    )
    factory = sessionmaker(engine)
    with factory.begin() as session:
        competitor = Competitor(name="Existing studio", page_id="123")
        session.add(competitor)
        session.flush()
        ad = Ad(
            competitor_id=competitor.id,
            library_id="111",
            creative_key="existing",
            data={"body": "Existing copy"},
            notes="Existing notes",
            saved=True,
        )
        session.add(ad)
        session.flush()
        ad_id = ad.id
    monkeypatch.setattr(db, "engine", engine)
    db.init_db()
    db.init_db()
    assert "ignored_ads" in inspect(engine).get_table_names()
    with factory.begin() as session:
        ad = session.get(Ad, ad_id)
        assert ad.saved and ad.notes == "Existing notes"
        session.add(IgnoredAd(ad_id=ad_id))
    engine.dispose()
