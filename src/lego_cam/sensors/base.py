from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator


class BaseSensor(ABC):
    """
    Base interface for sensors producing motion/presence events.
    """

    @abstractmethod
    async def events(self) -> AsyncIterator[bool]:
        """
        Yields True when motion/presence is detected.
        """
        raise NotImplementedError

