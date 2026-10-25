#!/usr/bin/env python3
"""
Lightweight HTTP Server for injekt-pro-landing with optional JSON lead logging.
Listens on port 8080 (or PORT env var) on 0.0.0.0.
"""
import http.server
import socketserver
import os
import json
from datetime import datetime

PORT = int(os.environ.get("PORT", 8080))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEADS_FILE = os.path.join(BASE_DIR, "leads.json")

class LandingHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def do_POST(self):
        if self.path == "/api/lead":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            try:
                lead_data = json.loads(post_data.decode("utf-8"))
                lead_data["received_at"] = datetime.now().isoformat()

                leads = []
                if os.path.exists(LEADS_FILE):
                    try:
                        with open(LEADS_FILE, "r", encoding="utf-8") as f:
                            leads = json.load(f)
                    except Exception:
                        leads = []

                leads.append(lead_data)
                with open(LEADS_FILE, "w", encoding="utf-8") as f:
                    json.dump(leads, f, ensure_ascii=False, indent=2)

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                response = {"status": "ok", "message": "Lead recorded successfully"}
                self.wfile.write(json.dumps(response).encode("utf-8"))
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] New lead received: {lead_data.get('phone')} / {lead_data.get('name')}")
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "error": str(e)}).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")

if __name__ == "__main__":
    os.chdir(BASE_DIR)
    with socketserver.TCPServer(("0.0.0.0", PORT), LandingHandler) as httpd:
        print(f"=====================================================")
        print(f"  INJEKT-PRO LANDING SERVER STARTED")
        print(f"  Local address: http://localhost:{PORT}")
        print(f"  Root directory: {BASE_DIR}")
        print(f"  Leads storage:  {LEADS_FILE}")
        print(f"=====================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
