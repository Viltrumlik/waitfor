"""Haqiqiy soket, haqiqiy HTTP server va haqiqiy fayllar bilan."""

import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, os.pardir, "waitfor.py")

spec = importlib.util.spec_from_file_location("waitfor", SCRIPT)
wf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wf)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ParseTest(unittest.TestCase):
    def test_urls_become_http_targets(self):
        for url in ("http://x/y", "https://x"):
            self.assertIsInstance(wf.parse_target(url), wf.HttpTarget)

    def test_a_bare_number_is_a_local_port(self):
        t = wf.parse_target("5432")
        self.assertIsInstance(t, wf.TcpTarget)
        self.assertEqual((t.host, t.port), ("127.0.0.1", 5432))

    def test_a_leading_colon_is_a_local_port(self):
        t = wf.parse_target(":6379")
        self.assertEqual((t.host, t.port), ("127.0.0.1", 6379))

    def test_host_and_port_are_kept(self):
        t = wf.parse_target("db:5432")
        self.assertEqual((t.host, t.port), ("db", 5432))

    def test_anything_else_is_a_path(self):
        self.assertIsInstance(wf.parse_target("/tmp/ready"), wf.FileTarget)
        self.assertIsInstance(wf.parse_target("./relative/path"), wf.FileTarget)

    def test_an_impossible_port_is_refused(self):
        with self.assertRaises(ValueError):
            wf.parse_target("db:99999")

    def test_an_empty_target_is_refused(self):
        with self.assertRaises(ValueError):
            wf.parse_target("   ")


class TcpTest(unittest.TestCase):
    def test_an_open_port_is_ready(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        try:
            port = server.getsockname()[1]
            self.assertTrue(wf.TcpTarget("127.0.0.1", port).ready())
        finally:
            server.close()

    def test_a_closed_port_is_not_ready(self):
        self.assertFalse(wf.TcpTarget("127.0.0.1", free_port()).ready())

    def test_a_port_that_opens_late_is_waited_for(self):
        port = free_port()
        started = threading.Event()

        def serve():
            time.sleep(0.4)
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            s.listen(1)
            started.set()
            time.sleep(1.5)
            s.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        ok, took = wf.wait([wf.TcpTarget("127.0.0.1", port)], timeout=5, interval=0.1)
        self.assertTrue(ok)
        self.assertGreater(took, 0.3)
        started.wait(2)


class Handler(BaseHTTPRequestHandler):
    status = 200

    def do_GET(self):
        self.send_response(self.status)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


class HttpTest(unittest.TestCase):
    def serve(self, status):
        Handler.status = status
        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return "http://127.0.0.1:%d/" % server.server_address[1]

    def test_a_200_is_ready(self):
        self.assertTrue(wf.HttpTarget(self.serve(200)).ready())

    def test_a_404_is_not_ready_by_default(self):
        self.assertFalse(wf.HttpTarget(self.serve(404)).ready())

    def test_a_404_is_ready_when_that_is_what_you_asked_for(self):
        url = self.serve(404)
        self.assertTrue(wf.HttpTarget(url, want_status=404).ready())

    def test_a_redirect_counts_as_alive(self):
        self.assertTrue(wf.HttpTarget(self.serve(302)).ready())

    def test_nothing_listening_is_not_ready(self):
        self.assertFalse(wf.HttpTarget("http://127.0.0.1:%d/" % free_port()).ready())


class FileAndCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="waitfor-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_an_existing_file_is_ready(self):
        path = os.path.join(self.tmp, "ready")
        open(path, "w").close()
        self.assertTrue(wf.FileTarget(path).ready())

    def test_a_file_that_appears_later_is_waited_for(self):
        path = os.path.join(self.tmp, "late")

        def touch():
            time.sleep(0.3)
            open(path, "w").close()

        threading.Thread(target=touch, daemon=True).start()
        ok, took = wf.wait([wf.FileTarget(path)], timeout=5, interval=0.05)
        self.assertTrue(ok)
        self.assertGreater(took, 0.2)

    def test_a_command_that_succeeds_is_ready(self):
        self.assertTrue(wf.CommandTarget("exit 0").ready())

    def test_a_command_that_fails_is_not(self):
        self.assertFalse(wf.CommandTarget("exit 1").ready())

    def test_a_command_that_does_not_exist_is_not_ready(self):
        self.assertFalse(wf.CommandTarget("definitely-not-a-real-command-xyz").ready())


class WaitTest(unittest.TestCase):
    def test_it_waits_for_every_target_not_just_the_first(self):
        tmp = tempfile.mkdtemp(prefix="waitfor-all-")
        self.addCleanup(shutil.rmtree, tmp, True)
        early = os.path.join(tmp, "a")
        late = os.path.join(tmp, "b")
        open(early, "w").close()

        def touch():
            time.sleep(0.3)
            open(late, "w").close()

        threading.Thread(target=touch, daemon=True).start()
        ok, took = wf.wait([wf.FileTarget(early), wf.FileTarget(late)],
                           timeout=5, interval=0.05)
        self.assertTrue(ok)
        self.assertGreater(took, 0.2)

    def test_it_gives_up_at_the_deadline(self):
        started = time.monotonic()
        ok, took = wf.wait([wf.FileTarget("/no/such/path/at/all")],
                           timeout=0.5, interval=0.1)
        self.assertFalse(ok)
        self.assertLess(time.monotonic() - started, 2.0)

    def test_it_does_not_sleep_past_the_deadline(self):
        started = time.monotonic()
        wf.wait([wf.FileTarget("/no/such/path")], timeout=0.3, interval=10)
        self.assertLess(time.monotonic() - started, 2.0)


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT, *args],
                              capture_output=True, text=True)

    def test_an_existing_file_exits_zero(self):
        self.assertEqual(self.run_cli(__file__, "--quiet").returncode, 0)

    def test_a_timeout_exits_three(self):
        out = self.run_cli("/no/such/path", "--timeout", "0.4", "--interval", "0.1", "--quiet")
        self.assertEqual(out.returncode, 3)
        self.assertIn("muhlat tugadi", out.stderr)

    def test_no_target_prints_help(self):
        out = self.run_cli()
        self.assertEqual(out.returncode, 2)
        self.assertIn("usage", out.stdout.lower())

    def test_a_negative_timeout_is_a_usage_error(self):
        self.assertEqual(self.run_cli("x", "--timeout", "0").returncode, 2)

    def test_quiet_says_nothing_on_success(self):
        out = self.run_cli(__file__, "--quiet")
        self.assertEqual(out.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
