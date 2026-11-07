"""Explicit, disposable UI fixture. Never imported by production entrypoint."""
import tempfile
from knowledge_app import create_app
from test_knowledge import FakeProvider, MATERIAL

temporary = tempfile.TemporaryDirectory(prefix="knowledge-offline-ui-")
provider = FakeProvider()
provider.model = "offline-test"
app = create_app(temporary.name, provider)
work = app.state.service.repo.create({**MATERIAL, "title": "离线测试：原文核对"})
