from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import urllib.request
import urllib.error

class FetchHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path != "/fetch":
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Not found. Use /fetch?url=<url>")
            return

        query = parse_qs(parsed.query)
        target_url = query.get("url", [None])[0]

        if not target_url:
            self.send_response(400)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Missing 'url' query parameter")
            return

        try:
            req = urllib.request.Request(
                target_url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; FetchServer/1.0)"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                content_type = response.headers.get("Content-Type", "text/plain")
                body = response.read()

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(body)

        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"HTTP Error: {e.code} {e.reason}".encode())

        except urllib.error.URLError as e:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"URL Error: {e.reason}".encode())

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Server Error: {str(e)}".encode())

def run(host="localhost", port=8000):
    server = HTTPServer((host, port), FetchHandler)
    print(f"Serving on http://{host}:{port}")
    print(f"Try: http://{host}:{port}/fetch?url=https://example.com")
    server.serve_forever()

if __name__ == "__main__":
    run()
