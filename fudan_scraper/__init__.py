"""复旦大学学位论文在线阅读抓取工具。

模块划分：
    config      —— 站点地址、请求头等常量与默认参数
    client      —— 与 thesis.fudan.edu.cn 交互：检索、获取在线阅读器地址
    parser      —— 从阅读器页面 HTML 中提取无水印页面图片 URL
    downloader  —— 限速下载器（默认 3 秒/张）
    pdf_builder —— 把下载好的图片合并成一个 PDF
"""

__version__ = "0.1.0"
