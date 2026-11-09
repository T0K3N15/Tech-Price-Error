
#!/usr/bin/env python3
"""Free RSS-based discovery scanner for possible tech pricing errors."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

STATE_FILE = Path("state/seen.json")
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
USER_AGENT = "TechPriceErrorScanner/1.0 (+https://github.com/T0K3N15/Tech-Price-Error)"

# Only accept listings published within this many hours.
MAX_AGE_HOURS = 24

# Allow a small clock difference between feed providers and UTC.
FUTURE_TOLERANCE_MINUTES = 5

FEEDS = [
    ("Slickdeals", "https://slickdeals.net/newsearch.php?mode=frontpage&searcharea=deals&searchin=title&rss=1"),
    ("r/buildapcsales", "https://www.reddit.com/r/buildapcsales/new/.rss"),
    ("r/deals", "https://www.reddit.com/r/deals/new/.rss"),
    ("r/pcdeals", "https://www.reddit.com/r/pcdeals/new/.rss"),
    (
        "Google News: pricing errors",
        "https://news.google.com/rss/search?q=" + urllib.parse.quote(
            '("price error" OR "pricing error" OR misprice OR mispriced) '
            '(GPU OR computer OR monitor OR electronics)'
        ) + "&hl=en-US&gl=US&ceid=US:en",
    ),
    (
        "Google News: extreme tech discounts",
        "https://news.google.com/rss/search?q=" + urllib.parse.quote(
            '(GPU OR CPU OR SSD OR laptop OR monitor OR OLED OR electronics) '
            '("90% off" OR "85% off" OR "80% off" OR "75% off" OR "70% off" OR "price glitch")'
        ) + "&hl=en-US&gl=US&ceid=US:en",
    ),
]

TECH_TERMS = re.compile(
    r"\b(gpu|graphics card|rtx|geforce|radeon|cpu|processor|ryzen|intel|"
    r"motherboard|ram|ddr[45]|memory|ssd|nvme|hard drive|psu|power supply|"
    r"pc|desktop|laptop|notebook|mini pc|workstation|monitor|oled|qled|"
    r"television|tv|projector|phone|smartphone|tablet|ipad|wearable|"
    r"headphones|earbuds|speaker|camera|electronics|router|keyboard|mouse)\b",
    re.I,
)

ERROR_TERMS = re.compile(
    r"\b(price error|pricing error|price mistake|pricing mistake|misprice|"
    r"mispriced|price glitch|pricing glitch|obvious error|mistake price|"
    r"incorrect price|incorrectly priced)\b",
    re.I,
)

EXTREME_TERMS = re.compile(
    r"\b(90%\s*off|85%\s*off|80%\s*off|75%\s*off|70%\s*off|"
    r"price glitch|pricing glitch|pricing error|price error)\b",
    re.I,
)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read(2_000_000)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def first_text(node: ET.Element, names: tuple[str, ...]) -> str:
    for child in node.iter():
        if local_name(child.tag) in names and child.text:
            return child.text.strip()
    return ""


def parse_published_date(item: ET.Element) -> datetime | None:
    """
    Read the original publication date from RSS or Atom.

    Prefer original publication/creation dates over updated dates,
    because an old listing can be refreshed without being a new deal.
    """
    date_fields = (
        "published",
        "pubdate",
        "created",
        "date",
        "updated",
    )

    raw_date = first_text(item, date_fields)

    if not raw_date:
        return None

    # First try RFC 2822 dates, commonly used by RSS.
    try:
        parsed = parsedate_to_datetime(raw_date)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    except (TypeError, ValueError, OverflowError):
        pass

    # Then try ISO 8601 dates, commonly used by Atom.
    try:
        parsed = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    except (TypeError, ValueError, OverflowError):
        return None


def parse_feed(data: bytes, source: str) -> list[dict]:
    root = ET.fromstring(data)
    entries = [
        node for node in root.iter()
        if local_name(node.tag) in ("item", "entry")
    ]

    found = []

    for item in entries[:100]:
        title = first_text(item, ("title",))
        link = first_text(item, ("link",))

        if not link:
            for child in item:
                if local_name(child.tag) == "link":
                    link = child.attrib.get("href", "")
                    if link:
                        break

        description = first_text(
            item,
            ("description", "summary", "content", "encoded"),
        )

        guid = first_text(item, ("guid", "id")) or link or title
        published_at = parse_published_date(item)

        if title and link:
            clean_description = html.unescape(
                re.sub(r"<[^>]+>", " ", description)
            )

            found.append({
                "source": source,
                "title": html.unescape(title).strip(),
                "link": link.strip(),
                "description": clean_description[:1500],
                "guid": guid,
                "published_at": published_at,
            })

    return found


def is_recent(item: dict, now: datetime) -> bool:
    published = item.get("published_at")

    # Missing or invalid publication dates are rejected.
    if not isinstance(published, datetime):
        return False

    age = now - published

    if age < timedelta(minutes=-FUTURE_TOLERANCE_MINUTES):
        return False

    if age > timedelta(hours=MAX_AGE_HOURS):
        return False

    return True


def format_age(published: datetime, now: datetime) -> str:
    minutes = max(0, int((now - published).total_seconds() / 60))

    if minutes < 60:
        return f"{minutes} minutes ago"

    hours = minutes // 60
    remaining_minutes = minutes % 60

    if hours < 24:
        return f"{hours}h {remaining_minutes}m ago"

    return "Over 24 hours ago"


def load_state() -> list[str]:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))

        return (
            data.get("seen", [])
            if isinstance(data.get("seen", []), list)
            else []
        )

    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def score_candidate(item: dict) -> str | None:
    combined = f"{item['title']} {item['description']}"

    if not TECH_TERMS.search(combined):
        return None

    if ERROR_TERMS.search(combined):
        return "Explicit pricing-error language"

    if EXTREME_TERMS.search(combined):
        return "Extreme discount / possible pricing glitch"

    return None


def post_discord(items: list[dict]) -> None:
    if not WEBHOOK:
        raise RuntimeError(
            "Missing DISCORD_WEBHOOK_URL GitHub Actions secret."
        )

    now = datetime.now(timezone.utc)

    lines = [
        "🚨 **Tech price-error candidates**",
        f"Showing listings published within the last {MAX_AGE_HOURS} hours.",
        "Public-feed leads only — verify the exact item and checkout price.",
        "",
    ]

    for item in items[:5]:
        published = item["published_at"]

        block = [
            f"**{item['title'][:180]}**",
            f"Source: {item['source']}",
            f"Signal: {item['reason']}",
            (
                f"Published: {published.strftime('%Y-%m-%d %H:%M UTC')} "
                f"({format_age(published, now)})"
            ),
            item["link"],
            "",
        ]

        if len("\n".join(lines + block)) > 1850:
            break

        lines.extend(block)

    lines.append(
        f"Checked: {now.strftime('%Y-%m-%d %H:%M UTC')}"
    )

    body = json.dumps({
        "content": "\n".join(lines),
        "allowed_mentions": {"parse": []},
    }).encode()

    request = urllib.request.Request(
        WEBHOOK,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=25) as response:
        if response.status not in (200, 204):
            raise RuntimeError(
                f"Discord returned HTTP {response.status}"
            )


def main() -> int:
    now = datetime.now(timezone.utc)

    seen_order = load_state()
    seen = set(seen_order)

    fresh = []

    stats = {
        "fetched": 0,
        "stale": 0,
        "missing_date": 0,
        "duplicates": 0,
        "candidates": 0,
    }

    for source, url in FEEDS:
        try:
            entries = parse_feed(fetch(url), source)

            print(f"{source}: fetched {len(entries)} entries")

            stats["fetched"] += len(entries)

            for entry in entries:
                fingerprint = hashlib.sha256(
                    (entry["guid"] + "|" + entry["link"]).encode()
                ).hexdigest()

                if fingerprint in seen:
                    stats["duplicates"] += 1
                    continue

                # Record the entry even if it is stale so it won't
                # be reconsidered on every subsequent scan.
                seen.add(fingerprint)
                seen_order.append(fingerprint)

                published = entry.get("published_at")

                if published is None:
                    stats["missing_date"] += 1
                    continue

                if not is_recent(entry, now):
                    stats["stale"] += 1
                    continue

                reason = score_candidate(entry)

                if reason:
                    entry["reason"] = reason
                    fresh.append(entry)
                    stats["candidates"] += 1

        except (
            urllib.error.URLError,
            TimeoutError,
            ET.ParseError,
            OSError,
        ) as exc:
            print(
                f"WARNING: {source} failed: {exc}",
                file=sys.stderr,
            )

        time.sleep(1)

    # Newest qualifying listings appear first.
    fresh.sort(
        key=lambda item: item["published_at"],
        reverse=True,
    )

    print("\n--- Scan summary ---")
    print(f"Total entries: {stats['fetched']}")
    print(f"Rejected as stale/future: {stats['stale']}")
    print(f"Rejected missing/invalid date: {stats['missing_date']}")
    print(f"Previously seen: {stats['duplicates']}")
    print(f"New qualifying candidates: {stats['candidates']}")

    if fresh:
        post_discord(fresh)

        print(
            f"Sent up to {min(len(fresh), 5)} "
            "new candidate(s) to Discord."
        )
    else:
        print("No new recent high-signal candidates.")

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    STATE_FILE.write_text(
        json.dumps(
            {"seen": seen_order[-5000:]},
            indent=2,
        ),
        encoding="utf-8",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
