"""Disposable offline UI preview. Never imported by the production entrypoint."""
import tempfile

from knowledge_app import create_app
from scenarios.knowledge_diagram.cards_schema import ImageRequest
from scenarios.knowledge_diagram.schemas import ClaimSelection, ExtractRequest, Versioned
from test_cards import FakeImages
from test_knowledge import MATERIAL, FakeProvider

temporary = tempfile.TemporaryDirectory(prefix='knowledge-cards-ui-')
provider = FakeProvider()
provider.model = 'offline-test'
images = FakeImages()
app = create_app(temporary.name, provider, images)
service, cards = app.state.service, app.state.cards
work = service.repo.create({**MATERIAL, 'title': '离线测试：从知识到图解'})
job = service.start_extraction(work['id'], ExtractRequest(expected_revision=1, operation_id='offline-extract-01'), submit=False)
service.run(work['id'], job['id'])
work = service.repo.get(work['id'])
work = service.confirm(work['id'], ClaimSelection(expected_revision=work['revision'], claim_ids=[c['id'] for c in work['claims']]))
work = cards.draft(work['id'], Versioned(expected_revision=work['revision']))
# Mark deterministic test assets explicitly. No real model or network is involved.
for card in work['cards'][:3]:
    job = cards.start(work['id'], ImageRequest(expected_revision=work['revision'], operation_id='offline-image-' + card['id'], max_cost_micro=40_000), 'illustration', card['id'], submit=False)
    cards.run(work['id'], job['id'])
    work = service.repo.get(work['id'])
images.enabled = False
