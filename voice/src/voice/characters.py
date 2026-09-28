"""Who is speaking.

The bible: "Named agents (30-50). Persistent characters with holdings, routes,
rivals, memory and a home region. They speak on events, not on ticks."

v1 has five, plus the Archivist and the institutions. Each one fronts real
firms in the simulation -- when Mira Vance writes that she needs ice, it is
because one of her electrolysis plants is genuinely short, and the money she
offers is genuinely escrowed out of that plant's account. The character is
the face; the balance sheet is the firm's.

The mapping from firm to character is by firm id prefix, so a spin-off of one
of Mira's plants is still Mira's.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Character:
    id: str
    name: str
    title: str
    org: str
    home: str | None
    colour: str            # the client's accent for this speaker
    sigil: str             # two letters for an avatar

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "title": self.title,
                "org": self.org, "home": self.home, "colour": self.colour,
                "sigil": self.sigil}


CHARACTERS: dict[str, Character] = {c.id: c for c in (
    Character("archivist", "The Archivist", "Keeper of the record",
              "lunarark.ai", None, "#a78bfa", "AR"),
    Character("ark_development_office", "Yusuf Brandt", "Charter officer",
              "Ark Development Office", "shackleton_depot", "#8b5cf6", "YB"),
    Character("mira_vance", "Mira Vance", "Owner",
              "Vance Propellant", "shackleton_depot", "#f472b6", "MV"),
    Character("sol_adeyemi", "Sol Adeyemi", "Chair",
              "Peary Ridge Ice Cooperative", "peary_ridge", "#38bdf8", "SA"),
    Character("ines_halloran", "Dr Ines Halloran", "Director",
              "Halloran Isotopes", "tranquillitatis_flats", "#fbbf24", "IH"),
    Character("tomas_okafor", "Tomas Okafor", "Quartermaster",
              "Peary Ridge Settlement", "peary_ridge", "#34d399", "TO"),
    Character("shackleton_stores", "Habitat Stores", "Procurement",
              "Shackleton Habitat", "shackleton_depot", "#94a3b8", "SH"),
    Character("tranquillitatis_stores", "Settlement Stores", "Procurement",
              "Tranquillitatis Settlement", "tranquillitatis_flats",
              "#94a3b8", "TS"),
    Character("shackleton_ice_guild", "Shackleton Ice Guild", "Miners",
              "Shackleton Ice Guild", "shackleton_depot", "#67e8f9", "IG"),
    Character("independent_hauler", "Independent hauler", "Freight",
              "Independent", None, "#64748b", "IH"),
)}

#: Firm id prefix -> character. First match wins, so the specific go first.
_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("shack_electrolysis_", "mira_vance"),
    ("shack_prop_trader_", "mira_vance"),
    ("shack_household_", "shackleton_stores"),
    ("shack_ice_", "shackleton_ice_guild"),
    ("peary_household_", "tomas_okafor"),
    ("peary_", "sol_adeyemi"),
    ("tranq_household_", "tranquillitatis_stores"),
    ("tranq_", "ines_halloran"),
    ("hauler_", "independent_hauler"),
)

NODE_NAMES = {
    "shackleton_depot": "Shackleton Depot",
    "peary_ridge": "Peary Ridge",
    "tranquillitatis_flats": "Tranquillitatis Flats",
}


def speaker(sender: str) -> Character:
    """The character behind a message sender or a firm id."""
    if sender in CHARACTERS:
        return CHARACTERS[sender]
    if sender.startswith("port:"):
        node = sender.split(":", 1)[1]
        name = NODE_NAMES.get(node, node)
        return Character(sender, "Harbour Control", "Traffic", name, node,
                         "#06b6d4", "HC")
    for prefix, cid in _BY_PREFIX:
        if sender.startswith(prefix):
            return CHARACTERS[cid]
    return CHARACTERS["archivist"]


def firm_label(firm_id: str) -> str:
    """A readable name for one firm: whose it is and which one."""
    who = speaker(firm_id)
    base = firm_id.split("_spinoff_")[0]
    number = base.rsplit("_", 1)[-1]
    kind = ("plant" if "electrolysis" in base or "separator" in base else
            "rig" if "_ice_" in base or "regolith" in base else
            "desk" if "trader" in base else
            "stores" if "household" in base else
            "Kestrel" if base.startswith("hauler_") else "firm")
    suffix = " (spin-off)" if "_spinoff_" in firm_id else ""
    if number.isdigit():
        return f"{who.org} {kind} {int(number) + 1}{suffix}"
    return f"{who.org}{suffix}"
