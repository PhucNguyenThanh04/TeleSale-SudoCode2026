"""Lifecycle no-ops for tests whose runtime doubles only model answer content.

Real preparation, playback persistence and history are covered in test_voice_lifecycle.
"""


class VoiceLifecycleStub:
    async def prepare_session(self, request):
        pass

    async def record_playback(self, request):
        pass
