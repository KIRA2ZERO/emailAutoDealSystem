import asyncio
import os
import re
import shlex
import subprocess
from contextlib import nullcontext

from common.config import get_list, get_path
from common.email_sender import send_email

NOTIFY_CLI = get_path("paths.notify_cli")
OSSUTIL_BIN = "ossutil"


def existJMDNAData(text: str):
    return (
        "解码云数据下载提醒" in text or "解码原始数据及报告释放" in text
    )


def parseJMDNAData(text: str):
    result = {}

    title_match = re.search(r"解码云数据下载提醒[（(]([^）)]+)[）)]", text)
    if title_match:
        result["title"] = title_match.group(1).strip()

    oss_path_match = re.search(r"阿里云(?:交付)?路径[:：]\s*(oss://\S+)", text)
    if oss_path_match:
        result["oss_path"] = oss_path_match.group(1).strip()

    access_key_id_match = re.search(r"accessKeyID[:：]\s*(\S+)", text)
    if access_key_id_match:
        result["access_key_id"] = access_key_id_match.group(1).strip()

    access_key_secret_match = re.search(r"accessKeySecret[:：]\s*(\S+)", text)
    if access_key_secret_match:
        result["access_key_secret"] = access_key_secret_match.group(1).strip()

    endpoint_match = re.search(r"oss_endpoint[:：]\s*(\S+)", text)
    if endpoint_match:
        result["endpoint"] = endpoint_match.group(1).strip()

    if "title" not in result and result.get("oss_path"):
        result["title"] = result["oss_path"].rstrip("/").split("/")[-1]

    return result


def append_log(log_file: str, message: str):
    if not log_file:
        return
    with open(log_file, "a", encoding="utf-8") as fh:
        fh.write(message.rstrip() + "\n")


async def dealJMDNAData(result: dict, log_file: str = None):
    title = result.get("title") or "JMDNAData"
    oss_path = result.get("oss_path")
    access_key_id = result.get("access_key_id")
    access_key_secret = result.get("access_key_secret")
    endpoint = result.get("endpoint")

    required = {
        "oss_path": oss_path,
        "access_key_id": access_key_id,
        "access_key_secret": access_key_secret,
        "endpoint": endpoint,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise ValueError(f"JMDNA 邮件缺少必要字段: {', '.join(missing)}")

    save_path = f"/SCL/BaiduDisk/JMDNAData/{os.path.basename(oss_path.rstrip('/'))}"
    log_path = log_file or "未生成"
    notify_email = get_list("notifications.default_recipients")
    notify_recipients = ",".join(notify_email)

    cmd = " ".join(
        [
            shlex.quote(OSSUTIL_BIN),
            "cp",
            "-r",
            "-f",
            "-i",
            shlex.quote(access_key_id),
            "-k",
            shlex.quote(access_key_secret),
            "-e",
            shlex.quote(endpoint),
            shlex.quote(oss_path),
            shlex.quote(save_path),
            "&&",
            shlex.quote(str(NOTIFY_CLI)),
            "--recipients",
            shlex.quote(notify_recipients),
            "--subject",
            shlex.quote(f"{title} 解码生物数据下载完成"),
            "--body",
            shlex.quote(f"存储路径为:{save_path}；日志路径为:{log_path}"),
        ]
    )

    append_log(log_file, f"开始 JMDNA 下载任务，title={title}")
    append_log(log_file, f"OSS 路径: {oss_path}")
    append_log(log_file, f"存储路径: {save_path}")
    append_log(log_file, f"下载命令:\n{cmd}")
    send_email(
        notify_email,
        f"{title} 解码生物数据下载开始",
        f"🚀 开始下载数据:\n{oss_path}\n下载命令为:{cmd}\n存储路径为:{save_path}\n日志路径为:{log_path}",
    )

    log_context = open(log_file, "a", encoding="utf-8") if log_file else nullcontext(subprocess.DEVNULL)
    with log_context as log_fh:
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=log_fh,
            stderr=log_fh,
        )
        await process.wait()
    append_log(log_file, f"JMDNA 下载任务结束，returncode={process.returncode}")
    return process.returncode
