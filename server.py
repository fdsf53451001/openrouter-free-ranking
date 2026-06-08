#!/usr/bin/env python3
"""
Local proxy server for the leaderboard app.
Usage: python3 server.py [port]
Then open: http://localhost:8080
"""
import http.server
import urllib.request
import urllib.error
import sys
import os

PROXY_ROUTES = {
    '/proxy/aa':           'https://artificialanalysis.ai/leaderboards/models',
    '/proxy/nvidia':       'https://integrate.api.nvidia.com/v1/models',
    '/proxy/nvidia-page':  'https://build.nvidia.com/models',
    '/proxy/or-frontend':  'https://openrouter.ai/api/frontend/models',
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

os.chdir(os.path.dirname(os.path.abspath(__file__)))


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0]
        if path in PROXY_ROUTES:
            self._proxy(PROXY_ROUTES[path])
        else:
            super().do_GET()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.end_headers()

    def _proxy(self, url):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = resp.read()
                ct = resp.headers.get('Content-Type', 'text/plain')
                self.send_response(200)
                self.send_header('Content-Type', ct)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            body = f'Upstream error {e.code}: {e.reason}'.encode()
            self.send_response(502)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            body = str(e).encode()
            self.send_response(502)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f'{args[1]} {args[0]}', file=sys.stderr)


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = http.server.HTTPServer(('', port), ProxyHandler)
    print(f'Leaderboard running at  http://localhost:{port}')
    print(f'Press Ctrl-C to stop.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
