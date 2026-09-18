from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from dsh_home_isolation import create_isolated_dsh_home

REQUIRED = {
    "settings.yaml": "provider: openrouter\napiKeyEnv: OPENROUTER_API_KEY\n",
    "profiles/headless/package.json": '{"private": true}\n',
    "profiles/headless/pnpm-workspace.yaml": "packages:\n  - .\n",
    "profiles/headless/cordis.patch.yml": "[]\n",
}


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_concurrent_tasks_receive_clean_independent_homes(tmp_path: Path) -> None:
    template = tmp_path / "template"
    for relative, content in REQUIRED.items():
        _write(template / relative, content)

    _write(template / ".credentials.yaml", "apiKey: must-not-copy\n")
    _write(template / "sessions/old/session.jsonl", "old session\n")
    _write(template / "profiles/headless/cordis.yml", "generated root\n")
    _write(template / "profiles/node_modules/example/index.js", "generated link tree\n")

    trial_roots = [tmp_path / f"trial-{index}" for index in range(4)]
    for trial_root in trial_roots:
        trial_root.mkdir()

    with ThreadPoolExecutor(max_workers=4) as executor:
        homes = list(
            executor.map(
                lambda trial_root: create_isolated_dsh_home(template, trial_root),
                trial_roots,
            )
        )

    assert len(set(homes)) == 4
    for home in homes:
        for relative, content in REQUIRED.items():
            assert (home / relative).read_text(encoding="utf-8") == content
        assert not (home / ".credentials.yaml").exists()
        assert not (home / "sessions").exists()
        assert not (home / "profiles/headless/cordis.yml").exists()
        assert not (home / "profiles/node_modules").exists()

    _write(homes[0] / "sessions/new/session.jsonl", "task zero\n")
    assert not (homes[1] / "sessions").exists()


def test_missing_required_template_configuration_fails(tmp_path: Path) -> None:
    template = tmp_path / "template"
    template.mkdir()
    trial_root = tmp_path / "trial"
    trial_root.mkdir()

    with pytest.raises(FileNotFoundError, match="template configuration is missing"):
        create_isolated_dsh_home(template, trial_root)


def test_inline_credentials_are_rejected(tmp_path: Path) -> None:
    template = tmp_path / "template"
    for relative, content in REQUIRED.items():
        _write(template / relative, content)
    inline_key = "sk-or" + "-v1-" + "x" * 32
    _write(template / "settings.yaml", f"apiKey: {inline_key}\n")
    trial_root = tmp_path / "trial"
    trial_root.mkdir()

    with pytest.raises(ValueError, match="contains an inline credential"):
        create_isolated_dsh_home(template, trial_root)
