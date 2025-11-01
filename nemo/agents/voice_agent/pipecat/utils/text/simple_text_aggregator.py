# Copyright (c) 2025, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import re
from typing import Optional

from loguru import logger
from pipecat.utils.string import match_endofsentence
from pipecat.utils.text.simple_text_aggregator import SimpleTextAggregator


def has_partial_decimal(text: str) -> bool:
    """Check if the text ends with a partial decimal.

    Returns True if the text ends with a number that looks like it could
    be a partial decimal (e.g., "3.", "3.14", "($3.14)"), but NOT if it's
    clearly a complete sentence (e.g., "It costs $3.14.") or a bullet point
    (e.g., "1. Alpha; 2.").
    """
    text = text.strip()

    # Check for bullet point pattern: ends with 1-3 digits followed by period
    # Examples: "1.", "12.", "123.", or "text; 2."
    # Bullet points are typically small numbers (1-999) at the end
    bullet_match = re.search(r'(?:^|[\s;,]|[^\d])(\d{1,3})\.$', text)
    if bullet_match:
        # It's likely a bullet point, not a partial decimal
        return False

    # Pattern to find decimal numbers near the end, allowing for trailing
    # non-word characters like ), ], ", ', etc.
    # Match: digit(s) + period + optional digit(s) + optional trailing non-word chars
    match = re.search(r'\d+\.(?:\d+)?([^\w\s]*)$', text)

    if not match:
        return False

    trailing = match.group(1)  # e.g., ")" or "" or "."

    # If trailing contains a period, it's sentence-ending punctuation
    # e.g., "3.14." means complete sentence
    if '.' in trailing:
        return False

    # Otherwise, it's a partial decimal (either incomplete like "3."
    # or complete number but sentence not finished like "($3.14)")
    return True


def find_last_period_index(text: str) -> int:
    """
    Find the last occurrence of a period in the text,
    but return -1 if the text doesn't seem to be a complete sentence.
    """
    num_periods = text.count(".")
    if num_periods == 0:
        return -1

    if num_periods == 1:
        if has_partial_decimal(text):
            # if the only period in the text is part of a number, return -1
            return -1
        # Check if the only period is a bullet point (e.g., "1. Alpha" or incomplete "1.")
        if re.search(r'(?:^|[\s;,]|[^\d])(\d{1,3})\.(?:\s+\w|\s*$)', text):
            # The period is after a bullet point number, either:
            # - followed by content (e.g., "1. Alpha")
            # - or at the end with optional whitespace (e.g., "1." or "1. ")
            return -1

        # Check if any of the abbreviations "e.", "i." "g.", "etc." are present in the text
        if re.search(r'\b(e\.|i\.|g\.)\b', text):
            # The period is after a character/word that is likely to be a abbreviation, return -1
            return -1

    # otherwise, check the last occurrence of a period
    idx = text.rfind(".")
    if idx <= 0:
        return idx
    if text[idx - 1].isdigit():
        # if the period is after a digit, it's likely a partial decimal, return -1
        return -1
    elif idx > 2 and text[idx - 3 : idx + 1] in ["e.g.", "i.e."]:
        # The period is after a character/word that is likely to be a abbreviation, return -1
        return -1

    # the text seems to have a complete sentence, return the index of the last period
    return idx


class SimpleSegmentedTextAggregator(SimpleTextAggregator):
    def __init__(
        self,
        punctuation_marks: str | list[str] = ".,!?;:",
        ignore_marks: str | list[str] = "*",
        min_sentence_length: int = 0,
        use_legacy_eos_detection: bool = False,
        **kwargs,
    ):
        """
        Args:
            punctuation_marks: The punctuation marks to use for sentence detection.
            ignore_marks: The marks to ignore in the text.
            min_sentence_length: The minimum length of a sentence to be considered.
            use_legacy_eos_detection: Whether to use the legacy EOS detection from pipecat.
            **kwargs: Additional arguments to pass to the SimpleTextAggregator constructor.
        """
        super().__init__(**kwargs)
        self._use_legacy_eos_detection = use_legacy_eos_detection
        self._min_sentence_length = min_sentence_length
        if not ignore_marks:
            self._ignore_marks = set()
        else:
            self._ignore_marks = set(ignore_marks)
        if not punctuation_marks:
            self._punctuation_marks = list()
        else:
            punctuation_marks = (
                [c for c in punctuation_marks] if isinstance(punctuation_marks, str) else punctuation_marks
            )
            if "." in punctuation_marks:
                punctuation_marks.remove(".")
            punctuation_marks += [
                "."
            ]  # put period at the end of the list to ensure it's the last punctuation mark to be matched
            self._punctuation_marks = punctuation_marks

    def _find_segment_end(self, text: str) -> Optional[int]:
        """find the end of text segment.

        Args:
            text: The text to find the end of the segment.

        Returns:
            The index of the end of the segment, or None if the text is too short.
        """
        if len(text.strip()) < self._min_sentence_length:
            return None

        for punc in self._punctuation_marks:
            if punc == ".":
                idx = find_last_period_index(text)
            else:
                idx = text.find(punc)
            if idx != -1:
                return idx + 1
        return None

    async def aggregate(self, text: str) -> Optional[str]:
        result: Optional[str] = None

        self._text += str(text)

        for ignore_mark in self._ignore_marks:
            self._text = self._text.replace(ignore_mark, "")

        eos_end_index = self._find_segment_end(self._text)

        if not eos_end_index and not has_partial_decimal(self._text) and self._use_legacy_eos_detection:
            # if the text doesn't have partial decimal, and no punctuation marks,
            # we use match_endofsentence to find the end of the sentence
            eos_end_index = match_endofsentence(self._text)

        if eos_end_index:
            result = self._text[:eos_end_index]
            if len(result.strip()) < self._min_sentence_length:
                result = None
                logger.debug(f"Text is too short, skipping: `{result}`, full text: `{self._text}`")
            else:
                logger.debug(f"Text Aggregator Result: `{result}`, full text: `{self._text}`")
                self._text = self._text[eos_end_index:]

        return result
