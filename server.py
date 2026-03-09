#!/usr/bin/env python3
"""Protected site server — two access levels: viewer and editor."""
import http.server
import os
import json
import hashlib
import subprocess
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
PUBLISH_KEY = "97d2870b8acfb063d9bc11e3ef9ce2db"
STATE_FILE = os.path.join(SITE_DIR, "state.json")

# --- Merge logic (from publish.py) ---
def step_content_size(step):
    return len(step.get("details", "") or "") + len(step.get("detailsHtml", "") or "")

def merge_step_content(existing_step, incoming_step):
    merged = dict(incoming_step)
    ex_content = step_content_size(existing_step)
    in_content = step_content_size(incoming_step)
    # Always keep the RICHER content (more detailsHtml chars wins)
    ex_html = existing_step.get("detailsHtml") or ""
    in_html = incoming_step.get("detailsHtml") or ""
    if len(ex_html) > len(in_html):
        merged["detailsHtml"] = ex_html
    # Same for details text
    ex_det = existing_step.get("details") or ""
    in_det = incoming_step.get("details") or ""
    if len(ex_det) > len(in_det):
        merged["details"] = ex_det
    return merged

def deep_merge_steps(existing_steps, incoming_steps):
    if not existing_steps: return incoming_steps or []
    if not incoming_steps: return existing_steps
    ex_map = {s["id"]: s for s in existing_steps}
    result, seen = [], set()
    for s in incoming_steps:
        seen.add(s["id"])
        if s["id"] in ex_map:
            merged = merge_step_content(ex_map[s["id"]], s)
            merged["children"] = deep_merge_steps(ex_map[s["id"]].get("children", []), s.get("children", []))
            result.append(merged)
        else:
            result.append(s)
    for s in existing_steps:
        if s["id"] not in seen:
            result.append(s)
    return result

def deep_merge_stage(existing_stage, incoming_stage):
    merged = dict(incoming_stage)
    merged["steps"] = deep_merge_steps(existing_stage.get("steps", []), incoming_stage.get("steps", []))
    return merged

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

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Publish-Key")
        self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/login":
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

        if path == "/publish":
            self.handle_publish()
            return

        if path == "/report":
            self.handle_report()
            return

        self.send_error(404)

    def handle_publish(self):
        key = self.headers.get("X-Publish-Key", "")
        if key != PUBLISH_KEY:
            self.send_response(401)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b'{"error":"unauthorized"}')
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            existing = {}
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r") as f:
                    try: existing = json.load(f)
                    except: pass
                # Backup before merge
                backup_dir = os.path.join(SITE_DIR, "backups")
                os.makedirs(backup_dir, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup_file = os.path.join(backup_dir, f"state-before-publish-{ts}.json")
                import shutil
                shutil.copy2(STATE_FILE, backup_file)
                # Keep only last 20 backups
                backups = sorted([f for f in os.listdir(backup_dir) if f.endswith('.json')])
                for old in backups[:-20]:
                    os.remove(os.path.join(backup_dir, old))
            if existing.get("stages") and data.get("stages"):
                existing_map = {s["id"]: s for s in existing["stages"]}
                merged_stages, seen = [], set()
                for s in data["stages"]:
                    seen.add(s["id"])
                    if s["id"] in existing_map:
                        merged_stages.append(deep_merge_stage(existing_map[s["id"]], s))
                    else:
                        merged_stages.append(s)
                for s in existing["stages"]:
                    if s["id"] not in seen:
                        merged_stages.append(s)
                data["stages"] = merged_stages
            author = data.get("publishedBy", "unknown")
            data["mergedAt"] = datetime.now().isoformat()
            with open(STATE_FILE, "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            subprocess.run(["git", "add", "state.json"], cwd=SITE_DIR, check=True)
            subprocess.run(["git", "commit", "-m", f"publish: merge by {author}"], cwd=SITE_DIR, check=True)
            subprocess.run(["git", "push"], cwd=SITE_DIR, check=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        except Exception as e:
            self.send_response(500)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def handle_report(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            reports_dir = os.path.join(SITE_DIR, "reports")
            os.makedirs(reports_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            reporter = data.get("reporter", "unknown").replace("/","_").replace("..","")
            filename = f"issues-{ts}-{reporter}.json"
            with open(os.path.join(reports_dir, filename), "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "file": filename}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

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
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
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
