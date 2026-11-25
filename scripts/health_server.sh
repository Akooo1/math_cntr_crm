#!/bin/sh
# The bot and the worker serve no pages, but a host may still health-check them on $PORT
# (Railway does when a service falls back to the root railway.json). Answer 200 "ok" there in
# the background. Without PORT (Docker Compose) do nothing.
[ -n "${PORT:-}" ] || exit 0
python - <<'PY' &
import http.server, os


class Ok(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


http.server.ThreadingHTTPServer(("0.0.0.0", int(os.environ["PORT"])), Ok).serve_forever()
PY
