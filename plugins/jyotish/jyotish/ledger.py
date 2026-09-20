"""What the cross-check has learned across charts, not just this one.

A verdict from one chart is evidence about *that* chart. It can also be
evidence about the convention: if the local computation reproduces the site's
D9 on one chart, that may be luck — the two happened to land in the same sign
— and if it does so on several unrelated charts, the rule behind it is
settled. The first case is `state/crosscheck.json` inside a reading; this
module is the second, kept outside every reading because it is about the
software, not about a person.

Three rules keep the accumulation honest:

* **A block is established only after several distinct charts agree** and
  **never** if any chart disagreed. One disagreement means the convention is
  not settled, however many agreements stand beside it — that is exactly the
  case the ledger exists to catch.
* **A verdict for the chart at hand always wins.** The ledger says what to do
  when nothing is known about this chart; it can never overrule what the
  cross-check found on it.
* **A change of conventions voids the evidence.** Every observation is
  recorded against a fingerprint — the version of PyJHora and the revision of
  the conventions in :mod:`jyotish.local`. When either moves, the old
  observations are dropped rather than quietly carried over, because they
  were made by different arithmetic.

No birth data is stored. A chart is counted by a digest of its parameters
under a salt generated once for this ledger, so the same chart is not counted
twice and none of the charts can be read back out of the file.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .client import Client

#: How many distinct charts must agree before a block is trusted without a
#: cross-check of its own. Three is the smallest number that distinguishes a
#: rule from a coincidence: two charts can share a sign by chance often
#: enough, three rarely.
DEFAULT_THRESHOLD = 3

VERSION = 1
AGREED = "совпало"


def ledger_path() -> Path:
    """Where the ledger lives — in the plugin's data, never inside a reading.

    A reading's folder holds one person's data and is gitignored; this file
    holds no personal data and must outlive any single reading.
    """
    override = os.environ.get("JYOTISH_LEDGER")
    if override:
        return Path(override)
    base = os.environ.get("CLAUDE_PLUGIN_DATA") or os.environ.get("XDG_DATA_HOME") \
        or str(Path.home() / ".local" / "share")
    return Path(base) / "jyotish" / "ledger.json"


def _version(package: str) -> str:
    try:
        from importlib.metadata import version

        return version(package)
    except Exception:
        return "?"


def fingerprint() -> str:
    """The arithmetic, the reading and the checks these observations were made by.

    All three matter. A changed convention means the local numbers came out
    differently; a changed **parser** means the site's numbers were read
    differently — vedic-parser 0.1.0 quietly shifted the columns of a
    fourteen-column planets table, so «сошлось» under it was a statement
    about other data; a changed check means «сошлось» meant something else
    again. In every case the old observations are not evidence about the
    current arrangement.
    """
    from . import crosscheck, local as local_module

    return (f"PyJHora {_version('PyJHora')} · соглашения {local_module.CONVENTIONS_VERSION}"
            f" · vedic-parser {_version('vedic-parser')}"
            f" · проверки {crosscheck.CHECKS_VERSION}")


@dataclass
class Ledger:
    """Observations per block, under one fingerprint."""

    fingerprint: str
    salt: str
    #: block key -> {"agreed": [chart ids], "disagreed": [chart ids]}
    blocks: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    updated: str = ""
    #: Set when loading found observations from another fingerprint.
    dropped: str = ""

    # ---- reading and writing ----------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "Ledger":
        path = path or ledger_path()
        current = fingerprint()
        if not path.exists():
            return cls(fingerprint=current, salt=secrets.token_hex(16))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return cls(fingerprint=current, salt=secrets.token_hex(16),
                       dropped="файл журнала повреждён — начат заново")
        stored = str(data.get("fingerprint") or "")
        salt = str(data.get("salt") or secrets.token_hex(16))
        if stored != current:
            # Не переносим: наблюдения сделаны другой арифметикой.
            return cls(fingerprint=current, salt=salt, dropped=stored or "неизвестная версия")
        blocks = {
            key: {"agreed": list(value.get("agreed") or []),
                  "disagreed": list(value.get("disagreed") or [])}
            for key, value in (data.get("blocks") or {}).items()
        }
        return cls(fingerprint=current, salt=salt, blocks=blocks,
                   updated=str(data.get("updated") or ""))

    def save(self, path: Path | None = None) -> Path:
        path = path or ledger_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated = datetime.now().isoformat(timespec="minutes")
        path.write_text(json.dumps({
            "version": VERSION,
            "fingerprint": self.fingerprint,
            "salt": self.salt,
            "updated": self.updated,
            "blocks": self.blocks,
        }, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return path

    # ---- counting ----------------------------------------------------------

    def chart_id(self, client: Client) -> str:
        """An opaque, stable id for one nativity. Not reversible without the salt.

        The **time is deliberately left out**. Two charts a minute apart are
        two different charts, and they would be real evidence — but they are
        also what a rectification produces by the dozen, and what
        ``sensitivity`` produces by the ten. Counting them as independent
        would let one nativity establish a convention on its own, which is
        the very coincidence the threshold exists to rule out. Counting by
        date and place undercounts instead, which is the safe direction.
        """
        chart = client.chart
        material = "|".join((self.salt, chart.date, chart.timezone,
                             str(chart.latitude), str(chart.longitude)))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]

    def record(self, client: Client, verdicts: dict[str, str]) -> None:
        """Add this chart's verdicts, replacing anything it said before.

        Re-running the cross-check on the same chart must not count twice,
        and a verdict that changed (a convention was fixed) must replace the
        old one rather than sit beside it.
        """
        chart = self.chart_id(client)
        for key, verdict in verdicts.items():
            block = self.blocks.setdefault(key, {"agreed": [], "disagreed": []})
            for side in ("agreed", "disagreed"):
                if chart in block[side]:
                    block[side].remove(chart)
            side = "agreed" if verdict == AGREED else "disagreed"
            block[side].append(chart)
            block[side].sort()

    def charts(self) -> int:
        """How many distinct charts this ledger has seen."""
        seen: set[str] = set()
        for block in self.blocks.values():
            seen.update(block["agreed"])
            seen.update(block["disagreed"])
        return len(seen)

    def status(self, key: str, threshold: int = DEFAULT_THRESHOLD) -> tuple[bool, str]:
        """Whether ``key`` is established, and the sentence that says why."""
        block = self.blocks.get(key)
        if not block:
            return False, "нет наблюдений"
        agreed, disagreed = len(block["agreed"]), len(block["disagreed"])
        if disagreed:
            return False, (f"совпало на {agreed}, **разошлось на {disagreed}** — "
                           "соглашение не закреплено, пока расхождение не объяснено")
        if agreed >= threshold:
            return True, f"совпало на {agreed} картах подряд, без расхождений"
        return False, f"совпало на {agreed} из {threshold} нужных карт"

    def established(self, threshold: int = DEFAULT_THRESHOLD) -> set[str]:
        """Blocks that may be computed locally on a chart never checked."""
        return {key for key in self.blocks if self.status(key, threshold)[0]}

    def rows(self, threshold: int = DEFAULT_THRESHOLD) -> list[tuple[str, str, str]]:
        """(block, verdict, why) for every block seen, for a table."""
        out = []
        for key in sorted(self.blocks):
            ok, why = self.status(key, threshold)
            out.append((key, "**закреплено**" if ok else "копится", why))
        return out


def record(client: Client, verdicts: dict[str, str], *,
           path: Path | None = None) -> Ledger:
    """Load, add this chart's verdicts, save. Returns the ledger as it now is."""
    book = Ledger.load(path)
    book.record(client, verdicts)
    book.save(path)
    return book


def established(threshold: int = DEFAULT_THRESHOLD, *, path: Path | None = None) -> set[str]:
    """What may be taken locally on a chart the cross-check has not seen."""
    return Ledger.load(path).established(threshold)


def render(book: Ledger, threshold: int = DEFAULT_THRESHOLD) -> str:
    """The ledger as a document, for `jyotish ledger`."""
    lines = [
        "# Журнал сверки: что подтверждено между картами",
        "",
        f"Арифметика: {book.fingerprint}. Карт в журнале: {book.charts()}. "
        f"Порог: {threshold}.",
        "",
        "Блок считается закреплённым, когда он совпал с сайтом на нескольких "
        "разных картах и **не разошёлся ни на одной**. Такой блок сборщик "
        "берёт локально и на новой карте, которую сверка ещё не видела. "
        "Вердикт по самой карте всегда сильнее журнала.",
        "",
    ]
    if book.dropped:
        lines += [
            f"**Прежние наблюдения отброшены**: они сделаны версией «{book.dropped}», "
            "а не текущей. Это другая арифметика, переносить её выводы нельзя.",
            "",
        ]
    if not book.blocks:
        lines += ["Наблюдений пока нет: запустите `jyotish crosscheck` хотя бы на одной карте."]
        return "\n".join(lines) + "\n"
    lines += ["| Блок | Статус | На чём держится |", "|---|---|---|"]
    lines += [f"| `{key}` | {verdict} | {why} |" for key, verdict, why in book.rows(threshold)]
    return "\n".join(lines) + "\n"
