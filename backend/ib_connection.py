"""Why the backend isn't connected to IB Gateway, and which client ID to try next.

Gateway allows one API connection per client ID. If another program already uses ours, Gateway
answers with error 326 and closes the connection; we then move on to the next ID instead of
retrying the same one forever.
"""
import asyncio
import time

CLIENT_ID_IN_USE = 326
# Client IDs tried after a clash: the first one, then the next ones, then back to the first
CLIENT_ID_RANGE = 10


class ConnectionStatus:
    def __init__(self, first_client_id):
        self.first_client_id = first_client_id
        self.client_id = first_client_id
        self.problem = None  # "client_id_in_use" | "refused" | "timeout" | "other" | None
        self.problem_since = None
        self._clash = False

    def on_ib_error(self, code):
        """Called for every IB error; only a client ID clash matters here."""
        if code == CLIENT_ID_IN_USE:
            self._clash = True

    def connected(self):
        self.problem = None
        self.problem_since = None

    def failed(self, exc):
        """Records why a connection attempt failed and picks the client ID for the next one."""
        if self._clash:
            self._clash = False
            self.problem = "client_id_in_use"
            step = (self.client_id - self.first_client_id + 1) % CLIENT_ID_RANGE
            self.client_id = self.first_client_id + step
        elif isinstance(exc, ConnectionRefusedError):
            self.problem = "refused"
        elif isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            self.problem = "timeout"
        else:
            self.problem = "other"
        if self.problem_since is None:
            self.problem_since = time.monotonic()

    def as_dict(self):
        """For /health: the problem and how long it has lasted (seconds)."""
        lasted = round(time.monotonic() - self.problem_since) if self.problem_since else 0
        return {"problem": self.problem, "problem_for_s": lasted, "client_id": self.client_id}
