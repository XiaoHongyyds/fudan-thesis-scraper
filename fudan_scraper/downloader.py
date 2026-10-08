"""限速下载器：逐张下载论文页面图片，默认每张间隔 3 秒。"""

from __future__ import annotations

import time
from pathlib import Path

import requests

from . import config

# 常见图片格式的魔数，用于确认拿到的是真图片而不是错误页
_MAGIC_NUMBERS = (
    b"\xff\xd8\xff",        # JPEG
    b"\x89PNG\r\n\x1a\n",   # PNG
)


def looks_like_image(content: bytes) -> bool:
    return any(content.startswith(magic) for magic in _MAGIC_NUMBERS)


class DownloadError(RuntimeError):
    """单张图片重试后仍失败。"""


def download_images(
    urls: list[str],
    out_dir: Path,
    session: requests.Session,
    delay: float = config.DEFAULT_IMAGE_DELAY,
    max_retries: int = config.MAX_RETRIES,
    backoff: float = config.RETRY_BACKOFF,
    limit: int | None = None,
    log=print,
) -> list[Path]:
    """按顺序下载图片到 out_dir，返回已落盘文件列表（与页序一致）。已存在且非空的同名文件直接跳过，因此中断后可断点续传。
    """
    if limit:
        urls = urls[:limit]
    out_dir.mkdir(parents=True, exist_ok=True)

    saved: list[Path] = []
    total = len(urls)
    for index, url in enumerate(urls, 1):
        target = out_dir / f"page_{index:04d}.jpg"
        if target.exists() and target.stat().st_size > 0:
            log(f"[{index}/{total}] 已存在，跳过：{target.name}")
            saved.append(target)
            continue

        attempt = 0
        while True:
            attempt += 1
            try:
                resp = session.get(
                    url,
                    headers={**config.HTML_HEADERS, "Referer": "https://drm.fudan.edu.cn/"},
                    timeout=config.IMAGE_TIMEOUT,
                    stream=True,
                )
                resp.raise_for_status()
                content = resp.content
                if not looks_like_image(content):
                    raise DownloadError(
                        f"返回内容不是图片（前 40 字节：{content[:40]!r}），"
                        "地址可能已过期，请重新获取阅读器页面"
                    )
                target.write_bytes(content)
                log(
                    f"[{index}/{total}] 下载成功 {target.name}"
                    f"（{len(content) / 1024:.0f} KB）"
                )
                saved.append(target)
                break
            except (requests.RequestException, DownloadError) as err:
                if attempt >= max_retries:
                    raise DownloadError(
                        f"第 {index} 页在 {max_retries} 次尝试后仍失败：{err}"
                    ) from err
                wait = backoff * attempt
                log(f"[{index}/{total}] 第 {attempt} 次失败（{err}），{wait:.0f} 秒后重试")
                time.sleep(wait)

        if index < total:
            time.sleep(delay)

    return saved
