import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            response_data = {
                'version': os.getenv('APP_VERSION', '1.0.0'),
                'color': os.getenv('APP_COLOR', 'blue'),
                'hostname': socket.gethostname()
            }
            self.wfile.write(json.dumps(response_data).encode('utf-8'))
            
        elif self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            response_data = {
                'status': 'ok'
            }
            self.wfile.write(json.dumps(response_data).encode('utf-8'))
            
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            response_data = {
                'error': 'Not Found'
            }
            self.wfile.write(json.dumps(response_data).encode('utf-8'))


def main():
    port = int(os.getenv('PORT', '8080'))
    server_address = ('', port)
    
    # Using ThreadingHTTPServer to handle requests concurrently
    httpd = ThreadingHTTPServer(server_address, SimpleHTTPRequestHandler)
    print(f"Starting minimal HTTP server on port {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        httpd.server_close()
        print("Server stopped.")


if __name__ == '__main__':
    main()
