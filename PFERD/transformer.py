# I'm sorry that this code has become a bit dense and unreadable. While
# reading, it is important to remember what True and False mean. I'd love to
# have some proper sum-types for the inputs and outputs, they'd make this code
# a lot easier to understand.

import ast
import re
from abc import ABC, abstractmethod
from pathlib import PurePath
from typing import Dict, Optional, Sequence, Union

from .logging import log
from .utils import fmt_path, str_path


class Rule(ABC):
    @abstractmethod
    def transform(self, path: PurePath) -> Union[PurePath, bool]:
        """
        Try to apply this rule to the path. Returns another path if the rule
        was successfully applied, True if the rule matched but resulted in an
        exclamation mark, and False if the rule didn't match at all.
        """

        pass


# These rules all use a Union[T, bool] for their right side. They are passed a
# T if the arrow's right side was a normal string, True if it was an
# exclamation mark and False if it was missing entirely.

class NormalRule(Rule):
    def __init__(self, left: PurePath, right: Union[PurePath, bool]):

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

        path_parts.reverse()
        return PurePath(*path_parts)

    def transform(self, path: PurePath) -> Union[PurePath, bool]:
        if rest := self._match_prefix(path):
            if isinstance(self._right, bool):
                return self._right or path
            else:
                return self._right / rest

        return False


class ExactRule(Rule):
    def __init__(self, left: PurePath, right: Union[PurePath, bool]):
        self._left = left
        self._right = right

    def transform(self, path: PurePath) -> Union[PurePath, bool]:
        if path == self._left:
            if isinstance(self._right, bool):
                return self._right or path
            else:
                return self._right

        return False


class NameRule(Rule):
    def __init__(self, subrule: Rule):
        self._subrule = subrule

    def transform(self, path: PurePath) -> Union[PurePath, bool]:
        matched = False
        result = PurePath()

        for part in path.parts:
            part_result = self._subrule.transform(PurePath(part))
            if isinstance(part_result, PurePath):
                matched = True
                result /= part_result
            elif part_result:
                # If any subrule call ignores its path segment, the entire path
                # should be ignored
                return True
            else:
                # The subrule doesn't modify this segment, but maybe other
                # segments
                result /= part

        if matched:
            return result
        else:
            # The subrule has modified no segments, so this name version of it
            # doesn't match
            return False


class ReRule(Rule):
    def __init__(self, left: str, right: Union[str, bool]):
        self._left = left
        self._right = right

    def transform(self, path: PurePath) -> Union[PurePath, bool]:
        if match := re.fullmatch(self._left, str_path(path)):
            if isinstance(self._right, bool):
                return self._right or path

            vars: Dict[str, Union[str, int, float]] = {}

            # For some reason, mypy thinks that "groups" has type List[str].
            # But since elements of "match.groups()" can be None, mypy is
            # wrong.
            groups: Sequence[Optional[str]] = [match[0]] + list(match.groups())
            for i, group in enumerate(groups):
                if group is None:
                    continue

                vars[f"g{i}"] = group

                try:
                    vars[f"i{i}"] = int(group)
                except ValueError:
                    pass

                try:
                    vars[f"f{i}"] = float(group)
                except ValueError:
                    pass

            result = eval(f"f{self._right!r}", vars)
            return PurePath(result)

        return False


class RuleParseError(Exception):
    def __init__(self, line: "Line", reason: str):
        super().__init__(f"Error in rule on line {line.line_nr}, column {line.index}: {reason}")

        self.line = line
        self.reason = reason

    def pretty_print(self) -> None:
        log.error(f"Error parsing rule on line {self.line.line_nr}:")
        log.error_contd(self.line.line)
        spaces = " " * self.line.index
        log.error_contd(f"{spaces}^--- {self.reason}")


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
    def line_nr(self) -> int:
        return self._line_nr

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
                raise RuleParseError(self, f"Expected {char!r}")


QUOTATION_MARKS = {'"', "'"}


def parse_string_literal(line: Line) -> str:
    escaped = False

    # Points to first character of string literal
    start_index = line.index

    quotation_mark = line.get()
    if quotation_mark not in QUOTATION_MARKS:
        # This should never happen as long as this function is only called from
        # parse_string.
        raise RuleParseError(line, "Invalid quotation mark")
    line.advance()

    while c := line.get():
        if escaped:
            escaped = False
            line.advance()
        elif c == quotation_mark:
            line.advance()
            stop_index = line.index
            literal = line.line[start_index:stop_index]
            return ast.literal_eval(literal)
        elif c == "\\":
            escaped = True
            line.advance()
        else:
            line.advance()

    raise RuleParseError(line, "Expected end of string literal")


def parse_until_space_or_eol(line: Line) -> str:
    result = []
    while c := line.get():
        if c == " ":
            break
        result.append(c)
        line.advance()

    return "".join(result)


def parse_string(line: Line) -> Union[str, bool]:
    if line.get() in QUOTATION_MARKS:
        return parse_string_literal(line)
    else:
        string = parse_until_space_or_eol(line)
        if string == "!":
            return True
        return string


def parse_arrow(line: Line) -> str:
    line.expect("-")

    name = []
    while True:
        c = line.get()
        if not c:
            raise RuleParseError(line, "Expected rest of arrow")
        elif c == "-":
            line.advance()
            c = line.get()
            if not c:
                raise RuleParseError(line, "Expected rest of arrow")
            elif c == ">":
                line.advance()
                break  # End of arrow
            else:
                name.append("-")
                continue
        else:
            name.append(c)

        line.advance()

    return "".join(name)


def parse_whitespace(line: Line) -> None:
    line.expect(" ")
    while line.get() == " ":
        line.advance()


def parse_eol(line: Line) -> None:
    if line.get() is not None:
        raise RuleParseError(line, "Expected end of line")


def parse_rule(line: Line) -> Rule:
    # Parse left side
    leftindex = line.index
    left = parse_string(line)
    if isinstance(left, bool):
        line.index = leftindex
        raise RuleParseError(line, "Left side can't be '!'")
    leftpath = PurePath(left)

    # Parse arrow
    parse_whitespace(line)
    arrowindex = line.index
    arrowname = parse_arrow(line)

    # Parse right side
    if line.get():
        parse_whitespace(line)
        right = parse_string(line)
    else:
        right = False
    rightpath: Union[PurePath, bool]
    if isinstance(right, bool):
        rightpath = right
    else:
        rightpath = PurePath(right)

    parse_eol(line)

    # Dispatch
    if arrowname == "":
        return NormalRule(leftpath, rightpath)
    elif arrowname == "name":
        if len(leftpath.parts) > 1:
            line.index = leftindex
            raise RuleParseError(line, "SOURCE must be a single name, not multiple segments")
        return NameRule(ExactRule(leftpath, rightpath))
    elif arrowname == "exact":
        return ExactRule(leftpath, rightpath)
    elif arrowname == "re":
        return ReRule(left, right)
    elif arrowname == "name-re":
        return NameRule(ReRule(left, right))
    else:
        line.index = arrowindex + 1  # For nicer error message
        raise RuleParseError(line, f"Invalid arrow name {arrowname!r}")


class Transformer:
    def __init__(self, rules: str):
        """
        May throw a RuleParseException.
        """

        self._rules = []
        for i, line in enumerate(rules.split("\n")):
            line = line.strip()
            if line:
                rule = parse_rule(Line(line, i))
                self._rules.append((line, rule))

    def transform(self, path: PurePath) -> Optional[PurePath]:
        for i, (line, rule) in enumerate(self._rules):
            log.explain(f"Testing rule {i+1}: {line}")

            try:
                result = rule.transform(path)
            except Exception as e:
                log.warn(f"Error while testing rule {i+1}: {line}")
                log.warn_contd(str(e))
                continue

            if isinstance(result, PurePath):
                log.explain(f"Match found, transformed path to {fmt_path(result)}")
                return result
            elif result:  # Exclamation mark
                log.explain("Match found, path ignored")
                return None
            else:
                continue

        log.explain("No rule matched, path is unchanged")
        return path
