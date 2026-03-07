#!/usr/bin/env python3
"""Protected site server — two access levels: viewer and editor."""
import http.server
import os
import json
import hashlib
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timedelta
import secrets

PORT = 8765
SITE_DIR = os.path.dirname(os.path.abspath(__file__))

# Passwords
VIEWER_PASS = "צופה2026"      # View only
EDITOR_PASS = "עורכת2026"     # View + edit

# Session tokens (in-memory)
sessions = {}  # token -> {"role": "viewer"|"editor", "expires": datetime}

SESSION_HOURS = 24

def make_token():
    return secrets.token_hex(32)

def check_session(cookie_header):
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("auth="):
            token = part[5:]
            sess = sessions.get(token)
            if sess and sess["expires"] > datetime.now():
                return sess["role"]
            elif sess:
                del sessions[token]
    return None

LOGIN_HTML = """<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>כניסה — ריבונות הכנסת</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Tahoma,Arial,sans-serif;background:linear-gradient(135deg,#0A5E6E 0%,#1B3A6B 100%);min-height:100vh;display:flex;align-items:center;justify-content:center;direction:rtl}
.login-box{background:#fff;border-radius:16px;padding:40px;box-shadow:0 8px 40px rgba(0,0,0,.3);max-width:400px;width:90%;text-align:center}
h1{color:#0A5E6E;margin-bottom:8px;font-size:24px}
.subtitle{color:#888;font-size:13px;margin-bottom:24px}
input[type="password"]{width:100%;padding:12px 16px;border:2px solid #ddd;border-radius:10px;font-family:inherit;font-size:16px;text-align:center;direction:rtl;margin-bottom:12px;transition:border-color .2s}
input:focus{outline:none;border-color:#0A5E6E}
button{width:100%;padding:12px;border:none;border-radius:10px;background:#0A5E6E;color:#fff;font-size:16px;font-weight:700;cursor:pointer;font-family:inherit;transition:all .2s}
button:hover{background:#087080}
.error{color:#CC0000;font-size:13px;margin-top:8px;display:none}
.logo{font-size:48px;margin-bottom:12px}
</style>
</head>
<body>
<div class="login-box">
  <div class="logo">🏛️</div>
  <h1>ריבונות הכנסת</h1>
  <p class="subtitle">הליך חקיקה פרטית — מערכת מוגנת</p>
  <form method="POST" action="/login">
    <input type="password" name="password" placeholder="סיסמה..." autofocus>
    <button type="submit">🔐 כניסה</button>
  </form>
  {error}
</div>
</body>
</html>"""

class ProtectedHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SITE_DIR, **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path

        # Login page doesn't need auth
        if path == "/login":
            self.send_login_page()
            return

        # Check auth
        role = check_session(self.headers.get("Cookie"))
        if not role:
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
            return

        # Inject role info into index.html
        if path == "/" or path == "/index.html":
            self.serve_index_with_role(role)
            return

        # Serve static files normally
        super().do_GET()

    def do_POST(self):
        if self.path == "/login":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            params = parse_qs(body)
            password = params.get("password", [""])[0]

            role = None
            if password == EDITOR_PASS:
                role = "editor"
            elif password == VIEWER_PASS:
                role = "viewer"

            if role:
                token = make_token()
                sessions[token] = {"role": role, "expires": datetime.now() + timedelta(hours=SESSION_HOURS)}
                self.send_response(302)
                self.send_header("Set-Cookie", f"auth={token}; Path=/; Max-Age={SESSION_HOURS*3600}; SameSite=Lax")
                self.send_header("Location", "/")
                self.end_headers()
            else:
                self.send_login_page(error=True)
            return

        # Forward other POSTs
        super().do_GET()

    def send_login_page(self, error=False):
        error_html = '<p class="error" style="display:block">סיסמה שגויה</p>' if error else ''
        html = LOGIN_HTML.replace("{error}", error_html)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def serve_index_with_role(self, role):
        filepath = os.path.join(SITE_DIR, "index.html")
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()

        # Inject role as JS variable and hide edit button for viewers
        role_script = f'<script>window.USER_ROLE = "{role}";</script>'
        if role == "viewer":
            # Hide edit toggle for viewers
            role_script += """<style>
.toolbar button[onclick*="toggleEditing"], .edit-actions, .step-edit-actions,
.add-step-btn, .flow-edit-actions, .flow-insert-btn, .flow-shape-sel,
button[onclick*="publishState"], .edit-btn-sm { display: none !important; }
</style>"""

        html = html.replace("</head>", role_script + "\n</head>")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        pass  # Quiet logs

if __name__ == "__main__":
    server = http.server.HTTPServer(("", PORT), ProtectedHandler)
    print(f"Protected site server on :{PORT}")
    print(f"  Viewer: {VIEWER_PASS}")
    print(f"  Editor: {EDITOR_PASS}")
    server.serve_forever()
