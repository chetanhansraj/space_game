"""Letters to players, and the lines of the world feed.

Every template here is filled from facts `sim` already committed. The choice
between variants is a pure function of the message id, so the same letter
reads the same way every time it is opened -- a letter that rewrites itself
on reload is not a letter.

The house style, for anyone adding to this: short. Characters say one thing
and mean it. Numbers are exact, because they are real. Nobody explains the
game; the fiction does that.
"""

from __future__ import annotations

from .characters import NODE_NAMES, firm_label, speaker

ASSET_NAMES = {
    "REGOLITH": "regolith", "ICE": "water ice", "PROP": "propellant",
    "IRON": "iron", "VOLATILE": "volatiles", "FOOD": "food",
    "RAREEARTH": "rare earths", "GOODS": "manufactured goods",
    "PGM": "platinum group metals", "HE3": "helium-3",
}


def cr(amount: int | None) -> str:
    return "—" if amount is None else f"{amount:,} cr"


def tonnes(kg: int) -> str:
    t = kg / 1000
    return f"{t:,.0f} t" if t == int(t) else f"{t:,.1f} t"


def place(node: str | None) -> str:
    return NODE_NAMES.get(node or "", node or "somewhere")


def goods(asset: str) -> str:
    return ASSET_NAMES.get(asset, asset.lower())


def _pick(options: list[str], key: int) -> str:
    return options[key % len(options)]


def _contract_line(c: dict) -> str:
    return (f"{tonnes(c['qty_kg'])} of {goods(c['asset'])} to "
            f"{place(c['node'])} — {cr(c['payment'])}, escrowed. "
            f"Deadline: game hour {c['deadline_tick']:,}.")


# -- letters ------------------------------------------------------------------

def _welcome(d: dict, key: int, ctx: dict) -> tuple[str, list[str]]:
    return (f"Welcome, {d['company']}", [
        "I keep the record of this world. Every cargo that has moved, every "
        "price that has cleared, every firm that has failed — it is all "
        "written down, and from today so is your company.",
        f"Your Kestrel is docked at {place(d['node'])}, on the rim of "
        "Shackleton crater, where the ice is and where the propellant is "
        "made. Three ports on the Moon trade with each other. They do not "
        "agree on what anything is worth. That disagreement is your "
        "business.",
        "The world does not wait. Ships fly, rigs work and prices move while "
        "you are away, and I will tell you what happened when you return.",
        "Read your letters. Somebody already wants something moved.",
    ])


def _charter(d: dict, key: int, ctx: dict) -> tuple[str, list[str]]:
    return ("Your charter", [
        f"{d['company']} — the development office has approved your "
        f"charter. {cr(d['grant'])} is in your account and your Kestrel "
        f"has a full tank: {tonnes(d['fuel_kg'])} of propellant.",
        f"The ship is the Ark's. The charter fee is {cr(d['upkeep_per_day'])} "
        "a day, taken at midnight. Docking fees are paid when you launch, "
        "not when you land — nobody gets stranded on my watch for want of "
        "eight hundred credits.",
        "The grant is not a loan. It is also not a gift. It is the Ark "
        "betting that one more company makes the Moon richer than one more "
        "tank of fuel would have. Don't make me explain the bet to the "
        "Council.",
        "— Yusuf Brandt, Ark Development Office",
    ])


_OFFER_OPENERS = {
    "mira_vance": [
        "You're the new Kestrel. Good. My plants eat ice faster than the "
        "guild can dig it, and the Peary cooperative sells it cheaper than "
        "they admit.",
    ],
    "sol_adeyemi": [
        "Welcome up. Peary is cold, dark and short of everything that isn't "
        "ice. We pay on the nail.",
    ],
    "ines_halloran": [
        "I have separators that cannot stop and a settlement that cannot "
        "run out of propellant. You have a ship. Let us be useful to each "
        "other.",
    ],
    "tomas_okafor": [
        "Brandt says you fly. Peary makes no propellant of its own — every "
        "tonne we burn came in on someone's ship. Here's what we need.",
    ],
}


def _offers(d: dict, key: int, ctx: dict) -> tuple[str, list[str]]:
    who = ctx.get("sender")
    opener = _pick(_OFFER_OPENERS.get(who, [
        "There is work on the board, and the money is already in escrow.",
    ]), key)
    contracts = [ctx["contracts"][c] for c in d.get("contracts", [])
                 if c in ctx.get("contracts", {})]
    body = [opener]
    body += [f"· {_contract_line(c)}" for c in contracts]
    body.append("The payment is held by the exchange until the goods are "
                "delivered. Take one on the contracts board. Buy where it is "
                "cheap, fly it in, and the ship settles the job the moment it "
                "docks.")
    return ("Work, if you want it", body)


def _arrival(d: dict, key: int, ctx: dict) -> tuple[str, list[str]]:
    body = [f"Kestrel docked at {place(d['node'])}"
            + (f" from {place(d.get('origin'))}." if d.get("origin") else ".")
            + (f" Docking fee {cr(d['fee'])}, paid at launch."
               if d.get("fee") else "")]
    for c in d.get("delivered", []):
        body.append(f"Contract {c['contract']} delivered: "
                    f"{tonnes(c['kg'])} of {goods(c['asset'])} to "
                    f"{speaker(c['issuer']).org}. Paid {cr(c['payment'])}.")
    for s in d.get("sold", []):
        body.append(f"Sold {tonnes(s['kg'])} of {goods(s['asset'])} for "
                    f"{cr(s['value'])}, averaging {cr(s['average'])} a tonne.")
    kept = d.get("kept") or {}
    if kept:
        held = ", ".join(f"{tonnes(q)} {goods(a)}" for a, q in kept.items())
        body.append(f"Still aboard: {held}. The book here would not take it "
                    "at a fair price.")
    if not d.get("delivered") and not d.get("sold") and not kept:
        body.append("Hold empty.")
    body.append(f"Account {cr(d.get('credits'))}. Tank "
                f"{tonnes(d.get('fuel_kg', 0))}.")
    subject = (f"Delivered at {place(d['node'])}" if d.get("delivered") else
               f"Docked at {place(d['node'])}")
    return (subject, body)


_PAID = {
    "mira_vance": ["Ice received, weighed, paid. You were faster than the "
                   "guild. I'll remember that — so will they."],
    "sol_adeyemi": ["Came in right on time. The cooperative thanks you, and "
                    "the cooperative does not thank people often."],
    "ines_halloran": ["Received. The separators never noticed they were "
                      "nearly hungry, which is exactly how I like it."],
    "tomas_okafor": ["Tanks are full again. There are forty people up here "
                     "who will never know your name and slept warmer "
                     "tonight because of it."],
}

_LAPSED = {
    "mira_vance": ["The deadline passed. I found my ice elsewhere, at a "
                   "worse price, and I know exactly whose fault that is."],
    "sol_adeyemi": ["We waited. The contract has lapsed and the money's gone "
                    "back to the cooperative. These things happen, once."],
    "ines_halloran": ["The window closed. I have noted it."],
    "tomas_okafor": ["Nobody came, so we rationed. We'll manage. Next time, "
                     "if you take a job, fly it."],
}


def _contract_paid(d: dict, key: int, ctx: dict) -> tuple[str, list[str]]:
    who = ctx.get("sender_character")
    line = _pick(_PAID.get(who, ["Delivery received. Payment released."]),
                 key)
    return (f"Paid: {tonnes(d['kg'])} {goods(d['asset'])}", [
        line,
        f"{cr(d['payment'])} released from escrow for contract "
        f"{d['contract']}.",
    ])


def _contract_lapsed(d: dict, key: int, ctx: dict) -> tuple[str, list[str]]:
    who = ctx.get("sender_character")
    line = _pick(_LAPSED.get(who, ["The contract lapsed undelivered."]), key)
    return (f"Lapsed: {tonnes(d['kg'])} {goods(d['asset'])}", [
        line,
        f"Contract {d['contract']} expired. The escrow has returned to the "
        "issuer.",
    ])


def _arrears(d: dict, key: int, ctx: dict) -> tuple[str, list[str]]:
    return ("Your ship is grounded", [
        f"The charter fee went unpaid: {cr(d['owed'])} is owed. The Kestrel "
        "stays docked until it is settled.",
        "Sell something. The fee comes out of the next launch automatically.",
        "— Yusuf Brandt, Ark Development Office",
    ])


_LETTERS = {
    "welcome": _welcome, "charter": _charter, "offers": _offers,
    "arrival": _arrival, "contract_paid": _contract_paid,
    "contract_lapsed": _contract_lapsed, "arrears": _arrears,
}


def render_letter(message: dict, ctx: dict | None = None) -> dict:
    """Turn one inbox message into a letter.

    ``message`` is a row from the inbox: id, tick, sender, kind, data.
    ``ctx`` carries facts the letter may refer to but the message does not
    hold, such as the details of contracts it mentions.
    """
    ctx = dict(ctx or {})
    who = speaker(message["sender"])
    ctx.setdefault("sender", who.id)
    ctx["sender_character"] = who.id
    make = _LETTERS.get(message["kind"])
    if make is None:
        subject, body = (message["kind"].replace("_", " ").capitalize(),
                         ["(No words for this yet. The facts are recorded.)"])
    else:
        try:
            subject, body = make(message.get("data", {}),
                                 int(message.get("id", 0)), ctx)
        except (KeyError, TypeError, ValueError):
            # A letter that cannot be written is never allowed to break the
            # inbox. The fact still arrived; only the prose is missing.
            subject, body = (message["kind"].replace("_", " ").capitalize(),
                             ["(This letter could not be written.)"])
    return {"id": message.get("id"), "tick": message.get("tick"),
            "kind": message["kind"], "read": message.get("read", False),
            "from": who.as_dict(), "subject": subject, "body": body}


# -- the feed -------------------------------------------------------------------

def render_event(event: dict, companies: dict[str, str] | None = None) -> str:
    """One line of the world feed, in the Archivist's voice."""
    companies = companies or {}
    d = event.get("data", {})
    kind = event["kind"]
    try:
        if kind == "solar_flare":
            return (f"Solar flare. Surface work halted across the Moon for "
                    f"{d['hours']} hours, and every launch is grounded.")
        if kind == "equipment_failure":
            return (f"{firm_label(event['subject'])} is down for "
                    f"{d['hours']} hours.")
        if kind == "insolvency":
            return (f"{firm_label(d['firm'])} has been wound up. Its stores "
                    f"are on the book at {place(d['node'])}, cheap.")
        if kind == "spinoff":
            return (f"{firm_label(d['firm'])} has done well enough to fund a "
                    f"rival: {cr(d['capital'])} of its own money.")
        if kind == "contract_posted":
            return (f"{speaker(d['issuer']).name} wants {tonnes(d['kg'])} of "
                    f"{goods(d['asset'])} at {place(d['node'])}, paying "
                    f"{cr(d['payment'])}.")
        if kind == "contract_fulfilled":
            taker = companies.get(d.get("taker") or "", "A pilot")
            return (f"{taker} delivered {tonnes(d['kg'])} of "
                    f"{goods(d['asset'])} to {speaker(d['issuer']).name}.")
        if kind == "player_joined":
            return (f"A new company, {d['company']}, has taken a charter at "
                    f"{place(d['node'])}.")
        if kind == "player_departure":
            return (f"{d['company']} launched from {place(d['origin'])} for "
                    f"{place(d['destination'])}.")
        if kind == "player_arrival":
            name = companies.get(d.get("owner") or "", "A Kestrel")
            return f"{name} docked at {place(d['node'])}."
    except (KeyError, TypeError):
        pass
    return event.get("detail", kind)
