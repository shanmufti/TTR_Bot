"""Complete Toontown Rewritten flower database.

Each flower is defined by a jellybean sequence string where each character
represents a bean color.  Flowers are grouped by the number of beans required.
"""

from __future__ import annotations

BEAN_COLORS: dict[str, tuple[str, str]] = {
    "r": ("Red", "#e74c3c"),
    "g": ("Green", "#2ecc71"),
    "o": ("Orange", "#e67e22"),
    "u": ("Purple", "#9b59b6"),
    "b": ("Blue", "#3498db"),
    "i": ("Pink", "#e91e8f"),
    "y": ("Yellow", "#f1c40f"),
    "c": ("Cyan", "#1abc9c"),
    "s": ("Silver", "#95a5a6"),
}

BEAN_CHAR_TO_TEMPLATE: dict[str, str] = {
    "r": "red_jellybean_button",
    "g": "green_jellybean_button",
    "o": "orange_jellybean_button",
    "u": "purple_jellybean_button",
    "b": "blue_jellybean_button",
    "i": "pink_jellybean_button",
    "y": "yellow_jellybean_button",
    "c": "cyan_jellybean_button",
    "s": "silver_jellybean_button",
}

# Flowers grouped by bean count (1-8).
# Key = bean count, value = dict of {flower_name: bean_sequence}.
FLOWERS: dict[int, dict[str, str]] = {
    1: {
        "Laff-o-dil": "r",
        "Daffy Dil": "g",
        "What-in Carnation": "i",
        "School Daisy": "b",
        "Lily-of-the-Alley": "o",
    },
    2: {
        "Summer's Last Rose": "rr",
        "Corn Rose": "ry",
        "Tinted Rose": "ri",
        "Chim Pansy": "gg",
        "Potsen Pansy": "gr",
        "Dandy Pansy": "gb",
        "Midsummer Daisy": "bg",
        "Freshasa Daisy": "by",
        "Lazy Daisy": "bb",
        "Lily Pad": "oc",
        "Tiger Lily": "oy",
    },
    3: {
        "Stinking Rose": "rrr",
        "Istilla Rose": "rbu",
        "Hybrid Red Rose": "rry",
        "Onelip": "ryy",
        "Twolip": "ryg",
        "Threelip": "ryb",
    },
    4: {
        "Marzi Pansy": "gggg",
        "Instant Carnation": "iiii",
        "Side Carnation": "iirr",
        "Daisy Bell": "bbbb",
        "Livered Lily": "oooo",
    },
    5: {
        "Indubitab Rose": "rrrry",
        "Car Petunia": "uuuub",
        "Platoonia": "uuuuy",
        "Crazy Daisy": "bbbbb",
        "Hazy Daisy": "bbbby",
    },
    6: {
        "Trance Orchid": "uuuubb",
        "Giraff-o-dil": "rrrrrr",
        "Dande-lion": "oooooo",
        "Lily-of-the-Valley": "ooooyy",
    },
    7: {
        "Model Orchid": "uuuubbb",
        "Nurture Rose": "rrrrryy",
        "Smarty Pansy": "ggggggg",
        "Upsy Daisy": "bbbbbbb",
    },
    8: {
        "Bossa Nova Rose": "rrrrryyy",
        "Time-and-a-half-o-dil": "rrrrrrrr",
        "Chili Lily": "oooooooo",
        "Lily of the Nile": "ooooooyy",
    },
}


def get_flowers_by_beans(count: int) -> dict[str, str]:
    """Return flowers that require exactly *count* beans."""
    return FLOWERS.get(count, {})


def get_all_flower_names() -> list[str]:
    """Return a flat list of every flower name."""
    names: list[str] = []
    for group in FLOWERS.values():
        names.extend(group.keys())
    return names


def lookup_flower(name: str) -> tuple[int, str] | None:
    """Return (bean_count, sequence) for a flower name, or None."""
    for count, group in FLOWERS.items():
        if name in group:
            return count, group[name]
    return None
