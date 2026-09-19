# Absence Request Demo — How to Use

An employee asks for time off; the manager gets an HTML email with **[Yes] / [No]**
buttons; one click saves the answer and emails the employee.
Mail is sent with **SMTP** (smtp.gmail.com, port 587), logging in with an
**OAuth 2.0 token** from **Google Cloud** instead of a password.
No UI — use Swagger at `/docs` and watch the inboxes.

```
Employee ─POST /nghiphep─▶ API ──SMTP──▶ Manager's inbox
                                                 │ clicks Yes / No
Employee's inbox ◀─result email─ API ◀───────────┘
```

**Files:** `app/store.py` (data, in memory) · `app/mail.py` (Gmail + emails) ·
`app/main.py` (routes) · `approved.json` (who may take part) · `templates/` (HTML emails) · `check_gmail.py` (one-time login) ·
`CODE_EXPLAINED.pdf` (code walkthrough)

## How it works

- **Secret token.** Each request gets a random token that exists only inside the
  two button links. The API never returns it. A click counts only if the token
  matches; it works **once** and expires after **48 h**. No login needed.
- **SMTP login (XOAUTH2).** The app connects to smtp.gmail.com:587, encrypts with
  **STARTTLS**, then logs in by sending an **OAuth 2.0 token instead of a password**.
- **Role of Google Cloud: the login provider.** It does not send mail — Gmail's SMTP
  server does. Google Cloud registers the app (`credentials.json`) and runs the
  consent screen; the mailbox owner approves once; Google issues `token.json`.
  No token → the SMTP login fails and nothing sends.
- **Scope: full mailbox, not send-only.** Google only accepts OAuth logins over SMTP
  with `https://mail.google.com/` — a send-only token is refused (`535`). This is
  Google's rule, not a setting you can change in Google Cloud. So: use a
  **dedicated system mailbox**, keep `token.json` secret, revoke it after the demo.
  (True send-only is possible only with the Gmail API and `gmail.send`.)
- **Why a token beats an app password:** it never exposes the password, expires,
  can be revoked for this app alone, and works even where app passwords are disabled.

- **Approved list.** `approved.json` lists who may ask (`employees`) and who may
  approve (`managers`). Anyone else gets **403** and nothing is saved or sent.
  Roles can't be swapped. Edit the file any time — no restart needed.
  Delete it to let everyone in.

## Setup

**1. Google Cloud** (signed in as the Gmail that will *send* the mails)
1. console.cloud.google.com → **New project**
2. APIs & Services → Library → **Gmail API** → Enable
3. Google Auth platform → Get started → Audience **External**
4. Audience → **Test users** → add that Gmail (keep the app in *Testing*)
5. Clients → Create client → **Desktop app** → download JSON →
   rename to **`credentials.json`** and put it in this folder

**2. Install and configure**
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
```
In `.env`, set `MAIL_ADDRESS` to that Gmail(The one used in test user of Google Cloud).
In `approved.json`, put the real employee and manager addresses you will use.

**3. Authorize (once) This is to create the token**
```bash
python check_gmail.py
```
Sign in → **Advanced → Go to app (unsafe)** → tick the Gmail permission (*read, compose, send and delete*) → Continue.
A test email arrives in that inbox.

**4. Run**
```bash
uvicorn app.main:app --reload
```
Open http://localhost:8000/docs

## Demo

1. **POST /nghiphep**:
   ```json
   {"employee_email": "employee@example.com", "manager_email": "manager@example.com",
    "reason": "Family trip", "from_date": "2026-10-01", "to_date": "2026-10-03"}
   ```
2. Manager's inbox (check **Spam** first time) → click **Yes, approve**
3. Employee gets the result email; **GET /nghiphep/1** shows `APPROVED`
4. Click the other button → "Already answered", nothing changes

## Two ways to run: where can the buttons be clicked?

The **[Yes] / [No]** buttons are links to *your* API (`BASE_URL`), so the browser
that opens them must be able to reach your computer. Sending email works either
way — this only decides **where the buttons can be clicked**.

### Method A — Same computer (simplest)

```
BASE_URL=http://localhost:8000
```
Open the manager's mailbox in a browser **on the computer running the server**
and click there. Nothing else to install.
On a phone it fails: there, `localhost` means the phone itself.

### Method B — Any device, with a Cloudflare tunnel

`cloudflared` (free, no account) gives your computer a temporary public HTTPS
address and forwards it to your local server:

```
phone ──HTTPS──▶ Cloudflare ──tunnel──▶ cloudflared (your computer) ──▶ localhost:8000
```

1. **Download** `cloudflared`:
   - Windows: https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
     (rename to `cloudflared.exe`)
   - Linux: https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
   - macOS: `brew install cloudflared`
2. **Terminal 1** — start the tunnel and leave it open:
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
   Copy the address it prints: `https://some-random-words.trycloudflare.com`.
   Warnings about *ICMP*, *buffer size* or *QUIC failed* are harmless.
3. Put that address in `.env`: `BASE_URL=https://some-random-words.trycloudflare.com`
4. **Terminal 2** — start (or restart) the server:
   `uvicorn app.main:app --reload`
5. Check: open `<that address>/docs` on your phone. Then send a **new** request.

> The address **changes every time** cloudflared restarts, and buttons in older
> emails stop working. Order: tunnel → `.env` → server → send.

## Troubleshooting

| Problem | Fix |
|---|---|
| `access_denied` when signing in | add that Gmail as a **Test user** |
| `Gmail is not authorized` | run `python check_gmail.py` |
| `535` / *Username and Password not accepted* | token has the wrong scope or `MAIL_ADDRESS` isn't the account you approved: delete `token.json`, re-run `check_gmail.py` |
| *timed out* connecting to smtp.gmail.com:587 | the network blocks SMTP (common on school Wi-Fi): use a phone hotspot |
| `invalid_grant` / token expired | tokens expire after 7 days: delete `token.json`, re-run `check_gmail.py` |
| port already in use | `--port 8001` and `BASE_URL=http://localhost:8001` |
| "Invalid link" after restart | data is in memory — send a new request |
| `403 ... not on the approved ... list` | add the address to `approved.json` (right role) |
| `.env` change ignored | restart the server |

**sensitive are stored in** `.env`, `credentials.json` or `token.json`.
