from agentic_facebook import redact


def test_redact_url_strips_query_on_signed_cdn_url():
    url = "https://scontent.xx.fbcdn.net/v/t1/photo.jpg?oh=abc123&oe=def456"
    assert redact.redact_url(url) == "https://scontent.xx.fbcdn.net/v/t1/photo.jpg"


def test_redact_url_leaves_non_cdn_url_untouched():
    url = "https://example.com/page?utm_source=test"
    assert redact.redact_url(url) == url


def test_is_signed_media_url():
    assert redact.is_signed_media_url("https://scontent-lax3-1.xx.fbcdn.net/x.jpg") is True
    assert redact.is_signed_media_url("https://example.com/x.jpg") is False


def test_redact_text_truncates_long_strings():
    long_text = "a" * 100
    result = redact.redact_text(long_text)
    assert result.startswith("a" * 40)
    assert "redacted 60 more chars" in result


def test_redact_text_leaves_short_strings_alone():
    assert redact.redact_text("short") == "short"


def test_redact_dict_drops_sensitive_keys():
    data = {"fb_dtsg": "some-real-token-value", "text": "hello"}
    result = redact.redact(data)
    assert result["fb_dtsg"] == "[REDACTED]"
    assert result["text"] == "hello"


def test_redact_dict_scrubs_nested_signed_urls():
    data = {"media": [{"url": "https://scontent.xx.fbcdn.net/photo.jpg?oh=secret"}]}
    result = redact.redact(data)
    assert result["media"][0]["url"] == "https://scontent.xx.fbcdn.net/photo.jpg"


def test_redact_raw_text_scrubs_fb_dtsg_inline():
    text = '{"fb_dtsg":"AbCdEf123456"}'
    result = redact.redact_raw_text(text)
    assert "AbCdEf123456" not in result
    assert '"fb_dtsg":"[REDACTED]"' in result


def test_redact_raw_text_scrubs_urls_in_free_text():
    text = "error fetching https://scontent.xx.fbcdn.net/x.jpg?oh=secret&oe=abc"
    result = redact.redact_raw_text(text)
    assert "secret" not in result


def test_redact_raw_text_scrubs_session_cookies_in_header_form():
    text = "cookie: datr=abcdef123; xs=98765; c_user=1000001"
    result = redact.redact_raw_text(text)
    assert "abcdef123" not in result
    assert "98765" not in result
    assert "1000001" not in result


def test_redact_raw_text_scrubs_tokens_in_querystring_form():
    text = "https://www.facebook.com/api/graphql/?fb_dtsg=SUPERSECRET&access_token=ALSOSECRET"
    result = redact.redact_raw_text(text)
    assert "SUPERSECRET" not in result
    assert "ALSOSECRET" not in result


def test_is_signed_media_url_rejects_lookalike_hosts():
    assert redact.is_signed_media_url("https://evilfbcdn.net/foo?token=abc") is False
    assert redact.is_signed_media_url("https://notfbcdn.net/foo?token=abc") is False
    assert redact.is_signed_media_url("https://xfbcdn.net/foo?token=abc") is False
