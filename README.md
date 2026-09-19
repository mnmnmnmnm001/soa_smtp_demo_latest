# Absence Request Demo — SMTP + OAuth 2.0 + Sign in with TDTU

An employee asks for time off; the manager gets an HTML email with **[Yes] / [No]**
buttons; one click saves the answer and emails the employee.

- Email is sent with **SMTP** (smtp.gmail.com:587), logging in with an **OAuth 2.0
  token** from **Google Cloud** instead of a password.
- Employees and managers **sign in with their TDTU Google account**.
- No UI of its own: use Swagger at `/docs` and the inboxes.

```
Employee ─sign in─▶ POST /nghiphep ─▶ API ──SMTP──▶ Manager's inbox
                                                        │ clicks Yes / No (signed in)
Employee's inbox ◀──SMTP── result email ◀── API ◀───────┘
```

**Files:** `app/main.py` (routes) · `app/auth.py` (TDTU sign-in) · `app/mail.py` (SMTP + emails) ·
`app/store.py` (data, in memory) · `approved.json` (who may take part) · `templates/` (HTML emails) ·
`check_gmail.py` (authorize the sender once) · `run_with_tunnel.py` (public address)

## How it works

- **Sign in with TDTU (OpenID Connect).** `/login` sends you to Google; only verified
  `@tdtu.edu.vn` / `@student.tdtu.edu.vn` accounts are accepted. It asks only for
  `openid email` — who you are, nothing in your mailbox. Your login is kept in a signed cookie.
- **Approved list.** Login proves *who* you are; `approved.json` decides *what* you may do:
  who may ask (`employees`) and who may approve (`managers`). Others get **403**.
- **Secret link + login.** Each request has a random token inside the two buttons; the API
  never returns it. A click counts only if the token matches **and** you are signed in as that
  request's manager. It works **once** and expires after **48 h**. A forwarded email is useless.
- **SMTP login (XOAUTH2).** The app connects to smtp.gmail.com:587, encrypts with **STARTTLS**,
  then logs in with the token instead of a password.
- **Role of Google Cloud: the login provider.** It does not send mail — Gmail's SMTP server
  does. Google Cloud registers the app (two OAuth clients) and runs the consent screen.
- **Scope: full mailbox.** Google only accepts OAuth logins over SMTP with
  `https://mail.google.com/` (a send-only token is refused with `535`). So use a mailbox that
  holds nothing sensitive, keep `token.json` secret and revoke it after the demo.

## Setup

### 1. Google Cloud (signed in as the project owner)

1. console.cloud.google.com → **New project**
2. APIs & Services → Library → **Gmail API** → Enable
3. Google Auth platform → Get started → Audience **External** (keep it in *Testing*)
4. Audience → **Test users** → add **every account that will be used**: the sending
   mailbox, the employee and the manager
5. Clients → Create client → **Desktop app** → download JSON → rename to
   **`credentials.json`** (used to authorize the sending mailbox)
6. Clients → Create client → **Web application** → Authorized redirect URIs:
   `http://localhost:8000/auth/callback` → download JSON → rename to **`login_client.json`**
   (used for sign-in)

Put both JSON files in this folder. Tip: name the clients *SMTP Sender* and *TDTU Login*.

### 2. Install and configure

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
```
In `.env`: set `MAIL_ADDRESS` (the sending mailbox) and a random `SESSION_SECRET`.
In `approved.json`: put the real employee and manager addresses.
One account may appear in both lists for a one-person demo.

### 3. Authorize the sending mailbox (once)

```bash
python check_gmail.py
```
Sign in as the **sending** mailbox → **Advanced → Go to app (unsafe)** → tick the Gmail
permission → Continue. A test email arrives in that inbox.

## Run

### A. On this computer only

```bash
uvicorn app.main:app --reload
```
Open **http://localhost:8000/login** (use `localhost`, not `127.0.0.1`).

### B. From any device — Cloudflare tunnel

Download `cloudflared` (free, no account; tested with version 2026.9.1) and put it in
this folder — it is not in the repository because each system needs its own file:
- Windows: https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
  (rename to `cloudflared.exe`)
- Linux: https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
  (rename to `cloudflared`, then `chmod +x cloudflared`)
- macOS: `brew install cloudflared`

```bash
python run_with_tunnel.py
```
It starts the tunnel, writes the public address into `.env` as `BASE_URL`, and prints a
redirect URI like `https://some-words.trycloudflare.com/auth/callback`.
**Add it to the Web (login) client in Google Cloud → Save**, wait a minute, press **Enter**.
Then open `https://some-words.trycloudflare.com/login` on any device.

> The address changes **every run**: add the new redirect URI each time, and buttons in
> emails sent before stop working. Ctrl+C stops the tunnel and the server.
> Warnings about *ICMP*, *buffer size* or *QUIC* in `tunnel.log` are harmless.

## Demo

1. Employee: open `/login`, sign in → you land on `/docs`; **GET /me** shows who you are
2. **POST /nghiphep**:
   ```json
   {"manager_email": "manager@tdtu.edu.vn", "reason": "Family trip",
    "from_date": "2026-10-01", "to_date": "2026-10-03"}
   ```
   The employee is whoever is signed in.
3. Manager: open the email (check **Spam** first time) → **Yes, approve**. Not signed in →
   Google sign-in first, then back to the button. (Same browser for both roles: use a
   private window for the manager.)
4. The employee gets the result email; **GET /nghiphep/1** shows `APPROVED`
5. Click the other button → "Already answered". A Gmail account at `/login` → 403.

## Demo with two people (tunnel)

A friend plays the **manager** and approves from **his own phone**.

**Before** (once):
1. His TDTU address is a **Test user** in Google Cloud
2. His address is under `managers` in `approved.json` (yours under `employees`)
3. `python run_with_tunnel.py` → add the printed redirect URI to the Web client → Enter

**Then:**
1. You open `<tunnel address>/login`, sign in, and in `/docs` send **POST /nghiphep**
   with `"manager_email": "<his TDTU address>"`
2. He opens the email on his phone → **Yes, approve** → signs in with **his** TDTU
   account → "Request approved"
3. You get the result email; **GET /nghiphep/1** shows `APPROVED`
4. Bonus: you click his button while signed in as yourself → **"Wrong account"** (403)

Keep in mind:
- He must **click a button**. Replying to the email does nothing — the app does not read
  replies.
- Send the request **after** the tunnel starts: the buttons contain the tunnel address.
- Keep your laptop and the tunnel **running** until he clicks. Restarting forgets the request
  and changes the address.

## Troubleshooting

| Problem | Fix |
|---|---|
| `redirect_uri_mismatch` at sign-in | add the exact `.../auth/callback` URI to the **Web** client, Save, wait a few minutes |
| `access_denied` | add the account as a **Test user** |
| 403 "Only TDTU accounts" | sign in with a TDTU account (or change `ALLOWED_DOMAINS`) |
| 403 "not on the approved … list" | add the address to `approved.json`, right role |
| 401 "Sign in first" | open `/login` in the **same** browser as `/docs` |
| "Wrong account" on a button | `/logout`, sign in as the request's manager |
| `Gmail is not authorized` | run `python check_gmail.py` |
| `535` from SMTP | token for the wrong account/scope: delete `token.json`, re-run `check_gmail.py`; right after a first approval, wait a minute and retry |
| timed out to smtp.gmail.com:587 | the network blocks SMTP (common on school Wi-Fi): use a phone hotspot |
| `invalid_grant` / expired | Testing-mode tokens last 7 days: delete `token.json`, re-run `check_gmail.py` |
| "Invalid link" after restart | data is in memory — send a new request |
| port already in use | `uvicorn app.main:app --port 8001`, set `BASE_URL` and the redirect URI to 8001 |

**Never share** `.env`, `credentials.json`, `login_client.json`, `token.json`.
Deleting the Desktop client in Google Cloud cancels the sending token.
