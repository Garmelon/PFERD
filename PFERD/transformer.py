import ast
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import Callable, Dict, List, Optional, Sequence, TypeVar, Union

from .logging import log
from .utils import fmt_path, str_path


class ArrowHead(Enum):
    NORMAL = 0
    SEQUENCE = 1


class Ignore:
    pass


class Empty:
    pass


RightSide = Union[str, Ignore, Empty]


@dataclass
class Transformed:
    path: PurePath


class Ignored:
    pass


TransformResult = Optional[Union[Transformed, Ignored]]


@dataclass
class Rule:
    left: str
    left_index: int
    name: str
    head: ArrowHead
    right: RightSide
    right_index: int

    def right_result(self, path: PurePath) -> Union[str, Transformed, Ignored]:
        if isinstance(self.right, str):
            return self.right
        elif isinstance(self.right, Ignore):
            return Ignored()
        elif isinstance(self.right, Empty):
            return Transformed(path)
        else:
            raise RuntimeError(f"Right side has invalid type {type(self.right)}")


class Transformation(ABC):
    def __init__(self, rule: Rule):
        self.rule = rule

    @abstractmethod
    def transform(self, path: PurePath) -> TransformResult:
        pass


class ExactTf(Transformation):
    def transform(self, path: PurePath) -> TransformResult:
        if path != PurePath(self.rule.left):
            return None

        right = self.rule.right_result(path)
        if not isinstance(right, str):
            return right

        return Transformed(PurePath(right))


class ExactReTf(Transformation):
    def transform(self, path: PurePath) -> TransformResult:
        match = re.fullmatch(self.rule.left, str_path(path))
        if not match:
            return None

        right = self.rule.right_result(path)
        if not isinstance(right, str):
            return right

        # For some reason, mypy thinks that "groups" has type List[str]. But
        # since elements of "match.groups()" can be None, mypy is wrong.
        groups: Sequence[Optional[str]] = [match[0]] + list(match.groups())

        locals_dir: Dict[str, Union[str, int, float]] = {}
        for i, group in enumerate(groups):
            if group is None:
                continue

            locals_dir[f"g{i}"] = group

            try:
                locals_dir[f"i{i}"] = int(group)
            except ValueError:
                pass

            try:
                locals_dir[f"f{i}"] = float(group)
            except ValueError:
                pass

        named_groups: Dict[str, str] = match.groupdict()
        for name, capture in named_groups.items():
            locals_dir[name] = capture

        result = eval(f"f{right!r}", {}, locals_dir)
        return Transformed(PurePath(result))


class RenamingParentsTf(Transformation):
    def __init__(self, sub_tf: Transformation):
        super().__init__(sub_tf.rule)
        self.sub_tf = sub_tf

    def transform(self, path: PurePath) -> TransformResult:
        for i in range(len(path.parts), -1, -1):
            parent = PurePath(*path.parts[:i])
            child = PurePath(*path.parts[i:])

            transformed = self.sub_tf.transform(parent)
            if not transformed:
                continue
            elif isinstance(transformed, Transformed):
                return Transformed(transformed.path / child)
            elif isinstance(transformed, Ignored):
                return transformed
            else:
                raise RuntimeError(f"Invalid transform result of type {type(transformed)}: {transformed}")

        return None


class RenamingPartsTf(Transformation):
    def __init__(self, sub_tf: Transformation):
        super().__init__(sub_tf.rule)
        self.sub_tf = sub_tf

    def transform(self, path: PurePath) -> TransformResult:
        result = PurePath()
        any_part_matched = False
        for part in path.parts:
            transformed = self.sub_tf.transform(PurePath(part))
            if not transformed:
                result /= part
            elif isinstance(transformed, Transformed):
                result /= transformed.path
                any_part_matched = True
            elif isinstance(transformed, Ignored):
                return transformed
            else:
                raise RuntimeError(f"Invalid transform result of type {type(transformed)}: {transformed}")

        if any_part_matched:
            return Transformed(result)
        else:
            return None


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


T = TypeVar("T")


class Line:
    def __init__(self, line: str, line_nr: int):
        self._line = line
        self._line_nr = line_nr
        self._index = 0

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

    @property
    def rest(self) -> str:
        return self.line[self.index:]

    def peek(self, amount: int = 1) -> str:
        return self.rest[:amount]

    def take(self, amount: int = 1) -> str:
        string = self.peek(amount)
        self.index += len(string)
        return string

    def expect(self, string: str) -> str:
        if self.peek(len(string)) == string:
            return self.take(len(string))
        else:
            raise RuleParseError(self, f"Expected {string!r}")

    def expect_with(self, string: str, value: T) -> T:
        self.expect(string)
        return value

    def one_of(self, parsers: List[Callable[[], T]], description: str) -> T:
        for parser in parsers:
            index = self.index
            try:
                return parser()
            except RuleParseError:
                self.index = index

        raise RuleParseError(self, description)


# RULE = LEFT SPACE '-' NAME '-' HEAD (SPACE RIGHT)?
# SPACE = ' '+
# NAME = '' | 'exact' | 'name' | 're' | 'exact-re' | 'name-re'
# HEAD = '>' | '>>'
# LEFT = STR | QUOTED_STR
# RIGHT = STR | QUOTED_STR | '!'


def parse_zero_or_more_spaces(line: Line) -> None:
    while line.peek() == " ":
        line.take()


def parse_one_or_more_spaces(line: Line) -> None:
    line.expect(" ")
    parse_zero_or_more_spaces(line)


def parse_str(line: Line) -> str:
    result = []
    while c := line.peek():
        if c == " ":
            break
        else:
            line.take()
            result.append(c)

    if result:
        return "".join(result)
    else:
        raise RuleParseError(line, "Expected non-space character")


QUOTATION_MARKS = {'"', "'"}


def parse_quoted_str(line: Line) -> str:
    escaped = False

    # Points to first character of string literal
    start_index = line.index

    quotation_mark = line.peek()
    if quotation_mark not in QUOTATION_MARKS:
        raise RuleParseError(line, "Expected quotation mark")
    line.take()

    while c := line.peek():
        if escaped:
            escaped = False
            line.take()
        elif c == quotation_mark:
            line.take()
            stop_index = line.index
            literal = line.line[start_index:stop_index]
            try:
                return ast.literal_eval(literal)
            except SyntaxError as e:
                line.index = start_index
                raise RuleParseError(line, str(e)) from e
        elif c == "\\":
            escaped = True
            line.take()
        else:
            line.take()

    raise RuleParseError(line, "Expected end of string literal")


def parse_left(line: Line) -> str:
    if line.peek() in QUOTATION_MARKS:
        return parse_quoted_str(line)
    else:
        return parse_str(line)


def parse_right(line: Line) -> Union[str, Ignore]:
    c = line.peek()
    if c in QUOTATION_MARKS:
        return parse_quoted_str(line)
    else:
        string = parse_str(line)
        if string == "!":
            return Ignore()
        return string


def parse_arrow_name(line: Line) -> str:
    return line.one_of([
        lambda: line.expect("exact-re"),
        lambda: line.expect("exact"),
        lambda: line.expect("name-re"),
        lambda: line.expect("name"),
        lambda: line.expect("re"),
        lambda: line.expect(""),
    ], "Expected arrow name")


def parse_arrow_head(line: Line) -> ArrowHead:
    return line.one_of([
        lambda: line.expect_with(">>", ArrowHead.SEQUENCE),
        lambda: line.expect_with(">", ArrowHead.NORMAL),
    ], "Expected arrow head")


def parse_eol(line: Line) -> None:
    if line.peek():
        raise RuleParseError(line, "Expected end of line")


def parse_rule(line: Line) -> Rule:
    parse_zero_or_more_spaces(line)
    left_index = line.index
    left = parse_left(line)

    parse_one_or_more_spaces(line)

    line.expect("-")
    name = parse_arrow_name(line)
    line.expect("-")
    head = parse_arrow_head(line)

    right_index = line.index
    right: RightSide
    try:
        parse_zero_or_more_spaces(line)
        parse_eol(line)
        right = Empty()
    except RuleParseError:
        line.index = right_index
        parse_one_or_more_spaces(line)
        right = parse_right(line)
        parse_eol(line)

    return Rule(left, left_index, name, head, right, right_index)


def parse_transformation(line: Line) -> Transformation:
    rule = parse_rule(line)

    if rule.name == "":
        return RenamingParentsTf(ExactTf(rule))
    elif rule.name == "exact":
        return ExactTf(rule)
    elif rule.name == "name":
        if len(PurePath(rule.left).parts) > 1:
            line.index = rule.left_index
            raise RuleParseError(line, "Expected name, not multiple segments")
        return RenamingPartsTf(ExactTf(rule))
    elif rule.name == "re":
        return RenamingParentsTf(ExactReTf(rule))
    elif rule.name == "exact-re":
        return ExactReTf(rule)
    elif rule.name == "name-re":
        return RenamingPartsTf(ExactReTf(rule))
    else:
        raise RuntimeError(f"Invalid arrow name {rule.name!r}")


class Transformer:
    def __init__(self, rules: str):
        """
        May throw a RuleParseException.
        """

        self._tfs = []
        for i, line in enumerate(rules.split("\n")):
            line = line.strip()
            if line:
                tf = parse_transformation(Line(line, i))
                self._tfs.append((line, tf))

    def transform(self, path: PurePath) -> Optional[PurePath]:
        for i, (line, tf) in enumerate(self._tfs):
            log.explain(f"Testing rule {i+1}: {line}")

            try:
                result = tf.transform(path)
            except Exception as e:
                log.warn(f"Error while testing rule {i+1}: {line}")
                log.warn_contd(str(e))
                continue

            if not result:
                continue

            if isinstance(result, Ignored):
                log.explain("Match found, path ignored")
                return None

            if tf.rule.head == ArrowHead.NORMAL:
                log.explain(f"Match found, transformed path to {fmt_path(result.path)}")
                path = result.path
                break
            elif tf.rule.head == ArrowHead.SEQUENCE:
                log.explain(f"Match found, updated path to {fmt_path(result.path)}")
                path = result.path
            else:
                raise RuntimeError(f"Invalid transform result of type {type(result)}: {result}")

        log.explain(f"Final result: {fmt_path(path)}")
        return path
