"""Shared, folded role aliases for decision obstacles and their resolution."""

import re
from enum import StrEnum


# Keep each person in one role. Generic relatives can open an obstacle but cannot
# resolve a specific spouse's obstacle without identifying that spouse.
ROLE_ALIASES = {
    "husband": ("chong", "ong xa", "anh nha", "ba be", "nha toi"),
    "wife": ("vo", "ba xa", "me be", "ba nha"),
    "parents": ("bo me", "ba me", "bo", "ba", "me"),
    "partner": ("nguoi yeu",),
    "friends": ("ban be", "ban than"),
    "unspecified": ("anh ay", "chi ay", "nguoi nha", "gia dinh"),
}


def _alias_pattern(aliases: tuple[str, ...]) -> str:
    return "(?:" + "|".join(re.escape(alias).replace(r"\ ", r"\s+")
                         for alias in sorted(aliases, key=len, reverse=True)) + ")"


_ROLE_BY_ALIAS = {alias: role for role, aliases in ROLE_ALIASES.items()
                  for alias in aliases}
PERSON_PATTERN = _alias_pattern(tuple(_ROLE_BY_ALIAS))
PERSON_RE = re.compile(r"\b" + PERSON_PATTERN + r"\b")


def person_mentions(folded_text: str):
    """Yield nonoverlapping (role, match) pairs, longest aliases first."""
    for match in PERSON_RE.finditer(folded_text):
        yield _ROLE_BY_ALIAS[re.sub(r"\s+", " ", match.group())], match


def roles_mentioned(folded_text: str) -> set[str]:
    """Find roles in already accent-folded text, never infer a spouse from kinship."""
    return {role for role, _ in person_mentions(folded_text)}


class BlockerResolutionReason(StrEnum):
    DECISION_MAKER_APPROVED = "decision_maker_approved"
    DIFFERENT_DECISION_MAKER = "different_decision_maker"
    APPROVAL_NEGATED = "approval_negated"
    HYPOTHETICAL_CONTEXT = "hypothetical_context"
    QUESTION_CONTEXT = "question_context"
    TENTATIVE_APPROVAL = "tentative_approval"
    UNCERTAIN_APPROVAL = "uncertain_approval"
    PRICE_ACCEPTED = "price_accepted"
    NO_RESOLUTION_EVIDENCE = "no_resolution_evidence"
    NO_PRIOR_BLOCKER = "no_prior_blocker"
