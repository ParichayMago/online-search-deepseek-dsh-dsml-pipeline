"""Create credential-free, per-task DeepSeek Harness homes."""

from __future__ import annotations

import re
from pathlib import Path

_REQUIRED_CONFIG_FILES = (
    Path("settings.yaml"),
    Path("profiles/headless/package.json"),
    Path("profiles/headless/pnpm-workspace.yaml"),
    Path("profiles/headless/cordis.patch.yml"),
)
_OPTIONAL_CONFIG_FILES = (
    Path("cordis.patch.yml"),
    Path("profiles/headless/pnpm-lock.yaml"),
)
_SECRET_PATTERNS = (
    re.compile(rb"sk-or-v1-[A-Za-z0-9_-]{16,}"),
    re.compile(
        rb"(?im)^\s*(?:apiKey|api_key|authorization|secret)\s*:\s*[^#\s]{16,}"
    ),
)


def _copy_regular_file(template_home: Path, isolated_home: Path, relative: Path) -> None:
    source = template_home / relative
    if source.is_symlink() or not source.is_file():
        raise FileNotFoundError(f"DSH template configuration is missing: {source}")
    content = source.read_bytes()
    if any(pattern.search(content) for pattern in _SECRET_PATTERNS):
        raise ValueError(f"DSH template configuration contains an inline credential: {source}")
    target = isolated_home / relative
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.write_bytes(content)
    target.chmod(0o600)


def create_isolated_dsh_home(template_home: Path, trial_root: Path) -> Path:
    """Copy only immutable configuration into a new task-owned DSH home.

    Runtime state is intentionally excluded: credentials, sessions, generated
    ``cordis.yml`` roots, and ``profiles/node_modules`` never cross from the
    shared template. DSH can safely generate those files beneath the returned
    task-specific directory while reading the OpenRouter key from its process
    environment.
    """
    template_home = template_home.expanduser().resolve(strict=True)
    isolated_home = trial_root.resolve() / "dsh-home"
    isolated_home.mkdir(mode=0o700, parents=False, exist_ok=False)

    for relative in _REQUIRED_CONFIG_FILES:
        _copy_regular_file(template_home, isolated_home, relative)
    for relative in _OPTIONAL_CONFIG_FILES:
        source = template_home / relative
        if source.exists():
            _copy_regular_file(template_home, isolated_home, relative)

    return isolated_home
