"""Simple JWKS server for dynamic API testing."""
from __future__ import annotations

import json
import base64
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Generate RSA key pair
_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_public_key = _private_key.public_key()

# PEMs for JWT signing
PRIVATE_PEM = _private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()

PUBLIC_PEM = _public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()

# Write private key so test script can sign JWTs with the same key
Path("/tmp/mock_jwks_private.pem").write_text(PRIVATE_PEM)

# Build JWKS JSON
numbers = _public_key.public_numbers()
n = base64.urlsafe_b64encode(numbers.n.to_bytes(256, "big")).rstrip(b"=").decode()
e = base64.urlsafe_b64encode(numbers.e.to_bytes(3, "big")).rstrip(b"=").decode()

JWKS_JSON = json.dumps({
    "keys": [{
        "kty": "RSA",
        "use": "sig",
        "kid": "test-key-1",
        "n": n,
        "e": e,
        "alg": "RS256",
    }]
})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/.well-known/jwks.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(JWKS_JSON.encode())
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = HTTPServer(("", port), Handler)
    print(f"JWKS server on port {port}")
    server.serve_forever()
