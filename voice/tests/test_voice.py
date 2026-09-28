"""voice/ must never be the reason the game breaks.

It renders whatever it is given, including facts it has never heard of and
facts with pieces missing, and it gives the same words for the same letter
every time.
"""

from voice import render_event, render_letter, speaker
from voice.characters import firm_label


def test_every_firm_has_a_face():
    assert speaker("shack_electrolysis_2").name == "Mira Vance"
    assert speaker("shack_electrolysis_2_spinoff_4").name == "Mira Vance"
    assert speaker("peary_household_0").name == "Tomas Okafor"
    assert speaker("peary_ice_3").name == "Sol Adeyemi"
    assert speaker("tranq_separator_1").name == "Dr Ines Halloran"
    assert speaker("port:peary_ridge").org == "Peary Ridge"
    assert speaker("something_unknown").id == "archivist"


def test_firm_labels_read_like_names():
    assert firm_label("shack_electrolysis_0") == "Vance Propellant plant 1"
    assert firm_label("peary_ice_7") == "Peary Ridge Ice Cooperative rig 8"


def test_a_letter_reads_the_same_every_time():
    msg = {"id": 7, "tick": 3, "sender": "tomas_okafor",
           "kind": "contract_paid",
           "data": {"contract": 4, "asset": "PROP", "kg": 12_000,
                    "payment": 24_192}}
    assert render_letter(msg) == render_letter(msg)
    letter = render_letter(msg)
    assert "24,192 cr" in " ".join(letter["body"])
    assert letter["from"]["name"] == "Tomas Okafor"


def test_unknown_and_broken_facts_never_raise():
    render_letter({"id": 1, "sender": "archivist", "kind": "never_heard_of_it",
                   "data": {}})
    broken = render_letter({"id": 2, "sender": "archivist", "kind": "arrival",
                            "data": {}})
    assert broken["body"]
    assert render_event({"kind": "solar_flare", "data": {},
                         "detail": "fallback"}) == "fallback"
    assert render_event({"kind": "brand_new_kind", "detail": "x"}) == "x"


def test_offers_list_the_contracts_they_mention():
    contract = {"id": 3, "qty_kg": 10_000, "asset": "ICE",
                "node": "shackleton_depot", "payment": 8_321,
                "deadline_tick": 72}
    letter = render_letter(
        {"id": 5, "sender": "shack_electrolysis_1", "kind": "offers",
         "data": {"contracts": [3]}},
        {"contracts": {3: contract}})
    text = " ".join(letter["body"])
    assert "10 t of water ice" in text and "8,321 cr" in text
