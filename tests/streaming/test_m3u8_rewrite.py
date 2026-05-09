"""HLS master + media playlist URL rewriting."""
from streamload.streaming.m3u8_rewrite import rewrite_master, rewrite_media

MASTER_SAMPLE = """\
#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Italian",DEFAULT=YES,LANGUAGE="ita",URI="https://upstream/playlist?type=audio&rendition=ita&token=t1"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="Italian",LANGUAGE="ita",URI="https://upstream/playlist?type=subtitle&rendition=ita&token=t1"
#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=854x480,AUDIO="audio",SUBTITLES="subs"
https://upstream/playlist?type=video&rendition=480p&token=t1
#EXT-X-STREAM-INF:BANDWIDTH=2150000,RESOLUTION=1280x720,AUDIO="audio",SUBTITLES="subs"
https://upstream/playlist?type=video&rendition=720p&token=t1
"""

MEDIA_SAMPLE = """\
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXTINF:5.5,
https://upstream/seg-001.ts
#EXTINF:5.5,
https://upstream/seg-002.ts
#EXT-X-ENDLIST
"""


def test_rewrite_master_replaces_video_renditions():
    out = rewrite_master(MASTER_SAMPLE, session_id="sid", base_path="/stream/sid")
    assert "/stream/sid/video/480p.m3u8" in out
    assert "/stream/sid/video/720p.m3u8" in out
    assert "upstream" not in out


def test_rewrite_master_replaces_audio_uris():
    out = rewrite_master(MASTER_SAMPLE, session_id="sid", base_path="/stream/sid")
    assert "/stream/sid/audio/ita.m3u8" in out
    assert "upstream" not in out


def test_rewrite_master_replaces_subtitle_uris():
    out = rewrite_master(MASTER_SAMPLE, session_id="sid", base_path="/stream/sid")
    assert "/stream/sid/sub/ita.vtt" in out


def test_rewrite_master_preserves_stream_inf_attributes():
    out = rewrite_master(MASTER_SAMPLE, session_id="sid", base_path="/stream/sid")
    assert "BANDWIDTH=1200000" in out
    assert "RESOLUTION=854x480" in out


def test_rewrite_media_replaces_segment_urls():
    out = rewrite_media(MEDIA_SAMPLE, session_id="sid", rendition="720p",
                        base_path="/stream/sid")
    assert "/stream/sid/seg/720p/0.ts" in out
    assert "/stream/sid/seg/720p/1.ts" in out
    assert "upstream" not in out


def test_rewrite_media_preserves_extinf_durations():
    out = rewrite_media(MEDIA_SAMPLE, session_id="sid", rendition="720p",
                        base_path="/stream/sid")
    assert "#EXTINF:5.5" in out
    assert "#EXT-X-ENDLIST" in out
