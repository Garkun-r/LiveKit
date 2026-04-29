import pytest

import agent
from sber_salutespeech_proto.synthesis.v1 import synthesis_pb2 as sber_pb
from sber_tts import SberSaluteTTS


@pytest.mark.asyncio
async def test_sber_stream_sends_ssml_request_and_emits_pcm_audio() -> None:
    seen_requests = []
    seen_metadata = []

    async def fake_stream(request, metadata, timeout):
        seen_requests.append(request)
        seen_metadata.append(metadata)
        yield sber_pb.SynthesisResponse(data=b"\0\0" * 480)

    tts_client = SberSaluteTTS(
        auth_key="",
        voice="Ost_24000",
        paint_pitch="2",
        paint_speed="4",
        paint_loudness="5",
        stream_factory=fake_stream,
    )

    stream = tts_client.stream()
    stream.push_text("Здравствуйте!")
    stream.end_input()
    events = [event async for event in stream]

    assert len(events) >= 1
    assert events[0].frame.sample_rate == 24000
    assert events[0].frame.num_channels == 1
    assert events[-1].is_final is True

    assert seen_metadata == [()]
    request = seen_requests[0]
    assert request.audio_encoding == sber_pb.SynthesisRequest.PCM_S16LE
    assert request.content_type == sber_pb.SynthesisRequest.SSML
    assert request.voice == "Ost_24000"
    assert request.language == "ru-RU"
    assert request.text == (
        '<speak><paint pitch="2" speed="4" loudness="5">'
        "Здравствуйте!"
        "</paint></speak>"
    )

    await tts_client.aclose()


@pytest.mark.asyncio
async def test_sber_stream_escapes_text_inside_ssml() -> None:
    seen_requests = []

    async def fake_stream(request, metadata, timeout):
        seen_requests.append(request)
        yield sber_pb.SynthesisResponse(data=b"\0\0" * 480)

    tts_client = SberSaluteTTS(auth_key="", stream_factory=fake_stream)
    stream = tts_client.stream()
    stream.push_text("2 < 3 & 5 > 4.")
    stream.end_input()
    _ = [event async for event in stream]

    assert "2 &lt; 3 &amp; 5 &gt; 4." in seen_requests[0].text

    await tts_client.aclose()


def test_build_tts_uses_sber_provider(monkeypatch) -> None:
    captured = {}

    class _FakeSberTTS:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(agent, "TTS_PROVIDER", "sber")
    monkeypatch.setattr(agent, "SBER_SALUTESPEECH_AUTH_KEY", "test-auth-key")
    monkeypatch.setattr(agent, "SBER_TTS_OAUTH_SCOPE", "SALUTE_SPEECH_PERS")
    monkeypatch.setattr(agent, "SBER_TTS_OAUTH_URL", "https://oauth.example/token")
    monkeypatch.setattr(agent, "SBER_TTS_ENDPOINT", "smartspeech.example:443")
    monkeypatch.setattr(agent, "SBER_TTS_CA_CERT_FILE", "")
    monkeypatch.setattr(agent, "SBER_TTS_VOICE", "Ost_24000")
    monkeypatch.setattr(agent, "SBER_TTS_LANGUAGE", "ru-RU")
    monkeypatch.setattr(agent, "SBER_TTS_SAMPLE_RATE", 24000)
    monkeypatch.setattr(agent, "SBER_TTS_PAINT_PITCH", "2")
    monkeypatch.setattr(agent, "SBER_TTS_PAINT_SPEED", "4")
    monkeypatch.setattr(agent, "SBER_TTS_PAINT_LOUDNESS", "5")
    monkeypatch.setattr(agent, "SBER_TTS_REQUEST_TIMEOUT_SEC", 15.0)
    monkeypatch.setattr(agent, "SBER_TTS_REBUILD_CACHE", False)
    monkeypatch.setattr(agent, "SBER_TTS_MIN_SENTENCE_LEN", 4)
    monkeypatch.setattr(agent, "SBER_TTS_STREAM_CONTEXT_LEN", 1)
    monkeypatch.setattr(agent, "provider_proxy_url", lambda provider: None)
    monkeypatch.setattr(agent, "SberSaluteTTS", _FakeSberTTS)

    result = agent.build_tts()

    assert isinstance(result, _FakeSberTTS)
    assert captured["auth_key"] == "test-auth-key"
    assert captured["voice"] == "Ost_24000"
    assert captured["paint_pitch"] == "2"
    assert captured["paint_speed"] == "4"
    assert captured["paint_loudness"] == "5"
    assert captured["sample_rate"] == 24000
