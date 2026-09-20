"""Turn a collection into the two documents Prompt 01 ends with.

``01_RAW_DATA.md`` is the full technical export, laid out in the nineteen
sections Prompt 01 lists, so another astrologer can check it against the site.
``01_MISSING_DATA.md`` says what did not arrive and why, in the marker wording
Prompt 01 prescribes.

The rule the whole module follows: nothing is smoothed over. A number that did
not arrive is named as absent; a number this repository computed rather than
read off the site is labelled as computed; a disagreement between the two is
printed as a РАСХОЖДЕНИЕ block instead of being quietly resolved.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from .client import VARGA_PURPOSE, Client
from .collect import NOT_SUPPLIED, PAID, UNAVAILABLE, Collection, Gap
from .derive import derive_all, sign_name

#: Prompt 01 §13's checklist of special states, mapped to where each is
#: actually found. The site marks most of them with a code in the planet's
#: ``position`` field; a few come from elsewhere, and a few have no source at
#: all. Keeping this as data is what lets the export distinguish "this chart
#: does not have it" from "nobody can tell you" — a distinction the reading
#: depends on and that a hardcoded sentence kept getting wrong.
SPECIAL_STATE_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("Варготтама", "code:V", ""),
    ("Гандантa", "code:G0°,G1°", ""),
    ("Мритью-бхага", "code:MB", ""),
    ("Пушкара-навамша", "code:PN", ""),
    ("Пушкара-бхага", "code:PB", ""),
    ("Марана-карака-стхана", "code:MKS", ""),
    ("Карака-бхава-нашая", "code:KBN", ""),
    ("Сандхи (стык знаков)", "code:S", ""),
    ("Диг-бала / нулевая диг-бала", "code:DB,ZDB", ""),
    ("Окружение вредителями", "code:HM", ""),
    ("Экзальтация, дебилитация, свой знак", "dignity", "колонка «Достоинство» в §2"),
    ("Ретроградность", "retrograde", "колонка «Ретро» в §2"),
    ("Граха-юддха", "war", "поле planetary_war"),
    ("Виша-навамша, 22-я дреккана, 64-я навамша", "other", "раздел §4, вкладка «Разное»"),
    ("Бадхака", "other", "раздел §4, вкладка «Разное»"),
    ("Паривартана", "derived", "**[расчёт]**, ниже"),
    ("Нича-бханга", "none", "сайт отдельно не помечает; определяется правилами"),
    ("Сожжение (комбустия)", "none", "сайт отдельно не помечает"),
    ("Абхукта-мула", "none", "источника нет"),
    ("Кендрадхипати-доша", "none", "источника нет; выводится из управления домами"),
)

#: Said next to every yoga table. Prompt 01 §11 and Prompt 10 §3–4 both exist
#: because a previous reading mistook this list for evidence.
YOGA_WARNING = (
    "Это автосписок сайта. Он фиксируется как данные, а не как доказательство: "
    "вывод «йога работает» на этом этапе не делается, условие каждой йоги "
    "проверяется отдельно на этапе 02."
)

#: Said next to the argala table — the parser hands the site's grouping through
#: unchanged, and the site swaps the groups for the sign Ketu occupies.
ARGALA_WARNING = (
    "Для знака, который занимает Кету, сайт меняет местами группы «аргала» и "
    "«виродха». Группировка приведена как есть, без исправления."
)


def render(client: Client, collection: Collection) -> tuple[str, str]:
    """Return ``(RAW_DATA.md, MISSING_DATA.md)`` as text."""
    derived = _derive(collection)
    return (
        "\n".join(_raw_data(client, collection, derived)).rstrip() + "\n",
        "\n".join(_missing_data(client, collection)).rstrip() + "\n",
    )


def write(client: Client, collection: Collection) -> tuple[str, str]:
    """Render and save both documents plus the stage summary."""
    raw_text, missing_text = render(client, collection)
    client.ensure_dirs()
    client.raw_data_md.write_text(raw_text, encoding="utf-8")
    client.missing_data_md.write_text(missing_text, encoding="utf-8")
    summary = "\n".join(summarise(client, collection)).rstrip() + "\n"
    (client.summaries_dir / "01.md").write_text(summary, encoding="utf-8")
    return raw_text, missing_text


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _table(headers: Iterable[str], rows: Iterable[Iterable[Any]]) -> list[str]:
    headers = list(headers)
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join("" if cell is None else str(cell) for cell in row) + " |")
    return lines


def _absent(what: str, marker: str = UNAVAILABLE) -> list[str]:
    return [f"`{marker}` — {what}", ""]


def _yes(value: Any) -> str:
    return "да" if value else ""


def _dignity(planet: dict[str, Any]) -> str:
    rasi = planet.get("rasi") or {}
    return rasi.get("dignity") or ""


def _derive(collection: Collection) -> dict[str, Any]:
    chart = collection.get("show-chart-D1")
    info = collection.get("show-info-D1")
    if not chart or not info:
        return {}
    return derive_all(chart, info, collection.get("show-bala-D1"))


# ---------------------------------------------------------------------------
# RAW_DATA.md
# ---------------------------------------------------------------------------


def _raw_data(client: Client, data: Collection, derived: dict[str, Any]) -> list[str]:
    out: list[str] = [
        f"# {client.slug} — технический экспорт (Промпт 01)",
        "",
        f"Собрано автоматически {date.today():%d.%m.%Y} командой `jyotish collect` "
        f"из vedic-horo ({client.collect.lang}). Интерпретации здесь нет и быть не должно.",
        "",
        "Помечено явно: **[расчёт]** — значение вычислено этим репозиторием, а не "
        "получено с сайта. Всё остальное перенесено с сайта как есть.",
        "",
    ]
    out += _section_1_parameters(client, data)
    out += _section_2_d1(data)
    out += _section_3_vargas(data)
    out += _section_4_nakshatras(data)
    out += _section_5_jaimini(data, derived)
    out += _section_6_arudhas(derived)
    out += _section_7_lagnas(data)
    out += _section_8_bala(data)
    out += _section_9_bhava(data, derived)
    out += _section_10_ashtakavarga(data)
    out += _section_11_yogas(data)
    out += _section_12_avasthas(data)
    out += _section_13_states(data, derived)
    out += _section_14_dashas(data)
    out += _section_15_varshaphala()
    out += _section_16_transits(data)
    out += _section_17_aspects(data)
    out += _section_18_panchanga(data)
    out += _section_20_quality(client, data, derived)
    return out


def _section_1_parameters(client: Client, data: Collection) -> list[str]:
    chart = client.chart
    other = data.get("show-other-D1") or {}
    ayanamsa = ((other.get("points") or {}).get("ayanamsa") or {}).get("value")
    out = ["## 1. Параметры расчёта", ""]
    out += _table(
        ["Параметр", "Значение"],
        [
            ("Имя / метка", chart.name),
            ("Дата", chart.date),
            ("Время", chart.time),
            ("Часовой пояс", chart.timezone),
            ("Место", client.place or "—"),
            ("Широта (град.мин)", chart.latitude),
            ("Долгота (град.мин)", chart.longitude),
            ("Айанамша", ayanamsa or f"`{UNAVAILABLE}`"),
            ("Источник", f"vedic-horo, язык {client.collect.lang}"),
            ("Стиль карты", "North (на разбор не влияет: обе разметки дают одни данные)"),
        ],
    )
    out += [
        "",
        f"**Статус времени рождения:** {client.birth_time.label}.",
        "",
    ]
    if client.birth_time.confirmed:
        out.append("Промпт 07 и выводы по D60 допустимы.")
    else:
        out.append(
            "**Промпт 07 не выполняется, выводы по D60 недопустимы** — время рождения "
            "не подтверждено и не ректифицировано."
        )
    out += [
        "",
        "Настройки узлов, способа расчёта варг, системы чара-карак и арудх сайт "
        "анонимному пользователю не показывает: использованы его значения по "
        "умолчанию. Караки ниже посчитаны в 7-караковой системе.",
        "",
    ]
    return out


def _planet_rows(info: dict[str, Any]) -> list[tuple[Any, ...]]:
    rows = []
    for planet in info.get("planets", []):
        nakshatra = planet.get("nakshatra") or {}
        lords = ", ".join(str(l["house"]) for l in planet.get("lords") or [])
        rows.append((
            planet.get("code"),
            planet.get("name"),
            (planet.get("rasi") or {}).get("name"),
            planet.get("degrees"),
            planet.get("house"),
            nakshatra.get("name"),
            nakshatra.get("pada"),
            nakshatra.get("lord"),
            planet.get("navamsa"),
            _dignity(planet),
            planet.get("relationship"),
            _yes(planet.get("retrograde")),
            lords,
            (planet.get("functional_beneficence") or {}).get("code"),
            (planet.get("natural_beneficence") or {}).get("code"),
            planet.get("shad_bala"),
            (planet.get("bindu") or {}).get("bav"),
            planet.get("karaka"),
            ", ".join(p.get("code", "") for p in planet.get("position") or []),
        ))
    return rows


def _section_2_d1(data: Collection) -> list[str]:
    info = data.get("show-info-D1")
    chart = data.get("show-chart-D1")
    out = ["## 2. D1 / Раши", ""]
    if not info:
        return out + _absent("таблица планет D1")

    out += _table(
        ["Код", "Планета", "Знак", "Градус", "Дом", "Накшатра", "Пада", "Упр. накш.",
         "Навамша", "Достоинство", "Отношение", "Ретро", "Управляет домами",
         "Функц.", "Натур.", "Шадбала %", "Бинду", "Карака", "Отметки"],
        _planet_rows(info),
    )
    out.append("")
    out.append("Расшифровка кодов в колонках «Функц.», «Натур.» и «Отметки»:")
    out.append("")
    seen: dict[str, str] = {}
    for planet in info.get("planets", []):
        for field_name in ("functional_beneficence", "natural_beneficence"):
            value = planet.get(field_name) or {}
            if value.get("code"):
                seen[value["code"]] = value.get("description", "")
        for mark in planet.get("position") or []:
            if mark.get("code"):
                seen[mark["code"]] = mark.get("description", "")
    out += _table(["Код", "Значение"], sorted(seen.items()))
    out.append("")

    if chart:
        out += ["### Дома D1: знак, состав, аспекты", ""]
        out += _table(
            ["Дом", "Знак", "Планеты", "Кто аспектирует"],
            [
                (
                    house["house"],
                    house["sign"]["name"],
                    ", ".join(p["code"] for p in house.get("planets", [])) or "—",
                    ", ".join(house.get("aspects", [])) or "—",
                )
                for house in chart.get("houses", [])
            ],
        )
        out.append("")
    for key, title in (
        ("show-info-D1-from-moon", "### D1, отсчёт от Луны"),
        ("show-info-D1-from-al", "### D1, отсчёт от Арудха Лагны"),
    ):
        block = data.get(key)
        if block:
            out += [title, ""]
            out += _table(
                ["Код", "Знак", "Дом", "Бинду"],
                [
                    (p.get("code"), (p.get("rasi") or {}).get("name"),
                     p.get("house"), (p.get("bindu") or {}).get("bav"))
                    for p in block.get("planets", [])
                ],
            )
            out.append("")
    return out


def _section_3_vargas(data: Collection) -> list[str]:
    out = ["## 3. Варги", ""]
    vargas = data.vargas_present
    if not vargas:
        return out + _absent("дробные карты")
    out += [
        "Знак в варге читается из карты (`show-chart`); в таблице планет сайта "
        "колонка «Раши» для варги остаётся натальной — это свойство сайта, не ошибка.",
        "",
    ]
    order = [v for v in ("D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10",
                         "D11", "D12", "D16", "D20", "D24", "D27", "D30", "D40",
                         "D45", "D60") if v in vargas]
    order += [v for v in vargas if v not in order]
    for varga in order:
        chart = data.get(f"show-chart-{varga}") or {}
        info = data.get(f"show-info-{varga}") or {}
        purpose = VARGA_PURPOSE.get(varga)
        out += [f"### {varga}" + (f" — {purpose}" if purpose else ""), ""]
        degrees = {p.get("code"): p.get("degrees") for p in info.get("planets", [])}
        bindu = {p.get("code"): (p.get("bindu") or {}).get("bav")
                 for p in info.get("planets", [])}
        bala = {p.get("code"): p.get("shad_bala") for p in info.get("planets", [])}
        out += _table(
            ["Код", "Знак", "Дом", "Градус", "Ретро", "Бинду", "Шадбала %"],
            [
                (p.get("code"), p.get("sign"), p.get("house"),
                 degrees.get(p.get("code")), _yes(p.get("retrograde")),
                 bindu.get(p.get("code")), bala.get(p.get("code")))
                for p in chart.get("planets", [])
            ],
        )
        out += ["", "Дома: " + "; ".join(
            f"{h['house']} {h['sign']['name']}"
            + (f" ({', '.join(p['code'] for p in h.get('planets', []))})"
               if h.get("planets") else "")
            for h in chart.get("houses", [])
        ), ""]
    return out


def _section_4_nakshatras(data: Collection) -> list[str]:
    info = data.get("show-info-D1")
    other = data.get("show-other-D1") or {}
    out = ["## 4. Накшатры", ""]
    if not info:
        return out + _absent("накшатры")
    out += _table(
        ["Код", "Накшатра", "Пада", "Управитель"],
        [
            (p.get("code"), (p.get("nakshatra") or {}).get("name"),
             (p.get("nakshatra") or {}).get("pada"), (p.get("nakshatra") or {}).get("lord"))
            for p in info.get("planets", []) if p.get("nakshatra")
        ],
    )
    out.append("")
    points = other.get("points") or {}
    special = {
        "drekkana_22": "22-я дреккана",
        "navamsa_64": "64-я навамша",
        "visha_navamsa": "Виша-навамша",
        "sarpa_drekkana": "Сарпа-дреккана",
        "badhaka": "Бадхака",
        "dagdha_rasi": "Дагдха-раши",
        "sahayogi": "Сахайоги",
    }
    rows = []
    for key, title in special.items():
        value = points.get(key)
        if value:
            raw = value.get("value")
            rows.append((title, "; ".join(raw) if isinstance(raw, list) else raw))
    if rows:
        out += _table(["Точка", "Значение"], rows) + [""]
    out += [
        "Гандантa, Мритью-бхага и Пушкара-навамша сайт помечает кодами прямо в "
        "таблице планет — см. колонку «Отметки» в разделе 2 и покрытие в разделе 13. "
        f"Абхукта-мула: `{UNAVAILABLE}`, источника нет.",
        "",
    ]
    return out


def _section_5_jaimini(data: Collection, derived: dict[str, Any]) -> list[str]:
    out = ["## 5. Джаймини: чара-караки", ""]
    karakas = (derived or {}).get("karakas") or {}
    if not karakas:
        return out + _absent("чара-караки")
    info = data.get("show-info-D1") or {}
    signs = {p.get("code"): (p.get("rasi") or {}).get("name") for p in info.get("planets", [])}
    houses = {p.get("code"): p.get("house") for p in info.get("planets", [])}
    degrees = karakas.get("degrees") or {}
    rows = []
    for title, planet in (karakas.get("computed") or {}).items():
        rows.append((title, planet, f"{degrees.get(planet, 0):.4f}°",
                     signs.get(planet), houses.get(planet),
                     karakas.get("reported", {}).get(title) or "—"))
    out += _table(
        ["Карака", "Планета [расчёт]", "Градус в знаке", "Знак", "Дом", "Показывает сайт"],
        rows,
    )
    out += [
        "",
        "Караки посчитаны по наибольшему градусу внутри знака, 7 планет, узлы не "
        "участвуют. Колонка «Показывает сайт» — для сверки; расхождения вынесены "
        "в раздел 20.",
        "",
    ]
    if karakas.get("near_ties"):
        out += [
            "**Близкие градусы, порядок карак чувствителен к округлению:** "
            + "; ".join(karakas["near_ties"]),
            "",
        ]
    other = data.get("show-other-D1") or {}
    for lagna in other.get("lagnas", []):
        if lagna.get("key") == "karakamsa_lagna":
            out += [f"Каракамша-лагна: {lagna.get('sign')} {lagna.get('degrees')}", ""]
    return out


def _section_6_arudhas(derived: dict[str, Any]) -> list[str]:
    out = ["## 6. Арудха-пады **[расчёт]**", ""]
    arudhas = (derived or {}).get("arudhas")
    if not arudhas:
        return out + _absent("арудхи")
    out += [
        "Сайт арудхи не отдаёт. Посчитаны здесь по классическому правилу: от дома "
        "к его управителю, затем столько же от управителя; пада, попавшая на сам дом "
        "или в 7-й от него, переносится в 10-й. Управитель знака берётся "
        "классический, узлы как со-управители не используются.",
        "",
    ]
    out += _table(
        ["Пада", "Дом", "Знак дома", "Управитель", "Знак управителя", "Отсчёт", "Знак пады", "Перенос"],
        [
            (a["name"], a["house"], sign_name(a["house_sign"]), a["lord"],
             sign_name(a["lord_sign"]), a["span"], sign_name(a["sign"]),
             f"с {sign_name(a['adjusted_from'])}" if a.get("adjusted_from") else "")
            for a in arudhas
        ],
    )
    out += [
        "",
        "«Второй Упапада» из Промпта 01 здесь не приводится: у термина нет "
        "однозначного определения, а гадать запрещено правилами разбора.",
        "",
    ]
    return out


def _section_7_lagnas(data: Collection) -> list[str]:
    other = data.get("show-other-D1")
    out = ["## 7. Специальные лагны, упаграхи и точки", ""]
    if not other:
        return out + _absent("вкладка «Разное»")
    out += ["### Специальные лагны и сфуты", ""]
    out += _table(
        ["Лагна", "Знак", "Градус", "Накшатра", "Пада"],
        [
            (l.get("name"), l.get("sign"), l.get("degrees"),
             (l.get("nakshatra") or {}).get("name"), (l.get("nakshatra") or {}).get("pada"))
            for l in other.get("lagnas", [])
        ],
    )
    out += ["", "### Упаграхи", ""]
    out += _table(
        ["Упаграха", "Знак", "Градус", "Дом", "Накшатра"],
        [
            (u.get("name"), u.get("sign"), u.get("degrees"), u.get("house"),
             (u.get("nakshatra") or {}).get("name"))
            for u in other.get("upagrahas", [])
        ],
    )
    out.append("")
    chakras = other.get("chakras") or []
    if chakras:
        out += ["### Чакры", ""]
        out += _table(
            ["№", "Чакра", "Стихия", "Знаки", "Планеты", "Занято"],
            [
                (c.get("number"), c.get("name"), c.get("element"),
                 ", ".join(c.get("signs") or []), ", ".join(c.get("planets") or []),
                 ", ".join(c.get("in_sign") or []))
                for c in chakras
            ],
        )
        out.append("")
    return out


def _section_8_bala(data: Collection) -> list[str]:
    out = ["## 8. Сила планет", ""]
    bala = data.get("show-bala-D1")
    if not bala:
        return out + _absent("Шад-бала")
    shad = bala.get("shad_bala") or {}
    rows = shad.get("planets") if isinstance(shad, dict) else shad
    if isinstance(rows, list) and rows:
        keys = [k for k in rows[0] if k != "code"]
        out += _table(["Код"] + keys, [[r.get("code")] + [_flat(r.get(k)) for k in keys]
                                       for r in rows])
    else:
        out += ["```json", _pretty(shad), "```"]
    out.append("")
    varga_bala = bala.get("varga_bala")
    if varga_bala:
        out += ["### Варга-бала (Вимшопака, Вайшешикамша)", "", "```json", _pretty(varga_bala), "```", ""]
    for varga in ("D9", "D10", "D60"):
        block = data.get(f"show-bala-{varga}")
        if block and block.get("shad_bala"):
            out += [f"### Шад-бала в {varga}", "", "```json", _pretty(block["shad_bala"]), "```", ""]
    return out


def _section_9_bhava(data: Collection, derived: dict[str, Any]) -> list[str]:
    out = ["## 9. Сила домов", ""]
    out += [
        "**Бхава-балы у сайта нет, и она здесь не реконструируется.** Вместо "
        "одного синтетического числа — три независимых показателя, каждый из "
        "которых прослеживается до конкретной цифры сайта. Они намеренно не "
        "складываются: сложение потребовало бы весов, которых методика не задаёт, "
        "и дало бы правдоподобное число, которое нечем проверить.",
        "",
    ]
    houses = (derived or {}).get("houses")
    if houses:
        out += _table(
            ["Дом", "Знак", "Планеты", "Бинду САВ", "Управитель",
             "Шадбала упр., %", "рупы", "Дришти: благ.", "неблаг.", "нетто"],
            [
                (h["house"], h["sign_name"], ", ".join(h["planets"]) or "—",
                 h["sav"], h["lord"], h["lord_shad_bala_percent"],
                 f"{h['lord_shad_bala_rupas']:.2f}" if h["lord_shad_bala_rupas"] else "",
                 f"{h['drishti_benefic']:.0f}", f"{h['drishti_malefic']:.0f}",
                 f"{h['drishti_net']:+.0f}")
                for h in houses
            ],
        )
        out += [
            "",
            "**Как читать.** «Бинду САВ» — сумма благоприятных точек, стоящих в "
            "доме. «Шадбала управителя» — классическая Бхавадхипати-бала, взятая "
            "как есть из раздела 8. «Дришти» — суммы вирупов из матрицы аспектов "
            "на дома, разнесённые по натуре аспектирующей планеты; это сырые "
            "числа сайта, а **не** Бхава-Дришти-бала: собственную дрик-балу "
            "планет сайт считает по другой формуле, воспроизвести её из этой "
            "матрицы не удалось.",
            "",
            "Дом силён, когда на него указывают все три показателя сразу. "
            "Расхождение между ними — тоже результат, и его надо назвать.",
            "",
        ]
        stray = sum(h.get("drishti_unclassified") or 0 for h in houses)
        if stray:
            out += [
                "",
                f"⚠️ **{stray:.0f} вирупов дришти не разнесены**: сайт не дал "
                "натуру аспектирующей планеты. Эти вирупы не попали ни в "
                "«благ.», ни в «неблаг.» — отнести их к вредителям молча значило "
                "бы сдвинуть нетто всех домов вниз на невидимую величину.",
            ]

    else:
        out += _absent("сводка по домам")

    out += ["### Геометрия бхава-чалиты", ""]
    bhava = data.get("show-bhava-D1")
    if not bhava:
        return out + _absent("бхава-чалита")
    out += _table(
        ["Дом", "Куспид", "Начало", "Конец", "Размер", "Планеты"],
        [
            (h.get("house"),
             f"{(h.get('cusp') or {}).get('sign')} {(h.get('cusp') or {}).get('degrees')}",
             f"{(h.get('start') or {}).get('sign')} {(h.get('start') or {}).get('degrees')}",
             f"{(h.get('end') or {}).get('sign')} {(h.get('end') or {}).get('degrees')}",
             h.get("size"), ", ".join(h.get("planets") or []) or "—")
            for h in bhava.get("houses", [])
        ],
    )
    out.append("")
    return out


def _section_10_ashtakavarga(data: Collection) -> list[str]:
    info = data.get("show-info-D1")
    out = ["## 10. Аштакаварга", ""]
    ashtaka = (info or {}).get("ashtakavarga")
    if not ashtaka:
        return out + _absent("аштакаварга")
    # Bindus are given by HOUSE, not by sign: the parser reads them off the
    # chart drawing in house order. Labelling the columns with signs would be
    # right only for an Aries Ascendant and silently wrong for every other.
    first = ashtaka.get("first_house_sign") or 1
    headers = [f"{house} ({sign_name(first + house - 1)})" for house in range(1, 13)]
    out += _table(["Ряд / дом"] + headers,
                  [["САВ"] + list(ashtaka.get("sav") or [])]
                  + [[code] + list(values) for code, values in (ashtaka.get("bav") or {}).items()])
    out += [
        "",
        f"Колонки — **дома** 1…12, в скобках знак каждого дома; в первом доме "
        f"знак №{first}. САВ — сумма семи планетных БАВ; БАВ Асцендента в сумму "
        "не входит.",
        "",
        f"Трикона-шодхана, Экадхипатья-шодхана, Шодхья-пинда, Раши-пинда, "
        f"Граха-пинда, Какшья и Прастара: `{UNAVAILABLE}` — сайт их не выводит.",
        "",
    ]
    return out


def _section_11_yogas(data: Collection) -> list[str]:
    out = ["## 11. Йоги", ""]
    found = False
    for varga in ("D1", "D9", "D10", "D60"):
        block = data.get(f"show-yogas-{varga}")
        if not block:
            continue
        found = True
        yogas = block.get("yogas") or []
        out += [f"### {varga} — найдено {len(yogas)}", ""]
        out += _table(
            ["Йога", "Категория", "Планеты", "Эффект", "Условие"],
            [
                (y.get("name"), y.get("category_label") or y.get("category"),
                 "все" if y.get("all_planets") else ", ".join(y.get("planets") or []),
                 y.get("effect"), y.get("condition"))
                for y in yogas
            ],
        )
        out.append("")
    if not found:
        return out + _absent("йоги")
    out += [f"> {YOGA_WARNING}", ""]
    return out


def _section_12_avasthas(data: Collection) -> list[str]:
    out = ["## 12. Авастхи", ""]
    block = data.get("show-avasthas-D1")
    if not block:
        return out + _absent("авастхи")
    rows = []
    for planet in block.get("planets", []):
        deeptadi = "; ".join(
            f"{d.get('state')} ({d.get('reason')})" for d in planet.get("deeptadi") or []
        )
        rows.append((
            planet.get("code"),
            f"{(planet.get('baladi') or {}).get('state')} "
            f"{(planet.get('baladi') or {}).get('strength_percent')}%",
            f"{(planet.get('jagradadi') or {}).get('state')} "
            f"{(planet.get('jagradadi') or {}).get('strength_percent')}%",
            (planet.get("shayanadi") or {}).get("state"),
            deeptadi,
        ))
    out += _table(["Код", "Баляди", "Джаградади", "Шаянади", "Диптади"], rows)
    out += [
        "",
        "Сила по шаянади зависит от первого слога имени; группы букв — в "
        "`raw/show-avasthas-D1.json`, здесь не развёрнуты.",
        "",
    ]
    return out


def _section_13_states(data: Collection, derived: dict[str, Any]) -> list[str]:
    info = data.get("show-info-D1")
    out = ["## 13. Специальные состояния", ""]
    if not info:
        return out + _absent("специальные состояния")
    rows = []
    for planet in info.get("planets", []):
        marks = [m.get("code") for m in planet.get("position") or []]
        war = planet.get("planetary_war")
        flags = []
        if planet.get("retrograde"):
            flags.append("ретро")
        if _dignity(planet):
            flags.append(_dignity(planet))
        if war:
            flags.append(f"граха-юддха: {war}")
        if marks:
            flags.append(", ".join(marks))
        if flags:
            rows.append((planet.get("code"), "; ".join(flags)))
    out += _table(["Код", "Состояния"], rows)
    out += ["", "### Покрытие списка Промпта 01 §13", ""]
    out += _table(
        ["Показатель", "Источник", "В этой карте"],
        _state_coverage(info),
    )
    out += [
        "",
        "«Не встретилось» — состояния в этой карте нет; это не пробел в данных. "
        "«Источника нет» — сайт такого показателя не даёт вовсе.",
        "",
    ]
    exchanges = [d for d in (derived or {}).get("dispositors", []) if d.get("exchange")]
    if exchanges:
        out += ["**Паривартана (обмен знаками) [расчёт]:** " + "; ".join(
            f"{d['planet']} ↔ {d['exchange']}" for d in exchanges), ""]
    own = [d["planet"] for d in (derived or {}).get("dispositors", []) if d.get("own_sign")]
    if own:
        out += ["**В своём знаке [расчёт]:** " + ", ".join(own), ""]
    out += ["### Диспозиторы **[расчёт]**", ""]
    out += _table(
        ["Планета", "Знак", "Диспозитор", "Знак диспозитора"],
        [
            (d["planet"], sign_name(d["sign"]), d["lord"], sign_name(d["lord_sign"]))
            for d in (derived or {}).get("dispositors", [])
        ],
    )
    return out


def _state_coverage(info: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Which of Prompt 01 §13's states this chart actually shows."""
    holders: dict[str, list[str]] = {}
    for planet in info.get("planets", []):
        for mark in planet.get("position") or []:
            holders.setdefault(mark.get("code", ""), []).append(planet.get("code", ""))
        if planet.get("planetary_war"):
            holders.setdefault("war", []).append(planet.get("code", ""))
        if planet.get("retrograde"):
            holders.setdefault("retrograde", []).append(planet.get("code", ""))
        if _dignity(planet) in ("Exaltation", "Debilitation", "Own sign", "Moolatrikona"):
            holders.setdefault("dignity", []).append(planet.get("code", ""))

    rows: list[tuple[str, str, str]] = []
    for title, source, note in SPECIAL_STATE_SOURCES:
        kind, _, argument = source.partition(":")
        if kind == "code":
            found: list[str] = []
            for code in argument.split(","):
                found += holders.get(code, [])
            where = f"коды {argument}"
            present = ", ".join(dict.fromkeys(found)) if found else "не встретилось"
        elif kind in ("war", "retrograde", "dignity"):
            found = holders.get(kind, [])
            where = note
            present = ", ".join(dict.fromkeys(found)) if found else "не встретилось"
        elif kind == "none":
            where = "источника нет"
            present = "—"
        else:
            where = note
            present = "см. раздел"
        rows.append((title, where, present))
    return rows


def _section_14_dashas(data: Collection) -> list[str]:
    out = ["## 14. Даши", ""]
    labels = {
        "show-dasha-vimshottari-1": "Вимшоттари, махадаши",
        "show-dasha-vimshottari-2": "Вимшоттари, антардаши",
        "show-dasha-vimshottari-3-current": "Вимшоттари, пратьянтардаши (текущий отрезок)",
        "show-dasha-vimshottari-4-current": "Вимшоттари, сукшма (текущий отрезок)",
        "show-dasha-ashtottari-2": "Аштоттари",
        "show-dasha-yogini-2": "Йогини",
        "show-dasha-chara_rao-2": "Чара (Рао)",
        "show-dasha-narayana-2": "Нараяна",
        "show-dasha-navamsa-2": "Навамша-даша",
    }
    any_found = False
    for key, title in labels.items():
        block = data.get(key)
        if not block:
            continue
        any_found = True
        periods = block.get("periods") or []
        out += [f"### {title} — {len(periods)} периодов", ""]
        out += _table(
            ["Период", "Начало", "Конец", "Возраст"],
            [
                (" – ".join(p.get("labels") or p.get("lords") or []),
                 p.get("start"), p.get("end"), p.get("age"))
                for p in periods
            ],
        )
        out.append("")
    if not any_found:
        return out + _absent("даши")
    out += [
        "Границы приходят с точностью до минуты; на стыках махадаш стороны иногда "
        "округляются по-разному, точного равенства «конец = начало» нет.",
        "",
        f"Калачакра-даша: `{UNAVAILABLE}` — сайт её не считает.",
        "",
    ]
    return out


def _section_15_varshaphala() -> list[str]:
    return [
        "## 15. Варшапхала",
        "",
        f"`{PAID}` — годовые карты, Мунтха, Сахамы, Таджака-йоги и Мудда-даша "
        "закрыты платным доступом (сайт отвечает 403).",
        "",
    ]


def _section_16_transits(data: Collection) -> list[str]:
    out = ["## 16. Транзиты", ""]
    out += [
        f"Таблица транзитов: `{PAID}` — вкладка закрыта платным доступом.",
        "",
    ]
    sade = data.get("show-sade-sati")
    if not sade:
        return out + _absent("Саде-Сати")
    out += ["### Саде-Сати", ""]
    for method in sade.get("methods", []):
        out += [f"**{method.get('title')}**", ""]
        out += _table(
            ["Период", "Начало", "Конец", "Фазы"],
            [
                (p.get("title"), p.get("start"), p.get("end"),
                 "; ".join(f"{s.get('description')} [{s.get('start')} – {s.get('end')}]"
                           for s in p.get("segments") or []))
                for p in method.get("periods") or []
            ],
        )
        out.append("")
    return out


def _section_17_aspects(data: Collection) -> list[str]:
    out = ["## 17. Аспекты, раши-дришти и аргала", ""]
    aspects = [(sign, data.get(f"get-aspects-{sign}-D1")) for sign in range(1, 13)]
    if any(block for _, block in aspects):
        out += ["### Раши-дришти и планетные аспекты на знак", ""]
        out += _table(
            ["Знак", "Планеты аспектируют знак", "Знак аспектирует знаки"],
            [
                (sign_name(sign),
                 ", ".join(block.get("planets") or []) or "—",
                 ", ".join(sign_name(s) for s in block.get("signs") or []) or "—")
                for sign, block in aspects if block
            ],
        )
        out.append("")
    argala = [(sign, data.get(f"get-argala-{sign}")) for sign in range(1, 13)]
    if any(block for _, block in argala):
        out += ["### Аргала и виродха-аргала", ""]
        out += _table(
            ["Знак", "Аргала", "Виродха", "Особая"],
            [
                (sign_name(sign),
                 ", ".join(sign_name(s) for s in block.get("argala") or []) or "—",
                 ", ".join(sign_name(s) for s in block.get("virodha") or []) or "—",
                 ", ".join(sign_name(s) for s in block.get("special") or []) or "—")
                for sign, block in argala if block
            ],
        )
        out += ["", f"> {ARGALA_WARNING}", ""]
    if not any(block for _, block in aspects) and not any(block for _, block in argala):
        out += _absent("аспекты и аргала")
    return out


def _section_18_panchanga(data: Collection) -> list[str]:
    other = data.get("show-other-D1")
    out = ["## 18. Панчанга рождения", ""]
    if not other or not other.get("panchanga"):
        return out + _absent("панчанга")
    out += _table(
        ["Элемент", "Значение", "Управитель"],
        [
            (value.get("label") or key, value.get("value"), value.get("lord") or "—")
            for key, value in (other.get("panchanga") or {}).items()
        ],
    )
    out.append("")
    return out


def _section_20_quality(client: Client, data: Collection, derived: dict[str, Any]) -> list[str]:
    out = ["## 20. Контроль качества этапа", ""]
    identical = {
        "дата": client.chart.date, "время": client.chart.time,
        "пояс": client.chart.timezone,
        "координаты": f"{client.chart.latitude} / {client.chart.longitude}",
    }
    out += [
        "Все блоки запрошены одним набором параметров, расхождение исходных данных "
        "между блоками технически невозможно: " +
        ", ".join(f"{k} {v}" for k, v in identical.items()) + ".",
        "",
    ]
    mismatches = ((derived or {}).get("karakas") or {}).get("mismatches") or []
    if mismatches:
        for text in mismatches:
            title, _, detail = text.partition(": ")
            out += [
                "```",
                "РАСХОЖДЕНИЕ",
                f"Показатель: чара-карака {title}",
                f"Значение VedicHoro: {detail.split('сайт показывает ')[-1]}",
                f"Значение контрольного материала: "
                f"{detail.split('даёт ')[-1].split(',')[0]} (расчёт по наибольшему градусу)",
                "Возможная причина: сайт может использовать 8-караковую систему "
                "или иной порядок отсчёта градуса для узлов.",
                "```",
                "",
            ]
    else:
        out += [
            "Чара-караки, посчитанные по наибольшему градусу, совпали с тем, что "
            "показывает сайт. Расхождений не обнаружено.",
            "",
        ]
    if data.gaps:
        out += [f"Незакрытых блоков: {len(data.gaps)} — перечислены в `01_MISSING_DATA.md`.", ""]
    return out


def _flat(value: Any) -> str:
    if isinstance(value, dict):
        return " / ".join(f"{k}: {v}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return "" if value is None else str(value)


def _pretty(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# MISSING_DATA.md
# ---------------------------------------------------------------------------


def _missing_data(client: Client, data: Collection) -> list[str]:
    out = [
        f"# {client.slug} — чего нет и почему (Промпт 01)",
        "",
        "Маркеры — дословно те, что предписывает Промпт 01. Отсутствие данных "
        "фиксируется, а не компенсируется догадкой.",
        "",
    ]

    if data.gaps:
        out += ["## Не получено при сборе", ""]
        out += _table(
            ["Блок", "Маркер", "Что теряется", "Причина"],
            [(g.key, f"`{g.marker}`", g.section or "—", g.reason) for g in data.gaps],
        )
        out.append("")

    out += ["## Закрыто платным доступом", ""]
    out += _table(
        ["Раздел Промпта 01", "Маркер", "Комментарий"],
        [
            ("§15 Варшапхала", f"`{PAID}`", "годовые карты, Мунтха, Сахамы, Мудда-даша"),
            ("§16 Транзиты", f"`{PAID}`", "таблица транзитов; Саде-Сати доступна и собрана"),
        ],
    )
    out.append("")

    out += ["## Сайт не считает вовсе", ""]
    out += _table(
        ["Показатель", "Раздел", "Комментарий"],
        [
            ("Бхава-бала", "§9", "есть только геометрия домов и дрик-бала на дома в §8"),
            ("Производные аштакаварги", "§10",
             "шодханы, пинды, какшья, прастара — считаются из БАВ, пока не реализовано"),
            ("Калачакра-даша", "§14", "система на сайте отсутствует"),
            ("Абхукта-мула", "§4", "источника нет"),
            ("Кендрадхипати-доша, Нича-бханга, сожжение", "§13",
             "сайт отдельно не помечает; выводятся правилами, пока не реализованы"),
            ("Арудхи A1–A12, UL", "§6",
             "сайт не отдаёт — считаются здесь, см. следующую таблицу"),
        ],
    )
    out += [
        "",
        "Гандантa, Мритью-бхага, Пушкара-навамша, Марана-карака-стхана, "
        "Карака-бхава-нашая, Варготтама и Сандхи **доступны** — сайт помечает их "
        "кодами в таблице планет. Полное покрытие списка §13 — в разделе 13 "
        "экспорта.",
    ]
    out.append("")

    out += ["## Считается здесь, а не берётся с сайта", ""]
    out += _table(
        ["Показатель", "Раздел", "Статус"],
        [
            ("Арудха-пады A1–A12, AL, UL, Дара-пада", "§6", "**[расчёт]**, классическое правило"),
            ("Чара-караки", "§5", "**[расчёт]** по градусам, сверены с сайтом"),
            ("Диспозиторы и паривартана", "§13", "**[расчёт]**"),
            ("«Второй Упапада»", "§6", f"`{UNAVAILABLE}` — термин не имеет однозначного определения"),
        ],
    )
    out.append("")

    if not client.biography_md.exists():
        out += [
            "## От человека",
            "",
            f"`{NOT_SUPPLIED}` — биографии нет (`biography.md` отсутствует). "
            "Гейт Промпта 03 закрыт: без неё все паттерны получают статус "
            "«не проверено биографией», а соответствие биографии числом не выставляется.",
            "",
        ]
    if not client.birth_time.confirmed:
        out += [
            "## Время рождения",
            "",
            f"Статус: {client.birth_time.label}. Промпт 07 (путь души) не "
            "выполняется, выводы по D60 недопустимы. Чтобы открыть их, нужно "
            "документальное подтверждение или профессиональная ректификация.",
            "",
        ]
    return out


# ---------------------------------------------------------------------------
# Summary for the next stage
# ---------------------------------------------------------------------------


def summarise(client: Client, data: Collection) -> list[str]:
    """The handover Prompt 01 ends with, generated instead of retyped."""
    info = data.get("show-info-D1") or {}
    planets = info.get("planets", [])
    ascendant = next((p for p in planets if p.get("code") == "As"), None)
    derived = _derive(data)
    karakas = (derived or {}).get("karakas") or {}

    strengths = sorted(
        ((p.get("code"), p.get("shad_bala")) for p in planets
         if p.get("code") != "As" and p.get("shad_bala") is not None),
        key=lambda item: item[1], reverse=True,
    )

    present = data.vargas_present
    absent = [v for v in client.collect.vargas if v not in present]

    out = [
        "# Сводка этапа 01",
        "",
        f"**Статус времени рождения:** {client.birth_time.label}. "
        + ("Промпт 07 и D60 допустимы."
           if client.birth_time.confirmed
           else "**Промпт 07 не выполняется, выводы по D60 недопустимы.**"),
        "",
    ]
    if ascendant:
        rasi = ascendant.get("rasi") or {}
        nakshatra = ascendant.get("nakshatra") or {}
        out += [
            f"**Лагна:** {rasi.get('name')} {ascendant.get('degrees')}"
            + (f", накшатра {nakshatra.get('name')} пада {nakshatra.get('pada')}"
               if nakshatra else ""),
            "",
        ]
    if karakas.get("computed"):
        atma = karakas["computed"].get("AK")
        agrees = not karakas.get("mismatches")
        out += [
            f"**Атмакарака:** {atma} (по наибольшему градусу; "
            + ("сайт подтверждает" if agrees else "**сайт показывает другое, см. раздел 20**")
            + ").",
            "",
        ]
    if strengths:
        # Prompt 01 asks for 3–5 of each; with seven planets the two lists must
        # not overlap, or the same planet reads as both strong and weak.
        size = max(1, min(5, len(strengths) // 2))
        top = ", ".join(f"{code} {value}%" for code, value in strengths[:size])
        bottom = ", ".join(f"{code} {value}%" for code, value in strengths[-size:])
        out += [
            f"**Сильнейшие по Шадбале:** {top}.",
            f"**Слабейшие по Шадбале:** {bottom}.",
            "",
        ]
    out += [
        f"**Варги получены ({len(present)}):** {', '.join(present) or '—'}.",
        "",
    ]
    if absent:
        purposes = ", ".join(
            f"{v} ({VARGA_PURPOSE[v]})" if v in VARGA_PURPOSE else v for v in absent
        )
        out += [f"**Варги не получены:** {purposes}.", ""]
    out += [
        "**Недоступные блоки:** варшапхала и транзиты — платный доступ; "
        "бхава-бала, производные аштакаварги и Калачакра — сайт их не считает. "
        "Подробно в `01_MISSING_DATA.md`.",
        "",
    ]
    if not client.biography_md.exists():
        out += [
            "**Биографии нет.** Гейт Промпта 03 закрыт: этап 02 выполняется "
            "вслепую, как и задумано, но этап 03 нельзя пропустить.",
            "",
        ]
    return out
