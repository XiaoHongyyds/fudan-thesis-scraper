
from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import parse_qs, urljoin


@dataclass(frozen=True)
class PageImage:
    """一页论文图片。order 保留其在源码中出现的先后，即页码顺序。"""

    url: str
    pdfname: str
    page: str
    scale: float


# 匹配 pdfboxServlet 地址。允许 http(s) 绝对地址、// 开头、/ 开头和相对形式，
# 终止于引号、空白、反斜杠（JS 字符串转义）或尖括号（HTML 属性）。
_URL_PATTERN = re.compile(
    r"(?:https?://[^\s\"'<>\\]+?)?"
    r"(?:/read/)?pdfboxServlet\?[^\s\"'<>\\]+",
    re.IGNORECASE,
)

# 命中水印相关关键词的地址一律丢弃（在线预览水印版）
_WATER_MARK_HINT = re.compile(r"water", re.IGNORECASE)


def _scale_value(raw: str | None) -> float:
    """scale 形如 3f / 3 / 2.5f，取数值部分，解析失败按 0 处理。"""
    if not raw:
        return 0.0
    digits = re.sub(r"[^0-9.]", "", raw)
    try:
        return float(digits) if digits else 0.0
    except ValueError:
        return 0.0


def _clean_candidate(raw: str, base_url: str) -> str | None:
    """整理一个候选字符串：反转义、补全、校验关键参数。"""
    text = raw.replace("\\u0026", "&").replace("\\/", "/")
    if "&amp;" in text:
        text = unescape(text)
    if not text.lower().startswith(("http://", "https://", "//")):
        text = urljoin(base_url, text if text.startswith("/") else "/" + text)
    elif text.startswith("//"):
        text = urljoin(base_url, text)

    query = parse_qs(text.split("?", 1)[1], keep_blank_values=True)
    pdfname = (query.get("pdfname") or [""])[0].strip()
    page = (query.get("page") or [""])[0].strip()
    if not pdfname or not page:
        return None  # 缺参数的是残缺片段（例如被 JS 拼接的半截 URL）
    if _WATER_MARK_HINT.search(text):
        return None
    return text


def extract_reader_params(html: str) -> dict:
    """解析动态阅读器（personaliiifServlet 页面）隐藏域里的会话参数。

    关键字段：fid（本次阅读会话的文件句柄）、filename、endpage/pageCount（总页数）。
    """
    inputs: dict[str, str] = {}
    for tag in re.findall(r"<input[^>]*>", html):
        id_match = re.search(r'id="([^"]+)"', tag)
        if not id_match:
            continue
        value_match = re.search(r'value="([^"]*)"', tag)
        inputs[id_match.group(1)] = value_match.group(1) if value_match else ""
    return inputs


def normalize_image_url(url: str, scale: str | None = None, strip_watermark: bool = True) -> str:
    """统一图片地址：改写 scale 分辨率，去掉带个人身份的 watermark 参数。"""
    if scale:
        if "scale=" in url:
            url = re.sub(r"scale=[^&]*", f"scale={scale}", url)
        else:
            url += f"&scale={scale}"
    if strip_watermark:
        url = re.sub(r"&?watermark=[^&\"]*", "", url)
    return url


def extract_page_images(html: str, base_url: str = "https://drm.fudan.edu.cn/read/") -> list[PageImage]:
    """从 HTML 源码中提取全部页面图片，按出现顺序去重。

    同一页出现多个 scale 版本时保留清晰度最高的那个。
    """
    html = unescape(html)
    ordered: list[PageImage] = []
    best_by_page: dict[str, PageImage] = {}

    for match in _URL_PATTERN.finditer(html):
        url = _clean_candidate(match.group(0), base_url)
        if not url:
            continue
        query = parse_qs(url.split("?", 1)[1], keep_blank_values=True)
        image = PageImage(
            url=url,
            pdfname=(query.get("pdfname") or [""])[0],
            page=(query.get("page") or [""])[0],
            scale=_scale_value((query.get("scale") or [""])[0]),
        )
        previous = best_by_page.get(image.page)
        if previous is None:
            best_by_page[image.page] = image
            ordered.append(image)
        elif image.scale > previous.scale:
            # 换成更清晰的版本，保持原有页序位置不变
            ordered[ordered.index(previous)] = image
            best_by_page[image.page] = image

    return ordered
