#!/usr/bin/env python3
"""Render a slim, animated 12-week GitHub activity pulse."""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUTPUT = Path("assets/activity-pulse.svg")
USERNAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def fetch_activity(username: str, token: str) -> tuple[list[tuple[str, int]], int]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=83)
    payload = json.dumps(
        {
            "query": QUERY,
            "variables": {
                "login": username,
                "from": start.isoformat(),
                "to": end.isoformat(),
            },
        }
    ).encode()
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "ElrhAhmed-profile-activity",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"GitHub activity request failed: {error}") from error

    if result.get("errors"):
        raise RuntimeError(f"GitHub GraphQL error: {result['errors'][0]['message']}")
    user = result.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user not found: {username}")

    calendar = user["contributionsCollection"]["contributionCalendar"]
    days = [
        (day["date"], int(day["contributionCount"]))
        for week in calendar["weeks"]
        for day in week["contributionDays"]
    ][-84:]
    return days, sum(count for _, count in days)


def render_svg(
    username: str,
    days: list[tuple[str, int]],
    total: int,
    *,
    syncing: bool = False,
) -> str:
    if len(days) != 84:
        raise ValueError("activity pulse requires exactly 84 days")

    width, height = 900, 132
    left, right, baseline = 34, 866, 82
    maximum = max((count for _, count in days), default=0)
    span = right - left
    points: list[tuple[float, float, float, int]] = []
    for index, (_, count) in enumerate(days):
        ratio = math.sqrt(count / maximum) if maximum else 0
        x = left + span * index / (len(days) - 1)
        y = baseline - ratio * 42
        points.append((x, y, ratio, count))

    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in points)
    dots = "\n".join(
        (
            f'    <circle class="day" cx="{x:.1f}" cy="{y:.1f}" '
            f'r="{1.4 + ratio * 2.6:.1f}" opacity="{0.16 + ratio * 0.78:.2f}"/>'
        )
        for x, y, ratio, count in points
        if count
    )
    start_label = html.escape(days[0][0])
    end_label = html.escape(days[-1][0])
    safe_username = html.escape(username)
    total_label = "SYNCING ON FIRST RUN" if syncing else f"{total} CONTRIBUTIONS"

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">{safe_username} public GitHub activity pulse</title>
  <desc id="desc">A subtle animated line representing public contribution activity over the last twelve weeks.</desc>
  <style>
    :root {{ --ink:#dce7f4; --muted:#71839a; --line:#2b3d52; --amber:#f59e0b; --blue:#58a6ff; }}
    .label {{ font:600 10px "Red Hat Display","Segoe UI",sans-serif; letter-spacing:2px; fill:var(--muted); }}
    .amber-stop {{ stop-color:var(--amber); }}
    .blue-stop {{ stop-color:var(--blue); }}
    .pulse {{ fill:none; stroke:url(#pulse-ink); stroke-width:1.6; stroke-linecap:round; stroke-linejoin:round; }}
    .day {{ fill:var(--ink); }}
    .runner {{ animation:travel 7s 1.4s ease-in-out infinite; }}
    @keyframes travel {{ 0% {{ transform:translateX(0); opacity:0; }} 10% {{ opacity:1; }} 85% {{ opacity:1; }} 100% {{ transform:translateX(832px); opacity:0; }} }}
    @media (prefers-color-scheme:light) {{
      :root {{ --ink:#27364a; --muted:#65758a; --line:#d7e0ea; --amber:#c86f00; --blue:#1769aa; }}
    }}
    @media (prefers-reduced-motion:reduce) {{
      .runner {{ display:none; }}
    }}
  </style>
  <defs>
    <linearGradient id="pulse-ink" x1="{left}" y1="0" x2="{right}" y2="0" gradientUnits="userSpaceOnUse">
      <stop class="amber-stop" offset="0" stop-opacity=".28"/>
      <stop class="blue-stop" offset=".48"/>
      <stop class="amber-stop" offset="1" stop-opacity=".28"/>
    </linearGradient>
    <filter id="runner-glow" x="-300%" y="-300%" width="700%" height="700%">
      <feGaussianBlur stdDeviation="3" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <text class="label" x="{left}" y="17">PUBLIC ACTIVITY · 12 WEEKS</text>
  <text class="label" x="{right}" y="17" text-anchor="end">{total_label}</text>
  <path d="M{left} {baseline}H{right}" stroke="var(--line)" stroke-width="1"/>
  <polyline class="pulse" points="{polyline}"/>
{dots}
  <circle class="runner" cx="{left}" cy="{baseline}" r="3.2" fill="var(--amber)" filter="url(#runner-glow)"/>
  <text class="label" x="{left}" y="120">{start_label}</text>
  <text class="label" x="{right}" y="120" text-anchor="end">{end_label}</text>
</svg>
"""


def preview_days() -> list[tuple[str, int]]:
    start = datetime.now(timezone.utc).date() - timedelta(days=83)
    return [
        ((start + timedelta(days=index)).isoformat(), 0)
        for index in range(84)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        sample = preview_days()
        sample[12] = (sample[12][0], 3)
        sample[57] = (sample[57][0], 8)
        rendered = render_svg("ElrhAhmed", sample, 11)
        ET.fromstring(rendered)
        assert "11 CONTRIBUTIONS" in rendered
        assert rendered.count('class="day"') == 2
        return 0

    username = os.environ.get("GH_USER", "ElrhAhmed")
    if not USERNAME_RE.fullmatch(username):
        raise SystemExit("invalid GitHub username")

    if args.preview:
        days, total, syncing = preview_days(), 0, True
    else:
        token = os.environ.get("GH_TOKEN")
        if not token:
            raise SystemExit("GH_TOKEN is required")
        days, total = fetch_activity(username, token)
        syncing = False

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        render_svg(username, days, total, syncing=syncing),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
