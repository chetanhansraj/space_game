"""voice -- the only place the world speaks.

CLAUDE.md: "The only place LLM calls exist. Takes structured event data,
returns text. If this service is down, the game must keep running perfectly
with placeholder text."

v1 has no language model at all. Every letter and every line of the feed is a
template filled from structured facts, chosen deterministically. That is not a
stopgap to apologise for: it is the fallback the invariant demands, built
first, so that the day a model is added it can only ever make the words
better and never make the game depend on it.

Nothing in here can change a number. It reads facts that `sim` already
committed and returns strings.
"""

from .characters import CHARACTERS, Character, speaker
from .letters import render_event, render_letter

__all__ = ["CHARACTERS", "Character", "speaker", "render_event",
           "render_letter"]
