#!/usr/bin/env python3
"""Simple publish server - accepts state.json POST and writes to file + git push"""
import http.server
import json
import subprocess
import os

PUBLISH_KEY = "97d2870b8acfb063d9bc11e3ef9ce2db"
SITE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SITE_DIR, "state.json")

class PublishHandler(http.server.BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Publish-Key")
        self.end_headers()
    
    def do_POST(self):
        if self.path != "/publish":
            self.send_error(404)
            return
        
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
            with open(STATE_FILE, "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # Git commit and push
            subprocess.run(["git", "add", "state.json"], cwd=SITE_DIR, check=True)
            subprocess.run(["git", "commit", "-m", "publish: update shared state"], cwd=SITE_DIR, check=True)
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

if __name__ == "__main__":
    server = http.server.HTTPServer(("", 8766), PublishHandler)
    print("Publish server on :8766")
    server.serve_forever()
