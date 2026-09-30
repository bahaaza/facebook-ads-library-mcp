import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { AdDate } from "./AdDate";
import {
  Activity,
  ArrowUpRight,
  Bell,
  Bookmark,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Download,
  ExternalLink,
  Eye,
  EyeOff,
  LayoutGrid,
  LoaderCircle,
  LogOut,
  Mail,
  Pause,
  Play,
  Plus,
  Radar,
  RefreshCw,
  Search,
  Settings2,
  Trash2,
  Users,
  X,
} from "lucide-react";
import "./style.css";

type Scan = {
  id: number;
  competitor_name: string;
  status: string;
  error: string;
  ads_found: number;
  new_ads: number;
  partial: boolean;
  queued_at: string;
  finished_at: string | null;
};
type Competitor = {
  id: number;
  name: string;
  page_id: string;
  country: string;
  interval_hours: number;
  enabled: boolean;
  ad_count: number;
  failures: number;
  notes: string;
  baseline_at: string | null;
  last_success_at: string | null;
  next_scan_at: string;
  library_url: string;
  last_scan: Scan | null;
};
type Ad = {
  id: number;
  competitor_id: number;
  competitor_name: string;
  library_id: string;
  first_seen: string;
  last_seen: string;
  baseline: boolean;
  saved: boolean;
  ignored: boolean;
  notes: string;
  creative_key: string;
  data: {
    body?: string;
    link_text?: string;
    creative_image?: string;
    landing_url?: string;
    landing_domain?: string;
    cta?: string;
    page_id?: string;
    variant_count?: number;
    variants?: {
      body?: string;
      link_text?: string;
      creative_image?: string;
      landing_url?: string;
      cta?: string;
    }[];
    started_running?: string;
    status?: string;
    platforms?: string[];
    ad_details_url: string;
  };
};
type Delivery = {
  id: number;
  channel: string;
  status: string;
  attempts: number;
  error: string;
};
type Alert = {
  id: number;
  competitor_id: number;
  kind: string;
  title: string;
  body: string;
  created_at: string;
  read: boolean;
  deliveries: Delivery[];
};
type Overview = {
  competitors: number;
  enabled: number;
  ads: number;
  new_week: number;
  unread: number;
  failed_competitors: number;
  worker_online: boolean;
  channels: string[];
  failed_deliveries: number;
  worker_heartbeat: string | null;
};
type Tab = "ads" | "competitors" | "alerts" | "scans" | "settings";
const tabs: { id: Tab; label: string; icon: typeof Eye }[] = [
  { id: "ads", label: "Ad library", icon: LayoutGrid },
  { id: "competitors", label: "Watchlist", icon: Users },
  { id: "alerts", label: "Alerts", icon: Bell },
  { id: "scans", label: "Scan history", icon: Activity },
];
let authGeneration = 0;
async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  notifyUnauthorized = true,
): Promise<T> {
  const generation = authGeneration;
  const response = await fetch("/api" + path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    if (
      response.status === 401 &&
      notifyUnauthorized &&
      generation === authGeneration
    ) {
      window.dispatchEvent(new Event("adwatch:unauthorized"));
    }
    const result = await response
      .json()
      .catch(() => ({ detail: "Request failed" }));
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : (result.detail?.[0]?.msg ?? `Request failed (${response.status})`),
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
const date = (value: string | null) =>
  value
    ? new Date(value).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Not yet";
const safeLink = (value?: string) => {
  try {
    const u = new URL(value ?? "");
    return ["https:", "http:"].includes(u.protocol) ? u.href : undefined;
  } catch {
    return undefined;
  }
};
function Empty({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <Radar size={42} strokeWidth={1.2} />
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
function App({ onLogout }: { onLogout: () => Promise<void> }) {
  const initial = new URLSearchParams(location.search).get("tab") as Tab;
  const [tab, setTab] = useState<Tab>(
    ["ads", "competitors", "alerts", "scans", "settings"].includes(initial)
      ? initial
      : "ads",
  );
  const [overview, setOverview] = useState<Overview | null>(null),
    [competitors, setCompetitors] = useState<Competitor[]>([]);
  const [ads, setAds] = useState<Ad[]>([]),
    [alerts, setAlerts] = useState<Alert[]>([]),
    [scans, setScans] = useState<Scan[]>([]);
  const [query, setQuery] = useState(""),
    [search, setSearch] = useState(""),
    [filter, setFilter] = useState(""),
    [saved, setSaved] = useState(false),
    [ignoredOnly, setIgnoredOnly] = useState(false),
    [newOnly, setNewOnly] = useState(false);
  const [offset, setOffset] = useState(0),
    [total, setTotal] = useState(0),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [modal, setModal] = useState(false),
    [detail, setDetail] = useState<Ad | null>(null),
    [edit, setEdit] = useState<Competitor | null>(null);
  const [note, setNote] = useState(""),
    [group, setGroup] = useState(false);
  const [mailTesting, setMailTesting] = useState(false);
  const [mailResult, setMailResult] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);
  useEffect(() => {
    const t = setTimeout(() => setSearch(query), 300);
    return () => clearTimeout(t);
  }, [query]);
  useEffect(
    () => setOffset(0),
    [search, filter, saved, newOnly, ignoredOnly, tab],
  );
  const sequence = useRef(0);
  const load = useCallback(async () => {
    const requestId = ++sequence.current;
    try {
      const [o, c] = await Promise.all([
        api<Overview>("/overview"),
        api<Competitor[]>("/competitors"),
      ]);
      if (requestId !== sequence.current) return;
      setOverview(o);
      setCompetitors(c);
      if (tab === "ads") {
        const params = new URLSearchParams({
          q: search,
          saved: String(saved),
          new_only: String(newOnly),
          ignored: String(ignoredOnly),
          offset: String(offset),
          limit: "60",
        });
        if (filter) params.set("competitor_id", filter);
        const r = await api<{ items: Ad[]; total: number }>("/ads?" + params);
        if (requestId !== sequence.current) return;
        if (offset > 0 && offset >= r.total) {
          setOffset(Math.max(0, Math.ceil(r.total / 60) - 1) * 60);
          return;
        }
        setAds(r.items);
        setTotal(r.total);
      }
      if (tab === "alerts") {
        const r = await api<{ items: Alert[]; total: number }>(
          "/alerts?offset=" + offset,
        );
        if (requestId !== sequence.current) return;
        setAlerts(r.items);
        setTotal(r.total);
      }
      if (tab === "scans") {
        const r = await api<{ items: Scan[]; total: number }>(
          "/scans?offset=" + offset + "&limit=60",
        );
        if (requestId !== sequence.current) return;
        setScans(r.items);
        setTotal(r.total);
      }
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      if (requestId === sequence.current) setLoading(false);
    }
  }, [tab, search, saved, newOnly, ignoredOnly, filter, offset]);
  useEffect(() => {
    setLoading(true);
    void load();
    const t = setInterval(() => void load(), 15000);
    return () => clearInterval(t);
  }, [load]);
  useEffect(() => {
    const close = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setModal(false);
        setDetail(null);
        setEdit(null);
      }
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const go = (t: Tab) => {
    setTab(t);
    setOffset(0);
    history.replaceState(null, "", "/?tab=" + t);
  };
  const showAd = (ad: Ad) => {
    setDetail(ad);
    setNote(ad.notes);
  };
  const toggleIgnored = (ad: Ad) =>
    act(async () => {
      await api("/ads/" + ad.id, "PATCH", { ignored: !ad.ignored });
      setDetail((current) => (current?.id === ad.id ? null : current));
    });
  const groups = new Map<string, Ad[]>();
  for (const ad of ads) {
    const key = group ? ad.creative_key : String(ad.id);
    groups.set(key, [...(groups.get(key) ?? []), ad]);
  }
  const pagination = total > 60 && (
    <div className="pagination">
      <span>
        {offset + 1}–{Math.min(offset + 60, total)} of {total}
      </span>
      <button
        disabled={offset === 0}
        onClick={() => setOffset(Math.max(0, offset - 60))}
      >
        <ChevronLeft size={16} /> Previous
      </button>
      <button
        disabled={offset + 60 >= total}
        onClick={() => setOffset(offset + 60)}
      >
        Next <ChevronRight size={16} />
      </button>
    </div>
  );
  return (
    <div className="app">
      <aside className="sidebar">
        <a className="brand" href="/">
          <span className="brand-mark">
            <Radar size={24} />
          </span>
          adwatch<span className="brand-dot">.</span>
        </a>
        <div className="workspace">
          <div className="avatar">3D</div>
          <div>
            <strong>Competitor intelligence</strong>
            <small>Your printing business</small>
          </div>
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={tab === id ? "active" : ""}
              onClick={() => go(id)}
            >
              <Icon size={19} />
              {label}
              {id === "alerts" && !!overview?.unread && (
                <span className="count">{overview.unread}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="status">
            <i className={overview?.worker_online ? "online" : ""} />
            <div>
              <strong>
                {overview?.worker_online
                  ? "Monitoring is running"
                  : "Worker is offline"}
              </strong>
              <small>{overview?.enabled ?? 0} pages on your watchlist</small>
            </div>
          </div>
          <button
            className={
              tab === "settings" ? "active settings-link" : "settings-link"
            }
            onClick={() => go("settings")}
          >
            <Settings2 size={18} /> Settings & delivery
          </button>
          <button
            className="settings-link"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onLogout();
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <LogOut size={18} /> Sign out
          </button>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <span>/</span>{" "}
            <strong>
              {tab === "settings"
                ? "Settings"
                : tabs.find((t) => t.id === tab)?.label}
            </strong>
          </div>
          <div className="top-actions">
            <span className="live">
              <i /> Updates every 15s
            </span>
            <button
              aria-label="Refresh dashboard"
              className="icon-button"
              onClick={() => void load()}
            >
              <RefreshCw size={17} />
            </button>
            <div className="avatar small">B</div>
          </div>
        </header>
        <div className="content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">YOUR COMPETITIVE EDGE</div>
              <h1>
                {tab === "ads"
                  ? "See what’s out there."
                  : tab === "competitors"
                    ? "Keep your competitors in view."
                    : tab === "alerts"
                      ? "The changes that matter."
                      : tab === "scans"
                        ? "Know your monitoring is working."
                        : "Make Adwatch yours."}
              </h1>
              <p>
                {tab === "ads"
                  ? "A living collection of the ads your competitors are running."
                  : tab === "competitors"
                    ? "Add a Facebook Page once. Let the scheduled scans do the checking."
                    : tab === "alerts"
                      ? "Newly observed ads and monitoring updates, all in one inbox."
                      : tab === "scans"
                        ? "Every attempt, with a clear outcome and the evidence behind it."
                        : "Your schedule, delivery channels, and self-hosted setup."}
              </p>
            </div>
            <button className="primary" onClick={() => setModal(true)}>
              <Plus size={17} /> Add competitor
            </button>
          </div>
          {error && (
            <div className="error" role="alert">
              {error}
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {overview && (
            <div className="stats">
              <div>
                <span>
                  Pages on watchlist <Users size={16} />
                </span>
                <strong>{overview.competitors}</strong>
                <small>{overview.enabled} actively monitored</small>
              </div>
              <div>
                <span>
                  Ads collected <LayoutGrid size={16} />
                </span>
                <strong>{overview.ads}</strong>
                <small>Stored across all your pages</small>
              </div>
              <div>
                <span>
                  New this week <ArrowUpRight size={17} />
                </span>
                <strong>
                  {overview.new_week}
                  <em>7 days</em>
                </strong>
                <small>First observed after baseline</small>
              </div>
              <div>
                <span>
                  Unread alerts <Bell size={16} />
                </span>
                <strong>{overview.unread}</strong>
                <small>
                  {overview.failed_competitors
                    ? `${overview.failed_competitors} pages need attention`
                    : "Your competitive pulse"}
                </small>
              </div>
            </div>
          )}
          {overview && !overview.worker_online && (
            <div className="notice">
              <Activity size={18} />
              <span>
                The browser worker is offline. Scheduled scans resume when it
                starts. Last heartbeat: {date(overview.worker_heartbeat)}.
              </span>
            </div>
          )}
          {loading ? (
            <div className="loading">
              <LoaderCircle className="spin" /> Loading your workspace…
            </div>
          ) : tab === "ads" ? (
            <>
              <section className="gallery-header">
                <div>
                  <h2>
                    {ignoredOnly ? "Ignored ads" : "Competitor ads"}{" "}
                    <span>{total}</span>
                  </h2>
                  <small>
                    {ignoredOnly
                      ? "Ignored ads are hidden from your library. Restore any ad to show it again."
                      : "“New” means first observed by your monitor. It may have launched earlier. Ignored ads are hidden."}
                  </small>
                </div>
                <a className="button subtle" href="/api/export.csv">
                  <Download size={16} /> Export CSV
                </a>
              </section>
              <div className="filters">
                <label className="search">
                  <Search size={17} />
                  <input
                    placeholder="Search copy, headlines, destinations…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>
                <select
                  aria-label="Filter by competitor"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                >
                  <option value="">All competitors</option>
                  {competitors.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
                <button
                  className={newOnly ? "selected" : ""}
                  onClick={() => setNewOnly(!newOnly)}
                >
                  New ads
                </button>
                <button
                  className={saved ? "selected" : ""}
                  onClick={() => setSaved(!saved)}
                >
                  <Bookmark size={15} /> Saved
                </button>
                <button
                  className={ignoredOnly ? "selected" : ""}
                  aria-pressed={ignoredOnly}
                  onClick={() => setIgnoredOnly(!ignoredOnly)}
                >
                  <EyeOff size={15} /> Ignored ads
                </button>
                <button
                  className={group ? "selected" : ""}
                  onClick={() => setGroup(!group)}
                >
                  Group by copy
                </button>
              </div>
              {!ads.length ? (
                <Empty
                  title={
                    ignoredOnly
                      ? "No ignored ads in this view"
                      : competitors.length
                        ? "No ads in this view yet"
                        : "Your radar starts here"
                  }
                  description={
                    ignoredOnly
                      ? "Ads you ignore will appear here. Try clearing other filters if an ignored ad is missing."
                      : competitors.length
                        ? "Try clearing filters, check Ignored ads, or check Scan history for your first successful scan."
                        : "Add a competitor’s Ad Library link to build your first baseline. Future scans will highlight newly observed ads."
                  }
                  action={
                    !competitors.length && (
                      <button
                        className="primary"
                        onClick={() => setModal(true)}
                      >
                        <Plus size={16} /> Add your first competitor
                      </button>
                    )
                  }
                />
              ) : (
                <div className="ad-grid">
                  {[...groups.values()].map((items) => {
                    const ad = items[0];
                    return (
                      <article className="ad-card" key={ad.id}>
                        <div className="ad-top">
                          <div className="mini-avatar">
                            {ad.competitor_name.slice(0, 2).toUpperCase()}
                          </div>
                          <div>
                            <strong>{ad.competitor_name}</strong>
                            <small>
                              Ad Library · {ad.data.status ?? "unknown"}
                            </small>
                          </div>
                          <button
                            className={
                              ad.saved ? "icon-button is-saved" : "icon-button"
                            }
                            aria-label={ad.saved ? "Unsave ad" : "Save ad"}
                            disabled={busy}
                            onClick={() =>
                              void act(() =>
                                api("/ads/" + ad.id, "PATCH", {
                                  saved: !ad.saved,
                                }),
                              )
                            }
                          >
                            <Bookmark
                              size={18}
                              fill={ad.saved ? "currentColor" : "none"}
                            />
                          </button>
                          <button
                            className="icon-button"
                            aria-label={ad.ignored ? "Restore ad" : "Ignore ad"}
                            title={
                              ad.ignored
                                ? "Restore ad to library"
                                : "Ignore ad (hide from library)"
                            }
                            disabled={busy}
                            onClick={() => void toggleIgnored(ad)}
                          >
                            {ad.ignored ? (
                              <Eye size={18} />
                            ) : (
                              <EyeOff size={18} />
                            )}
                          </button>
                        </div>
                        <button className="creative" onClick={() => showAd(ad)}>
                          {safeLink(ad.data.creative_image) ? (
                            <img
                              src={safeLink(ad.data.creative_image)}
                              alt="Competitor ad creative"
                              loading="lazy"
                              referrerPolicy="no-referrer"
                              onError={(e) => {
                                e.currentTarget.style.display = "none";
                              }}
                            />
                          ) : null}
                          <span className="creative-fallback">
                            <LayoutGrid size={30} />
                            <span>View creative in Ad Library</span>
                          </span>
                          {!ad.baseline && (
                            <span className="new-badge">Newly observed</span>
                          )}
                          {items.length > 1 && (
                            <span className="group-badge">
                              {items.length} with similar copy
                            </span>
                          )}
                        </button>
                        <div className="ad-copy">
                          <small>
                            {ad.data.landing_domain ?? "Ad creative"}
                          </small>
                          <h3>
                            {ad.data.link_text ||
                              ad.data.cta ||
                              "Competitor ad"}
                          </h3>
                          <p dir="auto">
                            {ad.data.body ||
                              "Copy was not available in the rendered page."}
                          </p>
                        </div>
                        <AdDate value={ad.data.started_running} />
                        <div className="ad-footer">
                          <span>
                            <Clock3 size={13} /> First observed{" "}
                            {date(ad.first_seen)}
                          </span>
                          <button onClick={() => showAd(ad)}>
                            Details <ArrowUpRight size={15} />
                          </button>
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
              {pagination}
            </>
          ) : tab === "competitors" ? (
            <>
              <div className="section-heading">
                <h2>Your watchlist</h2>
                <span>Exact Page IDs · Country-specific monitoring</span>
              </div>
              {!competitors.length ? (
                <Empty
                  title="Pick the pages worth watching"
                  description="Open a competitor in Meta Ad Library, choose See all ads, and copy that link here."
                  action={
                    <button className="primary" onClick={() => setModal(true)}>
                      Add competitor
                    </button>
                  }
                />
              ) : (
                <div className="watchlist">
                  {competitors.map((c) => (
                    <article className="competitor" key={c.id}>
                      <div className="competitor-head">
                        <div className="mini-avatar large">
                          {c.name.slice(0, 2).toUpperCase()}
                        </div>
                        <div>
                          <h3>{c.name}</h3>
                          <small>
                            Page {c.page_id} ·{" "}
                            {c.country === "ALL" ? "All countries" : c.country}
                          </small>
                        </div>
                        <span
                          className={
                            "pill " +
                            (!c.enabled
                              ? "neutral"
                              : c.failures
                                ? "warning"
                                : "green")
                          }
                        >
                          {!c.enabled
                            ? "Paused"
                            : c.failures
                              ? "Needs attention"
                              : !c.baseline_at
                                ? "Awaiting baseline"
                                : "Monitoring"}
                        </span>
                      </div>
                      <div className="competitor-metrics">
                        <div>
                          <small>Collected ads</small>
                          <strong>{c.ad_count}</strong>
                        </div>
                        <div>
                          <small>Schedule</small>
                          <strong>Every {c.interval_hours}h</strong>
                        </div>
                        <div>
                          <small>Last success</small>
                          <strong>{date(c.last_success_at)}</strong>
                        </div>
                        <div>
                          <small>Next check</small>
                          <strong>
                            {c.enabled ? date(c.next_scan_at) : "Paused"}
                          </strong>
                        </div>
                      </div>
                      {c.last_scan && (
                        <div className="scan-note">
                          Latest scan: {c.last_scan.status}
                          {c.last_scan.partial
                            ? " · Scroll limit reached; coverage may be incomplete"
                            : ""}
                          {c.last_scan.error && (
                            <span>{c.last_scan.error}</span>
                          )}
                        </div>
                      )}
                      {c.notes && <p className="competitor-notes">{c.notes}</p>}
                      <div className="competitor-actions">
                        <button
                          disabled={
                            busy ||
                            !c.enabled ||
                            ["queued", "running"].includes(
                              c.last_scan?.status ?? "",
                            )
                          }
                          onClick={() =>
                            void act(() =>
                              api("/competitors/" + c.id + "/scan", "POST"),
                            )
                          }
                        >
                          <RefreshCw size={15} />{" "}
                          {c.last_scan?.status === "running"
                            ? "Scanning…"
                            : c.last_scan?.status === "queued"
                              ? "Queued"
                              : "Check now"}
                        </button>
                        <a
                          className="button"
                          href={c.library_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Ad Library <ExternalLink size={14} />
                        </a>
                        <button
                          onClick={() => {
                            setEdit(c);
                            setNote(c.notes);
                          }}
                        >
                          <Settings2 size={15} /> Edit
                        </button>
                        <button
                          disabled={busy}
                          onClick={() =>
                            void act(() =>
                              api("/competitors/" + c.id, "PATCH", {
                                enabled: !c.enabled,
                              }),
                            )
                          }
                        >
                          {c.enabled ? <Pause size={14} /> : <Play size={14} />}{" "}
                          {c.enabled ? "Pause" : "Resume"}
                        </button>
                        <button
                          className="danger icon-button"
                          aria-label={"Remove " + c.name}
                          onClick={() => {
                            if (
                              confirm(
                                `Remove ${c.name} and its collected history?`,
                              )
                            )
                              void act(() =>
                                api("/competitors/" + c.id, "DELETE"),
                              );
                          }}
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </>
          ) : tab === "alerts" ? (
            <>
              <div className="section-heading">
                <h2>Your alert inbox</h2>
                <span>
                  {overview?.channels.length
                    ? `External delivery: ${overview.channels.join(" + ")}`
                    : "Dashboard alerts are enabled"}
                </span>
              </div>
              {!alerts.length ? (
                <Empty
                  title="You’re all caught up"
                  description="Your baseline scan is quiet. New ads observed afterward will appear here, along with scan failures and recoveries."
                />
              ) : (
                <div className="alert-list">
                  {alerts.map((a) => (
                    <article
                      className={"alert " + (a.read ? "read" : "")}
                      key={a.id}
                    >
                      <div className={"alert-symbol " + a.kind}>
                        {a.kind === "new_ads" ? (
                          <Bell size={20} />
                        ) : (
                          <Activity size={20} />
                        )}
                      </div>
                      <div>
                        <small>
                          {date(a.created_at)} · {a.kind.replaceAll("_", " ")}
                        </small>
                        <h3>{a.title}</h3>
                        <p>{a.body}</p>
                        <div className="alert-actions">
                          <button
                            onClick={() => {
                              setFilter(String(a.competitor_id));
                              go("ads");
                            }}
                          >
                            View competitor ads <ArrowUpRight size={14} />
                          </button>
                          {!a.read && (
                            <button
                              disabled={busy}
                              onClick={() =>
                                void act(() =>
                                  api("/alerts/" + a.id + "/read", "POST"),
                                )
                              }
                            >
                              <Check size={14} /> Mark read
                            </button>
                          )}
                          {a.deliveries.map((d) => (
                            <span className="delivery" key={d.id}>
                              {d.channel}: {d.status} ({d.attempts} attempts)
                              {d.status === "failed" && (
                                <button
                                  onClick={() =>
                                    void act(() =>
                                      api(
                                        "/deliveries/" + d.id + "/retry",
                                        "POST",
                                      ),
                                    )
                                  }
                                >
                                  Retry
                                </button>
                              )}
                            </span>
                          ))}
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              )}
              {pagination}
            </>
          ) : tab === "scans" ? (
            <>
              <div className="section-heading">
                <h2>Scan history</h2>
                <span>Failed reads never delete your ad history</span>
              </div>
              {!scans.length ? (
                <Empty
                  title="No scans yet"
                  description="Add a competitor to automatically queue its first scan."
                />
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Competitor</th>
                        <th>Queued</th>
                        <th>Outcome</th>
                        <th>Ads</th>
                        <th>New</th>
                        <th>Evidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {scans.map((s) => (
                        <tr key={s.id}>
                          <td>
                            <strong>{s.competitor_name}</strong>
                            <small>
                              {s.error ||
                                (s.partial
                                  ? "Scroll limit reached · partial coverage"
                                  : "")}
                            </small>
                          </td>
                          <td>{date(s.queued_at)}</td>
                          <td>
                            <span
                              className={
                                "pill " +
                                (s.status === "failed"
                                  ? "warning"
                                  : s.status === "succeeded"
                                    ? "green"
                                    : "neutral")
                              }
                            >
                              {s.status}
                            </span>
                          </td>
                          <td>{s.ads_found}</td>
                          <td>{s.new_ads}</td>
                          <td>
                            <a
                              href={"/api/scans/" + s.id + "/evidence"}
                              target="_blank"
                              rel="noreferrer"
                            >
                              Text <ExternalLink size={13} />
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {pagination}
            </>
          ) : (
            <div className="settings-grid">
              <section className="settings-card">
                <Bell size={24} />
                <h2>Alert delivery</h2>
                <p>
                  Every alert stays in your dashboard. Configure external
                  channels in your server’s <code>.env</code> file, then restart
                  the API and worker.
                </p>
                <div className="setting-row">
                  <strong>Dashboard inbox</strong>
                  <span className="pill green">Enabled</span>
                </div>
                <div className="setting-row">
                  <strong>Email</strong>
                  <span
                    className={
                      "pill " +
                      (overview?.channels.includes("email")
                        ? "green"
                        : "neutral")
                    }
                  >
                    {overview?.channels.includes("email")
                      ? "Configured"
                      : "Not configured"}
                  </span>
                </div>
                <p className="hint">
                  Set SMTP_HOST, SMTP_PORT, SMTP_FROM, SMTP_TO and
                  authentication. SMTP_TLS supports starttls or ssl.
                </p>
                <button
                  disabled={
                    mailTesting || !overview?.channels.includes("email")
                  }
                  onClick={async () => {
                    setMailTesting(true);
                    setMailResult(null);
                    try {
                      const result = await api<{ message: string }>(
                        "/notifications/email/test",
                        "POST",
                      );
                      setMailResult({ ok: true, message: result.message });
                    } catch (e) {
                      setMailResult({
                        ok: false,
                        message: (e as Error).message,
                      });
                    } finally {
                      setMailTesting(false);
                    }
                  }}
                >
                  {mailTesting ? (
                    <LoaderCircle size={16} className="spin" />
                  ) : (
                    <Mail size={16} />
                  )}
                  {mailTesting ? "Sending test email…" : "Send test email"}
                </button>
                <p className="hint">
                  Sends one test message to the recipients configured for email
                  alerts.
                </p>
                {mailResult && (
                  <p
                    role={mailResult.ok ? "status" : "alert"}
                    className={mailResult.ok ? "mail-success" : "login-error"}
                  >
                    {mailResult.message}
                  </p>
                )}
                <div className="setting-row">
                  <strong>Telegram</strong>
                  <span
                    className={
                      "pill " +
                      (overview?.channels.includes("telegram")
                        ? "green"
                        : "neutral")
                    }
                  >
                    {overview?.channels.includes("telegram")
                      ? "Configured"
                      : "Not configured"}
                  </span>
                </div>
                <p className="hint">
                  Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. Tokens stay on
                  your server.
                </p>
                <p>
                  Delivery failures retry five times. Failed deliveries can be
                  retried from the alert inbox after fixing configuration.
                </p>
              </section>
              <section className="settings-card">
                <Clock3 size={24} />
                <h2>A useful monitoring rhythm</h2>
                <p>
                  Start with checks every 12 hours. You can set each competitor
                  to check every 1–168 hours from the watchlist.
                </p>
                <ul>
                  <li>The first successful scan establishes your baseline.</li>
                  <li>Ad IDs keep alerts unique across restarts.</li>
                  <li>
                    “New” means newly observed, not necessarily newly launched.
                  </li>
                  <li>
                    A page disappearing from a scan does not prove an ad stopped
                    running.
                  </li>
                  <li>
                    Similar copy is grouped within the current gallery page.
                  </li>
                  <li>
                    Failed reads use a longer retry delay and preserve history.
                  </li>
                </ul>
                <p className="hint">
                  Public Ad Library scraping can be incomplete or blocked. Ad
                  age and creative counts do not establish budget, performance,
                  or profitability.
                </p>
              </section>
            </div>
          )}
          <footer className="footer">
            <span>
              <Radar size={14} /> Public Ad Library intelligence
            </span>
            <span>Self-hosted · Your data stays on your server</span>
          </footer>
        </div>
      </main>
      {modal && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="add-title"
          >
            <button
              className="modal-close icon-button"
              aria-label="Close"
              onClick={() => setModal(false)}
            >
              <X size={20} />
            </button>
            <div className="modal-icon">
              <Radar size={25} />
            </div>
            <h2 id="add-title">Add a competitor</h2>
            <p>Give your radar a new page to watch.</p>
            {error && (
              <div className="error" role="alert">
                {error}
              </div>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const f = new FormData(e.currentTarget);
                void act(async () => {
                  await api("/competitors", "POST", {
                    name: f.get("name"),
                    source: f.get("source"),
                    country: f.get("country"),
                    interval_hours: Number(f.get("interval_hours")),
                    notes: f.get("notes"),
                  });
                  setModal(false);
                  go("competitors");
                });
              }}
            >
              <label>
                Competitor name
                <input
                  name="name"
                  required
                  autoFocus
                  maxLength={120}
                  placeholder="e.g. Local Print Studio"
                />
              </label>
              <label>
                Ad Library link or numeric Page ID
                <input
                  name="source"
                  required
                  placeholder="https://www.facebook.com/ads/library/?view_all_page_id=…"
                />
                <small>
                  In Meta Ad Library, open the competitor and copy its “See all
                  ads” link.
                </small>
              </label>
              <div className="form-row">
                <label>
                  Country code
                  <input
                    name="country"
                    defaultValue="ALL"
                    maxLength={3}
                    required
                    placeholder="ALL, IL, PS, US…"
                  />
                </label>
                <label>
                  Check every
                  <select name="interval_hours" defaultValue="12">
                    <option value="1">1 hour</option>
                    <option value="6">6 hours</option>
                    <option value="12">12 hours</option>
                    <option value="24">24 hours</option>
                    <option value="168">1 week</option>
                  </select>
                </label>
              </div>
              <label>
                Notes <span className="optional">optional</span>
                <textarea
                  name="notes"
                  maxLength={5000}
                  placeholder="Products, strengths, or things to pay attention to…"
                />
              </label>
              <div className="baseline-note">
                <Eye size={17} /> First scan builds a baseline. Alerts start
                with later scans.
              </div>
              <button className="primary full" disabled={busy}>
                {busy ? (
                  <LoaderCircle className="spin" size={16} />
                ) : (
                  <Plus size={16} />
                )}{" "}
                Start monitoring
              </button>
            </form>
          </section>
        </div>
      )}
      {detail && (
        <div className="modal-backdrop">
          <section
            className="modal ad-detail"
            role="dialog"
            aria-modal="true"
            aria-labelledby="ad-title"
          >
            <button
              className="modal-close icon-button"
              aria-label="Close"
              onClick={() => setDetail(null)}
            >
              <X size={20} />
            </button>
            <div className="eyebrow">{detail.competitor_name}</div>
            <h2 id="ad-title">{detail.data.link_text || "Ad details"}</h2>
            <p className="full-copy" dir="auto">
              {detail.data.body || "Ad copy unavailable."}
            </p>
            <div className="detail-info">
              <span>
                Library ID <strong>{detail.library_id}</strong>
              </span>
              <AdDate
                value={detail.data.started_running}
                className="ad-date--detail"
              />
              <span>
                First observed <strong>{date(detail.first_seen)}</strong>
              </span>
              <span>
                Last observed <strong>{date(detail.last_seen)}</strong>
              </span>
            </div>
            {!!detail.data.variants?.length && (
              <div className="variants">
                <h3>
                  Creative variants{" "}
                  <small>
                    {detail.data.variant_count ?? detail.data.variants.length}
                  </small>
                </h3>
                <p className="hint">
                  Public variants from the same ad. Up to 20 are shown here;
                  open the original ad for all versions.
                </p>
                <div className="variant-grid">
                  {detail.data.variants.map((variant, index) => (
                    <article key={index}>
                      {safeLink(variant.creative_image) && (
                        <img
                          src={safeLink(variant.creative_image)}
                          alt={`Ad variant ${index + 1}`}
                          loading="lazy"
                          referrerPolicy="no-referrer"
                        />
                      )}
                      <strong>
                        {variant.link_text || `Variant ${index + 1}`}
                      </strong>
                      {variant.body && <p dir="auto">{variant.body}</p>}
                      {safeLink(variant.landing_url) && (
                        <a
                          href={safeLink(variant.landing_url)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Landing page <ExternalLink size={12} />
                        </a>
                      )}
                    </article>
                  ))}
                </div>
              </div>
            )}
            <div className="detail-links">
              <button
                disabled={busy}
                onClick={() => void toggleIgnored(detail)}
              >
                {detail.ignored ? <Eye size={15} /> : <EyeOff size={15} />}
                {detail.ignored ? "Restore ad" : "Ignore ad"}
              </button>
              <a
                className="button primary"
                href={safeLink(detail.data.ad_details_url)}
                target="_blank"
                rel="noreferrer"
              >
                Open original ad <ExternalLink size={15} />
              </a>
              {safeLink(detail.data.landing_url) && (
                <a
                  className="button"
                  href={safeLink(detail.data.landing_url)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Landing page <ExternalLink size={15} />
                </a>
              )}
            </div>
            <label>
              Your notes
              <textarea
                value={note}
                maxLength={5000}
                onChange={(e) => setNote(e.target.value)}
                placeholder="What makes this offer interesting?"
              />
            </label>
            <button
              className="primary"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  await api("/ads/" + detail.id, "PATCH", { notes: note });
                  setDetail((current) =>
                    current?.id === detail.id
                      ? { ...current, notes: note }
                      : current,
                  );
                })
              }
            >
              Save notes
            </button>
          </section>
        </div>
      )}
      {edit && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="edit-title"
          >
            <button
              className="modal-close icon-button"
              aria-label="Close"
              onClick={() => setEdit(null)}
            >
              <X size={20} />
            </button>
            <h2 id="edit-title">Edit {edit.name}</h2>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const f = new FormData(e.currentTarget);
                void act(async () => {
                  await api("/competitors/" + edit.id, "PATCH", {
                    name: f.get("name"),
                    interval_hours: Number(f.get("interval_hours")),
                    notes: note,
                  });
                  setEdit(null);
                });
              }}
            >
              <label>
                Name
                <input
                  name="name"
                  defaultValue={edit.name}
                  required
                  maxLength={120}
                />
              </label>
              <label>
                Hours between checks
                <input
                  name="interval_hours"
                  type="number"
                  min={1}
                  max={168}
                  defaultValue={edit.interval_hours}
                  required
                />
              </label>
              <label>
                Notes
                <textarea
                  value={note}
                  maxLength={5000}
                  onChange={(e) => setNote(e.target.value)}
                />
              </label>
              <p className="hint">
                Page ID and country identify this watchlist entry. Add another
                entry to monitor a different country.
              </p>
              <button className="primary full" disabled={busy}>
                Save changes
              </button>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
function SignIn() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const expired = () => {
      authGeneration++;
      setAuthenticated(false);
    };
    window.addEventListener("adwatch:unauthorized", expired);
    api<{ authenticated: boolean }>("/session", "GET", undefined, false)
      .then(() => {
        if (active) setAuthenticated(true);
      })
      .catch((e: Error) => {
        if (!active) return;
        setAuthenticated(false);
        if (e.message !== "Sign in to Adwatch") setError(e.message);
      });
    return () => {
      active = false;
      window.removeEventListener("adwatch:unauthorized", expired);
    };
  }, []);

  const logout = async () => {
    await api("/session", "DELETE");
    authGeneration++;
    setPassword("");
    setAuthenticated(false);
  };
  if (authenticated) return <App onLogout={logout} />;

  return (
    <main className="login-page">
      <section className="login-card">
        <div className="brand">
          <span className="brand-mark">
            <Radar size={24} />
          </span>
          adwatch<span className="brand-dot">.</span>
        </div>
        {authenticated === null ? (
          <p role="status">Checking your session…</p>
        ) : (
          <>
            <h1>Sign in to Adwatch</h1>
            <p>Keep an eye on your competitors’ next move.</p>
            <form
              onSubmit={async (event) => {
                event.preventDefault();
                setBusy(true);
                setError("");
                try {
                  await api("/session", "POST", { username, password }, false);
                  authGeneration++;
                  setPassword("");
                  setAuthenticated(true);
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <label>
                Username
                <input
                  autoComplete="username"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  required
                />
              </label>
              <label>
                Password
                <input
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
              </label>
              {error && (
                <p className="login-error" role="alert">
                  {error}
                </p>
              )}
              <button className="primary full" disabled={busy}>
                {busy ? "Signing in…" : "Sign in"}
              </button>
            </form>
            <p className="hint">
              Use the login credentials in your installation’s .env file.
            </p>
          </>
        )}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <SignIn />
  </React.StrictMode>,
);
