import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import PurePath
from typing import Dict, Optional, Union


class Rule(ABC):
    @abstractmethod
    def transform(self, path: PurePath) -> Optional[PurePath]:
        pass


class NormalRule(Rule):
    def __init__(self, left: PurePath, right: PurePath):
        self._left = left
        self._right = right

    def _match_prefix(self, path: PurePath) -> Optional[PurePath]:
        left_parts = list(reversed(self._left.parts))
        path_parts = list(reversed(path.parts))

        if len(left_parts) > len(path_parts):
            return None

        while left_parts and path_parts:
            left_part = left_parts.pop()
            path_part = path_parts.pop()

            if left_part != path_part:
                return None

        if left_parts:
            return None

        return PurePath(*path_parts)

    def transform(self, path: PurePath) -> Optional[PurePath]:
        if rest := self._match_prefix(path):
            return self._right / rest

        return None


class ExactRule(Rule):
    def __init__(self, left: PurePath, right: PurePath):
        self._left = left
        self._right = right

    def transform(self, path: PurePath) -> Optional[PurePath]:
        if path == self._left:
            return self._right

        return None


class ReRule(Rule):
    def __init__(self, left: str, right: str):
        self._left = left
        self._right = right

    def transform(self, path: PurePath) -> Optional[PurePath]:
        if match := re.fullmatch(self._left, str(path)):
            kwargs: Dict[str, Union[int, float]] = {}

            groups = [match[0]] + list(match.groups())
            for i, group in enumerate(groups):
                try:
                    kwargs[f"i{i}"] = int(group)
                except ValueError:
                    pass

                try:
                    kwargs[f"f{i}"] = float(group)
                except ValueError:
                    pass

            return PurePath(self._right.format(*groups, **kwargs))

        return None


@dataclass
class RuleParseException(Exception):
    line: "Line"
    reason: str

    def pretty_print(self) -> None:
        print(f"Error parsing rule on line {self.line.line_nr}:")
        print(self.line.line)
        spaces = " " * self.line.index
        print(f"{spaces}^--- {self.reason}")


class Line:
    def __init__(self, line: str, line_nr: int):
        self._line = line
        self._line_nr = line_nr
        self._index = 0

    def get(self) -> Optional[str]:
        if self._index < len(self._line):
            return self._line[self._index]

        return None

    @property
    def line(self) -> str:
        return self._line

    @property
    def line_nr(self) -> str:
        return self._line

    @property
    def index(self) -> int:
        return self._index

    @index.setter
    def index(self, index: int) -> None:
        self._index = index

    def advance(self) -> None:
        self._index += 1

    def expect(self, string: str) -> None:
        for char in string:
            if self.get() == char:
                self.advance()
            else:
                raise RuleParseException(self, f"Expected {char!r}")


QUOTATION_MARKS = {'"', "'"}


def parse_string_literal(line: Line) -> str:
    escaped = False
    result = []

    quotation_mark = line.get()
    if quotation_mark not in QUOTATION_MARKS:
        # This should never happen as long as this function is only called from
        # parse_string.
        raise RuleParseException(line, "Invalid quotation mark")
    line.advance()

    while c := line.get():
        if escaped:
            result.append(c)
            escaped = False
            line.advance()
        elif c == quotation_mark:
            line.advance()
            return "".join(result)
        elif c == "\\":
            escaped = True
            line.advance()
        else:
            result.append(c)
            line.advance()

    raise RuleParseException(line, "Expected end of string literal")


def parse_until_space_or_eol(line: Line) -> str:
    result = []
    while c := line.get():
        if c == " ":
            break
        result.append(c)
        line.advance()

    return "".join(result)


def parse_string(line: Line) -> str:
    if line.get() in QUOTATION_MARKS:
        return parse_string_literal(line)
    else:
        return parse_until_space_or_eol(line)


def parse_arrow(line: Line) -> str:
    line.expect("-")

    name = []
    while True:
        if c := line.get():
            if c == "-":
                break
            else:
                name.append(c)
            line.advance()
        else:
            raise RuleParseException(line, "Expected rest of arrow")

    line.expect("->")
    return "".join(name)


def parse_rule(line: Line) -> Rule:
    left = parse_string(line)
    line.expect(" ")
    arrowindex = line.index
    arrowname = parse_arrow(line)
    line.expect(" ")
    right = parse_string(line)

    if arrowname == "":
        return NormalRule(PurePath(left), PurePath(right))
    elif arrowname == "exact":
        return ExactRule(PurePath(left), PurePath(right))
    elif arrowname == "re":
        return ReRule(left, right)
    else:
        line.index = arrowindex + 1  # For nicer error message
        raise RuleParseException(line, "Invalid arrow name")


class Transformer:
    def __init__(self, rules: str):
        """
        May throw a RuleParseException.
        """

        self._rules = []
        for i, line in enumerate(rules.split("\n")):
            line = line.strip()
            if line:
                self._rules.append(parse_rule(Line(line, i)))

    def transform(self, path: PurePath) -> Optional[PurePath]:
        for rule in self._rules:
            if result := rule.transform(path):
                return result

        return None
