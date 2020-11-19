"""
Transforms let the user define functions to decide where the downloaded files
should be placed locally. They let the user do more advanced things like moving
only files whose names match a regex, or renaming files from one numbering
scheme to another.
"""

import os
import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Callable, List, Optional, TypeVar

from .utils import PathLike, Regex, to_path, to_pattern

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
        new_path = transform(transformable.path)
        if new_path:
            transformable.path = new_path
            result.append(transformable)
    return result

# Transform combinators

def keep(path: PurePath) -> Optional[PurePath]:
    return path

def attempt(*args: Transform) -> Transform:
    def inner(path: PurePath) -> Optional[PurePath]:
        for transform in args:
            result = transform(path)
            if result:
                return result
        return None
    return inner

def optionally(transform: Transform) -> Transform:
    return attempt(transform, lambda path: path)

def do(*args: Transform) -> Transform:
    def inner(path: PurePath) -> Optional[PurePath]:
        current = path
        for transform in args:
            result = transform(current)
            if result:
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
    source_path = to_path(source_dir)
    target_path = to_path(target_dir)
    def inner(path: PurePath) -> Optional[PurePath]:
        if source_path in path.parents:
            return target_path / path.relative_to(source_path)
        return None
    return inner

def move(source: PathLike, target: PathLike) -> Transform:
    source_path = to_path(source)
    target_path = to_path(target)
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
        match = to_pattern(regex).fullmatch(str(path))
        if match:
            groups = [match.group(0)]
            groups.extend(match.groups())
            return PurePath(target.format(*groups))
        return None
    return inner

def re_rename(regex: Regex, target: str) -> Transform:
    def inner(path: PurePath) -> Optional[PurePath]:
        match = to_pattern(regex).fullmatch(path.name)
        if match:
            groups = [match.group(0)]
            groups.extend(match.groups())
            return path.with_name(target.format(*groups))
        return None
    return inner


def sanitize_windows_path(path: PurePath) -> Optional[PurePath]:
    """
    A small function to escape characters that are forbidden in windows path names.
    This method is a no-op on other operating systems.
    """
    # Escape windows illegal path characters
    if os.name == 'nt':
        sanitized_parts = [re.sub(r'[<>:"|?]', "_", x) for x in list(path.parts)]
        return PurePath(*sanitized_parts)
    return path
