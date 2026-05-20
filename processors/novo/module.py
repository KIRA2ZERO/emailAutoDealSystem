import re,os,subprocess,asyncio
from contextlib import nullcontext
from pathlib import Path

from common.config import get_list, get_path
from common.email_sender import send_email

LND_BIN = Path(__file__).resolve().parent / "bin" / "lnd"
NOTIFY_CLI = get_path("paths.notify_cli")

def existNovoData(text:str):
    if "北京诺禾致源科技股份有限公司" in text:
        return True
    else:
        return False

def parseNovoData(text: str):
    """
    从诺禾致源的邮件正文中提取 数据路径 / 登录账号 / 登录密码
    """
    result = {}

    # 数据路径
    path_match = re.search(r"数据路径为[:：]\s*(\S+)", text)
    if path_match:
        result["data_path"] = path_match.group(1)

    # 登录账号
    account_match = re.search(r"登录账号[:：]\s*(\S+)", text)
    if account_match:
        result["account"] = account_match.group(1)

    # 登录密码
    password_match = re.search(r"登录密码[:：]\s*(\S+)", text)
    if password_match:
        result["password"] = password_match.group(1)

    return result

def append_log(log_file: str, message: str):
    if not log_file:
        return
    with open(log_file, "a", encoding="utf-8") as fh:
        fh.write(message.rstrip() + "\n")


async def dealNovoData(result: dict, log_file: str = None):
    """
    使用 Docker 调用 lnd 客户端登录诺禾致源云并下载数据
    result: dict，包含 'account', 'password', 'data_path'
    """
    account = result.get("account")
    password = result.get("password")
    data_path = result.get("data_path")    
    save_path = f"/SCL/BaiduDisk/NovoData/{account}"
    log_path = log_file or "未生成"
    notify_email = get_list("notifications.default_recipients")
    notify_recipients = ",".join(notify_email)
    # 构建下载命令
    cmd = f"""
    docker run --rm \
    -v {LND_BIN}:/root/lnd \
    -v /SCL:/SCL \
    -w /root \
    ubuntu:24.04 \
    bash -c './lnd login -u {account} -p {password} && ./lnd cp -d oss://{data_path} {save_path} && {NOTIFY_CLI} --recipients {notify_recipients} --subject {account}批次数据下载完成 --body 存储路径为:{save_path}；日志路径为:{log_path}'
    """    
    # 下载数据
    append_log(log_file, f"开始 Novo 下载任务，account={account}, data_path={data_path}")
    append_log(log_file, f"下载命令:\n{cmd}")
    send_email(notify_email, f"{account}批次数据下载开始", f"🚀 开始下载数据:\n{data_path} \n 下载命令为:{cmd} \n 存储路径为:{save_path}\n日志路径为:{log_path}")
    log_context = open(log_file, "a", encoding="utf-8") if log_file else nullcontext(subprocess.DEVNULL)
    with log_context as log_fh:
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=log_fh,
            stderr=log_fh,
        )
        await process.wait()  # 等待进程结束
    append_log(log_file, f"Novo 下载任务结束，returncode={process.returncode}")
    return process.returncode
  
