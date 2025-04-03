from dataclasses import dataclass


@dataclass
class UserContext:
    name: str | None
    email: str | None
    sid: str | None
