"""The one record every extractor produces."""
from dataclasses import dataclass


@dataclass
class Comment:
    path: str
    line: int  # 1-based
    col: int  # 1-based
    kind: str  # doc | line | block | trailing | docstring
    raw: str  # delimiters included, as it appears in the file
    text: str  # normalized, as the model sees it
