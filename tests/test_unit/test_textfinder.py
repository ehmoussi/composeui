r"""Tests of TextFinder."""

from composeui.items.core.textfinder import TextFinder

import pytest


@pytest.mark.parametrize(
    ("pattern", "match_case", "match_whole_word", "use_regex", "expected_result"),
    [
        # no options
        ("complex", False, False, False, False),
        ("test", False, False, False, True),
        # only match case
        ("test", True, False, False, False),
        ("Test", True, False, False, True),
        # only match whole word
        ("test", False, True, False, False),
        ("a simple test", False, True, False, True),
        # match case and whole word
        ("simple", True, True, False, False),
        ("a simple test", True, True, False, False),
        ("a simple Test", True, True, False, True),
        # only use regex
        ("t[0-9]st", False, False, True, False),
        ("[a-z]est", False, False, True, True),
        # match case and use regex
        ("[a-z]est", True, False, True, False),
        ("[A-Z]est", True, False, True, True),
        # match whole word and use regex
        ("[a-z]est", False, True, True, False),
        ("a simple [a-z]est", False, True, True, True),
        # match case and whole word and use regex
        ("[a-z]est", True, True, True, False),
        ("a simple [a-z]est", True, True, True, False),
        ("a simple [A-Z]est", True, True, True, True),
    ],
)
def test_match(
    pattern: str,
    match_case: bool,
    match_whole_word: bool,
    use_regex: bool,
    expected_result: bool,
) -> None:
    r"""Test the match function using all the combinations of the options."""
    text_finder = TextFinder()
    text_finder.pattern = pattern
    text_finder.match_case = match_case
    text_finder.match_whole_word = match_whole_word
    text_finder.use_regex = use_regex
    assert text_finder.match("a simple Test") is expected_result


def test_is_regex_valid() -> None:
    r"""Check the attribute is_regex_valid of TextFinder."""
    text_finder = TextFinder()
    # default
    assert text_finder.is_regex_valid is True
    assert text_finder.has_pattern is False
    # incorrect regular expression
    text_finder.use_regex = True
    text_finder.pattern = "[a-z"
    assert text_finder.is_regex_valid is False
    assert text_finder.has_pattern is False
    # correct regular expression
    text_finder.pattern = "[a-z]"
    assert text_finder.is_regex_valid is True
    assert text_finder.has_pattern is True


@pytest.mark.parametrize(
    ("pattern", "match_case", "match_whole_word", "use_regex", "expected_result"),
    [
        (">=3e3", False, False, False, False),
        ("<=3e3", False, False, False, True),
        (">3e3", False, False, False, False),
        ("<3e3", False, False, False, True),
        (">=1.15e2", False, False, False, True),
        ("<=1.15e2", False, False, False, True),
        (">1.15e2", False, False, False, False),
        ("<1.15e2", False, False, False, False),
    ],
)
def test_match_with_operator(
    pattern: str,
    match_case: bool,
    match_whole_word: bool,
    use_regex: bool,
    expected_result: bool,
) -> None:
    r"""Test the match using an operator in the pattern."""
    text_finder = TextFinder()
    text_finder.pattern = pattern
    text_finder.match_case = match_case
    text_finder.match_whole_word = match_whole_word
    text_finder.use_regex = use_regex
    assert text_finder.match("1.15e2") is expected_result
