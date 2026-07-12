"""Lift of dnd5e_combat/dice.py, unchanged. `Resolver` wraps whatever `Dice`
instance it's given — in this engine, `ctx.dice`, the per-trial seeded stream
`simharness.TrialRunner` hands to `Dnd5eSystem` (design doc 02 section 3), not
a directly-constructed one. All randomness in a trial flows through one
Resolver so the trial's stream fully determines its outcome.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from dieroller import Dice

# A damage/roll code is standard dice notation understood by py-die-roller
# ("2d8+3", "8d6", "1d6"). Only the leading dice term is doubled on a crit —
# flat modifiers and (for these sims) single-term codes cover every action we
# model. If a future action needs multi-term crit doubling, extend `crit_code`.
_DICE_TERM = re.compile(r"(\d+)d(\d+)")


_FLAT_TERM = re.compile(r"([+-]\d+)")


def crit_code(code: str) -> str:
    """Return `code` with its dice count doubled, for a critical hit."""
    m = _DICE_TERM.search(code)
    count = int(m.group(1))
    return code[: m.start(1)] + str(count * 2) + code[m.end(1):]


def split_damage(code: str) -> tuple[str, int]:
    """Split "1d8+4" into ("1d8", 4). Needed by martial riders (e.g. Savage
    Attacker) that reroll the weapon die but not the flat ability modifier."""
    m = _DICE_TERM.search(code)
    die = m.group(0)
    flat = sum(int(x) for x in _FLAT_TERM.findall(code[m.end():]))
    return die, flat


def die_maximum(die_code: str) -> int:
    """Maximum roll of a bare dice term like "1d8" (-> 8) or "2d8" (-> 16)."""
    m = _DICE_TERM.search(die_code)
    return int(m.group(1)) * int(m.group(2))


@dataclass(frozen=True)
class AttackRoll:
    natural: int
    total: int
    hit: bool
    crit: bool


class Resolver:
    """All randomness in a simulation flows through one Resolver so a single
    seed reproduces the whole run. Handlers/policies never touch a Dice or
    `random` directly."""

    def __init__(self, dice: Dice) -> None:
        self.dice = dice

    def _d20(self, advantage: bool, disadvantage: bool) -> int:
        # Advantage and disadvantage cancel rather than stack (5e rule): if both
        # are set, roll a single straight d20.
        if advantage and not disadvantage:
            return max(self.dice.roll("1d20"), self.dice.roll("1d20"))
        if disadvantage and not advantage:
            return min(self.dice.roll("1d20"), self.dice.roll("1d20"))
        return self.dice.roll("1d20")

    def _d20_bonus(self, bonus_dice: Sequence[str], penalty_dice: Sequence[str]) -> int:
        # Bane/Bless-style effects contribute signed dice to a d20 roll. They're
        # kept as separate positive-code lists (py-die-roller has no signed-dice
        # notation) and netted here.
        total = sum(self.dice.roll(c) for c in bonus_dice)
        total -= sum(self.dice.roll(c) for c in penalty_dice)
        return total

    def attack(
        self,
        bonus: int,
        target_ac: int,
        *,
        crit_range: int = 20,
        advantage: bool = False,
        disadvantage: bool = False,
        bonus_dice: Sequence[str] = (),
        penalty_dice: Sequence[str] = (),
    ) -> AttackRoll:
        natural = self._d20(advantage, disadvantage)
        total = natural + bonus + self._d20_bonus(bonus_dice, penalty_dice)
        crit = natural >= crit_range
        hit = crit or (natural != 1 and total >= target_ac)
        return AttackRoll(natural=natural, total=total, hit=hit, crit=crit)

    def save(
        self,
        modifier: int,
        dc: int,
        *,
        advantage: bool = False,
        disadvantage: bool = False,
        bonus_dice: Sequence[str] = (),
        penalty_dice: Sequence[str] = (),
    ) -> bool:
        natural = self._d20(advantage, disadvantage)
        total = natural + modifier + self._d20_bonus(bonus_dice, penalty_dice)
        return total >= dc

    def damage(self, code: str, *, crit: bool = False) -> int:
        return self.dice.roll(crit_code(code) if crit else code)

    def great_weapon(self, code: str, *, crit: bool = False) -> int:
        """Roll damage with the Great Weapon Fighting style: reroll any weapon
        die that lands on 1 or 2, once, and keep the new roll."""
        die, flat = split_damage(code)
        m = _DICE_TERM.search(die)
        count, sides = int(m.group(1)), int(m.group(2))
        if crit:
            count *= 2
        total = 0
        for _ in range(count):
            roll = self.dice.roll(f"1d{sides}")
            if roll <= 2:
                roll = self.dice.roll(f"1d{sides}")
            total += roll
        return total + flat

    def roll(self, code: str) -> int:
        return self.dice.roll(code)
