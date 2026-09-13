from dataclasses import dataclass


@dataclass(frozen=True)
class TopicTitle:
    """Value object representing a topic title."""

    value: str

    def __post_init__(self) -> None:
        """Validate the topic title after initialization."""
        if not self.value or not self.value.strip():
            raise ValueError("Topic title must not be empty")

        object.__setattr__(self, "value", self.value.lower().strip())
