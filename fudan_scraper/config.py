
# ---- 站点地址 ---------------------------------------------------------------

BASE_URL = "https://thesis.fudan.edu.cn"
API_BASE = BASE_URL + "/md/"
DRM_READ_BASE = "https://drm.fudan.edu.cn/read/"

# 检索接口（匿名可用）
SEARCH_API = API_BASE + "papersearch/simpSearch"
# 站点配置（匿名可用）：casloginUrl、PdfServerPath、loginType 等
SYSTEM_CONFIG_API = API_BASE + "setting/personalitySetting"
# 统一认证回调换 token（learnid/name/vcode 由 CAS 回跳参数提供）
CAS_LOGIN_API = API_BASE + "account/caslogin"
# 校验 token 是否有效
ACCOUNT_INFO_API = API_BASE + "account/getAccount"
# 在线阅读地址接口（需要 token）
DRM_VIEW_API = API_BASE + "docobject/drmView"
# 备选：加密路径接口（部分学校配置走这个）
ENCRYPTION_PATH_API = API_BASE + "docobject/GetEncryptionPath"

# ---- 浏览器伪装 --------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

HTML_HEADERS = {
    **BASE_HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
    "image/webp,image/apng,*/*;q=0.8",
    "Referer": BASE_URL + "/",
}

# ---- 站点配置 ---------------------------------------------------------------

# 复旦大学租户号。CAS 回跳参数里通常不带 tenantcode，但 caslogin 接口必需，
# 因此作为默认值补上（前端从站点配置的 currentTenant 里取到的是同一个值）。
DEFAULT_TENANTCODE = "10246"

# ---- 限速与网络 --------------------------------------------------------------

# 每张图片之间的间隔（秒）。
DEFAULT_IMAGE_DELAY = 3.0
# 检索、拿阅读器地址这类小接口之间的间隔（秒）
DEFAULT_API_DELAY = 1.5
REQUEST_TIMEOUT = 60          # 普通请求超时（秒）
IMAGE_TIMEOUT = 90            # 单页大图超时（秒）
MAX_RETRIES = 3               # 单张图片最大尝试次数
RETRY_BACKOFF = 5.0           # 重试前额外等待（秒）

# ---- DRM 阅读器 ---------------------------------------------------------------

# 逐页图片分辨率。阅读器默认缩略图是 0.2f，3f 为 1785x2525 全尺寸。
IMAGE_SCALE = "3f"
# pdfboxServlet 地址末尾的 watermark 参数会把"姓名 学号 日期"烙进图片，
# 服务器不校验该参数，去掉即得到阅读器同源的干净页面图。
STRIP_WATERMARK_PARAM = True

# ---- 检索请求体模板 -----------------------------------------------------------
# 与网页前端发出的请求保持一致；keyword 由调用方填入 searchfields

SEARCH_BODY_TEMPLATE = {
    "indexname": "paper",
    "curpage": 1,
    "pagesize": 20,
    "papertype": "paper",
    "newsearh": 0,
    "searchtype": 1,
    "sortfields": [{"fieldname": "addtime", "orderby": "desc", "type": "date"}],
    "factfields": [
        {
            "facetLimit": "100",
            "facetMinCount": "1",
            "fielddesc": "DESC",
            "fieldname": "degree_year",
            "type": "fieldnumber",
        }
    ],
    "searchfields": [
        {
            "fieldname": "all",
            "keytype": "ordinary",
            "keyword": "",
            "relation": "AND",
            "searchtype": "match",
        }
    ],
}
