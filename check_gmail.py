"""Authorize the system mailbox once, then check that sending works.

Needs credentials.json (from Google Cloud) in this folder.
Creates token.json after you approve access in the browser.

    python check_gmail.py
"""
from app import mail


def main():
    mail.get_credentials(interactive=True)  # first run: opens the browser
    print("[1/2] Authorized: Google accepted the app and saved token.json")

    if not mail.MAIL_ADDRESS:
        raise SystemExit("Set MAIL_ADDRESS in .env to the Gmail you just authorized.")

    mail.send(mail.MAIL_ADDRESS, "SMTP + OAuth 2.0 test",
              "If you can read this, sending works.",
              "<p>If you can read this, <b>sending</b> works.</p>")
    print(f"[2/2] Send OK: test email sent to {mail.MAIL_ADDRESS}")

    if "localhost" in mail.BASE_URL:
        print(f"\nNote: BASE_URL is {mail.BASE_URL}, so the buttons only open on this computer.")
    print("\nAll good. Keep credentials.json and token.json private.")


if __name__ == "__main__":
    main()
