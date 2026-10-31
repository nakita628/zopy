"""User regexes run natively in Rust only where Python ``re`` semantics are preserved."""

import re

import pytest

from zopy import z
from zopy._compile import _rust_regex

# Patterns such as ``[[a]`` are deliberate: they are the cases where Rust and Python disagree.
pytestmark = pytest.mark.filterwarnings("ignore::FutureWarning")

CASES = [
    (r"^\d{3}-\d{4}$", ["123-4567", "123-4567\n", "123-45678", "x"]),
    (r"^[a-z]+$", ["abc", "abc\n", "ABC", ""]),
    (re.compile(r"^abc$", re.IGNORECASE), ["ABC", "abc", "abd"]),
    (re.compile(r"^b$", re.MULTILINE), ["a\nb\nc", "abc"]),
    (r"^(?=.*\d)[a-z\d]+$", ["abc1", "abc"]),
    (r"^(a)\1$", ["aa", "ab"]),
    (r"^\w+$", ["héllo", "a b", "x²"]),
    (r"^\s$", ["\x1c", " ", "a"]),
    (r"^a{,2}$", ["", "aa", "aaa"]),
    (r"^[[a]+$", ["[a", "b"]),
    (r"^[a&&b]+$", ["a&b", "c"]),
    (r"^[]a]+$", ["]a", "b"]),
    (r"^[^]a]+$", ["b", "]"]),
    (r"^ab\Z", ["ab", "ab\n"]),
]


@pytest.mark.parametrize(("pattern", "values"), CASES)
def test_regex_matches_python_re(pattern, values):
    compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
    schema = z.string().regex(compiled)
    for value in values:
        result = schema.safeParse(value)
        assert result.success is (compiled.search(value) is not None), (pattern, value)
        if not result.success:
            assert result.error is not None
            assert result.error.issues[0]["code"] == "invalid_format"
            assert result.error.issues[0]["format"] == "regex"


def test_translation():
    assert _rust_regex(re.compile(r"^\d+$")) == (r"^\d+$", True)
    assert _rust_regex(re.compile(r"\d+")) == (r"\d+", False)
    assert _rust_regex(re.compile(r"^ab$", re.I | re.S)) == (r"(?is)^ab$", True)
    assert _rust_regex(re.compile(r"[$]")) == (r"[$]", False)
    assert _rust_regex(re.compile(r"\$")) == (r"\$", False)
    for unsafe in (r"\w", r"\s", r"\b", r"a{,2}", r"[[a]", r"[a-c--b]", r"[a~~b]", r"\Z"):
        assert _rust_regex(re.compile(unsafe)) is None, unsafe
    assert _rust_regex(re.compile(r"a", re.VERBOSE)) is None
    assert _rust_regex(re.compile(rb"a")) is None


def test_custom_email_pattern_and_string_format():
    email = z.email(pattern=re.compile(r"^[a-z]+@example\.com$"))
    assert email.safeParse("ada@example.com").success
    bad = email.safeParse("ada@other.com")
    assert not bad.success
    assert bad.error is not None
    assert bad.error.issues[0]["format"] == "email"
    fmt = z.stringFormat("zip", re.compile(r"^\d{3}-\d{4}$"))
    assert fmt.safeParse("123-4567").success
    assert not fmt.safeParse("1234567").success
