from app.config import Settings


def test_debug_parses_release_to_false() -> None:
    s = Settings(DEBUG="release")
    assert s.DEBUG is False


def test_debug_parses_dev_to_true() -> None:
    s = Settings(DEBUG="dev")
    assert s.DEBUG is True


def test_debug_unrecognized_defaults_false() -> None:
    s = Settings(DEBUG="maybe")
    assert s.DEBUG is False
