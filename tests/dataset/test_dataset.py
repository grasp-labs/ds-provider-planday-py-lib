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
from ds_resource_plugin_py_lib.common.resource.dataset.errors import (
    CreateError,
    DeleteError,
    ReadError,
    UpdateError,
)
from ds_resource_plugin_py_lib.common.resource.errors import NotSupportedError

from ds_provider_planday_py_lib.dataset.planday import (
    PlandayDataset,
    PlandayDatasetSettings,
    ReadSettings,
)
from ds_provider_planday_py_lib.enums import PlandayDataProducts, ResourceType


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


@pytest.fixture
def dataset_with_delete_support(mock_linked_service):
    """Create a PlandayDataset with endpoint that supports DELETE method.

    Uses EMPLOYEE_GROUP_DETAILS endpoint which supports GET, PUT, DELETE
    with pages=false, so path parameters are read from row data.
    """
    settings = PlandayDatasetSettings(
        data_product=PlandayDataProducts.EMPLOYEE_GROUP_DETAILS,
        read=ReadSettings(limit=50),
    )
    return PlandayDataset(
        id=uuid4(),
        name="test-dataset-delete",
        version="1.0.0",
        linked_service=mock_linked_service,
        settings=settings,
    )


@pytest.fixture
def dataset_unsupported_methods(mock_linked_service):
    """Create a PlandayDataset with endpoint that doesn't support create/update/delete.

    Uses EMPLOYEE_TYPE endpoint which only supports GET method.
    """
    settings = PlandayDatasetSettings(
        data_product=PlandayDataProducts.EMPLOYEE_TYPE,
        read=ReadSettings(limit=50),
    )
    return PlandayDataset(
        id=uuid4(),
        name="test-dataset-unsupported",
        version="1.0.0",
        linked_service=mock_linked_service,
        settings=settings,
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

    def test_create_not_supported(self, dataset_unsupported_methods):
        """Test create() raises NotSupportedError."""
        with pytest.raises(NotSupportedError):
            dataset_unsupported_methods.create()

    def test_update_not_supported(self, dataset_unsupported_methods):
        """Test update() raises NotSupportedError."""
        with pytest.raises(NotSupportedError):
            dataset_unsupported_methods.update()

    def test_delete_not_supported(self, dataset_unsupported_methods):
        """Test delete() raises NotSupportedError."""
        with pytest.raises(NotSupportedError):
            dataset_unsupported_methods.delete()

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


class TestCreateMethod:
    """Test create() method for POST operations."""

    def test_create_empty_input(self, dataset):
        """Test create() with empty input returns empty output."""
        dataset.input = pd.DataFrame()
        dataset.create()

        assert dataset.output is not None
        assert len(dataset.output) == 0

    def test_create_single_record(self, dataset, mock_linked_service):
        """Test creating a single record."""
        # Setup
        dataset.input = pd.DataFrame([{"id": 1, "name": "John"}])
        mock_response = MagicMock(ok=True)
        mock_response.json.return_value = {"id": 101, "name": "John"}
        mock_linked_service.session.post.return_value = mock_response

        # Execute
        dataset.create()

        # Verify
        assert len(dataset.output) == 1
        assert dataset.output.iloc[0]["id"] == 101
        mock_linked_service.session.post.assert_called_once()

    def test_create_multiple_records(self, dataset, mock_linked_service):
        """Test creating multiple records."""
        # Setup
        dataset.input = pd.DataFrame(
            [
                {"id": 1, "name": "John"},
                {"id": 2, "name": "Jane"},
            ]
        )
        responses = [
            MagicMock(ok=True, json=MagicMock(return_value={"id": 101, "name": "John"})),
            MagicMock(ok=True, json=MagicMock(return_value={"id": 102, "name": "Jane"})),
        ]
        mock_linked_service.session.post.side_effect = responses

        # Execute
        dataset.create()

        # Verify
        assert len(dataset.output) == 2
        assert mock_linked_service.session.post.call_count == 2

    def test_create_api_error_raises(self, dataset, mock_linked_service):
        """Test create() raises CreateError on API failure."""
        # Setup
        dataset.input = pd.DataFrame([{"id": 1, "name": "John"}])
        mock_response = MagicMock(ok=False, status_code=400, text="Bad Request")
        mock_linked_service.session.post.return_value = mock_response

        # Execute
        with pytest.raises(CreateError) as exc_info:
            dataset.create()

        assert exc_info.value.details["status_code"] == 400

    def test_create_response_not_json_uses_input(self, dataset, mock_linked_service):
        """Test create() uses input row if response isn't JSON."""
        # Setup
        dataset.input = pd.DataFrame([{"id": 1, "name": "John"}])
        mock_response = MagicMock(ok=True)
        mock_response.json.side_effect = ValueError("Not JSON")
        mock_linked_service.session.post.return_value = mock_response

        # Execute
        dataset.create()

        # Verify: Input row is used when response isn't JSON
        assert len(dataset.output) == 1
        assert dataset.output.iloc[0]["name"] == "John"

    def test_create_unexpected_exception_wrapped(self, dataset, mock_linked_service):
        """Test create() wraps unexpected exceptions as CreateError."""
        # Setup: Simulate unexpected error
        dataset.input = pd.DataFrame([{"id": 1, "name": "John"}])
        mock_linked_service.session.post.side_effect = RuntimeError("Connection failed")

        # Execute
        with pytest.raises(CreateError) as exc_info:
            dataset.create()

        assert "Unexpected error" in exc_info.value.message
        assert exc_info.value.details["error_type"] == "RuntimeError"


class TestUpdateMethod:
    """Test update() method for PUT operations."""

    def test_update_empty_input(self, dataset):
        """Test update() with empty input returns empty output."""
        dataset.input = pd.DataFrame()
        dataset.update()

        assert dataset.output is not None
        assert len(dataset.output) == 0

    def test_update_single_record_without_path_params(self, dataset, mock_linked_service):
        """Test updating a single record (no path params, append ID)."""
        # Setup
        dataset.input = pd.DataFrame([{"id": 101, "name": "John Updated"}])
        mock_response = MagicMock(ok=True)
        mock_response.json.return_value = {"id": 101, "name": "John Updated"}
        mock_linked_service.session.put.return_value = mock_response

        # Execute
        dataset.update()

        # Verify: Should PUT to /endpoint/ID
        call_args = mock_linked_service.session.put.call_args
        assert "/101" in call_args[0][0]
        assert len(dataset.output) == 1

    def test_update_missing_id_raises_error(self, dataset):
        """Test update() raises UpdateError when 'id' column is missing."""
        # Setup: Row without 'id' column
        dataset.input = pd.DataFrame([{"name": "John"}])

        # Execute
        with pytest.raises(UpdateError) as exc_info:
            dataset.update()

        assert "'id' column required" in exc_info.value.message

    def test_update_api_error_raises(self, dataset, mock_linked_service):
        """Test update() raises UpdateError on API failure."""
        # Setup
        dataset.input = pd.DataFrame([{"id": 101, "name": "John"}])
        mock_response = MagicMock(ok=False, status_code=404, text="Not Found")
        mock_linked_service.session.put.return_value = mock_response

        # Execute
        with pytest.raises(UpdateError):
            dataset.update()

    def test_update_unexpected_exception_wrapped(self, dataset, mock_linked_service):
        """Test update() wraps unexpected exceptions as UpdateError."""
        # Setup
        dataset.input = pd.DataFrame([{"id": 101, "name": "John"}])
        mock_linked_service.session.put.side_effect = RuntimeError("Connection failed")

        # Execute
        with pytest.raises(UpdateError) as exc_info:
            dataset.update()

        assert "Unexpected error" in exc_info.value.message
        assert exc_info.value.details["error_type"] == "RuntimeError"


class TestDeleteMethod:
    """Test delete() method for DELETE operations."""

    def test_delete_empty_input(self, dataset_with_delete_support):
        """Test delete() with empty input returns empty output."""
        dataset_with_delete_support.input = pd.DataFrame()
        dataset_with_delete_support.delete()

        assert dataset_with_delete_support.output is not None
        assert len(dataset_with_delete_support.output) == 0

    def test_delete_single_record_without_path_params(self, dataset_with_delete_support, mock_linked_service):
        """Test deleting a single record (no path params, append ID)."""
        # Setup
        dataset_with_delete_support.input = pd.DataFrame([{"id": 101, "name": "John"}])
        mock_response = MagicMock(ok=True, status_code=204)
        mock_linked_service.session.delete.return_value = mock_response

        # Execute
        dataset_with_delete_support.delete()

        # Verify: Should DELETE /endpoint/ID
        call_args = mock_linked_service.session.delete.call_args
        assert "/101" in call_args[0][0]
        assert len(dataset_with_delete_support.output) == 1

    def test_delete_multiple_records(self, dataset_with_delete_support, mock_linked_service):
        """Test deleting multiple records."""
        # Setup
        dataset_with_delete_support.input = pd.DataFrame(
            [
                {"id": 101, "name": "John"},
                {"id": 102, "name": "Jane"},
            ]
        )
        mock_response = MagicMock(ok=True, status_code=204)
        mock_linked_service.session.delete.return_value = mock_response

        # Execute
        dataset_with_delete_support.delete()

        # Verify
        assert len(dataset_with_delete_support.output) == 2
        assert mock_linked_service.session.delete.call_count == 2

    def test_delete_missing_id_raises_error(self, dataset_with_delete_support):
        """Test delete() raises DeleteError when 'id' column is missing."""
        # Setup: Row without 'id' column
        dataset_with_delete_support.input = pd.DataFrame([{"name": "John"}])

        # Execute
        with pytest.raises(DeleteError):
            dataset_with_delete_support.delete()

    def test_delete_api_error_raises(self, dataset_with_delete_support, mock_linked_service):
        """Test delete() raises DeleteError on API failure."""
        # Setup
        dataset_with_delete_support.input = pd.DataFrame([{"id": 101}])
        mock_response = MagicMock(ok=False, status_code=404, text="Not Found")
        mock_linked_service.session.delete.return_value = mock_response

        # Execute
        with pytest.raises(DeleteError):
            dataset_with_delete_support.delete()

    def test_delete_unexpected_exception_wrapped(self, dataset_with_delete_support, mock_linked_service):
        """Test delete() wraps unexpected exceptions as DeleteError."""
        # Setup
        dataset_with_delete_support.input = pd.DataFrame([{"id": 101}])
        mock_linked_service.session.delete.side_effect = RuntimeError("Connection failed")

        # Execute
        with pytest.raises(DeleteError) as exc_info:
            dataset_with_delete_support.delete()

        assert "Unexpected error" in exc_info.value.message
        assert exc_info.value.details["error_type"] == "RuntimeError"


class TestPathParameterResolution:
    """Test path parameter resolution for endpoints with templated URLs."""

    def test_endpoint_without_path_params(self, dataset):
        """Test endpoint without path parameters passes through."""
        result = dataset._resolve_endpoint_with_path_params("hr/v1.0/employees")
        assert result == "hr/v1.0/employees"

    def test_has_path_parameters_detection(self, dataset):
        """Test detecting endpoints with path parameters."""
        assert dataset._has_path_parameters("hr/v1.0/employees/{id}") is True
        assert dataset._has_path_parameters("hr/v1.0/employees") is False

    def test_read_with_path_params_from_settings(self, mock_linked_service):
        """Test read() resolves path params from settings for GET endpoints."""
        # Setup: Create dataset with endpoint that has path params and supports GET
        settings = PlandayDatasetSettings(
            data_product=PlandayDataProducts.EMPLOYEE_GROUP_DETAILS,
            read=ReadSettings(limit=50, path_params={"id": "group123"}),
        )
        dataset = PlandayDataset(
            id=uuid4(),
            name="test-path-params",
            version="1.0.0",
            linked_service=mock_linked_service,
            settings=settings,
        )

        mock_response = MagicMock(ok=True)
        mock_response.json.return_value = {"data": []}
        mock_linked_service.session.get.return_value = mock_response

        # Execute
        dataset.read()

        # Verify: URL should contain resolved path param
        call_args = mock_linked_service.session.get.call_args
        endpoint_url = call_args[0][0]
        assert "group123" in endpoint_url
        assert "{id}" not in endpoint_url

    def test_path_params_missing_from_settings_raises_error(self, dataset):
        """Test that missing path params in settings raises ReadError."""
        # Setup: Dataset with path param endpoint but no path_params in settings
        dataset.settings.read.path_params = None

        # Execute - should raise ReadError
        with pytest.raises(ReadError) as exc_info:
            dataset._resolve_endpoint_with_path_params("hr/v1.0/employees/{id}")

        assert "'id' not provided" in exc_info.value.message

    def test_path_params_missing_from_row_data_raises_error(self, dataset_with_delete_support):
        """Test that missing path params in row data raises ReadError."""
        # Row data without required 'id' field for path param resolution
        row_data = {"name": "John"}  # Missing 'id'

        # Execute - should raise ReadError
        with pytest.raises(ReadError) as exc_info:
            dataset_with_delete_support._resolve_endpoint_with_path_params("hr/v1.0/employeegroups/{id}", row_data)

        assert "'id' not provided" in exc_info.value.message


class TestPropertiesAndAttributes:
    """Test dataset properties and attributes."""

    def test_supports_checkpoint_property(self, dataset):
        """Test that supports_checkpoint property returns True."""
        assert dataset.supports_checkpoint is True

    def test_type_property(self, dataset):
        """Test that type property returns PLANDAY_DATASET."""
        assert dataset.type == ResourceType.PLANDAY_DATASET


class TestUpdateWithMissingId:
    """Test update() behavior when 'id' is missing from row data."""

    def test_update_missing_id_raises_error(self, dataset, mock_linked_service):
        """Test update() raises UpdateError when 'id' column is missing."""
        # Setup: Row without 'id' field
        dataset.input = pd.DataFrame([{"name": "John"}])

        # Execute
        with pytest.raises(UpdateError) as exc_info:
            dataset.update()

        assert "'id' column required" in exc_info.value.message


class TestDeleteWithMissingId:
    """Test delete() behavior when 'id' is missing from row data."""

    def test_delete_missing_id_raises_error(self, dataset_with_delete_support, mock_linked_service):
        """Test delete() raises DeleteError when 'id' column is missing."""
        # Setup: Row without 'id' field
        dataset_with_delete_support.input = pd.DataFrame([{"name": "John"}])

        # Execute
        with pytest.raises(DeleteError) as exc_info:
            dataset_with_delete_support.delete()

        assert "'id' column required" in exc_info.value.message


class TestEdgeCasesAndBranches:
    """Test additional edge cases to improve code coverage."""

    def test_read_uses_settings_offset_when_no_checkpoint(self, dataset, mock_linked_service):
        """Test that read() uses settings.read.offset when checkpoint is not set."""
        # Setup: No checkpoint, set custom offset in settings
        dataset.checkpoint = None
        dataset.settings.read.offset = 10

        mock_response = MagicMock(ok=True)
        mock_response.json.return_value = {"data": [{"id": 1}]}
        mock_linked_service.session.get.return_value = mock_response

        # Execute
        dataset.read()

        # Verify: First GET call uses offset=10 from settings
        call_args = mock_linked_service.session.get.call_args
        params = call_args[1]["params"]
        assert params["offset"] == 10

    def test_read_empty_checkpoint_returns_offset_zero(self, dataset, mock_linked_service):
        """Test that read with empty checkpoint starts from offset 0."""
        # Setup: Empty checkpoint means starting from offset 0
        dataset.checkpoint = {}

        mock_response = MagicMock(ok=True)
        mock_response.json.return_value = {"data": [{"id": 1}]}
        mock_linked_service.session.get.return_value = mock_response

        # Execute
        dataset.read()

        # Verify: First GET call includes offset=0 in params
        call_args = mock_linked_service.session.get.call_args
        params = call_args[1]["params"]
        assert params["offset"] == 0

    def test_create_with_valid_json_response(self, dataset, mock_linked_service):
        """Test create() properly handles valid JSON response."""
        # Setup
        dataset.input = pd.DataFrame([{"id": 1, "name": "John"}])
        mock_response = MagicMock(ok=True)
        mock_response.json.return_value = {"id": 101, "name": "John", "created_at": "2025-01-01"}
        mock_linked_service.session.post.return_value = mock_response

        # Execute
        dataset.create()

        # Verify: Output contains the API response
        assert len(dataset.output) == 1
        assert dataset.output.iloc[0]["id"] == 101

    def test_update_with_valid_json_response(self, dataset, mock_linked_service):
        """Test update() properly handles valid JSON response."""
        # Setup
        dataset.input = pd.DataFrame([{"id": 1, "name": "John"}])
        mock_response = MagicMock(ok=True)
        mock_response.json.return_value = {"id": 1, "name": "John Updated"}
        mock_linked_service.session.put.return_value = mock_response

        # Execute
        dataset.update()

        # Verify: Output contains the API response
        assert len(dataset.output) == 1
        assert dataset.output.iloc[0]["name"] == "John Updated"

    def test_delete_success_returns_input_copy(self, dataset_with_delete_support, mock_linked_service):
        """Test delete() returns input copy as output on success."""
        # Setup
        input_data = pd.DataFrame([{"id": 1, "name": "John"}])
        dataset_with_delete_support.input = input_data
        mock_response = MagicMock(ok=True)
        mock_linked_service.session.delete.return_value = mock_response

        # Execute
        dataset_with_delete_support.delete()

        # Verify: Output is a copy of input
        assert len(dataset_with_delete_support.output) == 1
        assert dataset_with_delete_support.output.iloc[0]["id"] == 1
        assert dataset_with_delete_support.output.iloc[0]["name"] == "John"

    def test_get_supported_methods_returns_list(self, dataset):
        """Test _get_supported_methods returns list of methods."""
        methods = dataset._get_supported_methods()
        assert isinstance(methods, list)
        assert "GET" in methods
        assert "POST" in methods
        assert "PUT" in methods

    def test_get_supported_methods_on_error(self, dataset):
        """Test _get_supported_methods returns empty list on error."""
        # Mock the data_product to None to trigger error
        dataset.settings.data_product = None
        methods = dataset._get_supported_methods()
        assert methods == []

    def test_has_pagination_on_error(self, dataset):
        """Test _has_pagination returns False on error."""
        # Mock the data_product to None to trigger error
        dataset.settings.data_product = None
        has_paging = dataset._has_pagination()
        assert has_paging is False

    def test_close_method_does_nothing(self, dataset):
        """Test close() method executes without error."""
        # Should not raise any exception
        dataset.close()


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
