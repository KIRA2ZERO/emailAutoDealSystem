import re, os, subprocess, asyncio
from pathlib import Path

from common.email_sender import send_email

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAYFILE_C_BIN = Path(__file__).resolve().parent / "bin" / "rayfile-c"
NOTIFY_CLI = PROJECT_ROOT / "servicebot_send_email"

def existHYkData(text: str):
    """检查邮件正文是否包含华银康高通量测序交付平台"""
    if "华银康高通量测序交付平台" in text:
        return True
    else:
        return False

def parseHYkData(text: str):
    """
    从邮件中提取rayfile命令和标题
    返回格式: {"command": str, "title": str}
    """
    result = {"command": None,"title":None}

    # 提取rayfile命令（从rayfile-c到-d）
    command_match = re.search(r'(rayfile-c.*?-d)\b', text)
    if command_match:
        result["command"] = command_match.group(1)

    title_match = re.search(r'(?<=-s\s/)([^/\s]+)', result["command"] )
    if title_match:
        result["title"] = title_match.group(1)
    return result

async def dealHYkData(result: dict):
    """
    处理华银康数据下载
    result: dict，包含 'command' 和 'title'
    """
    title = result["title"] 
    command = result["command"].replace("rayfile-c", str(RAYFILE_C_BIN), 1) + " ./"

    # 设置保存路径
    save_path = f"/SCL/BaiduDisk/hykData/"
    
    # 通知邮箱列表
    notify_email = [
        "zhangchuang@verygenome.com",
        "xiongtianzhu@verygenome.com",
        "zhuyuxuan@verygenome.com",
        "zhuojunyu@verygenome.com"
    ]
    notify_recipients = ",".join(notify_email)
    
    # 构建完整命令（在指定目录执行）
    send_cmd = f"cd {save_path} && {command}"
    send_email(
        notify_email,
        f"{title}华银康数据批次数据下载开始",
        f"🚀 开始下载数据:\n{title} \n下载命令: {send_cmd} \n存储路径: {save_path+title}"
    )
    exec_cmd = f"{send_cmd} && {NOTIFY_CLI} --recipients {notify_recipients} --subject {title}华银康数据批次数据下载完成 --body 存储路径为:{save_path+title}"
    # 执行下载命令
    process = await asyncio.create_subprocess_shell(
        exec_cmd
    )
    await process.wait()  # 等待进程结束  
    return process.returncode
    
