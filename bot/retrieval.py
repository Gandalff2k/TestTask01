from collections import defaultdict
from dataclasses import dataclass

from bot.mittens import ALL_MITTENS, GROUPS, MITTENS, describe_scope
from bot.storage import Document


@dataclass(frozen=True)
class Target:
    label: str
    scope: frozenset[str]
    everywhere: bool = False

    @property
    def is_forest(self) -> bool:
        return self.scope == ALL_MITTENS and not self.everywhere

    @property
    def is_mitten(self) -> bool:
        return len(self.scope) == 1


FOREST_TARGET = Target("весь ліс", ALL_MITTENS)
EVERYWHERE_TARGET = Target("усі рукавички", ALL_MITTENS, everywhere=True)


def mitten_target(mitten: str) -> Target:
    return Target(mitten, frozenset({mitten}))


def group_target(group: str) -> Target:
    return Target(group, GROUPS[group])


def docs_for(target: Target, docs: list[Document]) -> list[Document]:
    if target.everywhere:
        return list(docs)
    if target.is_mitten:
        (mitten,) = target.scope
        return [d for d in docs if mitten in d.scope]
    return [d for d in docs if d.scope >= target.scope]


def catalog(docs: list[Document]) -> dict[str, str]:
    scopes_by_type: dict[str, set[frozenset[str]]] = defaultdict(set)
    for doc in docs:
        scopes_by_type[doc.doc_type].add(doc.scope)
    result = {}
    for doc_type, scopes in sorted(scopes_by_type.items()):
        per_mitten = {s for s in scopes if len(s) == 1}
        other = [describe_scope(s) for s in scopes if len(s) != 1]
        parts = []
        if len(per_mitten) == len(MITTENS):
            parts.append("окремий для кожної рукавички")
        elif per_mitten:
            parts.extend(describe_scope(s) for s in per_mitten)
        parts.extend(sorted(other))
        result[doc_type] = ", ".join(parts)
    return result


def select(target: Target, doc_types: list[str], docs: list[Document]) -> list[Document]:
    candidates = docs_for(target, docs)
    if target.everywhere:
        return [d for t in doc_types for d in candidates if d.doc_type == t]
    wanted = set(doc_types)
    if target.is_mitten:
        return [d for d in candidates if d.doc_type in wanted or d.scope == target.scope]
    return [d for d in candidates if d.doc_type in wanted]


def has_local_versions(doc_types: list[str], docs: list[Document]) -> bool:
    wanted = set(doc_types)
    return any(d.doc_type in wanted and not d.is_forest_wide for d in docs)
