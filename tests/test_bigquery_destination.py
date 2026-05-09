"""Tests for BigQuery destination helpers."""

from unittest.mock import Mock

from google.cloud import bigquery
import pytest

from src.destinations.bigquery import BigQueryDestination


def make_destination(client: Mock | None = None) -> BigQueryDestination:
    """Create a destination with a mock BigQuery client."""
    return BigQueryDestination(
        project_id="oudseed",
        dataset_id="ads_pipeline",
        client=client or Mock(),
    )


def test_insert_rows_returns_zero_for_empty_rows() -> None:
    """Empty inserts are a no-op."""
    client = Mock()
    destination = make_destination(client)

    assert destination.insert_rows("unified_ads_daily", []) == 0
    client.insert_rows_json.assert_not_called()


def test_insert_rows_inserts_json_rows() -> None:
    """Rows are inserted with the fully-qualified table id."""
    client = Mock()
    client.insert_rows_json.return_value = []
    destination = make_destination(client)

    count = destination.insert_rows("unified_ads_daily", [{"date": "2026-05-03"}])

    assert count == 1
    client.insert_rows_json.assert_called_once_with(
        "oudseed.ads_pipeline.unified_ads_daily",
        [{"date": "2026-05-03"}],
    )


def test_insert_rows_raises_readable_error() -> None:
    """BigQuery insert errors are surfaced with table context."""
    client = Mock()
    client.insert_rows_json.return_value = [{"index": 0, "errors": ["bad row"]}]
    destination = make_destination(client)

    with pytest.raises(RuntimeError, match="Failed to insert rows"):
        destination.insert_rows("unified_ads_daily", [{"date": "2026-05-03"}])


def test_insert_rows_error_message_is_summarized() -> None:
    """Large BigQuery error lists are summarized."""
    client = Mock()
    client.insert_rows_json.return_value = [
        {"index": index, "errors": ["bad row"]} for index in range(5)
    ]
    destination = make_destination(client)

    with pytest.raises(RuntimeError, match="5 row errors total"):
        destination.insert_rows("unified_ads_daily", [{"date": "2026-05-03"}])


def test_load_rows_returns_zero_for_empty_rows() -> None:
    """Empty load jobs are a no-op."""
    client = Mock()
    destination = make_destination(client)

    assert destination.load_rows("unified_ads_daily", []) == 0
    client.load_table_from_json.assert_not_called()


def test_load_rows_uses_bigquery_load_job() -> None:
    """Load jobs append rows without BigQuery streaming inserts."""
    load_job = Mock()
    client = Mock()
    client.load_table_from_json.return_value = load_job
    destination = make_destination(client)

    count = destination.load_rows("unified_ads_daily", [{"date": "2026-05-03"}])

    assert count == 1
    rows, table_id = client.load_table_from_json.call_args.args[:2]
    job_config = client.load_table_from_json.call_args.kwargs["job_config"]
    assert rows == [{"date": "2026-05-03"}]
    assert table_id == "oudseed.ads_pipeline.unified_ads_daily"
    assert job_config.write_disposition == bigquery.WriteDisposition.WRITE_APPEND
    load_job.result.assert_called_once()


def test_delete_date_range_uses_query_parameters() -> None:
    """Deletes use parameters for dates and filter values."""
    query_job = Mock()
    client = Mock()
    client.query.return_value = query_job
    destination = make_destination(client)

    destination.delete_date_range(
        table_name="unified_ads_daily",
        start_date="2026-04-26",
        end_date="2026-05-03",
        filters={"workspace_id": "mark_internal", "platform": "meta_ads"},
    )

    query = client.query.call_args.args[0]
    job_config = client.query.call_args.kwargs["job_config"]
    assert "DELETE FROM `oudseed.ads_pipeline.unified_ads_daily`" in query
    assert "date BETWEEN @start_date AND @end_date" in query
    assert "workspace_id = @filter_0" in query
    assert "platform = @filter_1" in query
    assert len(job_config.query_parameters) == 4
    query_job.result.assert_called_once()


def test_replace_date_range_deletes_then_inserts() -> None:
    """Replacement deletes matching rows before loading latest rows."""
    load_job = Mock()
    client = Mock()
    client.load_table_from_json.return_value = load_job
    client.query.return_value = Mock()
    destination = make_destination(client)

    count = destination.replace_date_range(
        table_name="unified_ads_daily",
        rows=[{"date": "2026-05-03"}],
        start_date="2026-04-26",
        end_date="2026-05-03",
        filters={"account_id": "act_000000000000000"},
    )

    assert count == 1
    client.query.assert_called_once()
    client.load_table_from_json.assert_called_once()
    client.insert_rows_json.assert_not_called()


def test_replace_date_range_with_empty_rows_still_deletes() -> None:
    """Empty replacement rows still clear the matching target range."""
    client = Mock()
    client.query.return_value = Mock()
    destination = make_destination(client)

    count = destination.replace_date_range(
        table_name="unified_ads_daily",
        rows=[],
        start_date="2026-04-26",
        end_date="2026-05-03",
        filters={"account_id": "act_000000000000000"},
    )

    assert count == 0
    client.query.assert_called_once()
    client.insert_rows_json.assert_not_called()
    client.load_table_from_json.assert_not_called()


def test_execute_sql_waits_for_query_completion() -> None:
    """Ad hoc SQL execution waits for the BigQuery job to finish."""
    query_job = Mock()
    client = Mock()
    client.query.return_value = query_job
    destination = make_destination(client)

    destination.execute_sql("SELECT 1")

    client.query.assert_called_once_with("SELECT 1")
    query_job.result.assert_called_once()


def test_query_rows_returns_dict_rows() -> None:
    """Parameterized queries return rows as plain dictionaries."""
    query_job = Mock()
    query_job.result.return_value = [{"name": "Campaign", "spend": 100.0}]
    client = Mock()
    client.query.return_value = query_job
    destination = make_destination(client)

    rows = destination.query_rows("SELECT @client_id", [])

    assert rows == [{"name": "Campaign", "spend": 100.0}]
    client.query.assert_called_once_with("SELECT @client_id", job_config=None)


def test_query_rows_uses_query_parameters() -> None:
    """Parameterized queries pass a BigQuery job config."""
    query_job = Mock()
    query_job.result.return_value = []
    client = Mock()
    client.query.return_value = query_job
    destination = make_destination(client)

    rows = destination.query_rows(
        "SELECT @client_id",
        [bigquery.ScalarQueryParameter("client_id", "STRING", "demo")],
    )

    assert rows == []
    job_config = client.query.call_args.kwargs["job_config"]
    assert len(job_config.query_parameters) == 1


def test_invalid_table_name_is_rejected() -> None:
    """Interpolated BigQuery identifiers are validated."""
    destination = make_destination()

    with pytest.raises(ValueError, match="Invalid BigQuery table name"):
        destination.insert_rows("bad-table-name", [{"date": "2026-05-03"}])


def test_invalid_filter_field_is_rejected() -> None:
    """Filter field names are validated before SQL is built."""
    destination = make_destination()

    with pytest.raises(ValueError, match="Invalid BigQuery filter field"):
        destination.delete_date_range(
            table_name="unified_ads_daily",
            start_date="2026-04-26",
            end_date="2026-05-03",
            filters={"bad-field": "value"},
        )
