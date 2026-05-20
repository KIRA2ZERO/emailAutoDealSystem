import re,os,subprocess,asyncio,shlex
from contextlib import nullcontext
from pathlib import Path

from common.email_sender import send_email

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BAIDUPCS_GO_BIN = Path(__file__).resolve().parent / "bin" / "BaiduPCS-Go"
BAIDUPCS_GO_CMD = str(BAIDUPCS_GO_BIN) if BAIDUPCS_GO_BIN.exists() else "BaiduPCS-Go"
NOTIFY_CLI = PROJECT_ROOT / "servicebot_send_email"
BAIDU_SAVE_ROOT = "/SCL/BaiduDisk/4112800527_verygenome"

def append_log(log_file: str, message: str):
    if not log_file:
        return
    with open(log_file, "a", encoding="utf-8") as fh:
        fh.write(message.rstrip() + "\n")

def existBaiduDiskData(text:str):
    if "【百度网盘下载】" in text:
        return True
    else:
        return False

def parseBaiduDiskData(text: str):
    # # 匹配百度网盘链接
    # link_pattern = r"(https?://pan\.baidu\.com/s/[A-Za-z0-9_-]+)"
    # # 匹配提取码（常见写法：提取码: abcd 或 提取码：abcd）
    # pwd_pattern = r"(?:提取码)[：:\s]*([A-Za-z0-9]{4})"

    result_list = re.findall(r"【百度网盘下载】[（(](.*?)[）)]", text)
    return result_list

def safe_log_name(name: str):
    safe_name = re.sub(r"[^0-9A-Za-z._-]+", "_", name).strip("._")
    return safe_name or "baidu_disk_item"

def build_item_log_file(log_file: str, index: int, basename: str):
    if not log_file:
        return None
    log_path = Path(log_file)
    return str(log_path.with_name(f"{log_path.stem}_{index:02d}_{safe_log_name(basename)}{log_path.suffix}"))


async def dealBaiduDiskData(result_list: list, log_file: str = None):
    notify_email = [
        "zhangchuang@verygenome.com",
        "xiongtianzhu@verygenome.com",
        "zhuyuxuan@verygenome.com",
        "zhuojunyu@verygenome.com",
        "lishuangxi@verygenome.com"
    ]
    notify_recipients = ",".join(notify_email)
    result_list = [result.replace(" ", "") for result in result_list if result.replace(" ", "")]
    if not result_list:
        raise ValueError("百度网盘下载任务没有解析到有效路径")

    result_text = "\n".join(result_list)
    append_log(log_file, f"开始百度网盘下载任务，文件数量={len(result_list)}")
    append_log(log_file, f"下载内容:\n{result_text}")

    cmd_segments = []
    save_paths = []
    for index, remote_path in enumerate(result_list, start=1):
        basename = os.path.basename(remote_path.rstrip("/")) or f"item_{index:02d}"
        save_path = f"{BAIDU_SAVE_ROOT}/{basename}"
        item_log_file = build_item_log_file(log_file, index, basename)
        item_log_path = item_log_file or (log_file or "未生成")
        subject = f"百度网盘数据下载完成: {basename}"
        body = f"下载路径为:{remote_path}\n存储路径为:{save_path}\n日志路径为:{item_log_path}"
        download_cmd = " ".join(
            [
                shlex.quote(BAIDUPCS_GO_CMD),
                "d",
                "--saveto",
                shlex.quote(BAIDU_SAVE_ROOT),
                shlex.quote(remote_path),
            ]
        )
        notify_cmd = " ".join(
            [
                shlex.quote(str(NOTIFY_CLI)),
                "--recipients",
                shlex.quote(notify_recipients),
                "--subject",
                shlex.quote(subject),
                "--body",
                shlex.quote(body),
            ]
        )
        cmd_segments.append(
            {
                "remote_path": remote_path,
                "basename": basename,
                "save_path": save_path,
                "log_file": item_log_file,
                "cmd": f"{download_cmd} && {notify_cmd}",
            }
        )
        save_paths.append(save_path)
        append_log(
            log_file,
            f"[{index}/{len(result_list)}] 下载路径: {remote_path}\n"
            f"[{index}/{len(result_list)}] 存储路径: {save_path}\n"
            f"[{index}/{len(result_list)}] 日志路径: {item_log_path}\n"
            f"[{index}/{len(result_list)}] 下载命令:\n{download_cmd}",
        )

    send_email(
        notify_email, 
        f"百度网盘数据下载开始", 
        f"🚀 开始下载数据:\n{result_text}\n"
        f"存储根目录为:{BAIDU_SAVE_ROOT}\n"
        f"预期存储路径为:\n{chr(10).join(save_paths)}\n"
        f"任务总日志路径为:{log_file or '未生成'}"
    )

    for index, segment in enumerate(cmd_segments, start=1):
        append_log(
            log_file,
            f"[{index}/{len(cmd_segments)}] 开始下载 {segment['remote_path']} -> {segment['save_path']}",
        )
        log_context = open(segment["log_file"], "a", encoding="utf-8") if segment["log_file"] else nullcontext(subprocess.DEVNULL)
        with log_context as log_fh:
            process = await asyncio.create_subprocess_shell(
                segment["cmd"],
                stdout=log_fh,
                stderr=log_fh,
            )
            await process.wait()
        append_log(
            log_file,
            f"[{index}/{len(cmd_segments)}] 下载结束 {segment['basename']}，returncode={process.returncode}",
        )
        if process.returncode != 0:
            append_log(log_file, f"百度网盘下载任务中止，失败路径: {segment['remote_path']}")
            return process.returncode

    append_log(log_file, "百度网盘下载任务全部完成，returncode=0")
    return 0
