#!/usr/bin/env python3
"""Simple publish server - accepts state.json POST and writes to file + git push"""
import http.server
import json
import subprocess
import os
from datetime import datetime

PUBLISH_KEY = "97d2870b8acfb063d9bc11e3ef9ce2db"

def step_content_size(step):
    """Calculate total content size of a step (details + detailsHtml)"""
    return len(step.get("details", "") or "") + len(step.get("detailsHtml", "") or "")

def build_step_map(steps):
    """Recursively build a map of step_id -> step for all steps in a tree"""
    result = {}
    if not steps:
        return result
    for s in steps:
        result[s["id"]] = s
        result.update(build_step_map(s.get("children", [])))
    return result

def merge_step_content(existing_step, incoming_step):
    """Merge a single step: keep the version with more content for details fields.
    For other fields, incoming wins (user's latest structural changes)."""
    merged = dict(incoming_step)  # Start with incoming (structural changes)
    
    # For content fields, keep the richer version to prevent data loss
    ex_content = step_content_size(existing_step)
    in_content = step_content_size(incoming_step)
    
    if ex_content > in_content and in_content == 0:
        # Incoming has no content but existing does — preserve existing content
        merged["details"] = existing_step.get("details", "")
        merged["detailsHtml"] = existing_step.get("detailsHtml")
    
    return merged

def deep_merge_steps(existing_steps, incoming_steps):
    """Recursively merge step lists, preserving content from both sides"""
    if not existing_steps:
        return incoming_steps or []
    if not incoming_steps:
        return existing_steps
    
    ex_map = {s["id"]: s for s in existing_steps}
    result = []
    seen = set()
    
    for s in incoming_steps:
        seen.add(s["id"])
        if s["id"] in ex_map:
            merged = merge_step_content(ex_map[s["id"]], s)
            # Recursively merge children
            merged["children"] = deep_merge_steps(
                ex_map[s["id"]].get("children", []),
                s.get("children", [])
            )
            result.append(merged)
        else:
            result.append(s)
    
    # Preserve steps only in existing (shouldn't happen but safe)
    for s in existing_steps:
        if s["id"] not in seen:
            result.append(s)
    
    return result

def deep_merge_stage(existing_stage, incoming_stage):
    """Merge a stage by recursively merging its steps"""
    merged = dict(incoming_stage)
    merged["steps"] = deep_merge_steps(
        existing_stage.get("steps", []),
        incoming_stage.get("steps", [])
    )
    return merged
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
        if self.path == "/report":
            return self.handle_report()
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
            # Load existing state for merge
            existing = {}
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r") as f:
                    try: existing = json.load(f)
                    except: pass
            
            # Step-level merge: merge individual steps within each stage
            if existing.get("stages") and data.get("stages"):
                existing_map = {s["id"]: s for s in existing["stages"]}
                incoming_map = {s["id"]: s for s in data["stages"]}
                
                merged_stages = []
                seen = set()
                for s in data["stages"]:
                    sid = s["id"]
                    seen.add(sid)
                    if sid in existing_map:
                        # Deep merge: for each step, keep the version with MORE content
                        merged_stage = deep_merge_stage(existing_map[sid], s)
                        merged_stages.append(merged_stage)
                    else:
                        merged_stages.append(s)
                for s in existing["stages"]:
                    if s["id"] not in seen:
                        merged_stages.append(s)
                data["stages"] = merged_stages
            
            # Always merge categories and flow (take incoming for now)
            author = data.get("publishedBy", "unknown")
            data["mergedAt"] = datetime.now().isoformat()
            
            with open(STATE_FILE, "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # Git commit and push
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
        """Receive issue reports and save to reports/ directory"""
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            reports_dir = os.path.join(SITE_DIR, "reports")
            os.makedirs(reports_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            reporter = data.get("reporter", "unknown").replace("/","_").replace("..","")
            filename = f"issues-{ts}-{reporter}.json"
            filepath = os.path.join(reports_dir, filename)
            with open(filepath, "w") as f:
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

if __name__ == "__main__":
    server = http.server.HTTPServer(("", 8766), PublishHandler)
    print("Publish server on :8766")
    server.serve_forever()
