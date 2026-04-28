import re, os, subprocess, asyncio
from contextlib import nullcontext
from pathlib import Path

from common.email_sender import send_email

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAYFILE_C_BIN = Path(__file__).resolve().parent / "bin" / "rayfile-c"
NOTIFY_CLI = PROJECT_ROOT / "servicebot_send_email"

def append_log(log_file: str, message: str):
    if not log_file:
        return
    with open(log_file, "a", encoding="utf-8") as fh:
        fh.write(message.rstrip() + "\n")

def existHaploxData(text: str):
    """检查邮件正文是否包含上饶海普洛斯医学检验实验室有限公司"""
    if "上饶海普洛斯医学检验实验室有限公司" in text:
        return True
    else:
        return False
        

def parseHaploxData(text: str):
    """
    从邮件中提取rayfile命令和标题
    返回格式: {"command": str, "title": str}
    """
    result = {"command": None,"title":None}

    # 提取rayfile命令（从rayfile-c到-d）
    command_match = re.search(r'(rayfile-c.*?-d)\b', text)
    if command_match:
        result["command"] = command_match.group(1)

    timestamp_match = re.search(r'/(\d{6})/', result["command"] )
    if timestamp_match:
        result["timestamp"] = timestamp_match.group(1)
        
    title_match = re.search(r'PSM-ZM\d{12}-\d{4}', result["command"] )
    if title_match:
        result["title"] = title_match.group(0)
    return result

async def dealHaploxData(result: dict, log_file: str = None):
    """
    处理海普洛斯数据下载
    result: dict，包含 'command' 和 'title'
    """
    title = result["title"] 
    date = result["timestamp"]
    command = result["command"].replace("rayfile-c", str(RAYFILE_C_BIN), 1) + " ./" + date

    # 设置保存路径
    save_path = f"/SCL/BaiduDisk/haploxData/"
    
    # 通知邮箱列表
    notify_email = [
        "zhangchuang@verygenome.com",
        "xiongtianzhu@verygenome.com",
        "zhuyuxuan@verygenome.com",
        "zhuojunyu@verygenome.com"
    ]
    notify_recipients = ",".join(notify_email)
    log_path = log_file or "未生成"
    
    # 构建完整命令（在指定目录执行）
    send_cmd = f"cd {save_path} && {command}"
    append_log(log_file, f"开始海普洛斯下载任务，title={title}, date={date}")
    append_log(log_file, f"下载命令:\n{send_cmd}")
    send_email(
        notify_email,
        f"{title}海普洛斯数据批次数据下载开始",
        f"🚀 开始下载数据:\n{title} \n下载命令: {send_cmd} \n存储路径: {save_path+date+title}\n日志路径为:{log_path}"
    )
    exec_cmd = f"{send_cmd} && {NOTIFY_CLI} --recipients {notify_recipients} --subject {title}海普洛斯数据批次数据下载完成 --body 存储路径为:{save_path+date+title}；日志路径为:{log_path}"
    # 执行下载命令
    log_context = open(log_file, "a", encoding="utf-8") if log_file else nullcontext(subprocess.DEVNULL)
    with log_context as log_fh:
        process = await asyncio.create_subprocess_shell(
            exec_cmd,
            stdout=log_fh,
            stderr=log_fh,
        )
        await process.wait()  # 等待进程结束
    append_log(log_file, f"海普洛斯下载任务结束，returncode={process.returncode}")
    return process.returncode
    
