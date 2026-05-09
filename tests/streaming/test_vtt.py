from streamload.streaming.vtt import is_webvtt, srt_to_vtt


def test_detects_webvtt_header():
    assert is_webvtt("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhi\n")


def test_rejects_non_webvtt():
    assert not is_webvtt("1\n00:00:01,000 --> 00:00:02,000\nhi")


def test_srt_converts_to_vtt():
    srt = "1\n00:00:01,500 --> 00:00:03,000\nCiao mondo\n\n2\n00:00:04,000 --> 00:00:05,000\nFine\n"
    out = srt_to_vtt(srt)
    assert out.startswith("WEBVTT")
    assert "00:00:01.500 --> 00:00:03.000" in out
    assert "Ciao mondo" in out
