from imapclient import IMAPClient
import asyncio
import email,imaplib
from email.header import decode_header
from pathlib import Path
import time
from common.task_queue import DownloadTask, TaskManager
from processors.novo.module import existNovoData,parseNovoData,dealNovoData
from processors.baidu_disk.module import existBaiduDiskData,parseBaiduDiskData,dealBaiduDiskData
from processors.hyk.module import existHYkData,parseHYkData,dealHYkData
from processors.haplox.module import existHaploxData,parseHaploxData,dealHaploxData
from processors.jmdna.module import existJMDNAData,parseJMDNAData,dealJMDNAData

# 邮箱配置
IMAP_SERVER = "smtphz.qiye.163.com"
EMAIL_ACCOUNT = "servicebot@verygenome.com"
PASSWORD = "Servicebot!"
WORKER_COUNT = 1
TASK_MAX_RETRIES = 2
TASK_RETRY_DELAY = 60
MAIL_POLL_INTERVAL = 30
TASK_STATE_FILE = Path(__file__).resolve().parent / "task_state.json"
TASK_LOG_DIR = Path(__file__).resolve().parent / "logs"

PROCESSORS = [
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
        "allow_without_auto_tag": True,
    },
]
TASK_HANDLERS = {processor["source"]: processor["deal"] for processor in PROCESSORS}

def log_status(message: str):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

async def process_email(client, uid, msg, task_manager: TaskManager):
    try:
        # 解析主题
        subject, encoding = decode_header(msg["Subject"])[0]
        if isinstance(subject, bytes):
            subject = subject.decode(encoding or "utf-8", errors="ignore")
        body = ""
        if msg.is_multipart():
            # 遍历邮件的各个部分
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    charset = part.get_content_charset() or "utf-8"
                    body = part.get_payload(decode=True).decode(charset, errors="ignore")
                    break
        else:
            charset = msg.get_content_charset() or "utf-8"
            body = msg.get_payload(decode=True).decode(charset, errors="ignore")

        if body:
            # print("📜 邮件正文：")
            # print(body.strip())
            matched = False
            body_text = body.strip()
            searchable_text = f"{subject}\n{body_text}"
            for processor in PROCESSORS:
                can_process = "【自动下载】" in subject or processor.get("allow_without_auto_tag", False)
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
                log_status(f"邮件 uid={uid} 已创建下载任务: {subject}")
            elif "【自动下载】" in subject:
                log_status(f"邮件 uid={uid} 主题匹配自动下载，但正文没有匹配到处理模块")

        else:
            print("⚠️ 没有找到可读正文")

    except Exception as e:
        print("❌ 处理邮件出错:", e)

    finally:
        # 不管中间报不报错，最后都把邮件标记为已读
        client.add_flags(uid, [r"\Seen"])

async def fetch_unseen(client, task_manager: TaskManager):
    messages = client.search(["UNSEEN"])
    log_status(f"未读邮件检查完成，数量: {len(messages)}")
    if messages:
        tasks = []
        for uid, message_data in client.fetch(messages, "RFC822").items():
            msg = email.message_from_bytes(message_data[b"RFC822"])
            tasks.append(process_email(client, uid, msg, task_manager))
        await asyncio.gather(*tasks)
    return len(messages)

async def poll_check():
    log_status(f"=============================================")
    log_status(f"邮件自动处理服务启动，连接服务器: {IMAP_SERVER}")
    task_manager = TaskManager(
        worker_count=WORKER_COUNT,
        monitor_interval=30,
        logger=log_status,
        state_file=str(TASK_STATE_FILE),
        handlers=TASK_HANDLERS,
        log_dir=str(TASK_LOG_DIR),
    )
    await task_manager.start()
    with IMAPClient(IMAP_SERVER) as client:
        client.login(EMAIL_ACCOUNT, PASSWORD)
        log_status(f"邮箱登录成功: {EMAIL_ACCOUNT}")
        client.select_folder("INBOX")
        log_status(f"进入轮询循环，间隔 {MAIL_POLL_INTERVAL}s")
        while True:
            await asyncio.sleep(MAIL_POLL_INTERVAL)
            await fetch_unseen(client, task_manager)

if __name__ == "__main__":
    asyncio.run(poll_check())
