from target import count_matches


def main() -> None:
    assert count_matches([1, 2, 2, 4], [2, 4]) == 3
    assert count_matches([], [1]) == 0
    assert count_matches([1, 2], []) == 0
    print("3 tests passed")


if __name__ == "__main__":
    main()

