#!/usr/bin/env python3
"""waitfor - block until a port, URL, file or command is ready.

Every CI pipeline eventually grows `sleep 10` before the tests, because
the database was not up yet. Sleep is either too short, and the build is
flaky, or too long, and you pay for it on every run forever.

    waitfor :5432 :6379 http://localhost:8000/health --timeout 60

Waits for all of them, returns as soon as the last one answers, and fails
loudly instead of silently continuing.

Exit codes: 0 ready, 1 error, 2 usage, 3 timed out.

Zero dependencies. Python 3.9+.
"""

import argparse
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

VERSION = "0.1.0"
EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_TIMEOUT = 0, 1, 2, 3

HOST_PORT = re.compile(r"^(?P<host>[^/\\:\s]*):(?P<port>\d{1,5})$")
BARE_PORT = re.compile(r"^\d{1,5}$")
CONNECT_TIMEOUT = 2.0


class Target:
    """Bitta kutiladigan narsa. ready() True qaytarsa, tayyor."""

    def __init__(self, label):
        self.label = label

    def ready(self):
        raise NotImplementedError

    def __str__(self):
        return self.label


class TcpTarget(Target):
    def __init__(self, host, port):
        Target.__init__(self, "%s:%d" % (host, port))
        self.host, self.port = host, port

    def ready(self):
        try:
            with socket.create_connection((self.host, self.port), CONNECT_TIMEOUT):
                return True
        except (OSError, socket.timeout):
            return False


class HttpTarget(Target):
    def __init__(self, url, want_status=None):
        Target.__init__(self, url)
        self.url, self.want_status = url, want_status

    def ready(self):
        request = urllib.request.Request(self.url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=CONNECT_TIMEOUT) as response:
                return self._accept(response.status)
        except urllib.error.HTTPError as e:
            # Javob keldi -- server tirik. 401 ham tayyorlik belgisi
            # bo'lishi mumkin, shuning uchun kodni o'zi hal qiladi.
            return self._accept(e.code)
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def _accept(self, status):
        if self.want_status is not None:
            return status == self.want_status
        return 200 <= status < 400


class FileTarget(Target):
    def ready(self):
        return os.path.exists(self.label)


class CommandTarget(Target):
    def ready(self):
        try:
            done = subprocess.run(self.label, shell=True,
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL,
                                  timeout=CONNECT_TIMEOUT * 5)
            return done.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False


def parse_target(text, want_status=None):
    """Matnni nimaga qarab kutish kerakligiga aylantiradi.

    Tartib muhim: http eng aniq belgi, keyin port, qolgani fayl yo'li.
    """
    text = text.strip()
    if not text:
        raise ValueError("empty target")
    if text.startswith("http://") or text.startswith("https://"):
        return HttpTarget(text, want_status)
    if BARE_PORT.match(text):
        return TcpTarget("127.0.0.1", int(text))
    m = HOST_PORT.match(text)
    if m:
        port = int(m.group("port"))
        if not 0 < port < 65536:
            raise ValueError("port out of range: %s" % text)
        return TcpTarget(m.group("host") or "127.0.0.1", port)
    return FileTarget(text)


def wait(targets, timeout, interval, on_progress=None):
    """Hammasi tayyor bo'lguncha kutadi. (tayyor, kutilgan_vaqt) qaytaradi."""
    started = time.monotonic()
    deadline = started + timeout
    pending = list(targets)
    while True:
        pending = [t for t in pending if not t.ready()]
        if not pending:
            return True, time.monotonic() - started
        if time.monotonic() >= deadline:
            return False, time.monotonic() - started
        if on_progress:
            on_progress(pending, deadline - time.monotonic())
        # Muhlatdan oshib ketmaslik uchun qolgan vaqtdan ko'proq uxlamaymiz.
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="waitfor",
        description="Block until a port, URL, file or command is ready.",
        epilog="example: waitfor :5432 http://localhost:8000/health --timeout 60")
    p.add_argument("targets", nargs="*", metavar="TARGET",
                   help="a port (5432 or host:5432), a URL, or a file path")
    p.add_argument("--cmd", action="append", metavar="COMMAND",
                   help="wait until this command exits 0 (repeatable)")
    p.add_argument("--timeout", type=float, default=30.0, metavar="SECONDS")
    p.add_argument("--interval", type=float, default=0.5, metavar="SECONDS")
    p.add_argument("--status", type=int, metavar="CODE",
                   help="require exactly this HTTP status")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("--version", action="version", version="waitfor " + VERSION)
    args = p.parse_args(argv)

    if args.timeout <= 0 or args.interval <= 0:
        print("error: timeout and interval must be positive", file=sys.stderr)
        return EXIT_USAGE

    targets = []
    try:
        for text in args.targets:
            targets.append(parse_target(text, args.status))
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    for command in (args.cmd or []):
        targets.append(CommandTarget(command))

    if not targets:
        p.print_help()
        return EXIT_USAGE

    def progress(pending, left):
        if not args.quiet:
            print("waiting (%ds left): %s"
                  % (left, ", ".join(str(t) for t in pending)), file=sys.stderr)

    try:
        ok, took = wait(targets, args.timeout, args.interval, progress)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_ERROR

    if ok:
        if not args.quiet:
            print("ready: %s (%.1fs)" % (", ".join(str(t) for t in targets), took))
        return EXIT_OK
    late = [str(t) for t in targets if not t.ready()]
    print("timed out after %gs: %s" % (args.timeout, ", ".join(late)), file=sys.stderr)
    return EXIT_TIMEOUT


if __name__ == "__main__":
    sys.exit(main())
