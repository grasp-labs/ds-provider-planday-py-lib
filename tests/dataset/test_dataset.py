"""
Tests for PlandayDataset implementation.

Tests cover:
- read() method with pagination
- checkpoint mechanism for resumable reads
- error handling and ReadError wrapping
- self.output population (partial on error)
- parameter building for Planday API
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pandas as pd
import pytest
from ds_resource_plugin_py_lib.common.resource.dataset.errors import ReadError
from ds_resource_plugin_py_lib.common.resource.errors import NotSupportedError

from ds_provider_planday_py_lib.dataset.planday import (
    PlandayDataset,
    PlandayDatasetSettings,
    ReadSettings,
)
from ds_provider_planday_py_lib.enums import PlandayDataProducts


@pytest.fixture
def mock_linked_service():
    """Create a mock linked service with session."""
    service = MagicMock()
    service.session = MagicMock()
    return service


@pytest.fixture
def dataset_settings():
    """Create dataset settings for employees endpoint."""
    return PlandayDatasetSettings(
        data_product=PlandayDataProducts.EMPLOYEES,
        read=ReadSettings(limit=50),
    )


@pytest.fixture
def dataset(mock_linked_service, dataset_settings):
    """Create a PlandayDataset instance with mocked linked service."""
    return PlandayDataset(
        id=uuid4(),
        name="test-dataset",
        version="1.0.0",
        linked_service=mock_linked_service,
        settings=dataset_settings,
    )


class TestReadSuccess:
    """Test successful read operations."""

    def test_read_single_page_full(self, dataset, mock_linked_service):
        """Test reading a single page (records < limit)."""
        # Setup: Mock API response with 30 records (< limit of 50)
        sample_data = [{"id": i, "name": f"Employee {i}"} for i in range(30)]
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "paging": {"offset": 0, "limit": 50, "total": 30},
            "data": sample_data,
        }
        mock_linked_service.session.get.return_value = mock_response

        # Execute
        dataset.read()

        # Verify output
        assert dataset.output is not None
        assert len(dataset.output) == 30
        assert list(dataset.output["id"]) == list(range(30))
        # Checkpoint updated with final offset
        assert dataset.checkpoint == {"offset": 30}

    def test_read_multiple_pages(self, dataset, mock_linked_service):
        """Test reading multiple pages (pagination)."""
        # Setup: Two requests - 50 records (first page), then 25 records (last page)
        page1_data = [{"id": i, "name": f"Employee {i}"} for i in range(50)]
        page2_data = [{"id": i, "name": f"Employee {i}"} for i in range(50, 75)]

        responses = [
            MagicMock(ok=True, json=MagicMock(return_value={"data": page1_data})),
            MagicMock(ok=True, json=MagicMock(return_value={"data": page2_data})),
        ]
        mock_linked_service.session.get.side_effect = responses

        # Execute
        dataset.read()

        # Verify
        assert len(dataset.output) == 75
        assert list(dataset.output["id"]) == list(range(75))
        assert dataset.checkpoint == {"offset": 75}

    def test_read_with_checkpoint_resume(self, dataset, mock_linked_service):
        """Test resuming read from checkpoint."""
        # Setup: Set checkpoint to resume from offset 50
        dataset.checkpoint = {"offset": 50}
        page_data = [{"id": i, "name": f"Employee {i}"} for i in range(50, 75)]
        mock_response = MagicMock(
            ok=True,
            json=MagicMock(return_value={"data": page_data}),
        )
        mock_linked_service.session.get.return_value = mock_response

        # Execute
        dataset.read()

        # Verify: Should have called with offset=50 in params
        call_args = mock_linked_service.session.get.call_args
        assert call_args[1]["params"]["offset"] == 50
        assert len(dataset.output) == 25
        assert dataset.checkpoint == {"offset": 75}

    def test_read_empty_result(self, dataset, mock_linked_service):
        """Test reading with empty result set."""
        mock_response = MagicMock(ok=True, json=MagicMock(return_value={"data": []}))
        mock_linked_service.session.get.return_value = mock_response

        # Execute
        dataset.read()

        # Verify: Output is empty DataFrame, checkpoint at 0
        assert len(dataset.output) == 0
        assert dataset.checkpoint == {"offset": 0}


class TestReadErrors:
    """Test error handling in read operations."""

    def test_read_no_data_product_raises(self, dataset, mock_linked_service):
        """Test that read raises ReadError when data_product is None."""
        dataset.settings.data_product = None

        with pytest.raises(ReadError) as exc_info:
            dataset.read()

        assert "Data product must be specified" in str(exc_info.value)

    def test_read_api_failure_partial_data_saved(self, dataset, mock_linked_service):
        """Test that partial data and checkpoint are saved on API failure."""
        # Setup: First request succeeds with 50 records, second fails
        page1_data = [{"id": i, "name": f"Employee {i}"} for i in range(50)]
        success_response = MagicMock(ok=True, json=MagicMock(return_value={"data": page1_data}))
        fail_response = MagicMock(ok=False, status_code=500, text="Internal Server Error")

        mock_linked_service.session.get.side_effect = [success_response, fail_response]

        # Execute and expect ReadError
        with pytest.raises(ReadError) as exc_info:
            dataset.read()

        # Verify: Partial data saved and checkpoint at 50
        assert len(dataset.output) == 50
        assert dataset.checkpoint == {"offset": 50}
        error = exc_info.value
        assert error.details["records_fetched_before_error"] == 50
        assert error.details["status_code"] == 500

    def test_read_http_error_raises_read_error(self, dataset, mock_linked_service):
        """Test that HTTP errors are wrapped as ReadError."""
        mock_response = MagicMock(
            ok=False,
            status_code=401,
            text="Unauthorized",
        )
        mock_linked_service.session.get.return_value = mock_response

        with pytest.raises(ReadError) as exc_info:
            dataset.read()

        error = exc_info.value
        assert error.details["status_code"] == 401
        assert "Unauthorized" in error.details["response_text"]

    def test_read_json_parse_error_wrapped(self, dataset, mock_linked_service):
        """Test that JSON parsing errors are wrapped as ReadError."""
        mock_response = MagicMock(ok=True)
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_linked_service.session.get.return_value = mock_response

        with pytest.raises(ReadError) as exc_info:
            dataset.read()

        error = exc_info.value
        assert "Unexpected error" in error.message
        assert error.details["error_type"] == "ValueError"

    def test_read_dataframe_conversion_error_sets_empty(self, dataset, mock_linked_service):
        """Test that DataFrame conversion errors set empty output and log (not raise)."""
        # Setup: Successful API response with data
        data = [{"col": None}]
        mock_response = MagicMock(ok=True)
        mock_response.json.return_value = {"data": data}
        mock_linked_service.session.get.return_value = mock_response

        # Mock DataFrame constructor to fail on first call (with data)
        # Use patch in the module where DataFrame is imported
        with patch("ds_provider_planday_py_lib.dataset.planday.pd.DataFrame") as mock_df:
            # First call fails, second call succeeds
            mock_df.side_effect = [
                Exception("DataFrame error"),
                pd.DataFrame(),  # Real empty DataFrame for second call
            ]
            # Should NOT raise - just set empty output and log
            dataset.read()

        # Verify: Empty DataFrame was set after error (method didn't raise)
        assert len(dataset.output) == 0


class TestCheckpointMechanism:
    """Test checkpoint functionality."""

    def test_supports_checkpoint_is_true(self, dataset):
        """Test that supports_checkpoint returns True."""
        assert dataset.supports_checkpoint is True

    def test_checkpoint_updated_after_each_fetch(self, dataset, mock_linked_service):
        """Test that checkpoint is updated after each successful fetch."""
        page1_data = [{"id": i} for i in range(50)]
        page2_data = [{"id": i} for i in range(50, 75)]

        responses = [
            MagicMock(ok=True, json=MagicMock(return_value={"data": page1_data})),
            MagicMock(ok=True, json=MagicMock(return_value={"data": page2_data})),
        ]
        mock_linked_service.session.get.side_effect = responses

        # Execute
        dataset.read()

        # Verify: Checkpoint is at final offset
        assert dataset.checkpoint == {"offset": 75}

    def test_checkpoint_preserved_on_error(self, dataset, mock_linked_service):
        """Test that checkpoint is preserved on error (partial load point)."""
        page1_data = [{"id": i} for i in range(50)]
        fail_response = MagicMock(ok=False, status_code=500, text="Error")

        mock_linked_service.session.get.side_effect = [
            MagicMock(ok=True, json=MagicMock(return_value={"data": page1_data})),
            fail_response,
        ]

        with pytest.raises(ReadError):
            dataset.read()

        # Checkpoint should be at point of failure
        assert dataset.checkpoint == {"offset": 50}


class TestReadParameters:
    """Test parameter building for read operations."""

    def test_read_params_includes_offset_and_limit(self, dataset):
        """Test that read params include offset and limit."""
        params = dataset._build_read_params(offset=0)

        assert params["offset"] == 0
        assert params["limit"] == 50  # Default limit

    def test_read_params_with_modified_from(self, dataset):
        """Test that modified_from is included in params."""
        dataset.settings.read.modified_from = "2024-01-01T00:00:00Z"
        params = dataset._build_read_params(offset=0)

        assert params["modifiedFrom"] == "2024-01-01T00:00:00Z"

    def test_read_params_with_department_ids(self, dataset):
        """Test that department_ids are comma-separated in params."""
        dataset.settings.read.department_ids = ["dept1", "dept2", "dept3"]
        params = dataset._build_read_params(offset=0)

        assert params["departmentIds"] == "dept1,dept2,dept3"

    def test_read_params_with_additional_params(self, dataset):
        """Test that additional_params are merged."""
        dataset.settings.read.additional_params = {
            "includeArchived": True,
            "fields": "id,name",
        }
        params = dataset._build_read_params(offset=0)

        assert params["includeArchived"] is True
        assert params["fields"] == "id,name"

    def test_read_params_additional_override(self, dataset):
        """Test that additional_params override standard params."""
        dataset.settings.read.additional_params = {"limit": 100}
        params = dataset._build_read_params(offset=0)

        # additional_params should override the standard limit
        assert params["limit"] == 100


class TestEndpointResolution:
    """Test endpoint resolution from query.json."""

    def test_get_endpoint_employees(self, dataset):
        """Test endpoint resolution for EMPLOYEES product."""
        endpoint = dataset._get_endpoint()
        assert endpoint == "hr/v1.0/employees"

    def test_get_endpoint_shifts(self, dataset):
        """Test endpoint resolution for different product."""
        dataset.settings.data_product = PlandayDataProducts.SHIFTS
        endpoint = dataset._get_endpoint()
        assert "shifts" in endpoint.lower() or "schedule" in endpoint.lower()

    def test_get_endpoint_not_found_raises(self, dataset):
        """Test that invalid product raises ReadError."""
        dataset.settings.data_product = None

        with pytest.raises(ReadError) as exc_info:
            dataset._get_endpoint()

        assert "Data product must be specified" in str(exc_info.value)


class TestUnsupportedMethods:
    """Test that unsupported methods raise NotSupportedError."""

    def test_create_not_supported(self, dataset):
        """Test create() raises NotSupportedError."""
        with pytest.raises(NotSupportedError):
            dataset.create()

    def test_update_not_supported(self, dataset):
        """Test update() raises NotSupportedError."""
        with pytest.raises(NotSupportedError):
            dataset.update()

    def test_delete_not_supported(self, dataset):
        """Test delete() raises NotSupportedError."""
        with pytest.raises(NotSupportedError):
            dataset.delete()

    def test_upsert_not_supported(self, dataset):
        """Test upsert() raises NotSupportedError."""
        with pytest.raises(NotSupportedError):
            dataset.upsert()

    def test_list_not_supported(self, dataset):
        """Test list() raises NotSupportedError."""
        with pytest.raises(NotSupportedError):
            dataset.list()

    def test_purge_not_supported(self, dataset):
        """Test purge() raises NotSupportedError."""
        with pytest.raises(NotSupportedError):
            dataset.purge()

    def test_rename_not_supported(self, dataset):
        """Test rename() raises NotSupportedError."""
        with pytest.raises(NotSupportedError):
            dataset.rename()


class TestOutputPopulation:
    """Test that self.output is always populated."""

    def test_output_populated_on_success(self, dataset, mock_linked_service):
        """Test output is populated after successful read."""
        data = [{"id": 1, "name": "Test"}]
        mock_response = MagicMock(ok=True, json=MagicMock(return_value={"data": data}))
        mock_linked_service.session.get.return_value = mock_response

        dataset.read()

        assert dataset.output is not None
        assert isinstance(dataset.output, pd.DataFrame)
        assert len(dataset.output) == 1

    def test_output_populated_partial_on_error(self, dataset, mock_linked_service):
        """Test output contains partial data on error."""
        # First page: 50 records (will trigger second request since 50 = limit)
        page1_data = [{"id": i} for i in range(50)]
        # Second response fails
        fail_response = MagicMock(ok=False, status_code=500, text="Error")

        mock_linked_service.session.get.side_effect = [
            MagicMock(ok=True, json=MagicMock(return_value={"data": page1_data})),
            fail_response,
        ]

        with pytest.raises(ReadError):
            dataset.read()

        # Partial data should be in output (first page's 50 records)
        assert len(dataset.output) == 50

    def test_output_empty_on_empty_result(self, dataset, mock_linked_service):
        """Test output is empty DataFrame on empty result."""
        mock_response = MagicMock(ok=True, json=MagicMock(return_value={"data": []}))
        mock_linked_service.session.get.return_value = mock_response

        dataset.read()

        assert isinstance(dataset.output, pd.DataFrame)
        assert len(dataset.output) == 0
