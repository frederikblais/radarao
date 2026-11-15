"""Régions administratives du Québec et déduction approximative à partir du code postal.

Les données ouvertes du SEAO publient `address.region = "QC"` (la province), pas la région
administrative. On la déduit de la région de tri d'acheminement (RTA, 3 premiers caractères
du code postal). La correspondance est approximative (une RTA rurale peut chevaucher deux
régions) : l'interface l'indique. Voir ADR-003.
"""

REGIONS: dict[str, str] = {
    "01": "Bas-Saint-Laurent",
    "02": "Saguenay–Lac-Saint-Jean",
    "03": "Capitale-Nationale",
    "04": "Mauricie",
    "05": "Estrie",
    "06": "Montréal",
    "07": "Outaouais",
    "08": "Abitibi-Témiscamingue",
    "09": "Côte-Nord",
    "10": "Nord-du-Québec",
    "11": "Gaspésie–Îles-de-la-Madeleine",
    "12": "Chaudière-Appalaches",
    "13": "Laval",
    "14": "Lanaudière",
    "15": "Laurentides",
    "16": "Montérégie",
    "17": "Centre-du-Québec",
}

# RTA exactes (3 caractères), prioritaires sur les préfixes de 2 caractères.
_FSA3: dict[str, str] = {
    # G — Est du Québec
    "G0A": "03", "G3A": "03", "G3B": "03", "G3C": "03", "G3E": "03", "G3G": "03", "G3H": "03",
    "G3J": "03", "G3K": "03", "G3L": "03", "G3M": "03", "G3N": "03", "G3Z": "03",
    "G0C": "11", "G0E": "11", "G4T": "11", "G4V": "11", "G4X": "11",
    "G0J": "01", "G0K": "01", "G0L": "01", "G4W": "01", "G5H": "01", "G5J": "01", "G5L": "01",
    "G5M": "01", "G5N": "01", "G5R": "01", "G5T": "01",
    "G0G": "09", "G0H": "09", "G4R": "09", "G4S": "09", "G4Z": "09", "G5A": "09", "G5B": "09",
    "G5C": "09",
    "G0M": "12", "G0N": "12", "G0R": "12", "G0S": "12", "G5V": "12", "G5X": "12", "G5Y": "12",
    "G5Z": "12", "G6A": "12", "G6C": "12", "G6E": "12", "G6G": "12", "G6H": "12", "G6J": "12",
    "G6K": "12", "G6L": "12", "G6V": "12", "G6W": "12", "G6X": "12", "G6Y": "12", "G6Z": "12",
    "G7A": "12",
    "G0T": "03", "G0V": "02", "G0W": "02", "G8P": "10", "G0Y": "05", "G6B": "05",
    "G0X": "04", "G0P": "17", "G0Z": "17", "G6P": "17", "G6R": "17", "G6S": "17", "G6T": "17",
    # J — Ouest et Sud
    "J0A": "17", "J0B": "05", "J0C": "17", "J0E": "16", "J0G": "17", "J0H": "16", "J0J": "16",
    "J0K": "14", "J0L": "16", "J0M": "10", "J0N": "15", "J0P": "16", "J0R": "15", "J0S": "16",
    "J0T": "15", "J0V": "07", "J0W": "15", "J0X": "07", "J0Y": "08", "J0Z": "08",
    "J2A": "17", "J2B": "17", "J2C": "17", "J2E": "17",
    "J5T": "14", "J5W": "14", "J5X": "14", "J5Y": "14", "J5Z": "14",
    "J6A": "14", "J6E": "14", "J6V": "14", "J6W": "14", "J6X": "14", "J6Y": "14", "J7K": "14",
    "J7L": "14",
    "J6Z": "15", "J7A": "15", "J7B": "15", "J7C": "15", "J7E": "15", "J7G": "15", "J7H": "15",
    "J7J": "15", "J7M": "15", "J7N": "15", "J7P": "15", "J7R": "15", "J7Y": "15", "J7Z": "15",
    "J8A": "15", "J8B": "15", "J8C": "15", "J8E": "15", "J8G": "15", "J8H": "15", "J9L": "15",
    "J9E": "07",
}

# Préfixes de 2 caractères (repli).
_FSA2: dict[str, str] = {
    "G1": "03", "G2": "03", "G3": "03", "G4": "01", "G5": "01", "G6": "12", "G7": "02", "G8": "02",
    "G9": "04",
    "H0": "06", "H1": "06", "H2": "06", "H3": "06", "H4": "06", "H5": "06", "H7": "13", "H8": "06",
    "H9": "06",
    "J1": "05", "J2": "16", "J3": "16", "J4": "16", "J5": "16", "J6": "16", "J7": "16", "J8": "07",
    "J9": "08",
}

# Exceptions d'une RTA qui contredisent le préfixe de 2 caractères.
_FSA3.update({
    "G8T": "04", "G8V": "04", "G8W": "04", "G8Y": "04", "G8Z": "04", "G9A": "04",
    "J8L": "07", "J8M": "07", "J8N": "07", "J8P": "07", "J8R": "07", "J8T": "07", "J8V": "07",
    "J8X": "07", "J8Y": "07", "J8Z": "07", "J9A": "07", "J9B": "07", "J9H": "07", "J9J": "07",
})


def normalize_postal_code(postal_code: str | None) -> str | None:
    if not postal_code:
        return None
    pc = "".join(ch for ch in postal_code.upper() if ch.isalnum())
    return pc if len(pc) >= 3 else None


def region_from_postal_code(postal_code: str | None) -> str | None:
    """Retourne le code de région administrative (« 05 ») ou None si hors Québec ou inconnu."""
    pc = normalize_postal_code(postal_code)
    if pc is None or pc[0] not in "GHJ":
        return None
    return _FSA3.get(pc[:3]) or _FSA2.get(pc[:2])
