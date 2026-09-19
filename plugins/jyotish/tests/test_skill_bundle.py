"""The skill must stay portable across agents.

It is packaged in the Agent Skills format, which ChatGPT, Codex and Claude all
read. Portability is easy to lose by accident — one `${CLAUDE_PLUGIN_ROOT}` in
SKILL.md and the bundle only works in one of them — so it is checked here rather
than remembered.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / "skills" / "jyotish-reading"
MANIFEST = SKILL / "SKILL.md"

#: Tokens only one vendor expands. Any of them in SKILL.md breaks the bundle
#: everywhere else, silently — the path just does not resolve.
VENDOR_TOKENS = (
    "${CLAUDE_PLUGIN_ROOT}", "$CLAUDE_PLUGIN_ROOT",
    "${CLAUDE_PLUGIN_DATA}", "${CLAUDE_PROJECT_DIR}",
    "${OPENAI_", "$OPENAI_",
)


@pytest.fixture(scope="module")
def manifest() -> str:
    return MANIFEST.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def frontmatter(manifest: str) -> dict[str, str]:
    assert manifest.startswith("---\n"), "SKILL.md должен начинаться с YAML-преамбулы"
    _, block, _ = manifest.split("---", 2)
    fields: dict[str, str] = {}
    key = None
    for line in block.strip().splitlines():
        match = re.match(r"^([a-z][a-z0-9-]*):\s*(.*)$", line)
        if match:
            key, value = match.groups()
            fields[key] = value.strip()
        elif key:                      # продолжение многострочного значения
            fields[key] += " " + line.strip()
    return fields


# ---- the manifest ----------------------------------------------------------


def test_skill_manifest_exists_and_is_the_only_one() -> None:
    assert MANIFEST.is_file()
    found = [p for p in SKILL.rglob("*") if p.name.lower() == "skill.md"]
    assert len(found) == 1, f"в бандле должен быть ровно один SKILL.md, найдено {found}"


def test_required_frontmatter_fields(frontmatter: dict[str, str]) -> None:
    """The spec requires exactly these two; everything else is optional."""
    assert frontmatter.get("name")
    assert frontmatter.get("description")


def test_name_matches_the_directory_and_is_kebab_case(frontmatter: dict[str, str]) -> None:
    name = frontmatter["name"]
    assert name == SKILL.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name), name
    assert len(name) <= 64


def test_description_says_when_to_use_and_when_not(frontmatter: dict[str, str]) -> None:
    description = frontmatter["description"]
    assert len(description) <= 1024, f"{len(description)} символов"
    assert "Используй" in description
    assert "Не используй" in description, "описание должно отсекать чужие темы"


# ---- portability -----------------------------------------------------------


@pytest.mark.parametrize("token", VENDOR_TOKENS)
def test_manifest_carries_no_vendor_specific_tokens(manifest: str, token: str) -> None:
    assert token not in manifest, (
        f"{token} раскрывает только один агент; в SKILL.md нужны относительные пути"
    )


def test_every_path_the_manifest_mentions_exists(manifest: str) -> None:
    """A reference that does not resolve is worse than one that is absent."""
    mentioned = set(re.findall(r"`((?:references|assets|scripts)/[^`]+)`", manifest))
    assert mentioned, "SKILL.md должен ссылаться на файлы бандла"
    missing = []
    for path in mentioned:
        # `NN` stands for a stage number in the manifest's prose, so it is
        # resolved as a glob rather than looked up literally.
        pattern = path.replace("NN", "[0-9][0-9]")
        if "*" in pattern or "[" in pattern:
            if not list(SKILL.glob(pattern)):
                missing.append(path)
        elif not (SKILL / path).exists():
            missing.append(path)
    assert not missing, f"в бандле нет: {missing}"


def test_bundle_has_the_methodology_and_the_template() -> None:
    references = sorted(p.name for p in (SKILL / "references").glob("*.md"))
    assert len(references) == 11, "00_README плюс десять этапов"
    assert references[0].startswith("00_")
    assert any(p.suffix == ".html" for p in (SKILL / "assets").iterdir())


def test_cli_wrapper_is_executable_and_degrades_instead_of_failing_silently() -> None:
    wrapper = SKILL / "scripts" / "jyotish"
    assert wrapper.is_file()
    assert os.access(wrapper, os.X_OK), "scripts/jyotish должен быть исполняемым"
    text = wrapper.read_text(encoding="utf-8")
    assert "ручной режим" in text or "ручном режиме" in text, (
        "обёртка должна отсылать к ручному режиму, а не просто падать"
    )


def test_manifest_documents_both_modes(manifest: str) -> None:
    """The skill is useless in ChatGPT if it assumes the CLI is always there."""
    assert "## Два режима" in manifest
    assert "Ручной режим" in manifest


def test_gates_and_scales_survive_in_the_portable_manifest(manifest: str) -> None:
    for rule in ("Гейт биографии", "Допуск к этапу 07", "Три шкалы",
                 "независимым подтверждением"):
        assert rule in manifest, rule
