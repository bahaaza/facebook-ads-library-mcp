import csv
import hashlib
import hmac
import io
import secrets
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from adwatch.config import settings
from adwatch.db import Session, init_db, now
from adwatch.models import Ad, Alert, Competitor, Delivery, Scan, WorkerState
from adwatch.scraper import build_url, page_id_from_source
from adwatch.service import enqueue

security = HTTPBasic(auto_error=False)


SESSION_COOKIE = "adwatch_session"
SESSION_SECONDS = 8 * 60 * 60


def valid_credentials(username: str, password: str) -> bool:
    config = settings()
    if not config.admin_password:
        raise HTTPException(503, "Set ADMIN_PASSWORD before starting Adwatch.")
    return secrets.compare_digest(username.encode(), config.admin_username.encode()) and (
        secrets.compare_digest(password.encode(), config.admin_password.encode())
    )


def session_signature(payload: str) -> str:
    config = settings()
    # Credential changes invalidate existing sessions. Cookies contain no credentials.
    key = (config.admin_username + "\0" + config.admin_password).encode()
    return hmac.new(key, ("adwatch-session:" + payload).encode(), hashlib.sha256).hexdigest()


def valid_session(token: str) -> bool:
    if not settings().admin_password:
        return False
    try:
        expires, nonce, signature = token.split(".")
        remaining = int(expires) - int(time.time())
        if not 0 < remaining <= SESSION_SECONDS or len(nonce) != 32:
            return False
        return secrets.compare_digest(signature, session_signature(expires + "." + nonce))
    except (ValueError, TypeError):
        return False


def auth(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(security)],
):
    if not settings().admin_password:
        raise HTTPException(503, "Set ADMIN_PASSWORD before starting Adwatch.")
    if credentials:
        if valid_credentials(credentials.username, credentials.password):
            return
    elif valid_session(request.cookies.get(SESSION_COOKIE, "")):
        return
    # An ordinary form handles sign-in; a Basic challenge can hide it in embedded browsers.
    raise HTTPException(401, "Sign in to Adwatch")


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(
    title="Adwatch",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def headers(request: Request, call_next):
    if request.method in {"POST", "PATCH", "DELETE", "PUT"}:
        origin = request.headers.get("origin")
        allowed = {
            settings().public_url.rstrip("/"),
            f"{request.url.scheme}://{request.url.netloc}",
        }
        if origin and origin not in allowed:
            return Response("Cross-origin writes are not allowed", status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' https://*.fbcdn.net https://*.facebook.com data:; "
        "style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    )
    return response


def db():
    with Session() as session:
        yield session


def record(model, session, item_id):
    item = session.get(model, item_id)
    if item is None:
        raise HTTPException(404, "Item not found")
    return item


def serialize(item):
    # Add Z to UTC timestamps so the UI displays local time correctly.
    return {
        column.name: (
            getattr(item, column.name).isoformat() + "Z"
            if hasattr(getattr(item, column.name), "isoformat")
            else getattr(item, column.name)
        )
        for column in item.__table__.columns
    }


class CompetitorInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, max_length=2000)
    country: str = "ALL"
    interval_hours: int = Field(default=12, ge=1, le=168)
    notes: str = Field(default="", max_length=5000)

    @field_validator("name", "source")
    @classmethod
    def clean(cls, value):
        if not value.strip():
            raise ValueError("Value cannot be blank")
        return value.strip()

    @field_validator("country")
    @classmethod
    def country_code(cls, value):
        import re

        value = value.upper()
        if not re.fullmatch(r"[A-Z]{2}|ALL", value):
            raise ValueError("Use a two-letter country code or ALL")
        return value


class CompetitorPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    interval_hours: int | None = Field(default=None, ge=1, le=168)
    notes: str | None = Field(default=None, max_length=5000)


class AdPatch(BaseModel):
    saved: bool | None = None
    notes: str | None = Field(default=None, max_length=5000)


class LoginInput(BaseModel):
    username: str = Field(max_length=120)
    password: str = Field(max_length=1000)


@app.post("/api/session")
def sign_in(data: LoginInput, request: Request):
    if not valid_credentials(data.username, data.password):
        raise HTTPException(401, "Incorrect username or password")
    payload = str(int(time.time()) + SESSION_SECONDS) + "." + secrets.token_hex(16)
    response = Response(status_code=204)
    response.set_cookie(
        SESSION_COOKIE,
        payload + "." + session_signature(payload),
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return response


@app.get("/api/session", dependencies=[Depends(auth)])
def session_status():
    return {"authenticated": True}


@app.delete("/api/session")
def sign_out():
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    return response


@app.get("/health")
def health(session=Depends(db)):
    session.execute(select(1))
    return {"status": "ok"}


@app.get("/api/overview", dependencies=[Depends(auth)])
def overview(session=Depends(db)):
    def count(model, *conditions):
        return session.scalar(select(func.count()).select_from(model).where(*conditions))

    worker = session.get(WorkerState, 1)
    return {
        "competitors": count(Competitor),
        "enabled": count(Competitor, Competitor.enabled.is_(True)),
        "ads": count(Ad),
        "new_week": count(Ad, Ad.baseline.is_(False), Ad.first_seen >= now() - timedelta(days=7)),
        "unread": count(Alert, Alert.read.is_(False)),
        "failed_competitors": count(Competitor, Competitor.failures > 0),
        "worker_online": bool(worker and worker.heartbeat_at > now() - timedelta(minutes=10)),
        "worker_heartbeat": serialize(worker)["heartbeat_at"] if worker else None,
        "channels": settings().channels,
        "failed_deliveries": count(Delivery, Delivery.status == "failed"),
    }


@app.get("/api/competitors", dependencies=[Depends(auth)])
def competitors(session=Depends(db)):
    result = []
    for item in session.scalars(select(Competitor).order_by(Competitor.created_at.desc())):
        last = session.scalar(
            select(Scan).where(Scan.competitor_id == item.id).order_by(Scan.id.desc()).limit(1)
        )
        count = session.scalar(
            select(func.count()).select_from(Ad).where(Ad.competitor_id == item.id)
        )
        result.append(
            {
                **serialize(item),
                "ad_count": count,
                "library_url": build_url(country=item.country, page_id=item.page_id),
                "last_scan": {k: v for k, v in serialize(last).items() if k != "evidence"}
                if last
                else None,
            }
        )
    return result


@app.post("/api/competitors", status_code=201, dependencies=[Depends(auth)])
def add_competitor(data: CompetitorInput, session=Depends(db)):
    try:
        page_id = page_id_from_source(data.source)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    item = Competitor(
        name=data.name,
        page_id=page_id,
        country=data.country,
        interval_hours=data.interval_hours,
        notes=data.notes,
    )
    session.add(item)
    try:
        session.flush()
        enqueue(session, item.id)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "This Page and country are already on your watchlist.") from exc
    return serialize(item)


@app.patch("/api/competitors/{item_id}", dependencies=[Depends(auth)])
def update_competitor(item_id: int, data: CompetitorPatch, session=Depends(db)):
    item = record(Competitor, session, item_id)
    values = data.model_dump(exclude_unset=True)
    if any(v is None for v in values.values()) or ("name" in values and not values["name"].strip()):
        raise HTTPException(422, "Fields cannot be null or blank")
    for key, value in values.items():
        setattr(item, key, value)
    if "interval_hours" in values or values.get("enabled"):
        item.next_scan_at = now()
    if values.get("enabled") is False:
        for scan in session.scalars(
            select(Scan).where(Scan.competitor_id == item_id, Scan.status == "queued")
        ):
            scan.status = "cancelled"
            scan.finished_at = now()
    session.commit()
    return serialize(item)


@app.delete("/api/competitors/{item_id}", status_code=204, dependencies=[Depends(auth)])
def delete_competitor(item_id: int, session=Depends(db)):
    session.delete(record(Competitor, session, item_id))
    session.commit()
    return Response(status_code=204)


@app.post("/api/competitors/{item_id}/scan", status_code=202, dependencies=[Depends(auth)])
def scan_now(item_id: int, session=Depends(db)):
    item = record(Competitor, session, item_id)
    if not item.enabled:
        raise HTTPException(409, "Resume monitoring before scanning")
    scan = enqueue(session, item_id)
    session.commit()
    return serialize(scan)


@app.get("/api/ads", dependencies=[Depends(auth)])
def ads(
    competitor_id: int | None = None,
    q: str = "",
    saved: bool = False,
    new_only: bool = False,
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session=Depends(db),
):
    query = select(Ad).order_by(Ad.first_seen.desc(), Ad.id.desc())
    if competitor_id:
        query = query.where(Ad.competitor_id == competitor_id)
    if saved:
        query = query.where(Ad.saved.is_(True))
    if new_only:
        query = query.where(Ad.baseline.is_(False))
    # JSON field extraction searches decoded Unicode consistently on both DBs.
    if q:
        query = query.where(
            or_(
                *(
                    Ad.data[field].as_string().icontains(q, autoescape=True)
                    for field in ("body", "link_text", "landing_url", "advertiser", "cta")
                )
            )
        )
    total = session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    names = {c.id: c.name for c in session.scalars(select(Competitor))}
    return {
        "total": total,
        "items": [
            {**serialize(ad), "competitor_name": names.get(ad.competitor_id)}
            for ad in session.scalars(query.offset(offset).limit(limit))
        ],
    }


@app.patch("/api/ads/{item_id}", dependencies=[Depends(auth)])
def update_ad(item_id: int, data: AdPatch, session=Depends(db)):
    item = record(Ad, session, item_id)
    values = data.model_dump(exclude_unset=True)
    if any(v is None for v in values.values()):
        raise HTTPException(422, "Fields cannot be null")
    for key, value in values.items():
        setattr(item, key, value)
    session.commit()
    return serialize(item)


@app.get("/api/alerts", dependencies=[Depends(auth)])
def alerts(limit: int = Query(60, ge=1, le=200), offset: int = Query(0, ge=0), session=Depends(db)):
    items = session.scalars(
        select(Alert).order_by(Alert.created_at.desc(), Alert.id.desc()).offset(offset).limit(limit)
    )
    result = []
    for item in items:
        deliveries = session.scalars(select(Delivery).where(Delivery.alert_id == item.id))
        result.append({**serialize(item), "deliveries": [serialize(d) for d in deliveries]})
    return {"items": result, "total": session.scalar(select(func.count()).select_from(Alert))}


@app.post("/api/alerts/{item_id}/read", dependencies=[Depends(auth)])
def read_alert(item_id: int, session=Depends(db)):
    item = record(Alert, session, item_id)
    item.read = True
    session.commit()
    return serialize(item)


@app.post("/api/deliveries/{item_id}/retry", dependencies=[Depends(auth)])
def retry_delivery(item_id: int, session=Depends(db)):
    item = record(Delivery, session, item_id)
    if item.status != "failed":
        raise HTTPException(409, "Only failed deliveries can be retried")
    item.status = "pending"
    item.attempts = 0
    item.next_attempt_at = now()
    session.commit()
    return serialize(item)


@app.get("/api/scans", dependencies=[Depends(auth)])
def scans(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), session=Depends(db)):
    names = {c.id: c.name for c in session.scalars(select(Competitor))}
    items = session.scalars(select(Scan).order_by(Scan.id.desc()).offset(offset).limit(limit))
    return {
        "items": [
            {
                **{k: v for k, v in serialize(s).items() if k != "evidence"},
                "competitor_name": names.get(s.competitor_id),
            }
            for s in items
        ],
        "total": session.scalar(select(func.count()).select_from(Scan)),
    }


@app.get("/api/scans/{item_id}/evidence", dependencies=[Depends(auth)])
def evidence(item_id: int, session=Depends(db)):
    return Response(record(Scan, session, item_id).evidence, media_type="text/plain")


@app.get("/api/export.csv", dependencies=[Depends(auth)])
def export(session=Depends(db)):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "competitor",
            "library_id",
            "first_seen_utc",
            "last_seen_utc",
            "started_running",
            "body",
            "headline",
            "landing_url",
            "ad_url",
            "saved",
            "notes",
        ]
    )
    names = {c.id: c.name for c in session.scalars(select(Competitor))}

    def safe(value):
        value = str(value or "")
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value

    for ad in session.scalars(select(Ad).order_by(Ad.id)):
        writer.writerow(
            [
                safe(value)
                for value in [
                    names[ad.competitor_id],
                    ad.library_id,
                    ad.first_seen,
                    ad.last_seen,
                    ad.data.get("started_running"),
                    ad.data.get("body"),
                    ad.data.get("link_text"),
                    ad.data.get("landing_url"),
                    ad.data.get("ad_details_url"),
                    ad.saved,
                    ad.notes,
                ]
            ]
        )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="adwatch.csv"'},
    )


STATIC = Path(__file__).parent.parent / "web" / "dist"
if (STATIC / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")


@app.get("/")
def index():
    if not (STATIC / "index.html").exists():
        raise HTTPException(503, "Build the web UI first: cd web && npm ci && npm run build")
    return FileResponse(STATIC / "index.html")
