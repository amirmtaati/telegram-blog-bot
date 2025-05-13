from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import os

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'Bot is running!')
    
    def log_message(self, format, *args):
        # Silence the log messages
        return

def run_server():
    server_address = ('', int(os.environ.get('PORT', 8080)))
    httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)
    httpd.serve_forever()

if __name__ == '__main__':
    run_server()
