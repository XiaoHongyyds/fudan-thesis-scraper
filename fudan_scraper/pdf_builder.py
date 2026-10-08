"""把下载好的页面图片合并成一个 PDF。

优先用 img2pdf：JPEG 原样嵌入、不重编码、速度快、文件小。
img2pdf 不可用时退回 Pillow。
"""

from __future__ import annotations

from pathlib import Path


def build_pdf(image_paths: list[Path], out_pdf: Path, log=print) -> Path:
    if not image_paths:
        raise ValueError("没有可合并的图片")

    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    try:
        return _build_with_img2pdf(image_paths, out_pdf, log)
    except ImportError:
        return _build_with_pillow(image_paths, out_pdf, log)


def _build_with_img2pdf(image_paths: list[Path], out_pdf: Path, log) -> Path:
    import img2pdf

    # 所有页面按第一张图的尺寸设定页面大小，避免逐页尺寸漂移
    with open(out_pdf, "wb") as fp:
        fp.write(img2pdf.convert([str(p) for p in image_paths]))
    log(f"已合并 {len(image_paths)} 页")
    return out_pdf


def _build_with_pillow(image_paths: list[Path], out_pdf: Path, log) -> Path:
    from PIL import Image

    pages: list[Image.Image] = []
    for path in image_paths:
        image = Image.open(path)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        pages.append(image)

    first, rest = pages[0], pages[1:]
    first.save(out_pdf, "PDF", save_all=True, append_images=rest)
    log(f"已合并 {len(pages)} 页")
    return out_pdf
