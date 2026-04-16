"""Tests for the flower database module."""

from ttr_bot.gardening.flowers import (
    BEAN_CHAR_TO_TEMPLATE,
    BEAN_COLORS,
    FLOWERS,
    get_all_flower_names,
    get_flowers_by_beans,
    lookup_flower,
)


class TestGetFlowersByBeans:
    def test_known_count_returns_dict(self):
        result = get_flowers_by_beans(3)
        assert isinstance(result, dict)
        assert "Summer's Last Rose" in result

    def test_unknown_count_returns_empty(self):
        assert get_flowers_by_beans(99) == {}

    def test_all_groups_present(self):
        for count in FLOWERS:
            result = get_flowers_by_beans(count)
            assert len(result) > 0, f"No flowers for count={count}"


class TestGetAllFlowerNames:
    def test_returns_list(self):
        names = get_all_flower_names()
        assert isinstance(names, list)
        assert len(names) > 0

    def test_all_flowers_included(self):
        names = get_all_flower_names()
        expected = sum(len(group) for group in FLOWERS.values())
        assert len(names) == expected

    def test_known_flower_present(self):
        assert "Summer's Last Rose" in get_all_flower_names()


class TestLookupFlower:
    def test_known_flower(self):
        result = lookup_flower("Summer's Last Rose")
        assert result is not None
        count, sequence = result
        assert count == 3
        assert sequence == "rrr"

    def test_unknown_flower(self):
        assert lookup_flower("Not A Real Flower") is None

    def test_sequences_use_valid_bean_chars(self):
        for count, group in FLOWERS.items():
            for name, seq in group.items():
                assert len(seq) == count, f"{name}: sequence length {len(seq)} != {count}"
                for char in seq:
                    assert char in BEAN_COLORS, f"{name}: invalid bean char '{char}'"
                    assert char in BEAN_CHAR_TO_TEMPLATE, f"{name}: no template for '{char}'"
