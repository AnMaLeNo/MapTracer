#!/usr/bin/env python3
"""Serveur statique minimal (sans cache) pour l'application d'annotation."""
import http.server, os, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def log_message(self, *a):
        pass


if __name__ == '__main__':
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    with http.server.ThreadingHTTPServer(('0.0.0.0', PORT), H) as srv:
        print(f'http://127.0.0.1:{PORT}/app/')
        srv.serve_forever()
