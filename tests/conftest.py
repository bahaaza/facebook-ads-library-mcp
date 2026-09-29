import pytest
from sqlalchemy.orm import sessionmaker

from adwatch import models  # noqa: F401
from adwatch.db import Base, make_engine


@pytest.fixture
def db_session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()
