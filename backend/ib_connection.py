"""Why the backend isn't connected to IB Gateway, and which client ID to try next.

Gateway allows one API connection per client ID. If another program already uses ours, Gateway
answers with error 326 and closes the connection; we then move on to the next ID instead of
retrying the same one forever.

Connected but not answering (#285): IBKR allows one session per username, so logging in to the
same account elsewhere (the mobile app, Client Portal, TWS, another Gateway) cuts this Gateway off
from IBKR's servers while its local port stays open. Requests then wait forever with no error.
Two signs are watched: IB error 1100 / 2110 (connectivity to IBKR lost; 1101 / 1102 = restored)
and a regular check request that doesn't answer (ib_core.check_answering).
"""
import asyncio
import time

CLIENT_ID_IN_USE = 326
# Gateway lost its connection to IBKR's servers, and got it back
CONNECTIVITY_LOST = (1100, 2110)
CONNECTIVITY_RESTORED = (1101, 1102)
# Check requests in a row without an answer before saying so (one slow answer isn't enough)
CHECKS_BEFORE_NOT_ANSWERING = 2

# Client IDs tried after a clash: the first one, then the next ones, then back to the first
CLIENT_ID_RANGE = 10


class ConnectionStatus:
    def __init__(self, first_client_id):
        self.first_client_id = first_client_id
        self.client_id = first_client_id
        self.problem = None  # "client_id_in_use" | "refused" | "timeout" | "other" | None
        self.problem_since = None
        self._clash = False
        # Connected but IBKR isn't answering (see the module notes)
        self.not_answering_since = None
        self._failed_checks = 0

    def on_ib_error(self, code):
        """Called for every IB error: a client ID clash, or IBKR's connectivity lost / restored."""
        if code == CLIENT_ID_IN_USE:
            self._clash = True
        elif code in CONNECTIVITY_LOST:
            self._not_answering()
        elif code in CONNECTIVITY_RESTORED:
            self.answering()

    def connected(self):
        self.problem = None
        self.problem_since = None
        self.answering()

    def _not_answering(self):
        if self.not_answering_since is None:
            self.not_answering_since = time.monotonic()

    def answering(self):
        """A check request was answered (or IBKR's connectivity came back)."""
        self._failed_checks = 0
        self.not_answering_since = None

    def check_failed(self):
        """A check request got no answer in time."""
        self._failed_checks += 1
        if self._failed_checks >= CHECKS_BEFORE_NOT_ANSWERING:
            self._not_answering()

    def not_answering(self):
        """For /health while connected: the problem and how long it has lasted, or None."""
        if self.not_answering_since is None:
            return None
        return {"problem": "not_answering", "problem_for_s": round(time.monotonic() - self.not_answering_since)}

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
