"""User settings: plain data plus load/save through the Store."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import Store


@dataclass
class Settings:
    # Suggestions
    max_suggestions: int = 4
    min_prefix_len: int = 1
    # Shorter words are still learned (they give bigram context) but are not
    # offered: completing "да" saves nothing and wastes a slot.
    min_suggest_len: int = 3
    predict_next_word: bool = False

    # Learning and ranking
    min_word_len: int = 2
    half_life_days: float = 30.0
    bigram_weight: float = 5.0

    # Uzbek Cyrillic <-> Latin: offer words learned in the other script
    cross_script: bool = False
    cross_script_penalty: float = 0.5

    # Suggestion window: shift from the automatic position, in screen pixels
    overlay_offset_x: int = 0
    overlay_offset_y: int = 0
    theme: str = "system"           # "system" | "dark" | "light"

    # Technical
    log_level: str = "INFO"

    @classmethod
    def load(cls, store: "Store") -> "Settings":
        settings = cls()
        stored = store.all_settings()
        for f in fields(cls):
            if f.name not in stored:
                continue
            value = stored[f.name]
            default = getattr(settings, f.name)
            if isinstance(default, bool):
                ok = isinstance(value, bool)
            elif isinstance(default, (int, float)):
                ok = isinstance(value, (int, float)) and not isinstance(value, bool)
                if ok:
                    value = type(default)(value)
            else:
                ok = isinstance(value, type(default))
            if ok:
                setattr(settings, f.name, value)
        return settings

    def save(self, store: "Store") -> None:
        with store.bulk():
            for f in fields(self):
                store.set_setting(f.name, getattr(self, f.name))
