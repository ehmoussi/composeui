r"""Find a pattern into a string."""

import re
from typing import Pattern


class TextFinder:
    def __init__(self) -> None:
        self._pattern = ""
        self._internal_pattern_re: Pattern[str] = re.compile("")
        self._internal_pattern: str = ""
        self._is_regex_valid: bool = True
        self._is_comparison_valid: bool = True
        self._comparison_type: int = 0
        self._match_case = False
        self._use_regex = False
        self.match_whole_word = False
        self._comparison_operator = {1: ">=", 2: "<=", 3: ">", 4: "<"}

    @property
    def has_pattern(self) -> bool:
        return self._pattern != "" and self._is_regex_valid

    @property
    def is_regex_valid(self) -> bool:
        return self._is_regex_valid

    @property
    def is_comparison_valid(self) -> bool:
        return self._is_comparison_valid

    @property
    def pattern(self) -> str:
        return self._pattern

    @pattern.setter
    def pattern(self, text: str) -> None:
        self._pattern = text
        self._update_internal_pattern()

    @property
    def use_regex(self) -> bool:
        return self._use_regex

    @use_regex.setter
    def use_regex(self, value: bool) -> None:
        self._use_regex = value
        self._update_internal_pattern()

    @property
    def match_case(self) -> bool:
        return self._match_case

    @match_case.setter
    def match_case(self, value: bool) -> None:
        self._match_case = value
        self._update_internal_pattern()

    def match(self, value: str) -> bool:
        if not self._match_case:
            value = value.lower()
        # match using operator greater/less than
        if self._comparison_type > 0 and not self.use_regex:
            return self._match_with_operator(value)
        # match using in/==/regex
        elif self.match_whole_word and not self._use_regex:
            return self._internal_pattern == value
        elif self.match_whole_word and self._use_regex:
            return self._internal_pattern_re.fullmatch(value) is not None
        elif self._use_regex:
            return self._internal_pattern_re.search(value) is not None
        else:
            return self._internal_pattern in value

    def _match_with_operator(self, value: str) -> bool:
        try:
            float(value)
        except (ValueError, TypeError):
            return False
        else:
            operator = self._comparison_operator[self._comparison_type]
            is_matching: bool = eval(f"{value}{operator}{self._internal_pattern}", None, None)
            return is_matching

    def _update_internal_pattern(self) -> None:
        r"""Update the internal pattern according to the options."""
        self._is_comparison_valid = True
        self._comparison_type = 0
        if self._match_case:
            self._internal_pattern = self._pattern
        else:
            self._internal_pattern = self._pattern.lower()
        if self._use_regex:
            try:
                self._internal_pattern_re = re.compile(self._internal_pattern)
            except re.error:
                self._internal_pattern_re = re.compile("")
                self._is_regex_valid = False
            else:
                self._is_regex_valid = True
        else:
            for comparison_type, comparison_char in self._comparison_operator.items():
                internal_patter = self._internal_pattern.strip()
                if internal_patter.startswith(comparison_char):
                    internal_pattern = internal_patter[len(comparison_char) :].strip()
                    try:
                        float(internal_pattern)
                    except (ValueError, TypeError):
                        self._is_comparison_valid = False
                    else:
                        self._is_comparison_valid = True
                        self._comparison_type = comparison_type
                        self._internal_pattern = internal_pattern
                    break
