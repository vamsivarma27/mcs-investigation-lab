"""Generate the deterministic multi-case corpus from the audited base case."""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "lab" / "data"
PUBLIC_DIR = DATA / "cases"
VAULT_DIR = DATA / "vaults"

DIFFICULTIES = [
    ("Beginner", 1, 6, 5, 12, "More starting evidence and fewer decisive links."),
    ("Easy", 2, 5, 6, 16, "Strong records with a small number of plausible distractions."),
    ("Moderate", 3, 4, 7, 20, "Balanced evidence, incomplete alibis, and several red herrings."),
    ("Hard", 4, 3, 8, 25, "Sparse starting evidence and a longer chain of corroboration."),
    ("Expert", 5, 3, 9, 30, "Maximum ambiguity, partial forensics, and the full evidence chain."),
]

THEMES = [
    ("aurora-observatory", "Aurora Observatory", "Northstar Observatory", "telescope control room",
     "astronomer", "Dr. Lena Frost", "meteorite provenance file", "cryogenic paralytic",
     "solstice gala", ["Mara Voss", "Jon Bell", "Iris Chen", "Owen Pike", "Nia Shah", "Felix Frost", "Tess Ward", "Ravi Cole"]),
    ("helix-biotech", "Helix Protocol", "Helix Biotech Campus", "genomics clean room",
     "geneticist", "Dr. Elias Wynn", "trial authorization packet", "neuromuscular compound",
     "investor showcase", ["Priya Nair", "Cal Moss", "Elena Ruiz", "Tomas Venn", "Mei Lin", "Noah Wynn", "Sara Holt", "Victor Ames"]),
    ("glasshouse-hotel", "The Glasshouse Silence", "Glasshouse Alpine Hotel", "private wine salon",
     "hotel auditor", "Clara Snow", "ownership transfer file", "botanical paralytic",
     "winter founders dinner", ["Astrid Vale", "Marco Stein", "Leah Kim", "Dario Costa", "Yuna Park", "Peter Snow", "Greta Holm", "Henrik Ross"]),
    ("ember-theatre", "The Ember Curtain", "Ember Grand Theatre", "locked costume archive",
     "artistic director", "Mina Rowe", "royalty contract", "stage muscle relaxant",
     "opening night reception", ["Celeste Ward", "Theo Grant", "Amara Singh", "Julian Cross", "Sofia Lane", "Miles Rowe", "Nora Blake", "Hector Quinn"]),
    ("vesper-museum", "The Vesper Collection", "Vesper Museum of Art", "restoration gallery",
     "chief curator", "Dr. Alma Reed", "provenance dossier", "conservation neurotoxin",
     "patron preview", ["Lydia Crane", "Mateo Silva", "Cora Bennett", "Samir Das", "Evelyn Cho", "Graham Reed", "June Price", "Arthur Knox"]),
    ("orbital-research", "The Orbital Blackout", "Kepler Orbital Research Center", "satellite command bay",
     "mission scientist", "Dr. Ren Ito", "launch certification file", "aerospace paralytic",
     "mission readiness briefing", ["Aiko Mercer", "Ben Torres", "Celia Moon", "Dev Kapoor", "Elin West", "Finn Ito", "Gina Brooks", "Hugo Kent"]),
    ("crown-courthouse", "The Crown Deposition", "Crown Central Courthouse", "sealed evidence chamber",
     "special prosecutor", "Maya Sterling", "witness immunity agreement", "forensic paralytic",
     "judicial retirement dinner", ["Ada Clarke", "Bennett Shaw", "Celine Ford", "Derek Rahman", "Erin Page", "Frank Sterling", "Grace Sato", "Harold Bell"]),
    ("redwood-vineyard", "The Redwood Vintage", "Redwood Crest Estate", "reserve tasting vault",
     "estate accountant", "Nora Field", "land trust amendment", "oenology paralytic",
     "harvest celebration", ["Ava Moreau", "Bruno Ortiz", "Camille Hart", "Dinesh Rao", "Elsa Park", "Fiona Field", "Gabi Stone", "Hugh Bell"]),
    ("mercy-hospital", "The Mercy Ward", "Mercy University Hospital", "restricted records suite",
     "clinical investigator", "Dr. Mira Hale", "adverse-event report", "surgical paralytic",
     "medical foundation reception", ["Anika Mercer", "Basil Ortiz", "Chloe Hart", "Davin Raman", "Eli Park", "Farah Hale", "Gia Sato", "Henry Bell"]),
    ("atlas-university", "The Atlas Thesis", "Atlas University", "rare manuscripts laboratory",
     "research dean", "Dr. Leah Stone", "grant review folio", "laboratory paralytic",
     "faculty awards reception", ["Amelia March", "Boris Ortega", "Carmen Hall", "Deepak Rami", "Elle Park", "Frederick Stone", "Georgia Sun", "Harlan Beck"]),
    ("midnight-express", "The Midnight Compartment", "Asteria Continental Express", "locked observation carriage",
     "railway investigator", "Mara Velez", "route concession file", "medical paralytic",
     "inaugural journey dinner", ["Anya Marek", "Benoit Ortez", "Colette Harte", "Dmitri Rane", "Elsie Perk", "Fabian Velez", "Greer Soto", "Hugo Bale"]),
    ("sunken-temple", "The Sunken Temple", "Pelagos Archaeological Institute", "artifact examination chamber",
     "expedition director", "Dr. Maia Vela", "repatriation dossier", "curare paralytic",
     "expedition donors reception", ["Ariadne Meros", "Bastian Orin", "Cassia Hara", "Deyan Rami", "Elara Pahl", "Faris Vela", "Gaia Soren", "Helio Bane"]),
]

VARIANTS = ["First Signal", "Broken Alibi", "Hidden Passage", "False Witness", "Last Disclosure"]
ROLES = [
    "Deputy director", "Security supervisor", "External liaison", "Technical specialist",
    "Digital records officer", "Victim's estranged relative", "Facilities technician", "Visiting expert",
]


def replace_text(text: str, replacements: list[tuple[str, str]]) -> str:
    for source, target in replacements:
        text = text.replace(source, target)
    return text


def generate() -> None:
    base_public = json.loads((DATA / "case_public.json").read_text())
    base_vault = json.loads((DATA / "case_vault.json").read_text())
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    for path in [*PUBLIC_DIR.glob("*.json"), *VAULT_DIR.glob("*.json")]:
        path.unlink()

    old_ids = [suspect["id"] for suspect in base_public["suspects"]]
    old_names = [suspect["name"] for suspect in base_public["suspects"]]
    for theme_index, theme in enumerate(THEMES):
        slug, title, institution, room, victim_role, victim_name, item, toxin, event, names = theme
        victim_surname = victim_name.split()[-1]
        for level_index, (difficulty, rank, initial_count, required_count, minutes, description) in enumerate(DIFFICULTIES):
            case_id = f"{slug}-{rank}"
            rotation = (theme_index * 3 + level_index) % len(old_ids)
            id_map = {old_id: old_ids[(index + rotation) % len(old_ids)]
                      for index, old_id in enumerate(old_ids)}
            rotated_names = names
            name_map = dict(zip(old_names, rotated_names))
            replacements = [(name, name_map[name]) for name in old_names]
            replacements += [(name.split()[0], name_map[name].split()[0]) for name in old_names]
            replacements += [
                ("Dr. Mira Vale", victim_name), ("Mira Vale", victim_name), ("Vale's", f"{victim_surname}'s"),
                ("Vale", victim_surname), ("Meridian Institute", institution),
                ("Meridian Archive", title), ("map room", room), ("Map room", room.title()),
                ("archivist", victim_role), ("donor reception", event), ("donor", "guest"),
                ("donation folio", item), ("forged donation", f"forged {item}"),
                ("folio", item), ("Folio", item.title()),
                ("conservation reagent", toxin), ("reagent", toxin), ("archive", "records"),
                ("Archive", "Records"),
            ]
            public = copy.deepcopy(base_public)
            public.update({
                "id": case_id, "title": f"{title}: {VARIANTS[level_index]}",
                "version": f"1.{rank}.0", "difficulty": difficulty, "difficulty_rank": rank,
                "category": title, "estimated_minutes": minutes,
                "difficulty_description": description,
            })
            public["premise"] = (
                f"At 22:06, {victim_role} {victim_name} was found dead in {institution}'s {room} "
                f"during {event}. A rolling power interruption obscured parts of the camera record. "
                "Eight people had plausible access or motive."
            )
            public["scene"] = (
                f"{room.title()}, one door, electronic badge reader, emergency light. "
                f"{victim_surname} lay beside an open {item}. A puncture mark was visible below the left ear. "
                "The victim's smartwatch last registered a pulse at 21:47. "
                "The room door recorded no ordinary entry between 21:39 and 22:04."
            )
            public["initial_evidence"] = [f"E{i:02d}" for i in range(1, initial_count + 1)]
            for logical_index, suspect in enumerate(public["suspects"]):
                suspect["id"] = id_map[suspect["id"]]
                suspect["name"] = rotated_names[logical_index]
                suspect["role"] = ROLES[logical_index]
                suspect["public_motive"] = replace_text(suspect["public_motive"], replacements)
            for evidence in public["evidence"]:
                evidence["title"] = replace_text(evidence["title"], replacements)
                evidence["text"] = replace_text(evidence["text"], replacements)
                if "suspect_id" in evidence:
                    evidence["suspect_id"] = id_map[evidence["suspect_id"]]

            vault = copy.deepcopy(base_vault)
            vault["case_id"] = case_id
            vault["version"] = public["version"]
            vault["killer_id"] = id_map[vault["killer_id"]]
            vault["motive"] = replace_text(vault["motive"], replacements)
            vault["means"] = replace_text(vault["means"], replacements)
            vault["opportunity"] = replace_text(vault["opportunity"], replacements)
            vault["true_timeline"] = [replace_text(row, replacements) for row in vault["true_timeline"]]
            vault["required_evidence"] = base_vault["required_evidence"][:required_count]
            vault["alternatives"] = {id_map[key]: value for key, value in vault["alternatives"].items()}
            vault["red_herrings"] = {key: replace_text(value, replacements)
                                      for key, value in vault["red_herrings"].items()}
            vault["timeline_markers"] = ["21:43", "21:45", "21:48"]
            vault["mmo_keywords"] = [[item.split()[0].lower(), "forg"],
                                     [toxin.split()[0].lower(), "inject"],
                                     ["corridor", "voltage", "blackout"]]

            (PUBLIC_DIR / f"{case_id}.json").write_text(json.dumps(public, indent=2) + "\n")
            (VAULT_DIR / f"{case_id}.json").write_text(json.dumps(vault, indent=2) + "\n")

    print(f"Generated {len(THEMES) * len(DIFFICULTIES)} cases")


if __name__ == "__main__":
    generate()
