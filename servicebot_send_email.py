import argparse
from common.email_sender import send_email

def main():
    parser = argparse.ArgumentParser(description="Send email via command line.")
    parser.add_argument('--recipients', type=str, required=True,
                        help='Comma-separated list of recipient emails')
    parser.add_argument('--subject', type=str, required=True,
                        help='Email subject')
    parser.add_argument('--body', type=str, required=True,
                        help='Email body')

    args = parser.parse_args()

    # 把逗号分隔的字符串转换为列表
    recipients_list = [email.strip() for email in args.recipients.split(',')]
    
    send_email(recipients_list, args.subject, args.body)

if __name__ == "__main__":
    main()
