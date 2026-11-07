"""Disposable video UI fixture, isolated data and explicit test tones. No live providers."""

from offline_cards import app, work
from test_videos import prepare_video

from scenarios.knowledge_diagram.video_schema import VideoRequest

videos, work = prepare_video((app.state.cards, work))
app.state.videos.provider = videos.provider
# Routes close over app.state's Videos instance and use the same isolated repository.
job = app.state.videos.start(
    work["id"],
    VideoRequest(
        expected_revision=work["revision"], operation_id="offline-video-ui-01", max_cost_micro=60000
    ),
    submit=False,
)
app.state.videos.run(work["id"], job["id"])
