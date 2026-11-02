"""Turn a transcribed narration into a plan location and an item.

Staff say locations in spoken form ("aisle one bay area two", "shelf A1 B2"); plan locations are codes like "A1-B2".
Only numbers that follow a location word ("aisle", "bay", "shelf") or a code like "B2" count, so item counts said
later ("four monitors") are never mistaken for a location.
"""
import difflib
import re

_NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
)}
# Position in a plan code: 0 is the aisle ("A1"), 1 is the shelf or bay ("B2").
_WORD_SLOT = {"aisle": 0, "bay": 1, "shelf": 1, "rack": 1, "bin": 1}
_LETTER_SLOT = {"a": 0, "b": 1}
_FILLER = {"area", "number", "no", "is", "at", "in"}


def _number(token: str) -> int | None:
    if token in _NUMBER_WORDS:
        return _NUMBER_WORDS[token]
    return int(token) if token.isdigit() else None


def spoken_location(text: str) -> dict[int, int]:
    """The aisle (slot 0) and shelf (slot 1) numbers said in the narration; a slot not said is absent."""
    said: dict[int, int] = {}
    pending: int | None = None
    in_location = False  # inside "shelf A1 B2": a letter on its own followed by a number is then a tag too
    skip = False
    tokens = re.findall(r"[a-z]+\d*|\d+", text.lower())
    for i, token in enumerate(tokens):
        if skip:
            skip = False
            continue
        following = tokens[i + 1] if i + 1 < len(tokens) else ""
        tagged = re.fullmatch(r"([ab])(\d+)", token)
        if tagged:  # "A1", "B2": the letter says which slot
            said.setdefault(_LETTER_SLOT[tagged.group(1)], int(tagged.group(2)))
            pending, in_location = None, True
        elif in_location and token in _LETTER_SLOT and _number(following) is not None:
            # On long recordings the transcript sometimes spaces the letter from its number: "A 1 B 4".
            said.setdefault(_LETTER_SLOT[token], _number(following))
            pending, skip = None, True
        elif token in _WORD_SLOT:
            pending, in_location = _WORD_SLOT[token], True
        elif pending is not None and _number(token) is not None:
            said.setdefault(pending, _number(token))
            pending = None
        elif token not in _FILLER:
            pending, in_location = None, False
    return said


def resolve_location(transcript: str, locations: list[str]) -> str | None:
    """The one plan location that agrees with every part said, or None if nothing matches or several do.

    "shelf B1" alone is ambiguous when both A3-B1 and A4-B1 exist, so it resolves to None rather than a guess.
    """
    said = spoken_location(transcript)
    if not said:
        return None
    matches = []
    for loc in locations:
        parts = [int(d) for d in re.findall(r"\d+", loc)]
        if all(slot < len(parts) and parts[slot] == n for slot, n in said.items()):
            matches.append(loc)
    return matches[0] if len(matches) == 1 else None


def mentioned_items(transcript: str, items: list[str]) -> list[str]:
    """Items whose every word is in the narration (allowing a near-miss spelling), best match first."""
    spoken = re.findall(r"[a-z0-9]+", transcript.lower())

    def hit(word: str) -> bool:
        return word in spoken or bool(difflib.get_close_matches(word, spoken, n=1, cutoff=0.85))

    scored = []
    for item in items:
        words = re.findall(r"[a-z0-9]+", item.lower())
        if words and all(hit(w) for w in words):
            scored.append((len(words), item))
    return [item for _, item in sorted(scored, reverse=True)]


def resolve_item(transcript: str, items: list[str]) -> str | None:
    """The one item named. If the narration names two unrelated items, None (a mixed clip)."""
    found = mentioned_items(transcript, items)
    # "TV unit" and "TV stand" both contain "tv"; a longer exact match wins over a prefix of it.
    found = [i for i in found if not any(i != o and i.lower() in o.lower() for o in found)]
    return found[0] if len(found) == 1 else None
