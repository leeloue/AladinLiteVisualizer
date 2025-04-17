#!/usr/bin/env python

# Adapted from https://gist.github.com/acdha/925e9ffc3d74ad59c3ea
"""Use instead of `python -m http.server` when you need CORS"""

import sys
import os

from http.server import HTTPServer, SimpleHTTPRequestHandler


class CORSRequestHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', '*')
        self.send_header('Access-Control-Allow-Headers', '*')

        return super(CORSRequestHandler, self).end_headers()

local_dir = '.'
if len(sys.argv)>=2:
    local_dir = sys.argv[1]

local_dir = os.path.realpath(local_dir)

port = 2024
if len(sys.argv)==3:
    port = int(sys.argv[2])

httpd = HTTPServer(('localhost', port), CORSRequestHandler)
print(f'Serving local directory {local_dir} from http://localhost:{port}/')
httpd.serve_forever()

