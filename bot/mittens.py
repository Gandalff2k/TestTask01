import re

MITTENS: tuple[str, ...] = (
    "Під ялиною",
    "У соснах",
    "Біля мурашника",
    "Під дубом",
    "У ліщині",
    "Під вербою",
    "Біля бобрової греблі",
    "На узліссі",
)

ALL_MITTENS: frozenset[str] = frozenset(MITTENS)

GROUPS: dict[str, frozenset[str]] = {
    "хвойний ліс": frozenset({"Під ялиною", "У соснах", "Біля мурашника"}),
    "листяний ліс": frozenset({"Під дубом", "У ліщині", "Під вербою"}),
    "біля річки": frozenset({"Під вербою", "Біля бобрової греблі"}),
}

FOREST = "весь ліс"

_GROUP_STEMS: dict[str, tuple[str, ...]] = {
    "хвойний ліс": ("хвойн",),
    "листяний ліс": ("листян",),
    "біля річки": ("річк",),
}


def mitten_by_name(name: str) -> str | None:
    cleaned = name.strip().strip("«»\"'").casefold()
    for mitten in MITTENS:
        if mitten.casefold() == cleaned:
            return mitten
    return None


def scope_from_labels(labels: list[str]) -> frozenset[str]:
    scope: set[str] = set()
    for label in labels:
        key = label.strip().casefold()
        if key == FOREST:
            return ALL_MITTENS
        if key in GROUPS:
            scope |= GROUPS[key]
            continue
        mitten = mitten_by_name(label)
        if mitten:
            scope.add(mitten)
    return frozenset(scope)


def scope_from_title(title: str) -> frozenset[str] | None:
    lowered = title.casefold()
    mittens = {m for m in MITTENS if m.casefold() in lowered}
    if mittens:
        return frozenset(mittens)
    scope: set[str] = set()
    for group, stems in _GROUP_STEMS.items():
        if any(stem in lowered for stem in stems):
            scope |= GROUPS[group]
    return frozenset(scope) or None


_FOREST_PHRASES = ("всіх мешканців лісу", "усіх мешканців лісу", "для всього лісу")


def scope_from_intro(text: str) -> frozenset[str] | None:
    intro = text[:600]
    for sentence in re.split(r"(?<=[.!?])\s+", intro):
        lowered = sentence.casefold()
        if "мешканц" not in lowered:
            continue
        if any(phrase in lowered for phrase in _FOREST_PHRASES):
            return ALL_MITTENS
        return scope_from_title(sentence)
    return None


_SCOPE_PHRASES = re.compile(
    r"\b(?:в|у|біля)?\s*(?:хвойн\w*|листян\w*)\s+ліс\w*|\bбіля\s+річки\b",
    re.IGNORECASE,
)


def doc_type_from_title(title: str) -> str:
    name = re.sub(r"\.(pdf|docx|txt)$", "", title.strip(), flags=re.IGNORECASE).casefold()
    for mitten in MITTENS:
        name = name.replace(mitten.casefold(), " ")
    name = _SCOPE_PHRASES.sub(" ", name)
    name = re.sub(r"[«»\"'()\[\],.:;!?—–-]", " ", name)
    return " ".join(name.split())


_GROUP_CUES: dict[str, re.Pattern] = {
    "хвойний ліс": re.compile(r"хвойн|\b(?:під|серед|між|біля)\s+(?:ялинами|ялин|соснами|сосен|сосон)\b", re.I),
    "листяний ліс": re.compile(r"листян|\b(?:під|серед|між|біля)\s+(?:дубами|дубів|грабами|березами|беріз)\b", re.I),
    "біля річки": re.compile(r"річк|\bбіля\s+води\b", re.I),
}


def verify_scope(scope: frozenset[str], text: str) -> frozenset[str]:
    if not scope or scope == ALL_MITTENS:
        return scope
    lowered = text.casefold()
    keep = {m for m in scope if m.casefold() in lowered}
    for group, members in GROUPS.items():
        if members <= scope and _GROUP_CUES[group].search(text):
            keep |= members
    if keep:
        return frozenset(keep)
    cued: set[str] = set()
    for group, cue in _GROUP_CUES.items():
        if cue.search(text):
            cued |= GROUPS[group]
    return frozenset(cued)


def describe_scope(scope: frozenset[str]) -> str:
    if scope == ALL_MITTENS:
        return FOREST
    for group, members in GROUPS.items():
        if scope == members:
            return group
    return ", ".join(m for m in MITTENS if m in scope)


def ordered(scope: frozenset[str]) -> list[str]:
    return [m for m in MITTENS if m in scope]
