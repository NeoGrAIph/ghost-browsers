import pytest

from camoufox_runner.url_utils import navigable_start_url


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://example.com", "https://example.com"),
        ("http://example.com", "http://example.com"),
        ("bot.sannysoft.com", "https://bot.sannysoft.com"),
        (
            "bot.sannysoft.com/path?q=1#frag",
            "https://bot.sannysoft.com/path?q=1#frag",
        ),
        ("//example.com/foo", "https://example.com/foo"),
        ("localhost:9222", "https://localhost:9222"),
        ("about:blank", "about:blank"),
        ("data:text/plain,hello", "data:text/plain,hello"),
        ("/relative", "/relative"),
        ("./script.js", "./script.js"),
    ],
)
def test_navigable_start_url(value: str, expected: str) -> None:
    assert navigable_start_url(value) == expected
