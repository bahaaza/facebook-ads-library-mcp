"""Worker health probe for Docker; API health checks its database separately."""

from datetime import timedelta

from adwatch.db import Session, now
from adwatch.models import WorkerState

if __name__ == "__main__":
    with Session() as session:
        state = session.get(WorkerState, 1)
        raise SystemExit(0 if state and state.heartbeat_at > now() - timedelta(minutes=10) else 1)
