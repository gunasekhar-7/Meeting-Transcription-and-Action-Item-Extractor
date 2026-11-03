from app.pipelines.alignment import Turn, Word, assign_speaker, split_by_speaker


def test_words_are_assigned_and_split_at_turn_boundaries() -> None:
    turns = [Turn(0, 1000, "SPEAKER_00"), Turn(1000, 2000, "SPEAKER_01")]
    words = [
        Word(0, 400, "hello"),
        Word(500, 900, "there"),
        Word(1100, 1500, "how"),
        Word(1600, 1900, "are"),
    ]
    segments = split_by_speaker(words, turns)
    assert [(segment.speaker, segment.text) for segment in segments] == [
        ("SPEAKER_00", "hello there"),
        ("SPEAKER_01", "how are"),
    ]
    assert segments[0].start_ms == 0
    assert segments[1].end_ms == 1900


def test_tie_goes_to_the_earlier_turn() -> None:
    turns = [Turn(0, 1000, "A"), Turn(1000, 2000, "B")]
    assert assign_speaker(Word(900, 1100, "boundary"), turns) == "A"


def test_word_outside_all_turns_has_no_speaker() -> None:
    turns = [Turn(0, 1000, "A")]
    assert assign_speaker(Word(5000, 6000, "silence"), turns) is None


def test_single_word_segment() -> None:
    segments = split_by_speaker([Word(0, 100, "yes")], [Turn(0, 100, "A")])
    assert len(segments) == 1
    assert segments[0].text == "yes"
    assert segments[0].speaker == "A"
