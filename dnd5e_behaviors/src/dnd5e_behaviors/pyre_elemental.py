"""The Opera House Pyre Elemental — the burning building itself, wearing an
initiative slot. Referenced from a sim's `[[hazard_actors]]`.

**It is not a monster and deliberately not a `Creature`.** The statblock says
"does not have hit points or an armor class and cannot be affected by any spell
the PCs possess unless they have access to Wish" — so modeling it as a combatant
would be actively wrong: it would be targetable, killable, and would keep the
monster side alive forever. Instead it is a `[[hazard_actors]]` driver: it reads
the board, drops fire, and summons Weirds, and there is simply nothing to attack.
That reframing is what keeps it from breaking the engine.

Its turn (per the statblock):
  * **Multiattack** — two Falling Debris, one of which may be upgraded to Large
    Falling Debris when that's recharged (5-6).
  * **Falling Debris** — DC 16 Dex save in a 10-ft sphere, 4d6 (half bludgeoning,
    half fire), and LEAVES a 10-ft fire that burns 2d6 until its next turn.
  * **Large Falling Debris** (Recharge 5-6) — DC 16 Dex in a 15-ft sphere, 8d6,
    leaving a 15-ft fire burning 4d6.
  * **Legendary actions** (3/round, refreshed on its own turn), spent after other
    creatures' turns: Enflame Pyre (1, max 1/turn — everyone standing in its
    fires takes 4d6, half on a DC 16 Con save), Drop Debris (1 — another Falling
    Debris), Summon Pyre Weird (2 — into one of its fires, max 2 active).

**Target selection** abstracts the module's d12 table. The table's shape is what
matters: the elemental is indiscriminate and mostly lands on GUARDS (7 of 12
outcomes) rather than PCs (4 of 12), with the last slot on stage folk who aren't
modeled here. So: roll d12, pick a side per the table, then aim at whichever cell
catches the most of that side (a cluster, not a single body). With no guards left
(phase 2) every roll lands on the party.

**It ignores the unconscious** — "has no interest in anyone who is unconscious"
— which is why a subdued party can lie on the floor while the building burns
around them, and is the hinge the whole phase-2 hand-off swings on.
"""

from __future__ import annotations

from dnd5e import aoe

DEBRIS_DC = 16
LEGENDARY_PER_ROUND = 3
MAX_WEIRDS = 2


def _dice(code: str, drop: int) -> str:
    """Shave `drop` d6 off a damage expression ("4d6" with drop=1 -> "3d6").

    The tuning knob for "make the WEIRDS the danger, not the falling masonry":
    `drop_d6 = 1` on the hazard actor reduces every one of the elemental's
    damage expressions — the debris itself AND the fires it leaves — by one die.
    Floors at 1d6 so nothing becomes harmless."""
    if drop <= 0:
        return code
    n, _, faces = code.partition("d")
    return f"{max(1, int(n) - drop)}d{faces}"


class PyreElementalDriver:
    # ---- its own turn ---------------------------------------------------------

    def take_turn(self, view) -> None:
        s = view.scratch
        s["legendary_left"] = LEGENDARY_PER_ROUND      # refreshed on its turn
        s.pop("enflamed_this_turn", None)

        # SMOLDER MODE — the escape phase. The prose is explicit: once the
        # nobles have fled, "the Pyre Elemental will stop attacking anyone in the
        # front of the house like the PCs. Instead it will take a few rounds to
        # burn out anyone else in the back rooms... It will, however, spawn three
        # Pyre Weirds in the main room between the PCs and the last remaining
        # exit." So it stops bombing and just keeps the building alight and the
        # weirds coming. This matters enormously: at full aggression it drops a
        # standing party in ~3 rounds (measured), which would make the escape
        # unwinnable and isn't what the scene describes.
        if self._mode(view) == "smolder":
            self._stoke(view)
            return

        if self._recharge_large(view):
            self._large_debris(view)
            self._falling_debris(view)
        else:
            self._falling_debris(view)
            self._falling_debris(view)

    def _mode(self, view) -> str:
        """Two independent clocks, so the fire and the *monster* can be timed
        separately (they are different beats in the fiction):

          * the hazard actor's `start_round` — when the LANTERN FALLS and the
            building starts burning. From here it smolders: fire on the board,
            ticking on whoever stands in it, but nothing is being aimed.
          * `attack_round` — when the fire "becomes a raging Pyre Elemental",
            i.e. starts dropping Falling Debris, using Enflame, and spending
            legendary actions. Before this it is scenery; after, it is a monster.

        `mode = "smolder"` pins it to scenery forever (the phase-2 escape)."""
        if view.config.get("mode") == "smolder":
            return "smolder"
        attack_round = view.config.get("attack_round")
        if attack_round is not None and view.round_index < int(attack_round):
            return "smolder"
        return "attack"

    def _stoke(self, view) -> None:
        """Smolder upkeep: keep the fires burning without aiming anything at
        anyone. If nothing is alight yet this is the LANTERN FALLING — seed the
        first blaze at `ignite_at` (the stage, where Mathieu drops it) so the
        building is genuinely on fire during the smolder window rather than the
        elemental being an inert no-op until it starts attacking."""
        active = list(view.battlefield.hazards.active(view.round_index))
        if not active:
            seed = view.config.get("ignite_at")
            if seed is not None:
                view.add_hazard(tuple(seed), view.config.get("ignite_radius", 20),
                                view.config.get("ignite_damage", "1d6"), tag="fire")
            return
        for hazard in active:
            if hazard.expires_round is not None:
                hazard.expires_round = view.round_index + 1

    # ---- legendary actions, after someone else's turn -------------------------

    def legendary(self, view, after) -> None:
        s = view.scratch
        if s.get("legendary_left", 0) <= 0:
            return
        # Smoldering: the only thing it still does to the front of house is put
        # weirds between them and the door.
        if self._mode(view) == "smolder":
            if s["legendary_left"] >= 2 and self._summon_weird(view):
                s["legendary_left"] -= 2
            return
        # Priority: get a Weird out if we can afford it and have a fire to seed
        # (2 actions), else stoke the fires everyone is standing in (1), else
        # drop more debris (1).
        if s["legendary_left"] >= 2 and self._summon_weird(view):
            s["legendary_left"] -= 2
            return
        if not s.get("enflamed_this_turn") and self._enflame(view):
            s["enflamed_this_turn"] = True
            s["legendary_left"] -= 1
            return
        if self._falling_debris(view):
            s["legendary_left"] -= 1

    # ---- actions --------------------------------------------------------------

    def _recharge_large(self, view) -> bool:
        """Recharge 5-6, rolled at the start of its turn like any recharge."""
        s = view.scratch
        if s.get("large_ready", True):
            s["large_ready"] = False          # spending it now
            return True
        if view.resolver.roll("1d6") >= 5:
            s["large_ready"] = False
            return True
        return False

    def _drop(self, view) -> int:
        return int(view.config.get("drop_d6", 0))

    def _falling_debris(self, view) -> bool:
        d = self._drop(view)
        return self._debris(view, radius_ft=10, dice=_dice("4d6", d), fire=_dice("2d6", d))

    def _large_debris(self, view) -> bool:
        d = self._drop(view)
        return self._debris(view, radius_ft=15, dice=_dice("8d6", d), fire=_dice("4d6", d))

    def _debris(self, view, *, radius_ft: float, dice: str, fire: str) -> bool:
        """Aim, resolve the Dex save for everyone caught, and leave a fire that
        burns until the elemental's next turn (duration 1 round)."""
        center, caught = self._aim(view, radius_ft)
        if center is None:
            return False
        for victim in caught:
            amount = view.resolver.damage(dice)
            saved = view.combat.saving_throw(victim, "dexterity", DEBRIS_DC)
            dealt = amount // 2 if saved else amount
            # Half bludgeoning, half fire — so a fire-immune creature still eats
            # the falling masonry, which is what the statblock's split means.
            view.combat.environmental_damage(victim, dealt // 2, tag="debris",
                                             damage_type="bludgeoning")
            view.combat.environmental_damage(victim, dealt - dealt // 2, tag="debris",
                                             damage_type="fire")
        view.add_hazard(center, radius_ft, fire, duration=1, tag="fire")
        return True

    def _enflame(self, view) -> bool:
        """Enflame Pyre: everyone standing in one of the elemental's fires takes
        4d6 fire, halved on a DC 16 Con save."""
        hazards = view.battlefield.hazards.active(view.round_index)
        if not hazards:
            return False
        burning = set()
        for h in hazards:
            burning |= set(h.cells)
        victims = [c for c in view.creatures() if c.coord in burning]
        if not victims:
            return False
        for victim in victims:
            amount = view.resolver.damage(_dice("4d6", self._drop(view)))
            if view.combat.saving_throw(victim, "constitution", DEBRIS_DC):
                amount //= 2
            view.combat.environmental_damage(victim, amount, tag="enflame", damage_type="fire")
        return True

    def _summon_weird(self, view) -> bool:
        """Summon a Pyre Weird into one of the elemental's fires (max 2 active).
        The statblock says "a fire created by Large Falling Debris"; any active
        fire is used here — the distinction only controls flavor, and gating on
        the Large one would make summons hostage to a recharge roll."""
        import dnd5e_data
        from dnd5e.loader import load_creature

        live = [c for c in view.creatures(side=view.config.get("weird_side", "monsters"))
                if c.has_tag("weird")]
        if len(live) >= view.config.get("max_weirds", MAX_WEIRDS):
            return False
        hazards = view.battlefield.hazards.active(view.round_index)
        if not hazards:
            # No fire to rise from. In the escape phase that's the norm — the
            # elemental throws no wreckage into its own belly, so there are no
            # flames on the floor, but the SMOKE is thick enough to carry weirds
            # ("do not need to check for death for being outside of a fire").
            # Without this the prose's "spawn three Pyre Weirds" could never
            # happen and the elemental would contribute nothing at all.
            if self._mode(view) != "smolder":
                return False
            return self._summon_at(view, view.config.get("summon_at"))
        occupied = view.battlefield.occupied_cells()
        for h in hazards:
            free = [c for c in sorted(h.cells) if c not in occupied]
            if not free:
                continue
            return self._summon_at(view, free[0])
        return False

    def _summon_at(self, view, cell) -> bool:
        """Place one Weird at `cell` (a [x, y] pair). Returns False if there's
        nowhere to put it. The sim's overrides apply, so an escape-phase weird
        arrives already flying and free of Guttering."""
        import dnd5e_data
        from dnd5e.loader import load_creature
        if cell is None:
            return False
        cell = tuple(cell)
        if cell in view.battlefield.occupied_cells():
            return False
        statblock = load_creature(dnd5e_data.data_path("monsters", "pyre_weird.toml"),
                                  overrides=view.config.get("weird_overrides"))
        n = view.scratch.get("weirds_summoned", 0) + 1
        view.scratch["weirds_summoned"] = n
        return view.spawn(statblock, f"pyre_weird_s{n}",
                          view.config.get("weird_side", "monsters"), cell) is not None

    # ---- targeting ------------------------------------------------------------

    def _aim(self, view, radius_ft: float):
        """The d12 table, abstracted: pick a side by its weight, then the cell
        catching the most of that side. Falls back to whoever is actually on the
        board. Returns `(center, caught_creatures)`."""
        roll = view.resolver.roll("1d12")
        # The published table exactly: 1-6 guards (single / far group / largest
        # group), 7-10 PCs (largest group / any individual), 11-12 people on
        # stage who aren't Nico or Mélisse — nobody this sim models, so those two
        # slots are a genuine MISS. Mapping them onto the party instead would
        # over-target the PCs by a sixth.
        if roll >= 11:
            return None, []
        prefer = "monsters" if roll <= 6 else "party"
        pools = [prefer, "party" if prefer == "monsters" else "monsters"]

        for side in pools:
            # Never targets the unconscious ("no interest in anyone who is
            # unconscious") — `creatures()` already drops the Down.
            candidates = [c for c in view.creatures(side=side)
                          if not c.has_tag("weird")]      # doesn't bomb its own minions
            if not candidates:
                continue
            best, best_hit = None, -1
            for c in candidates:
                cells = aoe.sphere_cells(view.battlefield.board, c.coord, radius_ft)
                hit = [o for o in view.creatures() if o.coord in cells and not o.has_tag("weird")]
                if len(hit) > best_hit:
                    best, best_hit = c.coord, len(hit)
            if best is not None:
                cells = aoe.sphere_cells(view.battlefield.board, best, radius_ft)
                caught = [o for o in view.creatures() if o.coord in cells and not o.has_tag("weird")]
                return best, caught
        return None, []
