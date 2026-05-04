"""Base connector interfaces for ads platforms."""

from abc import ABC, abstractmethod


class BaseAdsConnector(ABC):
    """Common interface for ads platform connectors."""

    platform_name: str

    @abstractmethod
    def fetch_daily_report(
        self,
        account_id: str,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """Fetch daily ads report rows for an account and date range."""
