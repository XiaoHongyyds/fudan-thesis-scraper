from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from fudan_scraper import config
from fudan_scraper import auth
from fudan_scraper.client import SiteError, Thesis, ThesisSite
from fudan_scraper.downloader import download_images
from fudan_scraper.parser import extract_page_images
from fudan_scraper.pdf_builder import build_pdf


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fudan-thesis-scraper",
        description="从复旦大学学位论文库的在线阅读页抓取页面图片并合成 PDF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    source = parser.add_mutually_exclusive_group(required=False)
    source.add_argument("--title", help="论文标题/关键词，先检索再下载")
    source.add_argument("--keyid", help="直接指定检索结果里的 keyid")
    source.add_argument("--reader-url", help="直接指定在线阅读器页面地址")
    source.add_argument("--from-html", help="直接解析本地保存的阅读器页面 HTML")

    parser.add_argument("--search-only", action="store_true",
                        help="配合 --title 只列出检索结果，不下载")
    parser.add_argument("--login", action="store_true",
                        help="打开浏览器完成统一认证登录，token 缓存到本地后退出")
    parser.add_argument("--index", type=int, help="检索结果多于一条时指定第几条")
    parser.add_argument("--token", help="手动指定 token")
    parser.add_argument("--cookie", help="可选，需使用整串 Cookie")
    parser.add_argument("--delay", type=float, default=config.DEFAULT_IMAGE_DELAY,
                        help=f"每张图片下载间隔秒数，默认 {config.DEFAULT_IMAGE_DELAY}")
    parser.add_argument("--out", default="output", help="输出目录（默认 ./output）")
    parser.add_argument("--max-pages", type=int, default=0,
                        help="最多下载多少页，0 表示不限制（默认 0）")
    parser.add_argument("--no-pdf", action="store_true", help="只下载图片，不合成 PDF")

    args = parser.parse_args(argv)
    if not (args.login or args.search_only or args.title
            or args.keyid or args.reader_url or args.from_html):
        parser.error(
            "需要指定一种运行模式：--login（登录）/ --title（检索下载）/ "
            "--keyid / --reader-url / --from-html"
        )
    return args


def sanitize_filename(name: str) -> str:
    """去掉文件名里的非法字符"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name).strip(" ._")
    return cleaned or "thesis"


def resolve_thesis(site: ThesisSite, args: argparse.Namespace) -> Thesis | None:
    """根据命令行参数确定目标论文；无法确定时返回 None"""
    if args.from_html or args.reader_url:
        return None
    if args.keyid:
        return Thesis(keyid=args.keyid, title=args.keyid)
    return site.pick(args.title, index=args.index)


def collect_reader_html(site: ThesisSite, args: argparse.Namespace) -> tuple[str, str]:
    """拿到阅读器页面源码，返回"""
    if args.from_html:
        path = Path(args.from_html)
        return path.read_text(encoding="utf-8", errors="replace"), f"本地文件 {path.name}"

    thesis = resolve_thesis(site, args)
    assert thesis is not None
    if args.reader_url:
        reader_url = args.reader_url
    else:
        print(f"目标论文：{thesis.describe()}")
        print("正在获取在线阅读器地址...")
        reader_url = site.get_reader_url(thesis)
    print(f"阅读器地址：{reader_url}")
    return site.fetch_html(reader_url), reader_url


def resolve_token(args: argparse.Namespace, site: ThesisSite, log=print) -> str | None:
    """确定本次运行使用的登录态：命令行 > 本地缓存；并把缓存的 Cookie 一并恢复。

    站点将 token 与登录会话 Cookie 绑定校验，缺 Cookie 时 token 会被判失效。
    """
    cached = None if args.token else auth.load_auth()
    token = args.token or (cached or {}).get("token")
    if not token:
        return None

    cookies = (cached or {}).get("cookies") or {}
    for name, value in cookies.items():
        site.session.cookies.set(name, value)
    site.session.headers["token"] = token  # 校验与后续请求都要带上

    source = "命令行" if args.token else "本地缓存"
    if site.verify_token():
        log(f"使用{source}登录态（token + {len(cookies)} 条 Cookie，已验证有效）")
        return token
    if args.token:
        log("警告：命令行 token 校验未通过——token 需要配套登录会话的 Cookie，"
            "建议改用 py main.py --login", sys.stderr)
        return token
    log("本地缓存的登录态已失效，需要重新登录")
    return None


def run_login(site: ThesisSite) -> int:
    token, account = auth.browser_login(site)
    if not site.verify_token():
        print("警告：token 校验接口未通过，可能登录未完全生效", file=sys.stderr)
    who = account.get("name") or account.get("loginname") or ""
    print(f"登录成功{('：' + who) if who else ''}")
    print(f"登录态已缓存到 {auth.TOKEN_CACHE_FILE}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # 让 stdout 按行即时刷新，stderr 提示与进度打印保持先后顺序
    sys.stdout.reconfigure(line_buffering=True)
    args = parse_args(argv)
    site = ThesisSite(token=args.token, cookie=args.cookie)

    try:
        # ---- 登录模式 ---------------------------------------------------
        if args.login:
            return run_login(site)

        # ---- 检索模式 ---------------------------------------------------
        if args.search_only:
            if not args.title:
                print("--search-only 需要配合 --title 使用", file=sys.stderr)
                return 2
            results = site.search(args.title)
            if not results:
                print("没有检索到结果")
                return 1
            print(f"共 {len(results)} 条结果：")
            for i, thesis in enumerate(results, 1):
                print(f"  {i}. {thesis.describe()}")
                print(f"     keyid = {thesis.keyid}")
            return 0

        token = resolve_token(args, site)
        if token:
            site.session.headers["token"] = token
        elif not (args.from_html or args.reader_url):
            print(
                "未提供 token，获取在线阅读器地址大概率会失败。\n",
                file=sys.stderr,
            )

        # ---- 第一步：确定论文 -------------------------------------------
        thesis = resolve_thesis(site, args)
        title = thesis.title if thesis else "thesis"

        # ---- 第二步：拿到阅读器页面源码 ---------------------------------
        html, source_note = collect_reader_html(site, args)

        # ---- 第三步：解析全部页面的无水印图片地址 -------------------------
        # collect_image_urls 兼容两种阅读器：静态源码直接提取；
        # 动态阅读器（personaliiifServlet）自动调 doTest 拿全量列表。
        reader_url = source_note if source_note.startswith("http") else None
        if reader_url:
            urls = site.collect_image_urls(reader_url, html)
        else:
            from fudan_scraper.parser import extract_page_images
            urls = [img.url for img in extract_page_images(html)]
        if not urls:
            print(
                "没有在页面源码里找到 pdfboxServlet 图片地址。\n"
                "可能原因：\n"
                "  1) 抓到的是登录/错误页 —— 检查 token 与 Cookie；\n"
                "  2) 阅读器由脚本动态加载图片 —— 请在浏览器里打开阅读页并滚动到末尾，\n"
                "     然后 Ctrl+S 保存完整页面，用 --from-html 重试。",
                file=sys.stderr,
            )
            return 1
        print(f"共解析出 {len(urls)} 页图片（来自 {source_note}）")

        # ---- 第四步：限速下载 -------------------------------------------
        work_dir = Path(args.out) / sanitize_filename(title)
        image_dir = work_dir / "images"
        saved = download_images(
            urls,
            image_dir,
            session=site.session,
            delay=args.delay,
            limit=args.max_pages or None,
        )

        # ---- 第五步：合成 PDF --------------------------------------------
        if args.no_pdf:
            print(f"按要求跳过 PDF 合成，图片在 {image_dir}")
            return 0
        out_pdf = work_dir.parent / f"{sanitize_filename(title)}.pdf"
        build_pdf(saved, out_pdf)
        print(f"完成：{out_pdf}")
        return 0

    except SiteError as err:
        print(f"错误：{err}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已中断。已下载的图片保留在原处，重新运行可断点续传。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
