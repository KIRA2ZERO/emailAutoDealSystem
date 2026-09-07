import asyncio
import html
import re
import subprocess
from contextlib import nullcontext
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from common.config import get_list
from common.email_sender import send_email


BENAGEN_HOST = "download.benagen.com"
BENAGEN_SAVE_ROOT = Path("/SCL/BaiduDisk/benagenData")
PAGE_URL_PATTERN = re.compile(
    r"https?://download\.benagen\.com/[^\s<>\"']+?\.html(?:\?[^\s<>\"']*)?",
    re.IGNORECASE,
)


class _DownloadLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("data-url"):
            self.urls.append(attributes["data-url"])


def existBenagenData(text: str):
    return bool(PAGE_URL_PATTERN.search(html.unescape(text)))


def parseBenagenData(text: str):
    page_urls = []
    for match in PAGE_URL_PATTERN.findall(html.unescape(text)):
        url = match.rstrip(".,;:!?)）]")
        if url not in page_urls:
            page_urls.append(url)
    return {"page_urls": page_urls}


def extract_download_urls(page_html: str, page_url: str):
    parser = _DownloadLinkParser()
    parser.feed(page_html)

    result = []
    for raw_url in parser.urls:
        url = urljoin(page_url, html.unescape(raw_url).strip())
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname != BENAGEN_HOST:
            continue
        if parsed.path.lower().endswith(".html"):
            continue
        if url not in result:
            result.append(url)
    return result


def _fetch_page(page_url: str):
    request = Request(page_url, headers={"User-Agent": "emailAutoDealSystem/2.0"})
    with urlopen(request, timeout=60) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _delivery_name(page_url: str):
    name = Path(unquote(urlparse(page_url).path)).stem
    safe_name = re.sub(r"[^0-9A-Za-z._-]+", "_", name).strip("._")
    return safe_name or "benagen_delivery"


def append_log(log_file: str, message: str):
    if not log_file:
        return
    with open(log_file, "a", encoding="utf-8") as fh:
        fh.write(message.rstrip() + "\n")


async def dealBenagenData(result: dict, log_file: str = None):
    page_urls = result.get("page_urls") or []
    if not page_urls:
        raise ValueError("Benagen 邮件没有解析到交付页面链接")

    notify_email = get_list("notifications.default_recipients")
    log_context = (
        open(log_file, "a", encoding="utf-8")
        if log_file
        else nullcontext(subprocess.DEVNULL)
    )

    with log_context as log_fh:
        for page_url in page_urls:
            delivery_name = _delivery_name(page_url)
            save_path = BENAGEN_SAVE_ROOT / delivery_name
            save_path.mkdir(parents=True, exist_ok=True)

            append_log(log_file, f"读取 Benagen 交付页面: {page_url}")
            page_html = await asyncio.to_thread(_fetch_page, page_url)
            download_urls = extract_download_urls(page_html, page_url)
            if not download_urls:
                raise ValueError(f"Benagen 交付页面没有解析到数据链接: {page_url}")

            append_log(log_file, f"解析到 {len(download_urls)} 个下载链接")
            append_log(log_file, f"存储路径: {save_path}")
            send_email(
                notify_email,
                f"{delivery_name} 贝纳基因数据下载开始",
                f"开始下载 {len(download_urls)} 个文件\n交付页面:{page_url}\n"
                f"存储路径:{save_path}\n日志路径:{log_file or '未生成'}",
            )

            for index, download_url in enumerate(download_urls, start=1):
                command = ["wget", "-c", "--no-verbose", "-P", str(save_path), download_url]
                append_log(
                    log_file,
                    f"[{index}/{len(download_urls)}] 下载命令: "
                    + " ".join(command),
                )
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=log_fh,
                    stderr=log_fh,
                    start_new_session=True,
                )
                await process.wait()
                if process.returncode != 0:
                    append_log(
                        log_file,
                        f"[{index}/{len(download_urls)}] 下载失败，returncode={process.returncode}",
                    )
                    return process.returncode

            append_log(log_file, f"Benagen 交付批次下载完成: {delivery_name}")
            send_email(
                notify_email,
                f"{delivery_name} Benagen 数据下载完成",
                f"存储路径:{save_path}\n日志路径:{log_file or '未生成'}",
            )

    return 0
