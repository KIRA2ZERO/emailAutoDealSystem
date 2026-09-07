import asyncio
import email,imaplib
import signal
import socket
from email.header import decode_header
from pathlib import Path
import time
from imapclient import IMAPClient
from common.config import get_config
from common.task_queue import DownloadTask, TaskManager
from processors.novo.module import existNovoData,parseNovoData,dealNovoData
from processors.baidu_disk.module import existBaiduDiskData,parseBaiduDiskData,dealBaiduDiskData
from processors.hyk.module import existHYkData,parseHYkData,dealHYkData
from processors.haplox.module import existHaploxData,parseHaploxData,dealHaploxData
from processors.jmdna.module import existJMDNAData,parseJMDNAData,dealJMDNAData
from processors.benagen.module import existBenagenData,parseBenagenData,dealBenagenData

# 邮箱配置
IMAP_SERVER = get_config("email.imap.server")
EMAIL_ACCOUNT = get_config("email.imap.account")
PASSWORD = get_config("email.imap.password")
IMAP_FOLDER = get_config("email.imap.folder")
WORKER_COUNT = get_config("service.worker_count")
TASK_MAX_RETRIES = get_config("service.task_max_retries")
TASK_RETRY_DELAY = get_config("service.task_retry_delay")
MAIL_POLL_INTERVAL = get_config("service.mail_poll_interval")
MONITOR_INTERVAL = get_config("service.monitor_interval")
AUTO_DOWNLOAD_TAG = get_config("service.auto_download_tag")
IMAP_RECONNECT_DELAY = get_config("email.imap.reconnect_delay", 30)
TASK_STATE_FILE = Path(__file__).resolve().parent / "task_state.json"
TASK_LOG_DIR = Path(__file__).resolve().parent / "logs"
PROCESSOR_ENABLED = get_config("processors.enabled", {})
IMAP_CONNECTION_ERRORS = (
    imaplib.IMAP4.abort,
    imaplib.IMAP4.error,
    OSError,
    TimeoutError,
    socket.error,
)
FETCH_MESSAGE_PART = "BODY.PEEK[]"
MESSAGE_BODY_KEYS = (b"BODY[]", b"RFC822", "BODY[]", "RFC822")
FALLBACK_FETCH_MESSAGE_PART = "BODY[]"

ALL_PROCESSORS = [
    {
        "source": "novo",
        "exists": existNovoData,
        "parse": parseNovoData,
        "deal": dealNovoData,
    },
    {
        "source": "baidu_disk",
        "exists": existBaiduDiskData,
        "parse": parseBaiduDiskData,
        "deal": dealBaiduDiskData,
    },
    {
        "source": "hyk",
        "exists": existHYkData,
        "parse": parseHYkData,
        "deal": dealHYkData,
    },
    {
        "source": "haplox",
        "exists": existHaploxData,
        "parse": parseHaploxData,
        "deal": dealHaploxData,
    },
    {
        "source": "jmdna",
        "exists": existJMDNAData,
        "parse": parseJMDNAData,
        "deal": dealJMDNAData,
        "allow_without_auto_tag": False,
    },
    {
        "source": "benagen",
        "exists": existBenagenData,
        "parse": parseBenagenData,
        "deal": dealBenagenData,
        "allow_without_auto_tag": False,
    },
]


def is_processor_enabled(source: str) -> bool:
    if not isinstance(PROCESSOR_ENABLED, dict):
        return True
    return PROCESSOR_ENABLED.get(source, True)


PROCESSORS = [
    processor for processor in ALL_PROCESSORS if is_processor_enabled(processor["source"])
]
TASK_HANDLERS = {processor["source"]: processor["deal"] for processor in PROCESSORS}

def log_status(message: str):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

def connect_mailbox():
    client = IMAPClient(IMAP_SERVER)
    try:
        client.login(EMAIL_ACCOUNT, PASSWORD)
        log_status(f"邮箱登录成功: {EMAIL_ACCOUNT}")
        client.select_folder(IMAP_FOLDER)
        log_status(f"已选择邮箱目录: {IMAP_FOLDER}")
        return client
    except Exception:
        close_mailbox(client)
        raise

def close_mailbox(client):
    if client is None:
        return
    try:
        client.logout()
    except Exception:
        pass

def get_message_bytes(uid, message_data, log_missing=True):
    for key in MESSAGE_BODY_KEYS:
        body = message_data.get(key)
        if isinstance(body, bytes):
            return body

    for key, body in message_data.items():
        normalized_key = key.decode(errors="ignore") if isinstance(key, bytes) else str(key)
        normalized_key = normalized_key.upper()
        if isinstance(body, bytes) and (
            normalized_key == "RFC822" or normalized_key.startswith("BODY[")
        ):
            return body

    if log_missing:
        log_status(f"邮件 uid={uid} 未找到正文数据，fetch keys={list(message_data.keys())}")
    return None

async def process_email(client, uid, msg, task_manager: TaskManager):
    mark_as_seen = False
    try:
        # 解析主题
        subject, encoding = decode_header(msg["Subject"])[0]
        if isinstance(subject, bytes):
            subject = subject.decode(encoding or "utf-8", errors="ignore")
        body_parts = []
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                if content_type in {"text/plain", "text/html"} and "attachment" not in content_disposition:
                    charset = part.get_content_charset() or "utf-8"
                    payload = part.get_payload(decode=True)
                    if payload:
                        body_parts.append(payload.decode(charset, errors="ignore"))
        else:
            charset = msg.get_content_charset() or "utf-8"
            payload = msg.get_payload(decode=True)
            if payload:
                body_parts.append(payload.decode(charset, errors="ignore"))

        body = "\n".join(body_parts)

        if body:
            # print("📜 邮件正文：")
            # print(body.strip())
            matched = False
            body_text = body.strip()
            searchable_text = f"{subject}\n{body_text}"
            for processor in PROCESSORS:
                can_process = AUTO_DOWNLOAD_TAG in subject or processor.get("allow_without_auto_tag", False)
                if can_process and processor["exists"](searchable_text):
                    matched = True
                    payload = processor["parse"](searchable_text)
                    task = DownloadTask(
                        source=processor["source"],
                        subject=subject,
                        payload=payload,
                        email_uid=uid,
                        handler=processor["deal"],
                        max_retries=TASK_MAX_RETRIES,
                        retry_delay=TASK_RETRY_DELAY,
                    )
                    await task_manager.enqueue(task)
            if matched:
                mark_as_seen = True
                log_status(f"邮件 uid={uid} 已创建下载任务: {subject}")
            elif AUTO_DOWNLOAD_TAG in subject:
                log_status(f"邮件 uid={uid} 主题匹配自动下载，但正文没有匹配到处理模块")

        else:
            print("⚠️ 没有找到可读正文")

    except Exception as e:
        print("❌ 处理邮件出错:", e)

    finally:
        if mark_as_seen:
            client.add_flags(uid, [r"\Seen"])
    return mark_as_seen

async def fetch_unseen(client, task_manager: TaskManager):
    messages = client.search(["UNSEEN"])
    log_status(f"未读邮件检查完成，数量: {len(messages)}")
    if messages:
        tasks = []
        missing_body_uids = []
        for uid, message_data in client.fetch(messages, [FETCH_MESSAGE_PART]).items():
            message_bytes = get_message_bytes(uid, message_data, log_missing=False)
            if message_bytes is None:
                missing_body_uids.append(uid)
                continue
            msg = email.message_from_bytes(message_bytes)
            tasks.append(process_email(client, uid, msg, task_manager))
        await asyncio.gather(*tasks)
        for uid in missing_body_uids:
            fallback_data = client.fetch([uid], [FALLBACK_FETCH_MESSAGE_PART]).get(uid, {})
            message_bytes = get_message_bytes(uid, fallback_data)
            if message_bytes is None:
                continue
            msg = email.message_from_bytes(message_bytes)
            processed = await process_email(client, uid, msg, task_manager)
            if not processed:
                client.remove_flags(uid, [r"\Seen"])
                log_status(f"邮件 uid={uid} 未被本实例处理，已恢复为未读")
    return len(messages)

async def poll_check():
    log_status(f"=============================================")
    log_status(f"邮件自动处理服务启动，连接服务器: {IMAP_SERVER}")
    log_status(f"启用处理器: {', '.join(TASK_HANDLERS) or '无'}")
    task_manager = TaskManager(
        worker_count=WORKER_COUNT,
        monitor_interval=MONITOR_INTERVAL,
        logger=log_status,
        state_file=str(TASK_STATE_FILE),
        handlers=TASK_HANDLERS,
        log_dir=str(TASK_LOG_DIR),
    )
    await task_manager.start()
    while True:
        client = None
        try:
            client = connect_mailbox()
            await fetch_unseen(client, task_manager)
            log_status(f"进入轮询循环，间隔 {MAIL_POLL_INTERVAL}s")
            while True:
                await asyncio.sleep(MAIL_POLL_INTERVAL)
                await fetch_unseen(client, task_manager)
        except IMAP_CONNECTION_ERRORS as exc:
            log_status(
                f"IMAP连接异常，{IMAP_RECONNECT_DELAY}s 后重连: "
                f"{type(exc).__name__}: {exc}"
            )
        except Exception as exc:
            log_status(
                f"邮件轮询异常，{IMAP_RECONNECT_DELAY}s 后重试: "
                f"{type(exc).__name__}: {exc}"
            )
        finally:
            close_mailbox(client)
        await asyncio.sleep(IMAP_RECONNECT_DELAY)

if __name__ == "__main__":
    asyncio.run(poll_check())
