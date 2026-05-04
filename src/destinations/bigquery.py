"""BigQuery destination helpers."""

import logging
import re
from typing import Any

from google.cloud import bigquery


LOGGER = logging.getLogger(__name__)
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class BigQueryDestination:
    """Write and replace rows in BigQuery tables."""

    def __init__(
        self,
        project_id: str,
        dataset_id: str,
        client: bigquery.Client | None = None,
    ) -> None:
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.client = client or bigquery.Client(project=project_id)

    def insert_rows(self, table_name: str, rows: list[dict]) -> int:
        """Insert JSON rows into a BigQuery table and return inserted count."""
        if not rows:
            LOGGER.info("No rows to insert into %s.", table_name)
            return 0

        table_id = self._table_id(table_name)
        errors = self.client.insert_rows_json(table_id, rows)
        if errors:
            error_preview = errors[:3]
            raise RuntimeError(
                f"Failed to insert rows into {table_id}: "
                f"{error_preview} ({len(errors)} row errors total)"
            )

        LOGGER.info("Inserted %s rows into %s.", len(rows), table_id)
        return len(rows)

    def delete_date_range(
        self,
        table_name: str,
        start_date: str,
        end_date: str,
        filters: dict,
    ) -> None:
        """Delete rows in an inclusive date range matching filter values."""
        table_id = self._table_id(table_name)
        clauses = ["date BETWEEN @start_date AND @end_date"]
        parameters: list[bigquery.ScalarQueryParameter] = [
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]

        for index, (key, value) in enumerate(filters.items()):
            self._validate_identifier(key, "filter field")
            parameter_name = f"filter_{index}"
            clauses.append(f"{key} = @{parameter_name}")
            parameters.append(
                bigquery.ScalarQueryParameter(parameter_name, "STRING", value)
            )

        query = f"""
        DELETE FROM `{table_id}`
        WHERE {" AND ".join(clauses)}
        """
        job_config = bigquery.QueryJobConfig(query_parameters=parameters)
        query_job = self.client.query(query, job_config=job_config)
        query_job.result()

        LOGGER.info(
            "Deleted rows from %s for %s to %s with filters %s.",
            table_id,
            start_date,
            end_date,
            sorted(filters.keys()),
        )

    def replace_date_range(
        self,
        table_name: str,
        rows: list[dict],
        start_date: str,
        end_date: str,
        filters: dict,
    ) -> int:
        """Delete matching rows in a date range, then insert replacement rows."""
        self.delete_date_range(
            table_name=table_name,
            start_date=start_date,
            end_date=end_date,
            filters=filters,
        )
        return self.insert_rows(table_name=table_name, rows=rows)

    def _table_id(self, table_name: str) -> str:
        """Return fully-qualified table id for a local table name."""
        self._validate_identifier(table_name, "table name")
        self._validate_identifier(self.dataset_id, "dataset id")
        return f"{self.project_id}.{self.dataset_id}.{table_name}"

    @staticmethod
    def _validate_identifier(value: str, label: str) -> None:
        """Validate BigQuery identifiers that are interpolated into SQL."""
        if not IDENTIFIER_PATTERN.match(value):
            raise ValueError(f"Invalid BigQuery {label}: {value}")
