"""
Transforms let the user define functions to decide where the downloaded files
should be placed locally. They let the user do more advanced things like moving
only files whose names match a regex, or renaming files from one numbering
scheme to another.
"""

import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Callable, List, Optional, Tuple, TypeVar, Union

Transform = Callable[[PurePath], Optional[PurePath]]


@dataclass
class Transformable:
    """
    An object that can be transformed by a Transform.
    """

    path: PurePath


TF = TypeVar("TF", bound=Transformable)


def apply_transform(
        transform: Transform,
        transformables: List[TF],
) -> List[TF]:
    """
    Apply a Transform to multiple Transformables, discarding those that were
    not transformed by the Transform.
    """

    result: List[TF] = []
    for transformable in transformables:
        if new_path := transform(transformable.path):
            transformable.path = new_path
            result.append(transformable)
    return result

# Utility types and functions

PathLike = Union[PurePath, str, Tuple[str, ...]]

def _path(pathlike: PathLike) -> PurePath:
    if isinstance(pathlike, tuple):
        return PurePath(*pathlike)
    return PurePath(pathlike)

Regex = Union[str, re.Pattern]

def _pattern(regex: Regex) -> re.Pattern:
    if isinstance(regex, re.Pattern):
        return regex
    return re.compile(regex)

# Transform combinators

def attempt(*args: Transform) -> Transform:
    def inner(path: PurePath) -> Optional[PurePath]:
        for transform in args:
            if result := transform(path):
                return result
        return None
    return inner

def optionally(transform: Transform) -> Transform:
    return attempt(transform, lambda path: path)

def do(*args: Transform) -> Transform:
    def inner(path: PurePath) -> Optional[PurePath]:
        current = path
        for transform in args:
            if result := transform(current):
                current = result
            else:
                return None
        return current
    return inner

def predicate(pred: Callable[[PurePath], bool]) -> Transform:
    def inner(path: PurePath) -> Optional[PurePath]:
        if pred(path):
            return path
        return None
    return inner

def glob(pattern: str) -> Transform:
    return predicate(lambda path: path.match(pattern))

def move_dir(source_dir: PathLike, target_dir: PathLike) -> Transform:
    source_path = _path(source_dir)
    target_path = _path(target_dir)
    def inner(path: PurePath) -> Optional[PurePath]:
        if source_path in path.parents:
            return target_path / path.relative_to(source_path)
        return None
    return inner

def move(source: PathLike, target: PathLike) -> Transform:
    source_path = _path(source)
    target_path = _path(target)
    def inner(path: PurePath) -> Optional[PurePath]:
        if path == source_path:
            return target_path
        return None
    return inner

def rename(source: str, target: str) -> Transform:
    def inner(path: PurePath) -> Optional[PurePath]:
        if path.name == source:
            return path.with_name(target)
        return None
    return inner

def re_move(regex: Regex, target: str) -> Transform:
    def inner(path: PurePath) -> Optional[PurePath]:
        if match := _pattern(regex).fullmatch(str(path)):
            groups = [match.group(0)]
            groups.extend(match.groups())
            return PurePath(target.format(*groups))
        return None
    return inner

def re_rename(regex: Regex, target: str) -> Transform:
    def inner(path: PurePath) -> Optional[PurePath]:
        if match := _pattern(regex).fullmatch(path.name):
            groups = [match.group(0)]
            groups.extend(match.groups())
            return path.with_name(target.format(*groups))
        return None
    return inner

# def match(regex: Union[str, re.Pattern]) -> Transform:
#     pattern: re.Pattern
#     if isinstance(regex, str):
#         pattern = re.compile(regex)
#     else:
#         pattern = regex

#     return predicate(lambda path: bool(pattern.match(path.name)))

# def full_match(regex: Union[str, re.Pattern]) -> Transform:
#     pattern: re.Pattern
#     if isinstance(regex, str):
#         pattern = re.compile(regex)
#     else:
#         pattern = regex

#     return predicate(lambda path: bool(pattern.match(str(path))))

# def zoom(
#         selector: Callable[[PurePath], Optional[Tuple[PurePath, PurePath]]],
#         actor: Callable[[PurePath], Transform],
# ) -> Transform:
#     def inner(path: PurePath) -> Optional[PurePath]:
#         if selected := selector(path):
#             base, relative = selected
#             return actor(base)(relative)
#         return None
#     return inner

# def move_from(source: PurePath, target: PurePath) -> Transform:
#     return zoom(
#         lambda path: (source, path.relative_to(source)) if source in path.parents else None,
#         lambda _: lambda path: target / path,
#     )

# re_move(r"Übungsmaterial/Blätter/(\d+).pdf", "Blätter/Blatt{1:02}.pdf")
# re_rename(r"(\d+).pdf", "Blatt{1:02}.pdf")

# def at(at_path: PurePath) -> Transform:
#     return predicate(lambda path: path == at_path)

# def inside(inside_path: PurePath) -> Transform:
#     return predicate(lambda path: inside_path in path.parents)
