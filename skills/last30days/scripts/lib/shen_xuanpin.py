"""Shen overlay: 调查口并入 last30days。国内风控走 xhs_search，Chrome 口串行。

新口：google_trends / baidu_index / tiktok_ads。
xiaohongshu 正路 xhs_search.py，禁止 xiaohongshu-mcp。
失败返回 []，不把整次 last30days 打挂。
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

WS = Path("/Users/shen/工作空间")
TOOLS = WS / "_claude_tools"
TT_DIR = WS / "竞品情报工具"
PY311 = Path.home() / ".venvs/main311/bin/python3"
XHS_SEARCH = (
    WS / "公司/运营/1688/modules/01_自进化上架/小红书图搜逆向/scripts/xhs_search.py"
)
HOLD = Path.home() / ".xhs-imgsearch/login_risk_hold.json"
CHROME_LOCK = Path.home() / ".config/last30days/chrome-main.lock"


def _py() -> str:
    if PY311.is_file():
        return str(PY311)
    return sys.executable


def _run_json(argv: list[str], *, timeout: float = 90.0) -> dict[str, Any]:
    fd, path = tempfile.mkstemp(prefix="l30-", suffix=".json")
    os.close(fd)
    cmd = list(argv)
    if "--out" not in cmd:
        cmd.extend(["--out", path])
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        raw = Path(path).read_text(encoding="utf-8") if Path(path).is_file() else ""
        if not raw.strip():
            return {}
        blob = json.loads(raw)
        return blob if isinstance(blob, dict) else {}
    except Exception:
        return {}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

AVAILABLE = ("google_trends", "baidu_index", "tiktok_ads", "meta_ads", "ig_tags")


def xhs_ready() -> bool:
    return XHS_SEARCH.is_file()


def xhs_blocked() -> bool:
    return HOLD.is_file()


@contextmanager
def chrome_lock():
    """Trends / 百度指数 / 创意中心 via-tab 都打 chrome-main 9222，必须串行。"""
    CHROME_LOCK.parent.mkdir(parents=True, exist_ok=True)
    handle = open(CHROME_LOCK, "a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        handle.close()


def _item(*, iid: str, title: str, snippet: str, url: str, **extra: Any) -> dict[str, Any]:
    body = {
        "id": iid,
        "title": title[:160],
        "snippet": snippet[:400],
        "url": url,
        "relevance": extra.get("relevance", 0.7),
        "why_relevant": extra.get("why") or title[:80],
        "metadata": extra.get("metadata") or {},
    }
    if extra.get("date"):
        body["date"] = extra["date"]
    if extra.get("engagement"):
        body["engagement"] = extra["engagement"]
    return body


def search_google_trends(topic: str, *, geo: str = "US") -> list[dict[str, Any]]:
    q = topic.strip()
    if not q:
        return []
    with chrome_lock():
        blob = _run_json(
            [_py(), str(TOOLS / "google_trends_http.py"), "--geo", geo, q],
            timeout=80,
        )
    href = str(blob.get("href") or "https://trends.google.com/trends/")
    out = []
    for row in blob.get("series") or []:
        c = row.get("class") or {}
        name = row.get("term") or q
        why = f"Google Trends {geo} {c.get('kind')} {c.get('why')}"
        out.append(
            _item(
                iid=f"gt:{geo}:{name}",
                title=f"Trends {geo} · {name} · {c.get('kind')}",
                snippet=why,
                url=href,
                why=why,
                metadata={"kind": c.get("kind"), "geo": geo},
            )
        )
    return out


def search_baidu_index(topic: str) -> list[dict[str, Any]]:
    words = [w for w in topic.replace(",", " ").split() if w][:2] or [topic]
    argv = [_py(), str(TOOLS / "baidu_index_http.py"), *words]
    with chrome_lock():
        blob = _run_json(argv, timeout=50)
    if not blob.get("ok") and not blob.get("series"):
        return []
    out = []
    for row in blob.get("series") or []:
        c = row.get("class") or {}
        why = (
            f"百度指数 {row.get('word')} {c.get('kind')} "
            f"avg={row.get('avg')} yoy={row.get('yoy')} qoq={row.get('qoq')}"
        )
        out.append(
            _item(
                iid=f"baidu:{row.get('word')}",
                title=f"百度指数 · {row.get('word')} · {c.get('kind')}",
                snippet=why,
                url=str(blob.get("href") or "https://index.baidu.com/"),
                why=why,
                metadata={"avg": row.get("avg"), "yoy": row.get("yoy"), "qoq": row.get("qoq")},
            )
        )
    return out


def search_tiktok_ads(topic: str, *, country: str = "US") -> list[dict[str, Any]]:
    script = str(TT_DIR / "tt_creative_http.py")
    with chrome_lock():
        blob = _run_json(
            [_py(), script, topic, "--country", country, "--period", "30"],
            timeout=50,
        )
        ads = blob.get("ads") or []
        period = 30
        if not ads:
            blob = _run_json(
                [_py(), script, topic, "--country", country, "--period", "180"],
                timeout=50,
            )
            ads = blob.get("ads") or []
            period = 180
    if not ads:
        why = f"TikTok 创意中心 {country} {period}d 「{topic}」无广告"
        return [
            _item(
                iid=f"ttads:empty:{topic}",
                title=why,
                snippet=why,
                url="https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en",
                why=why,
                relevance=0.4,
            )
        ]
    out = []
    for ad in ads[:8]:
        title = (ad.get("ad_title") or "")[:120] or "(无标题)"
        brand = ad.get("brand_name") or "—"
        out.append(
            _item(
                iid=f"ttads:{ad.get('id')}",
                title=f"[{brand}] {title}",
                snippet=f"like={ad.get('like')} ctr={ad.get('ctr')} period={period}d",
                url="https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en",
                why="TikTok 创意中心广告",
                engagement={"likes": ad.get("like") or 0},
                metadata={"period": period, "via": (blob.get("summary") or {}).get("via")},
            )
        )
    return out


def search_meta_ads(topic: str, *, country: str = "US") -> list[dict[str, Any]]:
    q = topic.strip()
    if not q:
        return []
    with chrome_lock():
        blob = _run_json(
            [_py(), str(TT_DIR / "meta_adlib.py"), q, "--country", country, "--first", "12"],
            timeout=70,
        )
    ads = blob.get("ads") or []
    if not blob.get("ok"):
        err = str(blob.get("error") or "")
        if blob.get("need_hand") or "NEED_HAND" in err:
            return []
        return []
    out = []
    for ad in ads[:8]:
        title = (ad.get("title") or ad.get("page_name") or "")[:120]
        body = (ad.get("body") or "")[:220]
        out.append(
            _item(
                iid=f"meta:{ad.get('ad_archive_id')}",
                title=f"{ad.get('page_name') or '—'} · {title or body[:40]}",
                snippet=body or str(ad.get("cta_text") or ""),
                url="https://www.facebook.com/ads/library/?id=" + str(ad.get("ad_archive_id") or ""),
                why="Meta 广告库 page-fetch",
                metadata={"platforms": ad.get("publisher_platform"), "format": ad.get("display_format")},
            )
        )
    if not out:
        why = f"Meta 广告库 {country} 「{q}」无广告"
        return [_item(iid=f"meta:empty:{q}", title=why, snippet=why, url="https://www.facebook.com/ads/library/", why=why, relevance=0.4)]
    return out


def search_ig_tags(topic: str, *, limit: int = 8) -> list[dict[str, Any]]:
    # tags/search 要带空格的原词（dachshund harness → #dachshundharness）。
    # 拼成 dachshundharness 会 0 条。reels 500 才走无空格形。
    q = topic.strip()
    if not q:
        return []
    with chrome_lock():
        blob = _run_json(
            [_py(), str(TOOLS / "ig_search_http.py"), "--own", q, "--limit", str(limit)],
            timeout=70,
        )
    if not blob.get("ok"):
        return []
    out = []
    for it in blob.get("items") or []:
        nm = str(it.get("title") or "").lstrip("#")
        out.append(
            _item(
                iid=f"igtag:{nm}",
                title=it.get("title") or nm,
                snippet=f"media_count={it.get('media')}",
                url=it.get("url") or "",
                why="IG 自己号 tags/search",
                engagement={"posts": it.get("media") or 0},
            )
        )
    return out[:limit]


def search_xhs(topic: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """国内口。xhs_search 自己 begin_click。hold 在就跳过。"""
    if not xhs_ready() or xhs_blocked():
        return []
    if not topic.strip():
        return []
    fd, path = tempfile.mkstemp(prefix="l30-xhs-", suffix=".json")
    os.close(fd)
    try:
        proc = subprocess.run(
            [sys.executable, str(XHS_SEARCH), topic.strip(), "--limit", str(limit), "--json", path],
            cwd=str(XHS_SEARCH.parent),
            capture_output=True,
            text=True,
            timeout=90,
        )
        if proc.returncode not in (0, None) and not Path(path).is_file():
            return []
        raw = Path(path).read_text(encoding="utf-8") if Path(path).is_file() else ""
        if not raw.strip():
            return []
        blob = json.loads(raw)
    except Exception:
        return []
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    rows = []
    if isinstance(blob, list):
        rows = blob
    elif isinstance(blob, dict):
        rows = blob.get("items") or blob.get("notes") or blob.get("feeds") or []
    out = []
    for it in rows[:limit]:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or it.get("desc") or "")[:120]
        nid = str(it.get("id") or it.get("note_id") or "")
        url = str(it.get("url") or "")
        if not url and nid:
            tok = str(it.get("xsec_token") or "")
            url = f"https://www.xiaohongshu.com/explore/{nid}"
            if tok:
                url += f"?xsec_token={tok}"
        out.append(
            _item(
                iid=f"xhs:{nid or title[:20]}",
                title=title or "(小红书)",
                snippet=str(it.get("desc") or it.get("title") or "")[:400],
                url=url,
                why="小红书搜字 xhs_search",
                engagement={
                    "likes": it.get("liked") or it.get("likes") or 0,
                    "comments": it.get("comments") or 0,
                },
            )
        )
    return out
