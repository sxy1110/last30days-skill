"""chrome-main 9222 续 last30days X 票：ISE 后收活票，不开登录页。"""
from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from lib import bird_x, health, shen_x_renew
from lib.subproc import SubprocResult

SEARCH_500 = '{"error": "Internal server error", "items": []}'
SEARCH_OK = '[{"id": "1", "text": "tweet"}]'


@pytest.fixture(autouse=True)
def _reset():
    saved = dict(bird_x._credentials)
    bird_x._credentials.clear()
    bird_x.set_session_failover(None, None)
    bird_x.set_env_pair_renew(None)
    os.environ.pop("LAST30DAYS_SHEN_X_RENEW_TEST", None)
    os.environ.pop("LAST30DAYS_SHEN_X_RENEW", None)
    yield
    bird_x._credentials.clear()
    bird_x._credentials.update(saved)
    bird_x.set_session_failover(None, None)
    bird_x.set_env_pair_renew(None)
    os.environ.pop("LAST30DAYS_SHEN_X_RENEW_TEST", None)


def test_persist_env_pair_replaces_only_x_lines(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("FOO=keep\nAUTH_TOKEN=old\nCT0=oldct\nBAR=also\n", encoding="utf-8")
    assert shen_x_renew.persist_env_pair("new-auth", "new-ct0", path=p)
    text = p.read_text(encoding="utf-8")
    assert "FOO=keep" in text
    assert "BAR=also" in text
    assert "AUTH_TOKEN=new-auth" in text
    assert "CT0=new-ct0" in text
    assert "AUTH_TOKEN=old" not in text


def test_persist_appends_when_missing(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("FOO=1\n", encoding="utf-8")
    shen_x_renew.persist_env_pair("a" * 12, "b" * 12, path=p)
    text = p.read_text(encoding="utf-8")
    assert "FOO=1" in text
    assert "AUTH_TOKEN=" in text and "CT0=" in text


def test_source_never_opens_login():
    src = Path(shen_x_renew.__file__).read_text(encoding="utf-8")
    body = src.split('"""', 2)[-1]
    for banned in (
        "json/new",
        "createTarget",
        "activateTarget",
        "Target.activate",
        "x.com/login",
        "box-chrome",
        "18800",
    ):
        assert banned not in body, banned
    assert "9222" in src
    assert "NEED_HAND" in src
    assert "不开登录页" in src


def test_harvest_prefers_x_home_tab():
    pages = [
        {"type": "page", "url": "https://example.com", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/a"},
        {"type": "page", "url": "https://x.com/home", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/xhome"},
        {"type": "page", "url": "https://x.com/explore", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/xex"},
    ]
    with mock.patch.object(shen_x_renew, "_http_json", return_value=pages):
        assert shen_x_renew.pick_x_ws() == "ws://127.0.0.1:9222/devtools/page/xhome"


def test_renew_hook_need_hand_when_no_pair():
    os.environ["LAST30DAYS_SHEN_X_RENEW_TEST"] = "1"
    with mock.patch.object(shen_x_renew, "harvest_chrome_main", return_value=None):
        out = shen_x_renew.renew_hook("dead-token")
    assert out and out.get("need_hand")
    assert "NEED_HAND" in out["need_hand"]
    assert "不开登录页" in out["need_hand"]


def test_renew_hook_skips_under_pytest_without_flag():
    os.environ.pop("LAST30DAYS_SHEN_X_RENEW_TEST", None)
    with mock.patch.object(shen_x_renew, "harvest_chrome_main") as harvest:
        assert shen_x_renew.renew_hook("dead") is None
    harvest.assert_not_called()


def test_bird_ise_retries_after_chrome_main_pair(tmp_path: Path):
    os.environ["LAST30DAYS_SHEN_X_RENEW_TEST"] = "1"
    os.environ["LAST30DAYS_CONFIG_DIR"] = str(tmp_path)
    bird_x.set_credentials("dead-session-token-0000", "dead-ct0-0000000000")
    bird_x.set_env_pair_renew(shen_x_renew.renew_hook)
    live = {"auth_token": "live-session-token-1111", "ct0": "live-ct0-1111111111"}
    outputs = [
        (SubprocResult(returncode=0, stdout=SEARCH_500, stderr=""), None),
        (SubprocResult(returncode=0, stdout=SEARCH_OK, stderr=""), None),
    ]
    with mock.patch.object(shen_x_renew, "harvest_chrome_main", return_value=live), \
         mock.patch.object(bird_x, "_invoke_bird_subprocess", side_effect=outputs) as run:
        response = bird_x._run_bird_search("kanye", count=10, timeout=30)
    assert response.get("items") == [{"id": "1", "text": "tweet"}]
    assert run.call_count == 2
    assert bird_x._credentials["AUTH_TOKEN"] == live["auth_token"]
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "AUTH_TOKEN=live-session-token-1111" in env


def test_bird_ise_need_hand_is_auth_failed():
    os.environ["LAST30DAYS_SHEN_X_RENEW_TEST"] = "1"
    bird_x.set_credentials("dead-session-token-0000", "dead-ct0-0000000000")
    bird_x.set_env_pair_renew(shen_x_renew.renew_hook)
    with mock.patch.object(shen_x_renew, "harvest_chrome_main", return_value=None), \
         mock.patch.object(
             bird_x,
             "_invoke_bird_subprocess",
             return_value=(SubprocResult(returncode=0, stdout=SEARCH_500, stderr=""), None),
         ):
        response = bird_x._run_bird_search("kanye", count=10, timeout=30)
    assert "NEED_HAND" in response["error"]
    assert bird_x.classify_run_failure("bird: " + response["error"]) == health.AUTH_FAILED
