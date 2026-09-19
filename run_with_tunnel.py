"""Start a Cloudflare quick tunnel and the server together, so the email buttons
and the TDTU sign-in work from any device (a phone, another laptop).

    python run_with_tunnel.py          # server on port 8000
    python run_with_tunnel.py 8001     # another port

Needs the free `cloudflared` program (see README). No Cloudflare account needed.

The tunnel gets a NEW random https address every time, so this script:
  1. starts cloudflared and reads the address it prints
  2. writes it into .env as BASE_URL (used for the button links and the login)
  3. shows the redirect URI you must add to the Web client in Google Cloud
  4. starts the server
Press Ctrl+C to stop both.
"""
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
ENV_FILE = Path(".env")
LOG_FILE = Path("tunnel.log")


def find_cloudflared():
    """cloudflared on the PATH, or next to this script, or in ~/bin."""
    for candidate in [shutil.which("cloudflared"), "cloudflared.exe", "cloudflared",
                      str(Path.home() / "bin" / "cloudflared")]:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    sys.exit("cloudflared not found. Download it (see README) and put it in this folder.")


def wait_for_address(tunnel, seconds=40):
    """cloudflared prints its address into the log after a few seconds."""
    for _ in range(seconds * 2):
        found = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", LOG_FILE.read_text())
        if found:
            return found.group(0)
        if tunnel.poll() is not None:
            break
        time.sleep(0.5)
    tunnel.terminate()
    sys.exit(f"The tunnel did not start. See {LOG_FILE} for details.")


def set_base_url(url):
    """Replace (or add) the BASE_URL line in .env."""
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    lines = [line for line in lines if not line.startswith("BASE_URL=")]
    lines.append(f"BASE_URL={url}")
    ENV_FILE.write_text("\n".join(lines) + "\n")


def main():
    with LOG_FILE.open("w") as log:
        tunnel = subprocess.Popen(
            [find_cloudflared(), "tunnel", "--url", f"http://localhost:{PORT}"],
            stdout=log, stderr=subprocess.STDOUT)
    try:
        url = wait_for_address(tunnel)
        set_base_url(url)
        print(f"\nPublic address : {url}")
        print(f"Saved in .env  : BASE_URL={url}")
        print("\nIn Google Cloud -> Clients -> your Web (login) client -> Authorized redirect URIs,")
        print(f"add:  {url}/auth/callback   -> Save (it can take a few minutes).")
        try:
            input("\nPress Enter when saved to start the server... ")
        except EOFError:
            pass
        print(f"\nOpen {url}/login  (on any device)   -   Ctrl+C stops everything\n")
        subprocess.run([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)])
    except KeyboardInterrupt:
        pass
    finally:
        tunnel.terminate()
        print("\nTunnel stopped. The address above no longer works.")


if __name__ == "__main__":
    main()
