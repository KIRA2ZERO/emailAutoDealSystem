from imapclient import IMAPClient
import asyncio
import email,imaplib
from email.header import decode_header
import time
from common.task_queue import DownloadTask, TaskManager
from processors.novo.module import existNovoData,parseNovoData,dealNovoData
from processors.baidu_disk.module import existBaiduDiskData,parseBaiduDiskData,dealBaiduDiskData
from processors.hyk.module import existHYkData,parseHYkData,dealHYkData
from processors.haplox.module import existHaploxData,parseHaploxData,dealHaploxData

# 邮箱配置
IMAP_SERVER = "smtphz.qiye.163.com"
EMAIL_ACCOUNT = "servicebot@verygenome.com"
PASSWORD = "Servicebot!"
WORKER_COUNT = 1
TASK_MAX_RETRIES = 2
TASK_RETRY_DELAY = 60

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
]

def log_status(message: str):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

async def process_email(client, uid, msg, task_manager: TaskManager):
    try:
        # 解析主题
        subject, encoding = decode_header(msg["Subject"])[0]
        if isinstance(subject, bytes):
            subject = subject.decode(encoding or "utf-8", errors="ignore")
        # 只处理主题包含 [自动下载] 的邮件
        if "【自动下载】" not in subject:
            return
        print("📩 处理自动下载邮件:", subject)

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
            for processor in PROCESSORS:
                if processor["exists"](body_text):
                    matched = True
                    payload = processor["parse"](body_text)
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
            if not matched:
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

async def idle_check():
    log_status(f"邮件自动处理服务启动，连接服务器: {IMAP_SERVER}")
    task_manager = TaskManager(
        worker_count=WORKER_COUNT,
        monitor_interval=30,
        logger=log_status,
    )
    task_manager.start()
    with IMAPClient(IMAP_SERVER) as client:
        client.login(EMAIL_ACCOUNT, PASSWORD)
        log_status(f"邮箱登录成功: {EMAIL_ACCOUNT}")
        client.select_folder("INBOX")
        log_status("已进入 INBOX，开始首次未读邮件检查")
        await fetch_unseen(client, task_manager)
        log_status("首次检查完成，进入 IDLE 监听循环")
        while True:
            client.idle()
            responses = await asyncio.to_thread(client.idle_check, timeout=30)
            client.idle_done()
            if responses:
                log_status(f"收到 IMAP IDLE 响应: {responses}")
            else:
                log_status("IDLE 本轮无事件，开始周期性未读邮件检查")
            unseen_count = await fetch_unseen(client, task_manager)
            if unseen_count == 0:
                log_status("运行正常，未检测到未读新邮件")

if __name__ == "__main__":
    asyncio.run(idle_check())
