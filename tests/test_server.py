"""Frame Control server checks that need no headset.

Starts ui/server.py against an SSH alias that can't resolve, then exercises the
request guards and input validation, which all run before any SSH call.

Run: python3 -m unittest discover -s tests
"""
import http.client
import json
import os
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        env = {**os.environ, "FRAME_ALIAS": "frame-control-test.invalid", "PYTHONDONTWRITEBYTECODE": "1"}
        cls.proc = subprocess.Popen([sys.executable, str(ROOT / "ui" / "server.py"), "--port", str(cls.port)],
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                if cls.request("GET", "/")[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(0.05)
        cls.proc.kill()
        raise RuntimeError("server didn't start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)

    @classmethod
    def request(cls, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=10)
        data = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, body=data, headers=headers or {})
        r = conn.getresponse()
        payload = r.read()
        conn.close()
        return r.status, dict(r.getheaders()), payload

    def post(self, path, body):
        status, _, payload = self.request("POST", path, body, {"X-Frame-UI": "1", "Content-Type": "application/json"})
        return status, json.loads(payload)

    def test_page_served_with_identifying_and_anti_framing_headers(self):
        status, headers, payload = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Server"].startswith("FrameControl"))
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn(b"<html", payload.lower())

    def test_foreign_host_rejected(self):
        # DNS rebinding: a hostile name pointed at 127.0.0.1.
        for path in ("/", "/api/status"):
            status, _, _ = self.request("GET", path, headers={"Host": f"evil.example:{self.port}", "X-Frame-UI": "1"})
            self.assertEqual(status, 403, path)

    def test_api_needs_custom_header(self):
        # <img src> and plain form posts from other sites can't set it.
        self.assertEqual(self.request("GET", "/api/status")[0], 403)
        self.assertEqual(self.request("GET", "/api/screenshot?view=headset")[0], 403)
        self.assertEqual(self.request("POST", "/api/launch", {"appid": "620"})[0], 403)

    def test_input_validation(self):
        cases = [
            ("/api/launch", {"appid": "620; rm -rf ~"}),
            ("/api/launch", {"appid": ""}),
            ("/api/flatpak", {"id": "org.example.App;id", "action": "install"}),
            ("/api/flatpak", {"id": "org.example.App", "action": "explode"}),
            ("/api/volume", {"level": 1.5}),
            ("/api/clipboard", {"text": ""}),
            ("/api/open", {"what": "anything-else"}),
        ]
        for path, body in cases:
            status, payload = self.post(path, body)
            self.assertEqual(status, 400, f"{path} {body} -> {payload}")

    def test_bad_bodies(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/launch", body=b"{not json", headers={"X-Frame-UI": "1"})
        self.assertEqual(conn.getresponse().status, 400)
        conn.close()
        status, _ = self.post("/api/launch", ["not", "an", "object"])
        self.assertEqual(status, 400)

    def test_unknown_routes(self):
        self.assertEqual(self.request("GET", "/nope")[0], 404)
        self.assertEqual(self.post("/api/nope", {})[0], 404)


class StatusProbe(unittest.TestCase):
    def test_runs_off_device_and_prints_one_json_object(self):
        # The probe runs on the Frame; elsewhere every field must degrade to null/empty.
        out = subprocess.run([sys.executable, str(ROOT / "ui" / "frame_status.py")],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        for key in ("hostname", "battery", "disk", "services", "games", "flatpaks"):
            self.assertIn(key, data)


if __name__ == "__main__":
    unittest.main()
