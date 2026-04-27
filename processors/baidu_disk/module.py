import re,os,subprocess,asyncio
from contextlib import nullcontext
from pathlib import Path

from common.email_sender import send_email

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BAIDUPCS_GO_BIN = Path(__file__).resolve().parent / "bin" / "BaiduPCS-Go"
BAIDUPCS_GO_CMD = str(BAIDUPCS_GO_BIN) if BAIDUPCS_GO_BIN.exists() else "BaiduPCS-Go"
NOTIFY_CLI = PROJECT_ROOT / "servicebot_send_email"

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


async def dealBaiduDiskData(result_list: list, log_file: str = None):
    notify_email = [
        "zhangchuang@verygenome.com",
        "xiongtianzhu@verygenome.com",
        "zhuyuxuan@verygenome.com",
        "zhuojunyu@verygenome.com"
    ]
    notify_recipients = ",".join(notify_email)
    result_list = [result.replace(" ", "") for result in result_list]
    file_paths = ' '.join(result_list)
    save_path = []
    for path in result_list:
        save_path.append(f"/SCL/BaiduDisk/4112800527_verygenome/{os.path.basename((path))}\n")
    cmd = f"{BAIDUPCS_GO_CMD} d {file_paths} && {NOTIFY_CLI} --recipients {notify_recipients} --subject 百度网盘数据下载完成 --body 存储路径为:{''.join(save_path)}"
    # 下载数据
    result_text = "\n".join(result_list)
    append_log(log_file, f"开始百度网盘下载任务，文件数量={len(result_list)}")
    append_log(log_file, f"下载内容:\n{result_text}")
    append_log(log_file, f"下载命令:\n{cmd}")
    send_email(
        notify_email, 
        f"百度网盘数据下载开始", 
        f"🚀 开始下载数据:\n{result_text} \n 存储路径为:{''.join(save_path)}"
    )    
    log_context = open(log_file, "a", encoding="utf-8") if log_file else nullcontext(subprocess.DEVNULL)
    with log_context as log_fh:
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=log_fh,
            stderr=log_fh,
        )
        await process.wait()  # 等待进程结束
    append_log(log_file, f"百度网盘下载任务结束，returncode={process.returncode}")
    return process.returncode
