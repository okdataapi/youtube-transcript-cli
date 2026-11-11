#!/usr/bin/env python3
"""yt-transcript: get the transcript of a YouTube video as text, SRT, VTT, Markdown or JSON.

Works from any machine, including servers and CI where direct caption requests often get blocked: the data comes
from the okdata API (https://okdata.online), $0.004 per video. Python 3.9+, standard library only.
The key goes in the OKDATA_API_KEY environment variable.

    yt-transcript https://www.youtube.com/watch?v=dQw4w9WgXcQ
    yt-transcript dQw4w9WgXcQ --lang en --format srt -o talk.srt
    yt-transcript URL1 URL2 URL3 --format md -o transcripts/
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

VERSION = "0.1.0"
SOURCE = "gh-youtube-transcript-cli"
SIGN_UP = f"https://okdata.online/signup/?src={SOURCE}"
API = os.environ.get("OKDATA_BASE_URL", "https://api.okdata.online").rstrip("/")
PRICE = Decimal("0.004")  # youtube.videos.transcript.get, per video
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
PATH_ID = re.compile(r"^/(?:shorts|live|embed|v|e)/([A-Za-z0-9_-]{11})")
FORMATS = ("txt", "srt", "vtt", "md", "json")
RETRY_STATUSES = {429, 500, 502, 503, 504}


class ApiError(Exception):
    def __init__(self, code: str, message: str, *, charged: Optional[bool] = False, retry: str = "no",
                 retry_after: Optional[float] = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.charged, self.retry, self.retry_after = code, charged, retry, retry_after


def video_id(target: str) -> str:
    """The 11-character id from an id, a watch link, a youtu.be link, or a shorts/live/embed link."""
    target = target.strip()
    if VIDEO_ID.match(target):
        return target
    parts = urlsplit(target if "://" in target else f"https://{target}")
    host = (parts.hostname or "").lower()
    if host == "youtu.be" or host.endswith(".youtu.be"):
        candidate = parts.path.strip("/").split("/")[0]
    elif host == "youtube.com" or host.endswith(".youtube.com") or host == "youtube-nocookie.com" or host.endswith(".youtube-nocookie.com"):
        found = PATH_ID.match(parts.path)
        candidate = found.group(1) if found else (parse_qs(parts.query).get("v") or [""])[0]
    else:
        candidate = ""
    if not VIDEO_ID.match(candidate):
        raise ValueError(f"not a YouTube video link or id: {target!r}")
    return candidate


def fetch(video: str, lang: Optional[str], key: str, sleep: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    """One paid call; retries reuse the Idempotency-Key so a retry is never charged twice."""
    query = urlencode({k: v for k, v in {"id": video, "lang": lang}.items() if v})
    headers = {"Authorization": f"Bearer {key}", "Idempotency-Key": str(uuid.uuid4()), "Accept": "application/json",
               "User-Agent": f"{SOURCE}/{VERSION}"}
    return request_json(f"{API}/v1/youtube/videos/transcript/get?{query}", headers, sleep)


def _http_error(exc: HTTPError) -> ApiError:
    try:
        body = json.loads(exc.read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        body = None
    if isinstance(body, dict) and "code" in body:
        return ApiError(str(body["code"]), str(body.get("message")), charged=body.get("charged", False),
                        retry=str(body.get("retry", "no")), retry_after=body.get("retry_after_seconds"))
    return ApiError(f"http_{exc.code}", str(exc.reason), charged=None, retry="yes" if exc.code in RETRY_STATUSES else "no")


def request_json(url: str, headers: Dict[str, str], sleep: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    """GET with up to 2 retries on the same Idempotency-Key, so a retry is never charged twice. After a lost
    answer the call may still be running on the server: wait for it, and if we give up, say the charge is unknown."""
    retries, waits, ambiguous = 0, 0, False
    while True:
        try:
            with urlopen(Request(url, headers=headers), timeout=90) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if isinstance(body, dict) and body.get("code") == "ok":
                return body
            err = (ApiError(str(body.get("code")), str(body.get("message"))) if isinstance(body, dict)
                   else ApiError("bad_response", "unexpected answer", charged=None, retry="same_key"))
        except HTTPError as exc:
            err = _http_error(exc)
        except (OSError, ValueError, http.client.HTTPException) as exc:  # network, timeout, cut-off or non-JSON body
            err = ApiError("connection_error", str(exc), charged=None, retry="same_key")
        ambiguous = ambiguous or err.charged is None
        if ambiguous and err.code == "rate_limited" and waits < 5:
            waits += 1
            sleep(_wait(err.retry_after, 1.0))
            continue
        if err.retry not in ("yes", "same_key") or retries == 2:
            if ambiguous and err.charged is False:
                err.charged = None  # an earlier attempt may still finish and be billed
            raise err
        sleep(_wait(err.retry_after, 2.0 ** retries))
        retries += 1


def _wait(value: Any, default: float) -> float:
    """Seconds to sleep: the server's hint if it is a sane number, capped at 30."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(seconds, 0.0), 30.0)


def use_utf8() -> None:
    """Chinese text in and out, also on Windows consoles and pipes."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace" if stream is sys.stderr else "strict")


# --- formats --------------------------------------------------------------------------------------

def clock(seconds: float, sep: str = ",") -> str:
    """3725.5 -> 01:02:05,500 (SRT) or 01:02:05.500 (VTT)."""
    ms = int(round(max(0.0, seconds) * 1000))
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def short_clock(seconds: float) -> str:
    total = int(seconds)
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def render(t: Dict[str, Any], fmt: str) -> str:
    segments: List[Dict[str, Any]] = t.get("segments") or []
    vid = t.get("video_id", "")
    if fmt == "json":
        return json.dumps(t, ensure_ascii=False, indent=2) + "\n"
    if fmt == "txt":
        return (t.get("text") or " ".join(s["text"] for s in segments)).strip() + "\n"
    if fmt == "srt":
        blocks = [f"{i}\n{clock(s['start'])} --> {clock(s['end'])}\n{s['text'].strip()}\n" for i, s in enumerate(segments, 1)]
        return "\n".join(blocks)
    if fmt == "vtt":
        blocks = [f"{clock(s['start'], '.')} --> {clock(s['end'], '.')}\n{s['text'].strip()}\n" for s in segments]
        return "WEBVTT\n\n" + "\n".join(blocks)
    if fmt == "md":
        lines = [f"# Transcript of https://youtu.be/{vid} ({t.get('lang', '?')})", ""]
        lines += [f"- [{short_clock(s['start'])}](https://youtu.be/{vid}?t={int(s['start'])}) {s['text'].strip()}" for s in segments]
        return "\n".join(lines) + "\n\n_Source: YouTube via okdata._\n"
    raise ValueError(f"unknown format {fmt}")


# --- command line ----------------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    use_utf8()
    p = argparse.ArgumentParser(prog="yt-transcript", description="YouTube transcripts as text, SRT, VTT, Markdown or JSON (okdata API, $0.004 a video).")
    p.add_argument("videos", nargs="+", help="YouTube links or 11-character video ids")
    p.add_argument("--lang", help="preferred transcript language, e.g. en or zh (default: the original)")
    p.add_argument("--format", choices=FORMATS, default="txt")
    p.add_argument("-o", "--output", help="a file (one video) or a folder (several videos); default: stdout")
    p.add_argument("--budget", type=Decimal, default=Decimal("1"), help="refuse runs that could cost more (USD, default 1)")
    p.add_argument("--dry-run", action="store_true", help="print the cost and stop")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = p.parse_args(argv)

    try:
        ids = list(dict.fromkeys(video_id(v) for v in args.videos))  # unique, in order
    except ValueError as err:
        p.error(str(err))
    cost = PRICE * len(ids)
    print(f"{len(ids)} video(s), at most ${cost}", file=sys.stderr)
    if args.dry_run:
        return 0
    if cost > args.budget:
        print(f"over the --budget of ${args.budget}", file=sys.stderr)
        return 3
    key = os.environ.get("OKDATA_API_KEY", "").strip()
    if not key:
        print(f"OKDATA_API_KEY is not set. Get a key at {SIGN_UP}", file=sys.stderr)
        return 2

    folder = Path(args.output) if args.output and (len(ids) > 1 or Path(args.output).is_dir()) else None
    if folder:
        folder.mkdir(parents=True, exist_ok=True)
    spent, failed = Decimal("0"), 0
    for vid in ids:
        try:
            body = fetch(vid, args.lang, key)
        except ApiError as err:
            failed += 1
            print(f"{vid}: {err} (charged: {err.charged})", file=sys.stderr)
            if err.code in ("unauthorized", "insufficient_balance"):
                return 1
            continue
        spent += Decimal((body.get("meta") or {}).get("billing", {}).get("amount", "0"))
        item = (body.get("data") or {}).get("item") or {}
        fmt = args.format
        try:
            text = render(item, fmt)
        except (KeyError, TypeError, ValueError) as exc:
            # Already paid for: keep the raw answer rather than lose it.
            print(f"{vid}: could not format as {fmt} ({exc!r}); saved the raw JSON instead", file=sys.stderr)
            fmt, text = "json", render(item, "json")
        if folder:
            (folder / f"{vid}.{fmt}").write_text(text, encoding="utf-8")
        elif args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
    print(f"done: {len(ids) - failed} of {len(ids)}; spent ${spent}", file=sys.stderr)
    return 1 if failed == len(ids) else 0


if __name__ == "__main__":
    sys.exit(main())
