from app.services.grounding import verify_quote


def test_exact_quote_returns_offsets() -> None:
    text = "We agreed to move the launch to the fourteenth of November."
    result = verify_quote(text, "move the launch")
    assert result is not None
    assert text[result.start : result.end] == "move the launch"


def test_case_and_whitespace_are_normalised() -> None:
    text = "We   agreed\nto move the launch."
    result = verify_quote(text, "AGREED TO MOVE")
    assert result is not None
    assert text[result.start : result.end].lower() == "agreed\nto move"


def test_surrounding_punctuation_is_tolerated() -> None:
    text = "The billing migration is blocked."
    assert verify_quote(text, '"billing migration is blocked."') is not None


def test_tampered_quote_is_rejected() -> None:
    text = "Ada will update the pricing deck."
    assert verify_quote(text, "Ada will delete the production database") is None


def test_quote_spanning_segments_is_rejected() -> None:
    text = "Yes, I will update the pricing deck by Friday."
    assert verify_quote(text, "I will update the pricing deck. Ada will") is None


def test_short_quote_is_rejected() -> None:
    assert verify_quote("yes indeed", "y") is None


def test_empty_segment_is_rejected() -> None:
    assert verify_quote("   ", "anything") is None
