"""Pure parser shared by the monitor and the backwards-compatible MCP tools."""

import re
from urllib.parse import parse_qs, urlparse


def _decode_landing_url(fb_link: str) -> str:
    """Turn an l.facebook.com/l.php?u=... redirect into the real destination URL."""
    try:
        qs = parse_qs(urlparse(fb_link).query)
        if "u" in qs:
            return qs["u"][0]
    except ValueError:
        pass
    return fb_link


# CTA button label sits as plain text immediately before the landing redirect link, e.g.
#   ... Learn more ](https://l.facebook.com/l.php?u=...)
# Match against Facebook's fixed set of button labels so we don't grab trailing caption words.
_CTA_LABELS = (
    "Learn more",
    "Sign up",
    "Shop now",
    "Book now",
    "Send message",
    "Send WhatsApp message",
    "Contact us",
    "Subscribe",
    "Get offer",
    "Get quote",
    "Apply now",
    "Download",
    "Watch more",
    "See menu",
    "Order now",
    "Donate now",
    "Play game",
    "Listen now",
    "Get showtimes",
    "Save",
    "Open link",
    "Message page",
    "Call now",
    "Get directions",
    "Follow page",
    "Use app",
    "Install now",
    "Buy tickets",
    "Request time",
    "Try in camera",
)
_CTA_RE = re.compile(
    r"\s("
    + "|".join(re.escape(c) for c in _CTA_LABELS)
    + r")\s*\]\(https://l\.facebook\.com/l\.php",
    re.IGNORECASE,
)


def _parse_ad_library_markdown(md: str) -> list[dict]:
    """Best-effort structured extraction of ad cards from rendered Ad Library markdown."""
    # Current markup places status immediately before the Library ID. Move it
    # into its own card so the next card's status cannot leak into this one.
    md = re.sub(
        r"(?m)^(Active|Inactive)[ \t]*\n\s*((?:\*\*)?Library ID:[^\n]*)", r"\2\nAd status: \1", md
    )
    ads = {}
    # Each card starts at a "Library ID: <digits>" line
    chunks = re.split(r"(?:^|\n)[ \t]*(?:\*\*)?Library ID:[ \t]*(?:\*\*)?[ \t]*", md)
    for chunk in chunks[1:]:
        lib_id = re.match(r"(\d+)", chunk)
        if not lib_id:
            continue
        lid = lib_id.group(1)
        ad = {
            "library_id": lid,
            "ad_details_url": f"https://www.facebook.com/ads/library/?id={lid}",
        }

        m = re.search(r"Started running on ([A-Za-z]+ \d{1,2}, \d{4})", chunk)
        ad["started_running"] = m.group(1) if m else None

        m = re.search(r"\*\*(\d+)\s+ads?\*\*\s+use this creative", chunk)
        ad["ads_using_creative"] = int(m.group(1)) if m else None

        # advertiser: first [Name](facebook.com/<handle>/) link in the block
        m = re.search(r"\[([^\]]+)\]\(https://www\.facebook\.com/([^/)]+)/?\)", chunk)
        if m:
            ad["advertiser"] = m.group(1)
            ad["advertiser_handle"] = m.group(2)

        # landing domain from the first l.facebook.com redirect
        m = re.search(r"\(https://l\.facebook\.com/l\.php\?u=([^)&]+)", chunk)
        if m:
            real = _decode_landing_url("https://l.facebook.com/l.php?u=" + m.group(1))
            ad["landing_url"] = real
            ad["landing_domain"] = urlparse(real).netloc

        # call-to-action button label (Learn more / Sign up / Send message / Shop now ...)
        m = _CTA_RE.search(chunk)
        ad["cta"] = next(
            (
                label
                for label in _CTA_LABELS
                if m and label.casefold() == m.group(1).strip().casefold()
            ),
            None,
        )

        # creative thumbnail + the headline/caption strip shown under it
        sponsored = re.split(r"(?:\*\*)?Sponsored(?:\*\*)?", chunk, maxsplit=1)
        creative_section = sponsored[-1] if len(sponsored) > 1 else ""
        # The first image in the card is often the advertiser's avatar.
        m = re.search(
            r"!\[[^\]]*\]\((https://scontent[^)]+?\.(?:jpe?g|png|webp)[^)]*)\)", creative_section
        )
        ad["creative_image"] = m.group(1) if m else None
        if ad["cta"]:
            # the creative card is [![<alt>](<img>) <headline/caption> <CTA> ](<l.facebook link>)
            m = re.search(
                r"\[!\[[^\]]*\]\(https?://scontent[^)]+\)\s+(.+?)\s+"
                + re.escape(ad["cta"])
                + r"\s*\]\(https://l\.facebook\.com",
                chunk,
                re.DOTALL | re.IGNORECASE,
            )
            if m:
                link_text = re.sub(r"\s+", " ", m.group(1)).strip()
                # drop a leading shouted domain token ("FB.ME", "GLYVER.NET")
                link_text = re.sub(r"^[A-Z0-9][A-Z0-9.\-]{2,}\s+", "", link_text)
                domain = ad.get("landing_domain", "").casefold()
                for suffix in {domain, domain.removeprefix("www.")}:
                    if suffix and link_text.casefold().endswith(" " + suffix):
                        link_text = link_text[: -(len(suffix) + 1)].strip()
                ad["link_text"] = link_text[:400]

        # body copy: text between "Sponsored" and the next structural marker
        body = re.search(
            r"(?:\*\*)?Sponsored(?:\*\*)?\s*\n(.+?)(?:\n\[?!\[|\nAd status:|\nActive\n|\nInactive\n|$)",
            chunk,
            re.DOTALL,
        )
        if body:
            txt = re.sub(r"\s+\n", "\n", body.group(1)).strip()
            # collapse "[visible text](l.facebook redirect)" links down to the visible text
            txt = re.sub(r"\[([^\]]+)\]\(https?://l\.facebook\.com[^)]*\)", r"\1", txt)
            # drop a trailing half-captured markdown link ("... offer: [https://x](https://l.fac")
            txt = re.sub(r"\s*\[[^\]]*\]\([^)]*$", "", txt).strip()
            ad["body"] = txt

        ad["platforms"] = [
            p for p in ("Facebook", "Instagram", "Audience Network", "Messenger") if p in chunk
        ]
        ad["status"] = (
            "inactive"
            if re.search(r"(?m)^(?:Ad status: )?Inactive[ \t]*$", chunk)
            else "active"
            if re.search(r"(?m)^(?:Ad status: )?Active[ \t]*$", chunk)
            else "unknown"
        )
        # A later viewport can hydrate richer fields for the same ID. Missing
        # fields from a partial rerender must not erase previously collected copy.
        stored = ads.setdefault(lid, {})
        stored.update({k: v for k, v in ad.items() if v is not None and v != [] and v != "unknown"})
        stored.setdefault("status", "unknown")
        stored.setdefault("platforms", [])
        for key in ("started_running", "cta", "creative_image", "ads_using_creative"):
            stored.setdefault(key, None)
    return list(ads.values())
