"""In-process protocol fakes and call recorders (spec 14)."""

from __future__ import annotations


class RecordingRecorder:
    def __init__(self):
        self.requests = []
        self.responses = []
        self.attempts = []

    def request(self, **kwargs):
        self.requests.append(kwargs)

    def response(self, **kwargs):
        self.responses.append(kwargs)

    def attempt(self, **kwargs):
        self.attempts.append(kwargs)
