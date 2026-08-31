"""The regex sentence splitter used by --split-sentences."""
from commentlint.comments import sentences


class TestSplit:
    def test_two_plain_sentences_split_apart(self):
        text = "This is the first sentence. This is the second sentence."
        assert sentences.split(text) == [
            "This is the first sentence.",
            "This is the second sentence.",
        ]

    def test_a_single_sentence_stays_whole(self):
        text = "Only one sentence here with no other boundary."
        assert sentences.split(text) == [text]

    def test_empty_text_returns_nothing(self):
        assert sentences.split("") == []
        assert sentences.split("   ") == []

    def test_whitespace_is_collapsed_within_a_sentence(self):
        text = "Line one\ncontinues   here."
        assert sentences.split(text) == ["Line one continues here."]

    def test_eg_abbreviation_does_not_end_a_sentence(self):
        text = "We saw this happen, e.g. right here in this file. It was surprising."
        assert sentences.split(text) == [
            "We saw this happen, e.g. right here in this file.",
            "It was surprising.",
        ]

    def test_single_letter_initial_does_not_end_a_sentence(self):
        text = "J. Smith wrote the original patch. Nobody has touched it since."
        assert sentences.split(text) == [
            "J. Smith wrote the original patch.",
            "Nobody has touched it since.",
        ]

    def test_question_and_exclamation_marks_are_boundaries(self):
        text = "Is this correct? Yes, it is! Good."
        assert sentences.split(text) == ["Is this correct?", "Yes, it is!", "Good."]

    def test_a_decimal_number_does_not_split(self):
        text = "The threshold is 0.71 by default."
        assert sentences.split(text) == [text]
