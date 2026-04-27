from email.message import EmailMessage
import smtplib

def send_email(recipients: list, subject: str, body: str):
    """简单 SMTP 邮件发送函数"""
    smtp_server = "smtphz.qiye.163.com"  # 根据实际邮箱修改
    smtp_port = 465
    sender_email = "servicebot@verygenome.com"
    sender_password = "Servicebot!"  # 使用邮箱授权码或密码

    msg = EmailMessage()
    msg["From"] = sender_email
    msg["To"] = ', '.join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")