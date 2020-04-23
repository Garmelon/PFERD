"""
Transforms let the user define functions to decide where the downloaded files
should be placed locally. They let the user do more advanced things like moving
only files whose names match a regex, or renaming files from one numbering
scheme to another.
"""

from dataclasses import dataclass
from pathlib import PurePath
from typing import Callable, List, Optional, TypeVar

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
