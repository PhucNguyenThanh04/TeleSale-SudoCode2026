
import re


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
    for match in PERSON_RE.finditer(folded_text):
        yield _ROLE_BY_ALIAS[re.sub(r"\s+", " ", match.group())], match


def roles_mentioned(folded_text: str) -> set[str]:
    return {role for role, _ in person_mentions(folded_text)}
