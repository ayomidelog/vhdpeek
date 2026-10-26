import http.server, threading, sys

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        code = {"/404.vhd": 404, "/403.vhd": 403, "/401.vhd": 401,
                "/500.vhd": 500, "/nolength.vhd": 200}.get(self.path, 404)
        self.send_response(code)
        if code == 200:
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        if code == 200:
            self.wfile.write(b"0\r\n\r\n")
    do_HEAD = do_GET

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8733), H)
print("ready", flush=True)
srv.serve_forever()
