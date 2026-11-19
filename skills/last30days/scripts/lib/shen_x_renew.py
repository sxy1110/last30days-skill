"""chrome-main 9222 HTTP/CDP 续 last30days X 票。

.env 里 AUTH_TOKEN/CT0 冻死时，X GraphQL SearchTimeline 回 HTTP 200 +
Internal server error。浏览器首页可以还登着。

正路：已开的 chrome-main（127.0.0.1:9222）Network.getAllCookies 收
auth_token+ct0，写回 .env，Bird 再搜一次。

禁止开登录页、开新标签、抢焦点、钥匙串。没活票 NEED_HAND 停。
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Optional

from . import bird_x, chrome_cdp, log

CHROME_MAIN = "http://127.0.0.1:9222"
NEED_HAND = (
    "X session stale (env AUTH_TOKEN). NEED_HAND: chrome-main 打开 x.com 首页再跑。"
    "不开登录页。"
)


def renew_enabled() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get(
        "LAST30DAYS_SHEN_X_RENEW_TEST"
    ) != "1":
        return False
    return os.environ.get("LAST30DAYS_SHEN_X_RENEW", "1") != "0"


def env_path() -> Optional[Path]:
    override = os.environ.get("LAST30DAYS_CONFIG_DIR")
    if override == "":
        return None
    if override:
        return Path(override) / ".env"
    return Path.home() / ".config/last30days/.env"


def persist_env_pair(auth_token: str, ct0: str, path: Optional[Path] = None) -> bool:
    """Replace AUTH_TOKEN/CT0 lines only. Never overwrite the rest of .env."""
    target = path if path is not None else env_path()
    if target is None:
        return False
    if not auth_token or not ct0:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = target.read_text(encoding="utf-8") if target.is_file() else ""
    lines = raw.splitlines()
    out: list[str] = []
    seen_a = seen_c = False
    for line in lines:
        if line.startswith("AUTH_TOKEN="):
            out.append(f"AUTH_TOKEN={auth_token}")
            seen_a = True
        elif line.startswith("CT0="):
            out.append(f"CT0={ct0}")
            seen_c = True
        else:
            out.append(line)
    if not seen_a:
        out.append(f"AUTH_TOKEN={auth_token}")
    if not seen_c:
        out.append(f"CT0={ct0}")
    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    target.write_text(text, encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return True


def _http_json(url: str, timeout: float = 1.5) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def pick_x_ws(base: str = CHROME_MAIN) -> Optional[str]:
    """Pick an existing page websocket. Prefer x.com. Never create a tab."""
    try:
        targets = _http_json(f"{base.rstrip('/')}/json")
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(targets, list):
        return None
    pages = [t for t in targets if isinstance(t, dict) and t.get("type") == "page"]
    x_pages = []
    others = []
    for t in pages:
        url = str(t.get("url") or "")
        ws = t.get("webSocketDebuggerUrl")
        if not (isinstance(ws, str) and ws.startswith("ws://")):
            continue
        if "x.com" in url or "twitter.com" in url:
            x_pages.append((url, ws))
        else:
            others.append(ws)
    if x_pages:
        home = next((ws for url, ws in x_pages if "/home" in url), None)
        return home or x_pages[0][1]
    return others[0] if others else None


def harvest_chrome_main(base: str = CHROME_MAIN) -> Optional[dict[str, str]]:
    """Complete auth_token+ct0 from chrome-main, or None. Never logs values."""
    try:
        version = _http_json(f"{base.rstrip('/')}/json/version")
    except (OSError, ValueError, json.JSONDecodeError):
        log.source_log("X/renew", "chrome-main 9222 没应答", tty_only=False)
        return None
    browser = str((version or {}).get("Browser") or "").lower()
    if "chrome" not in browser and "chromium" not in browser:
        return None
    ws = pick_x_ws(base)
    if not ws:
        log.source_log("X/renew", "chrome-main 没有 page 目标", tty_only=False)
        return None
    cookies = chrome_cdp._get_all_cookies(ws)
    if not cookies:
        return None
    pair = chrome_cdp._pair_from_cookies(cookies)
    if not (pair.get("auth_token") and pair.get("ct0")):
        log.source_log("X/renew", "9222 没有完整 x.com 票", tty_only=False)
        return None
    return {"auth_token": pair["auth_token"], "ct0": pair["ct0"]}


def renew_hook(started_auth: Optional[str]) -> Optional[dict[str, str]]:
    """Bird ISE 时调用。新票 dict 重试；need_hand 停；None 保持原错。"""
    if not renew_enabled():
        return None
    pair = harvest_chrome_main()
    if not pair:
        return {"need_hand": NEED_HAND}
    if started_auth and pair["auth_token"] == started_auth:
        return {"need_hand": NEED_HAND}
    persist_env_pair(pair["auth_token"], pair["ct0"])
    log.source_log(
        "X/renew",
        "env AUTH_TOKEN 废了，已从 chrome-main 9222 收下活票",
        tty_only=False,
    )
    return pair


def install() -> None:
    bird_x.set_env_pair_renew(renew_hook)
