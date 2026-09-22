# Absence Request Demo — FastAPI + SMTP with OAuth 2.0 (Google Cloud)

A seminar demo of **email service integration**: an employee asks for time off, the
manager receives an HTML email with **[Yes] / [No]** buttons, and one click records
the answer and emails the employee back.

## 1. Background

Sending email from an application used to mean putting a mailbox password in the
code. That single string gives whoever holds it **complete, permanent access** to
the mailbox, and Google has been switching it off for exactly that reason.

This demo shows the modern alternative:

* **SMTP** — the standard email protocol (RFC 5321), spoken to `smtp.gmail.com:587`
* **STARTTLS** — the connection is encrypted before anything secret is sent
* **XOAUTH2** — instead of a password, the login carries an **OAuth 2.0 access token**
* **Google Cloud** — where the app is registered, so a mailbox owner can grant it
  a named, expiring, revocable permission on Google's own consent screen
* **Sign in with Google (OpenID Connect)** — only TDTU accounts may use the system

The result: **two TDTU accounts email each other** through their own mailboxes, and
the application never sees anybody's password.

### Who does what

| Role | Plays | Needs |
|---|---|---|
| **Employee / worker** | asks for the absence; **their** mailbox sends the request | a TDTU account |
| **Manager** | approves or rejects; **their** mailbox sends the answer | a TDTU account |
| **Google Cloud** | registers the app, runs the consent screen, issues tokens | one Web OAuth client |
| **Gmail** | the SMTP server, the MTA and the delivery | nothing to configure |

There is **no system mailbox** and no shared password.

## 2. Overview of the flow

```
 worker ──/login──▶ Google ──consent──▶ app stores his token
        │
        └──POST /nghiphep──▶ app: saved PENDING + secret token
                                │  SMTP (worker's token)
                                ▼
                        manager's inbox: [Yes] [No]
                                │  clicks a button
                                ▼
                app: token ok? signed in as THIS manager?
                                │  yes -> APPROVED / REJECTED
                                │  SMTP (manager's token)
                                ▼
                        worker's inbox: the result
```

Security in four lines:

* the buttons carry a **random secret token**; the API never returns it
* the token alone is not enough — the clicker must be **signed in as that manager**,
  so a forwarded email is useless
* a decision is written **once** (a lock makes check-then-write one step) and the
  links expire after 48 h
* `approved.json` says who may ask and who may approve; nobody approves their own

### The code

| File | Job |
|---|---|
| `app/main.py` | the HTTP routes and all the checks |
| `app/auth.py` | Sign in with Google (TDTU only) + each person's send permission |
| `app/mail.py` | SMTP + XOAUTH2; sends as the signed-in person |
| `app/store.py` | the data (one dictionary in memory) and the approved list |
| `templates/` | the two HTML emails and the page shown after a click |
| `approved.json` | who may ask (`employees`) and who may approve (`managers`) |

| Endpoint | Purpose |
|---|---|
| `GET /login` | sign in (`?force=1` always shows the consent screen) |
| `GET /me` · `GET /logout` | who am I · sign out and revoke at Google |
| `POST /nghiphep` | create a request (the employee is whoever is signed in) |
| `GET /nghiphep/{id}/decision` | the link behind the Yes/No buttons |
| `GET /nghiphep` · `GET /nghiphep/{id}` | read your own requests |

## 3. Setup

### Google Cloud (once)

1. console.cloud.google.com → **New project**
2. APIs & Services → Library → **Gmail API** → **Enable**
3. **Google Auth platform** → Audience **External**, keep the app in *Testing*
4. **Audience → Test users** → add **both** TDTU accounts (worker and manager)
5. **Clients → Create client → Web application** → Authorized redirect URI
   `http://localhost:8001/auth/callback` → download the JSON →
   rename to **`login_client.json`** in this folder

At sign-in each person approves two things: who they are (`openid email`) and
permission to send from their mailbox (`https://mail.google.com/`).

### Install and configure

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # set SESSION_SECRET, keep BASE_URL matching your port
cp approved.example.json approved.json   # put the two real TDTU addresses here
```

### Run

```bash
uvicorn app.main:app --port 8001
```
Open **http://localhost:8001/login** — use `localhost`, not `127.0.0.1`
(the login cookie belongs to one host name).

## 4. Testing the flow

You need **two browser sessions**, because one cookie jar holds one signed-in person:
two Chrome profiles, or a normal window plus an incognito window. A single window
also works if you re-run `/login` to switch account before clicking the button.

| # | Where | Do this | Expect |
|---|---|---|---|
| 1 | window A | `/login` → sign in as the **worker**, tick the send-email box | lands on `/docs` |
| 2 | window A | `GET /me` | the worker's address, `"can_send": true` |
| 3 | window A | `POST /nghiphep` with `manager_email`, `reason`, `from_date`, `to_date` | `201`, `"status": "PENDING"` |
| 4 | manager's inbox | open `[ABSENT #1] …` (check **Spam** the first time) | email **from the worker's address**, with two buttons |
| 5 | window B | click **Yes, approve** | Google sign-in if needed → **"Request approved"** |
| 6 | worker's inbox | | result email **from the manager's address** |
| 7 | window A | `GET /nghiphep/1` | `"status": "APPROVED"`, and no token in the response |

### Worth showing as well

| Try | Expect | Demonstrates |
|---|---|---|
| Click the other button in the same email | "Already answered" | a decision happens once |
| Change one character of the token in the URL | "Invalid link" | the secret authorises the click |
| Click the manager's link while signed in as the worker | "Wrong account" | a forwarded email is useless |
| Open `/nghiphep` in a window that is not signed in | `401` | reasons are private |
| `/login` with a non-TDTU (e.g. Gmail) account | `403` | domain restriction |
| Ask with yourself as manager | `400` | no self-approval |
| `/logout` | `permission_revoked_at_google: true` | the grant is really cancelled |

## 5. Points to explain in the seminar

* **Google Cloud is the login provider, not a mail server.** Gmail's SMTP server sends
  the mail. Google Cloud registers the app and issues the token that replaces the password.
* **The scope is the full mailbox** (`https://mail.google.com/`), because Google only
  accepts OAuth over SMTP with that scope — a send-only token is refused with `535`.
  The Gmail API would allow send-only; that is the trade-off of using real SMTP.
* **Authentication vs authorization.** Signing in proves *who* you are (OpenID Connect);
  `approved.json` decides *what* you may do.
* **Least privilege, revocably granted.** The owner approves on Google's own page,
  the token expires, and it can be revoked for this app alone.
* **The SMTP conversation**: connect 587 → STARTTLS → AUTH XOAUTH2 → MAIL FROM /
  RCPT TO / DATA. The login is only base64, so it must travel inside TLS.
* **HTML email**: `multipart/alternative` (text + HTML), inline CSS, tables instead of
  flexbox, and Jinja2 autoescaping so a reason containing `<script>` stays text.

## 6. Limits

* Requests and permissions live **in memory**: restarting the server forgets them.
* Testing mode: only listed test users may sign in, and permissions expire after 7 days.
* Sign-in uses redirect URIs registered in Google Cloud, so the demo runs on `localhost`.
  Another address (a tunnel, a server) must be registered there first.
* The buttons are GET links; a production system would show a confirmation page and POST.
* Google may ask for 2-step verification before granting mailbox access in a new browser.

**Never commit** `.env`, `login_client.json` or `approved.json` (real addresses).
