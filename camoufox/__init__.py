"""Compatibility shim delegating to the official Camoufox SDK.

The historical Ghost Browsers repository shipped a lightweight stub so unit
tests could run without downloading the proprietary Camoufox runtime.  The
project now depends on the public `camoufox` package published on PyPI.  To
keep existing imports working we bootstrap the upstream distribution under an
internal alias and proxy a handful of helpers that the runner and smoke tests
expect to exist.

Example:
    >>> from camoufox import Camoufox, get_path
    >>> try:
    ...     path = get_path()
    ... except FileNotFoundError:
    ...     path = "<missing>"
    >>> isinstance(path, (str, Path))
    True
"""

from __future__ import annotations

import importlib
import importlib.metadata as metadata
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Iterable


def _bootstrap_sdk() -> tuple[ModuleType, Path]:
    """Load the upstream Camoufox SDK under an internal module alias.

    Returns:
        tuple[ModuleType, Path]: The imported module object and the directory
        containing the official package sources.

    Raises:
        ImportError: If the ``camoufox`` distribution cannot be located.

    Example:
        >>> module, package_path = _bootstrap_sdk()  # doctest: +SKIP
        >>> module.__name__  # doctest: +SKIP
        'camoufox_sdk'
    """

    try:
        dist = metadata.distribution("camoufox")
    except metadata.PackageNotFoundError as exc:  # pragma: no cover - defensive
        raise ImportError(
            "The official 'camoufox' package is required but not installed."
        ) from exc
    package_dir = Path(dist.locate_file("camoufox"))
    spec = importlib.util.spec_from_file_location(
        "camoufox_sdk",
        package_dir / "__init__.py",
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError("Unable to load the upstream Camoufox SDK")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules.setdefault(spec.name, module)
    return module, package_dir


_SDK_ROOT, _SDK_PATH = _bootstrap_sdk()
"""Loaded entry point for the upstream Camoufox SDK module."""

# Extend the package search path so that ``import camoufox.<submodule>``
# resolves to the genuine SDK implementation.  This mirrors the behaviour that
# consumers expected from the previous stub while still allowing us to expose
# additional compatibility helpers from this module.
__path__ = [str(_SDK_PATH)]  # type: ignore[assignment]


def _load_sdk_module(relative_name: str) -> ModuleType:
    """Import a submodule from the official SDK.

    Args:
        relative_name: Dotted name relative to the upstream package, e.g.
            ``"sync_api"`` or ``"__main__"``.

    Returns:
        ModuleType: The imported submodule.

    Example:
        >>> sync_api = _load_sdk_module("sync_api")  # doctest: +SKIP
        >>> hasattr(sync_api, "Camoufox")  # doctest: +SKIP
        True
    """

    return importlib.import_module(f".{relative_name}", package=_SDK_ROOT.__name__)


_sync_api = _load_sdk_module("sync_api")
Camoufox = _sync_api.Camoufox
NewBrowser = _sync_api.NewBrowser

_pkgman = _load_sdk_module("pkgman")
_addons = _load_sdk_module("addons")
DefaultAddons = _addons.DefaultAddons
launch_options = _SDK_ROOT.launch_options


def get_path(*, download_if_missing: bool = False) -> Path:
    """Return the filesystem path of the Camoufox browser binary.

    The helper mirrors the legacy stub API while delegating to the upstream
    installer logic.  By default it avoids triggering downloads so tests remain
    hermetic; callers can opt in via ``download_if_missing``.

    Args:
        download_if_missing: When ``True`` the upstream SDK is allowed to
            download and install Camoufox if it is not already present.

    Returns:
        Path: Absolute path to the Camoufox executable.

    Raises:
        FileNotFoundError: If the binary is not installed and downloads are
            disabled.
        Exception: Any error bubbled up by the official SDK when installation
            fails.

    Example:
        >>> try:
        ...     path = get_path()
        ... except FileNotFoundError:
        ...     path = None
        >>> path is None or isinstance(path, Path)
        True
    """

    try:
        install_dir = _pkgman.camoufox_path(download_if_missing=download_if_missing)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            "Camoufox binaries are missing. Run `python -m camoufox fetch` "
            "to install them."
        ) from exc
    launch_file = Path(_pkgman.LAUNCH_FILE[_pkgman.OS_NAME])
    binary_path = Path(install_dir) / launch_file
    return binary_path


def get_version() -> str:
    """Return the installed Camoufox version string reported by the SDK.

    Returns:
        str: Semantic version string describing the installed runtime.

    Raises:
        FileNotFoundError: If the version metadata file is unavailable because
            the binaries have not been fetched yet.

    Example:
        >>> try:
        ...     version = get_version()
        ... except FileNotFoundError:
        ...     version = "<unknown>"
        >>> isinstance(version, str)
        True
    """

    try:
        return _pkgman.installed_verstr()
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            "Camoufox version metadata is missing. Install the runtime first "
            "with `python -m camoufox fetch`."
        ) from exc


def __getattr__(name: str) -> object:
    """Delegate attribute lookups to the upstream SDK for compatibility."""

    try:
        return getattr(_SDK_ROOT, name)
    except AttributeError as exc:  # pragma: no cover - mirrors normal behaviour
        raise AttributeError(f"module {__name__!r} has no attribute {name}") from exc


def __dir__() -> Iterable[str]:
    """Combine local helper names with the upstream SDK export list."""

    return sorted(set(globals().keys()) | set(dir(_SDK_ROOT)))


__all__ = [
    "Camoufox",
    "DefaultAddons",
    "NewBrowser",
    "get_path",
    "get_version",
    "launch_options",
]
