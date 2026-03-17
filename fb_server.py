#!/usr/bin/env python3
"""FB 친구 포스팅 서버 - 피드 + 친구 관리 UI"""

import http.server
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime

PORT = 8484
BASE_DIR = os.path.expanduser("~/facebook")
FRIENDS_FILE = os.path.join(BASE_DIR, "friends.json")
FEED_HTML = os.path.join(BASE_DIR, "fb_friend_posts.html")
FEED_JSON = os.path.join(BASE_DIR, "fb_friend_posts.json")

# 크롤링 상태 추적
crawl_state = {"running": False, "started": None, "finished": None, "pid": None}


def load_friends():
    try:
        with open(FRIENDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_friends(friends):
    with open(FRIENDS_FILE, "w", encoding="utf-8") as f:
        json.dump(friends, f, ensure_ascii=False, indent=2)


def get_last_scraped():
    try:
        mtime = os.path.getmtime(FEED_JSON)
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "없음"


def run_crawl():
    """크롤링 실행 (스레드에서 호출)"""
    crawl_state["running"] = True
    crawl_state["started"] = datetime.now().strftime("%H:%M:%S")
    crawl_state["finished"] = None
    try:
        proc = subprocess.Popen(
            [sys.executable, os.path.join(BASE_DIR, "fb_friend_posts.py")],
            stdout=open(os.path.join(BASE_DIR, "cron.log"), "a"),
            stderr=subprocess.STDOUT,
            cwd=BASE_DIR
        )
        crawl_state["pid"] = proc.pid
        proc.wait()
    except Exception:
        pass
    crawl_state["running"] = False
    crawl_state["finished"] = datetime.now().strftime("%H:%M:%S")
    crawl_state["pid"] = None


def admin_html():
    friends = load_friends()
    last = get_last_scraped()

    rows = ""
    for i, f in enumerate(friends):
        slug = f['url'].split('facebook.com/')[1] if 'facebook.com/' in f['url'] else f['url']
        rows += f"""
        <tr>
          <td class="name">{f['name']}</td>
          <td class="url"><a href="{f['url']}" target="_blank">{slug}</a></td>
          <td class="actions">
            <form method="POST" action="/admin/delete" style="display:inline">
              <input type="hidden" name="index" value="{i}">
              <button type="submit" class="btn-del" onclick="return confirm('삭제?')">삭제</button>
            </form>
            <form method="POST" action="/admin/move" style="display:inline">
              <input type="hidden" name="index" value="{i}">
              <input type="hidden" name="dir" value="up">
              <button type="submit" class="btn-move">↑</button>
            </form>
            <form method="POST" action="/admin/move" style="display:inline">
              <input type="hidden" name="index" value="{i}">
              <input type="hidden" name="dir" value="down">
              <button type="submit" class="btn-move">↓</button>
            </form>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FB Feed - 관리</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#18191a;color:#e4e6eb;padding:20px}}
.wrap{{max-width:700px;margin:0 auto}}
h1{{font-size:20px;margin-bottom:4px}}
.meta{{font-size:12px;color:#b0b3b8;margin-bottom:20px}}
.meta a{{color:#2d88ff;text-decoration:none}} .meta a:hover{{text-decoration:underline}}
.card{{background:#242526;border-radius:12px;border:1px solid #3e4042;padding:16px;margin-bottom:16px}}
.card h2{{font-size:16px;margin-bottom:12px}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;font-size:12px;color:#b0b3b8;padding:6px 8px;border-bottom:1px solid #3e4042}}
td{{padding:8px;border-bottom:1px solid #3e4042;font-size:14px}}
td.url a{{color:#2d88ff;text-decoration:none;font-size:12px}} td.url a:hover{{text-decoration:underline}}
.btn-del{{background:#c0392b;color:#fff;border:none;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:12px}}
.btn-del:hover{{background:#e74c3c}}
.btn-move{{background:#3e4042;color:#e4e6eb;border:none;padding:4px 8px;border-radius:6px;cursor:pointer;font-size:12px}}
.btn-move:hover{{background:#555}}
.add-form{{display:flex;gap:8px;margin-top:12px}}
.add-form input{{flex:1;background:#3a3b3c;border:1px solid #3e4042;border-radius:8px;padding:8px 12px;color:#e4e6eb;font-size:14px}}
.add-form input::placeholder{{color:#65676b}}
.btn-add{{background:#2d88ff;color:#fff;border:none;padding:8px 16px;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600;white-space:nowrap}}
.btn-add:hover{{background:#1a6ed8}}
.btn-run{{background:#27ae60;color:#fff;border:none;padding:10px 20px;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600;width:100%;transition:all .2s}}
.btn-run:hover{{background:#2ecc71}}
.btn-run:disabled{{background:#555;cursor:not-allowed}}
.crawl-status{{margin-top:10px;padding:10px;border-radius:8px;font-size:13px;display:none}}
.crawl-status.running{{display:block;background:#2c3e50;border:1px solid #3498db}}
.crawl-status.done{{display:block;background:#1e3a2f;border:1px solid #27ae60}}
.dots::after{{content:'';animation:dots 1.5s steps(4,end) infinite}}
@keyframes dots{{0%{{content:''}}25%{{content:'.'}}50%{{content:'..'}}75%{{content:'...'}}}}
.status{{margin-top:8px;font-size:12px;color:#b0b3b8}}
@media(prefers-color-scheme:light){{
  body{{background:#f0f2f5;color:#1c1e21}}
  .card{{background:#fff;border-color:#dadde1}}
  th{{color:#65676b;border-color:#dadde1}}td{{border-color:#dadde1}}
  .add-form input{{background:#f0f2f5;border-color:#dadde1;color:#1c1e21}}
  .btn-move{{background:#dadde1;color:#1c1e21}}
  .crawl-status.running{{background:#eaf2f8;border-color:#3498db}}
  .crawl-status.done{{background:#eafaf1;border-color:#27ae60}}
}}
</style></head><body>
<div class="wrap">
  <h1>Facebook Feed 관리</h1>
  <div class="meta">
    마지막 수집: {last} &middot; <a href="/">피드 보기</a>
  </div>

  <div class="card">
    <h2>트래킹 목록 ({len(friends)}명)</h2>
    <table>
      <tr><th>이름</th><th>프로필</th><th></th></tr>
      {rows}
    </table>
    <form method="POST" action="/admin/add" class="add-form">
      <input type="text" name="name" placeholder="이름 (빈칸이면 자동감지)">
      <input type="text" name="url" placeholder="Facebook URL" required>
      <button type="submit" class="btn-add">추가</button>
    </form>
  </div>

  <div class="card">
    <h2>크롤링</h2>
    <button class="btn-run" id="runBtn" onclick="startCrawl()">지금 크롤링 실행</button>
    <div class="crawl-status" id="crawlStatus"></div>
    <div class="status">크론: 매일 오전 10시, 오후 6시 자동 실행</div>
  </div>
</div>
<script>
let pollTimer = null;

function startCrawl() {{
  const btn = document.getElementById('runBtn');
  const status = document.getElementById('crawlStatus');
  btn.disabled = true;
  btn.textContent = '시작 중...';
  status.className = 'crawl-status running';
  status.innerHTML = '크롤링 진행 중<span class="dots"></span>';

  fetch('/admin/run', {{method: 'POST'}}).then(() => {{
    btn.textContent = '크롤링 중...';
    pollTimer = setInterval(pollStatus, 3000);
  }});
}}

function pollStatus() {{
  fetch('/api/crawl-status').then(r => r.json()).then(data => {{
    const status = document.getElementById('crawlStatus');
    const btn = document.getElementById('runBtn');

    if (data.running) {{
      const elapsed = data.elapsed || 0;
      status.className = 'crawl-status running';
      status.innerHTML = '크롤링 진행 중 (' + elapsed + '초 경과)<span class="dots"></span>';
    }} else if (data.finished) {{
      clearInterval(pollTimer);
      status.className = 'crawl-status done';
      status.innerHTML = '완료! (' + data.finished + ') 피드로 이동합니다...';
      btn.textContent = '완료!';
      setTimeout(() => {{ window.location.href = '/'; }}, 2000);
    }}
  }});
}}

// 페이지 로드 시 이미 크롤링 중이면 폴링 시작
fetch('/api/crawl-status').then(r => r.json()).then(data => {{
  if (data.running) {{
    const btn = document.getElementById('runBtn');
    const status = document.getElementById('crawlStatus');
    btn.disabled = true;
    btn.textContent = '크롤링 중...';
    status.className = 'crawl-status running';
    status.innerHTML = '크롤링 진행 중<span class="dots"></span>';
    pollTimer = setInterval(pollStatus, 3000);
  }}
}});
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/feed":
            self._serve_file(FEED_HTML, "text/html")
        elif self.path == "/admin":
            self._respond(200, "text/html", admin_html())
        elif self.path == "/api/friends":
            self._respond(200, "application/json",
                          json.dumps(load_friends(), ensure_ascii=False))
        elif self.path == "/api/feed":
            self._serve_file(FEED_JSON, "application/json")
        elif self.path == "/api/crawl-status":
            elapsed = 0
            if crawl_state["running"] and crawl_state["started"]:
                try:
                    start = datetime.strptime(crawl_state["started"], "%H:%M:%S")
                    now = datetime.now().replace(year=start.year, month=start.month, day=start.day)
                    elapsed = int((now - start.replace(year=now.year, month=now.month, day=now.day)).total_seconds())
                except Exception:
                    pass
            resp = {
                "running": crawl_state["running"],
                "started": crawl_state["started"],
                "finished": crawl_state["finished"],
                "elapsed": elapsed,
            }
            self._respond(200, "application/json", json.dumps(resp))
        else:
            fpath = os.path.join(BASE_DIR, self.path.lstrip("/"))
            if os.path.isfile(fpath):
                ct = "text/html" if fpath.endswith(".html") else "application/octet-stream"
                self._serve_file(fpath, ct)
            else:
                self._respond(404, "text/plain", "Not Found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        params = urllib.parse.parse_qs(body)

        if self.path == "/admin/add":
            url = params.get("url", [""])[0].strip()
            name = params.get("name", [""])[0].strip()
            if url:
                if not url.startswith("http"):
                    url = "https://www.facebook.com/" + url
                friends = load_friends()
                if not any(f["url"] == url for f in friends):
                    friends.append({"name": name or url.split("/")[-1], "url": url})
                    save_friends(friends)
            self.send_response(303)
            self.send_header("Location", "/admin")
            self.end_headers()

        elif self.path == "/admin/delete":
            idx = int(params.get("index", ["-1"])[0])
            friends = load_friends()
            if 0 <= idx < len(friends):
                friends.pop(idx)
                save_friends(friends)
            self.send_response(303)
            self.send_header("Location", "/admin")
            self.end_headers()

        elif self.path == "/admin/move":
            idx = int(params.get("index", ["-1"])[0])
            direction = params.get("dir", [""])[0]
            friends = load_friends()
            if direction == "up" and idx > 0:
                friends[idx], friends[idx-1] = friends[idx-1], friends[idx]
                save_friends(friends)
            elif direction == "down" and idx < len(friends) - 1:
                friends[idx], friends[idx+1] = friends[idx+1], friends[idx]
                save_friends(friends)
            self.send_response(303)
            self.send_header("Location", "/admin")
            self.end_headers()

        elif self.path == "/admin/run":
            if not crawl_state["running"]:
                t = threading.Thread(target=run_crawl, daemon=True)
                t.start()
            self._respond(200, "application/json", '{"ok":true}')

        else:
            self._respond(404, "text/plain", "Not Found")

    def _respond(self, code, content_type, body):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", len(data))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(data)

    def _serve_file(self, path, content_type):
        try:
            with open(path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", len(data))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self._respond(404, "text/plain", "File not found")

    def log_message(self, fmt, *args):
        pass


def main():
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"FB Feed 서버")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
