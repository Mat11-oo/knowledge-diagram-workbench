"""Restart harness only: injected offline providers, isolated RESTART_CHECK_DIR data."""

import os

from test_cards import FakeImages
from test_knowledge import FakeProvider
from test_videos import FakeTTS

from knowledge_app import create_app

app = create_app(os.environ["KNOWLEDGE_DATA_DIR"], FakeProvider(), FakeImages(), FakeTTS())
