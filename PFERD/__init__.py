import importlib.metadata
import warnings

try:
    __version__ = importlib.metadata.version(__name__)
except importlib.metadata.PackageNotFoundError as e:
    warnings.warn(f"Could not determine version of {__name__}."
                  f"Did you install it correctly?\n{e!s}", stacklevel=2)
    __version__ = "unknown"
