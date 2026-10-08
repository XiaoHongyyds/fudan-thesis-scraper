
from __future__ import annotations

import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

TOKEN_CACHE_DIR = Path.home() / ".fudan-thesis-scraper"
TOKEN_CACHE_FILE = TOKEN_CACHE_DIR / "token.json"
LOGIN_TIMEOUT = 300  # 等待用户在浏览器完成登录的最长时间（秒）


# ---- token 本地缓存 -----------------------------------------------------
# 注意：站点把 token 和登录会话的 Cookie 绑定校验，二者必须一起缓存、一起使用。

def load_cached_token() -> str | None:
    return (load_auth() or {}).get("token")


def load_auth() -> dict | None:
    """读取缓存的登录态：{token, cookies, account, saved_at}，损坏或不存在返回 None。"""
    try:
        data = json.loads(TOKEN_CACHE_FILE.read_text(encoding="utf-8"))
        return data if data.get("token") else None
    except (OSError, ValueError):
        return None


def save_token(token: str, account: dict | None = None, cookies: dict | None = None) -> Path:
    TOKEN_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "token": token,
        "cookies": cookies or {},
        "account": account or {},
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    TOKEN_CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    return TOKEN_CACHE_FILE


# ---- 本地回调服务器 -------------------------------------------------------

class _CallbackRecorder:
    """线程安全地保存回调参数。"""

    def __init__(self):
        self.event = threading.Event()
        self.params: dict[str, str] = {}


def _make_handler(recorder: _CallbackRecorder):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802（http.server 约定命名）
            query = parse_qs(urlparse(self.path).query)
            vcode = (query.get("vcode") or [""])[0]
            if not vcode:
                # CAS 偶尔会先跳一跳无关地址，忽略之
                self._respond("<h3>等待认证回调…</h3>")
                return
            recorder.params = {k: v[-1] for k, v in query.items()}
            recorder.event.set()
            self._respond(
                "<h3>登录成功！</h3><p>凭证已收到，可以关闭这个页面，回到终端查看进度。</p>"
            )

        def _respond(self, html: str):
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # 静默默认访问日志
            pass

    return Handler


def _params_from_pasted_url(text: str) -> dict[str, str]:
    """用户手动粘贴登录后浏览器地址栏的 URL。"""
    text = text.strip()
    query = parse_qs(urlparse(text).query)
    return {k: v[-1] for k, v in query.items() if v}


# ---- 对外入口 ------------------------------------------------------------

def browser_login(site, log=print) -> tuple[str, dict]:
    """跑完整登录流程，返回 (token, accountinfo)。

    site: fudan_scraper.client.ThesisSite，用于读配置和调用 caslogin。
    """
    config_data = site.get_system_config()
    caslogin_url = (config_data.get("casloginUrl") or "").strip()
    if not caslogin_url:
        raise RuntimeError("站点配置里没有 casloginUrl，无法进行统一认证登录")

    recorder = _CallbackRecorder()
    server = HTTPServer(("127.0.0.1", 0), _make_handler(recorder))
    port = server.server_address[1]
    callback_url = f"http://127.0.0.1:{port}/callback"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    login_entry = f"{caslogin_url}?url={quote(callback_url, safe='')}"
    log("正在打开浏览器进行统一认证登录……")
    log(f"若浏览器没有自动弹出，请手动访问：\n  {login_entry}")
    webbrowser.open(login_entry)
    log(f"等待登录回调（最长 {LOGIN_TIMEOUT // 60} 分钟），登录完成后浏览器会跳到本机地址。")

    params: dict[str, str] = {}
    try:
        if not recorder.event.wait(timeout=LOGIN_TIMEOUT):
            log("等待超时。")
            log("（若页面已自动跳转丢了参数，也可以直接粘贴 F12 → Local Storage 里的 token）")
            try:
                pasted = input("> ").strip()
            except EOFError:
                raise RuntimeError(
                    "等待登录回调超时且当前环境无法交互输入。"
                    "请在真实终端重新运行，或改用 --token <值> 手动指定。"
                ) from None
            if pasted.startswith("http"):
                params = _params_from_pasted_url(pasted)
            elif pasted:
                # 直接给了 token
                return pasted, {}
            if not params.get("vcode"):
                raise RuntimeError("没有拿到 vcode，登录失败")
        else:
            params = dict(recorder.params)
    finally:
        server.shutdown()
        thread.join(timeout=5)

    log("已收到认证回调，正在换取 token……")
    from . import config

    token, account = site.exchange_cas_login(
        learnid=params.get("learnid", ""),
        name=params.get("name", ""),
        vcode=params["vcode"],
        # 回跳参数里通常不带 tenantcode，但接口必需，用站点租户号兜底
        tenantcode=params.get("tenantcode") or config.DEFAULT_TENANTCODE,
    )
    # token 与登录会话 Cookie 绑定校验，必须连 cookie 一起缓存
    cookies = site.session.cookies.get_dict()
    site.session.headers["token"] = token  # 后续校验/抓取复用同一会话
    save_token(token, account, cookies)
    return token, account
