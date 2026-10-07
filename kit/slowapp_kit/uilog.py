"""/run/sb/ui.log: the warm UI's log as a 256 KB ring (docs/SLOWBOARD.md §8.3).

A UI lives for minutes and runs with --log-driver none, so its stderr would otherwise go nowhere.
serve() installs a tee: everything written to sys.stderr still reaches stderr and is appended to
ui.log; job children's stderr is piped in too (jobs.run_in_child). When the file passes 256 KB it
is cut to its newest half at a line boundary, so it never holds more than the cap.
"""
import os
import sys
import threading

CAP = 256 * 1024
PATH = os.environ.get("SLOWAPP_UI_LOG", "/run/sb/ui.log")

_active = None


class RingLog:
    def __init__(self, path=PATH, cap=CAP, echo=None):
        self.path, self.cap, self.echo = path, cap, echo
        self.lock = threading.Lock()

    def write(self, text):
        if self.echo is not None:
            try:
                self.echo.write(text)
                self.echo.flush()
            except (OSError, ValueError):
                pass
        data = text.encode(errors="replace") if isinstance(text, str) else bytes(text)
        with self.lock:
            try:
                with open(self.path, "ab") as f:
                    f.write(data)
                    size = f.tell()
                if size > self.cap:
                    self._trim()
            except OSError:
                pass                       # logging never takes the UI down
        return len(text)

    def _trim(self):
        with open(self.path, "rb") as f:
            f.seek(-(self.cap // 2), os.SEEK_END)
            tail = f.read()
        nl = tail.find(b"\n")
        tail = tail[nl + 1:] if 0 <= nl < len(tail) - 1 else tail
        tmp = self.path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(tail)
        os.replace(tmp, self.path)

    def flush(self):
        pass


def install(path=None):
    """Tee sys.stderr into the ring. Returns the RingLog."""
    global _active
    _active = RingLog(path or PATH, echo=sys.__stderr__)
    sys.stderr = _active
    return _active


def active():
    return _active


def pump(stream):
    """Copy a child's stderr (a binary pipe) into the ring, line by line, on a daemon thread."""
    def run():
        for line in iter(stream.readline, b""):
            (_active or sys.stderr).write(line.decode(errors="replace"))
        stream.close()
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t
