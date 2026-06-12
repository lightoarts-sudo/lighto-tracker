from youtube_clipper import _is_youtube_url, _safe_filename


def test_youtube_url_validation():
    assert _is_youtube_url("https://www.youtube.com/watch?v=abc")
    assert _is_youtube_url("https://youtu.be/abc")
    assert _is_youtube_url("https://m.youtube.com/shorts/abc")
    assert not _is_youtube_url("https://youtube.com.example.com/watch?v=abc")
    assert not _is_youtube_url("javascript:alert(1)")


def test_safe_filename():
    assert _safe_filename('  My: Video / Test?  ') == "My Video Test"
    assert _safe_filename("") == "youtube-clip"
