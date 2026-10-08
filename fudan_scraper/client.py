"""与 thesis.fudan.edu.cn 的接口交互：检索论文、获取在线阅读器地址。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import quote

import requests

from . import config


@dataclass
class Thesis:
    """一条检索结果。keyid 是后续所有接口的入场券。"""

    keyid: str          # 服务端返回的已是 URL 编码形式，原样回传即可
    title: str
    author: str = ""
    teacher: str = ""
    degree: str = ""
    year: str = ""

    def describe(self) -> str:
        return f"{self.title}（{self.author}，{self.degree}，{self.year}）"


class SiteError(RuntimeError):
    """接口返回异常时抛出，message 面向使用者。"""


class ThesisSite:
    """封装站点会话：统一的浏览器伪装、token、Cookie 与接口限速。"""

    def __init__(
        self,
        token: str | None = None,
        cookie: str | None = None,
        api_delay: float = config.DEFAULT_API_DELAY,
        timeout: float = config.REQUEST_TIMEOUT,
    ):
        self.api_delay = api_delay
        self.timeout = timeout
        self._last_request_at = 0.0

        self.session = requests.Session()
        self.session.headers.update(config.BASE_HEADERS)
        # 登录后从浏览器 localStorage 里复制的 token，接口以请求头形式携带
        if token:
            self.session.headers["token"] = token
        # DRM 阅读器页面有时需要站点会话，允许使用者整串粘贴 Cookie
        if cookie:
            self.session.headers["Cookie"] = cookie

    # ---- 内部工具 ------------------------------------------------------

    def _throttle(self) -> None:
        """简单的接口限速：距离上次请求不足 api_delay 秒则等待。"""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.api_delay:
            time.sleep(self.api_delay - elapsed)
        self._last_request_at = time.monotonic()

    def _request_json(self, method: str, url: str, **kwargs) -> dict:
        self._throttle()
        resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        return resp.json()

    # ---- 对外能力 ------------------------------------------------------

    def search(self, keyword: str, pagesize: int = 20) -> list[Thesis]:
        """按关键词检索，返回结果列表（匿名即可调用）。"""
        body = dict(config.SEARCH_BODY_TEMPLATE)
        body["curpage"] = 1
        body["pagesize"] = pagesize
        body["searchfields"] = [dict(config.SEARCH_BODY_TEMPLATE["searchfields"][0])]
        body["searchfields"][0]["keyword"] = keyword

        self._throttle()
        resp = self.session.post(
            config.SEARCH_API,
            json=body,
            headers={"Content-Type": "application/json;charset=UTF-8"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return self._parse_rows(resp.json())

    def _parse_rows(self, payload: dict) -> list[Thesis]:
        if payload.get("code") != 200:
            raise SiteError(f"检索接口返回异常：{payload.get('cnMessage') or payload}")

        rows = (payload.get("data") or {}).get("array") or []
        return [
            Thesis(
                keyid=row.get("keyid") or "",
                title=(row.get("title") or "").strip(),
                author=(row.get("author") or "").strip(),
                teacher=(row.get("teacher_name") or "").strip(),
                degree=(row.get("degree_type") or "").strip(),
                year=str(row.get("degree_year") or "").strip(),
            )
            for row in rows
        ]

    def pick(self, keyword: str, index: int | None = None) -> Thesis:
        """检索并选出目标论文：标题完全匹配优先，其次唯一结果，其次指定序号。"""
        results = self.search(keyword)
        if not results:
            raise SiteError(f"没有检索到与「{keyword}」相关的论文")

        if index is not None:
            if not 1 <= index <= len(results):
                raise SiteError(f"--index 需在 1~{len(results)} 之间")
            return results[index - 1]

        exact = [t for t in results if t.title == keyword]
        if len(exact) == 1:
            return exact[0]
        if len(results) == 1:
            return results[0]

        listing = "\n".join(f"  {i}. {t.describe()}" for i, t in enumerate(results, 1))
        raise SiteError(
            f"检索到 {len(results)} 条结果且无法自动确定目标，请用 --index 指定：\n{listing}"
        )

    def get_system_config(self) -> dict:
        """站点公开配置（匿名）：casloginUrl、PdfServerPath、loginType 等。"""
        data = self._request_json("GET", config.SYSTEM_CONFIG_API)
        return data.get("data") or {}

    def exchange_cas_login(
        self, learnid: str, name: str, vcode: str, tenantcode: str | None = None
    ) -> tuple[str, dict]:
        """用统一认证回跳参数换取 token，返回 (token, accountinfo)。"""
        params: dict = {"learnid": learnid, "name": name, "vcode": vcode}
        if tenantcode:
            params["tenantcode"] = tenantcode

        try:
            data = self._request_json("POST", config.CAS_LOGIN_API, params=params)
        except requests.HTTPError as err:
            raise SiteError(
                f"caslogin 请求失败（HTTP {err.response.status_code}）："
                "vcode 通常是一次性的，请重新运行 --login 再登录一次"
            ) from err

        if data.get("code") != 200 or not (data.get("data") or {}).get("token"):
            raise SiteError(f"换取 token 失败：{data.get('cnMessage') or data}")

        payload = data["data"]
        return payload["token"], payload.get("accountinfo") or {}

    def verify_token(self) -> bool:
        """用 account/getAccount 探一下 token 是否有效。"""
        try:
            data = self._request_json("GET", config.ACCOUNT_INFO_API)
        except requests.HTTPError:
            return False
        return data.get("code") == 200

    def get_reader_url(self, thesis: Thesis, isappend: int = 0) -> str:
        """获取在线阅读器页面地址（需要已登录的 token）。

        常规配置走 drmView，返回形如
        https://drm.fudan.edu.cn/read/pdfindex?... 的地址。
        部分配置走 GetEncryptionPath + PdfServer，这里一并兜底。
        """
        params = {"keyid": thesis.keyid, "isappend": isappend}

        # 常规配置：drmView 直接返回阅读器地址。
        # 未登录/无有效 token 时服务端可能直接 500，这里捕获后统一走兜底逻辑。
        try:
            data = self._request_json(
                "GET", config.DRM_VIEW_API, params={**params, "onlineflag": "online"}
            )
        except requests.HTTPError as err:
            data = {"cnMessage": f"drmView 请求失败（{err.response.status_code}）"}

        if data.get("code") == 200 and data.get("data"):
            return str(data["data"]).strip()

        # 备选配置：GetEncryptionPath 返回加密路径，交给 PdfServer 渲染
        try:
            fallback = self._request_json("POST", config.ENCRYPTION_PATH_API, params=params)
        except requests.HTTPError as err:
            fallback = {"cnMessage": f"GetEncryptionPath 请求失败（{err.response.status_code}）"}

        if fallback.get("code") == 200 and fallback.get("data"):
            path = str(fallback["data"]).strip()
            if path.startswith("http"):
                return path
            # 站点用 PdfServer 渲染：配置里存着服务地址，拼上加密路径即可
            pdf_server = str(self.get_system_config().get("PdfServerPath") or "").strip()
            if pdf_server:
                return f"{pdf_server.rstrip('/')}?path={quote(path, safe='')}"
            raise SiteError(
                f"GetEncryptionPath 返回的是加密路径（{path[:60]}...），"
                "但站点配置里没有 PdfServerPath，请改用 --from-html 方式：\n"
                "在浏览器里打开在线阅读页后 Ctrl+S 保存，把文件路径传给 --from-html"
            )

        message = fallback.get("cnMessage") or data.get("cnMessage") or "未知错误"
        raise SiteError(
            f"获取阅读器地址失败：{message}\n"
            "最常见原因是 token 缺失或已过期：先运行 py main.py --login 重新登录，\n"
            "或在浏览器里打开在线阅读页后 Ctrl+S 保存，改用 --from-html 方式。"
        )

    def fetch_html(self, url: str) -> str:
        """抓取阅读器页面源码。注意：drm 服务器把阅读会话绑定在本次请求的
        Cookie 上，后续 doTest/jumpServlet 必须复用同一个 session。"""
        self._throttle()
        resp = self.session.get(
            url,
            headers={**config.HTML_HEADERS, "Referer": config.BASE_URL + "/"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text

    def collect_image_urls(self, reader_url: str, html: str) -> list[str]:
        """从阅读器页面得到全部页面的图片地址（有序）。

        两种阅读器形态：
        1. 静态页：源码里直接写有 pdfboxServlet 地址 —— 正则提取；
        2. 动态页（personaliiifServlet，麦达 DRM）：源码只有 fid 等隐藏域，
           调一次 doTest?fid=...&startpage=1&endpage=总页数 即可拿到全部
           页面地址（默认缩略图规格），再统一改写为目标分辨率。
        """
        from .parser import extract_page_images, extract_reader_params, normalize_image_url

        static_urls = extract_page_images(html, base_url=reader_url)
        if static_urls:
            return [img.url for img in static_urls]

        params = extract_reader_params(html)
        fid = params.get("fid") or ""
        total = params.get("pageCount") or params.get("endpage") or ""
        if not fid or not total.isdigit():
            raise SiteError(
                "阅读器页面里既没有静态图片地址，也解析不到 fid/页数（可能抓到了错误页）"
            )

        self._throttle()
        resp = self.session.post(
            config.DRM_READ_BASE + "doTest",
            params={"fid": fid, "startpage": 1, "endpage": total},
            headers={"Referer": reader_url, "X-Requested-With": "XMLHttpRequest"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        try:
            payload = resp.json()
        except ValueError as err:
            raise SiteError(f"doTest 返回的不是 JSON（前 80 字符：{resp.text[:80]!r}）") from err

        urls = payload.get("list") if isinstance(payload, dict) else payload
        if not urls:
            raise SiteError("doTest 没有返回页面列表，阅读会话可能已失效，请重试")

        return [
            normalize_image_url(
                str(url), scale=config.IMAGE_SCALE, strip_watermark=config.STRIP_WATERMARK_PARAM
            )
            for url in urls
        ]
