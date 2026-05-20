from email.message import EmailMessage
import smtplib

from common.config import get_config

def send_email(recipients: list, subject: str, body: str):
    """简单 SMTP 邮件发送函数"""
    smtp_server = get_config("email.smtp.server")
    smtp_port = get_config("email.smtp.port")
    sender_email = get_config("email.smtp.sender")
    sender_password = get_config("email.smtp.password")
    use_ssl = get_config("email.smtp.use_ssl")

    msg = EmailMessage()
    msg["From"] = sender_email
    msg["To"] = ', '.join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        with smtp_class(smtp_server, smtp_port) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
