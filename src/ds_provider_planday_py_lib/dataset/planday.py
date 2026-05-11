"""
**File:** ``planday.py``
**Region:** ``ds_provider_planday_py_lib/dataset/planday.py``

Planday Dataset

This module implements a dataset for Planday APIs.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, TypeVar

import pandas as pd  # type: ignore[import-untyped]
from ds_common_logger_py_lib import Logger
from ds_common_serde_py_lib import Serializable
from ds_resource_plugin_py_lib.common.resource.dataset import (
    DatasetSettings,
    DatasetStorageFormatType,
    TabularDataset,
)
from ds_resource_plugin_py_lib.common.resource.dataset.errors import (
    CreateError,
    DeleteError,
    ReadError,
    UpdateError,
)
from ds_resource_plugin_py_lib.common.resource.errors import NotSupportedError
from ds_resource_plugin_py_lib.common.serde.deserialize import PandasDeserializer
from ds_resource_plugin_py_lib.common.serde.serialize import PandasSerializer

from ..enums import PlandayDataProducts, ResourceType
from ..linked_service.planday import PlandayLinkedService

logger = Logger.get_logger(__name__, package=True)


@dataclass(kw_only=True)
class ReadSettings(Serializable):
    """Settings for Planday read() operation.

    Supports offset-based pagination and optional filtering parameters specific to Planday API.

    Common parameters are mapped explicitly. For any other Planday API parameters not listed
    here, use the `additional_params` field to pass them through.
    """

    offset: int = 0
    """Starting offset for pagination. Default is 0. Used to resume reads or start from a specific position."""

    limit: int = 50
    """Records per page for Planday API. Planday max is 50. Default is 50."""

    modified_from: str | None = None
    """Return records modified after this timestamp (for employees endpoint). Use yyyy-mm-ddThh:mm:ssZ format"""

    modified_to: str | None = None
    """Return records modified before this timestamp (for employees endpoint). Use yyyy-mm-ddThh:mm:ssZ format"""

    created_from: str | None = None
    """Return records created after given datetime. Use yyyy-mm-ddThh:mm:ssZ format"""

    created_to: str | None = None
    """Return records created before given datetime. Use yyyy-mm-ddThh:mm:ssZ format"""

    department_ids: list[str] | None = None
    """Filter by department IDs (for payroll endpoints). Pass list of department ID strings."""

    additional_params: dict[str, Any] | None = None
    """Additional query parameters to pass to the Planday API.

    Use this for any parameters not explicitly mapped above. Parameters here will be
    merged with the standard parameters. Example: {"includeArchived": True, "fields": "id,name"}
    """

    path_params: dict[str, str] | None = None
    """Path parameters for read() with templated endpoints (DATASET_CONTRACT rule).

    Some endpoints have path parameters like /employees/{employeeId}/details.
    Since read() has no self.input, path parameters must be provided via settings.
    Example: {"employeeId": "12345"}. Path parameters will be substituted into the
    endpoint URL before making the request.

    Note: For write methods (create/update/delete), path parameters are extracted
    from self.input row data (typically the identity column), not from settings.
    """


@dataclass(kw_only=True)
class PlandayDatasetSettings(DatasetSettings):
    """Settings for Planday dataset.

    Inherits params and path_params from parent DatasetSettings.
    These are populated by read() from the ReadSettings and used by HTTP layer.

    Attributes:
        data_product: The Planday data product to read (required).
        read: Read-specific settings for pagination and filtering.
    """

    data_product: PlandayDataProducts | None = None
    """Data product to read (e.g., PlandayDataProducts.EMPLOYEES).

    Used to look up the endpoint from query.json.
    """

    read: ReadSettings = field(default_factory=ReadSettings)
    """Settings for read() operation."""


PlandayDatasetSettingsType = TypeVar(
    "PlandayDatasetSettingsType",
    bound=PlandayDatasetSettings,
)
PlandayLinkedServiceType = TypeVar(
    "PlandayLinkedServiceType",
    bound=PlandayLinkedService[Any],
)


@dataclass(kw_only=True)
class PlandayDataset(
    TabularDataset[
        PlandayLinkedServiceType,
        PlandayDatasetSettingsType,
        PandasSerializer,
        PandasDeserializer,
    ],
    Generic[PlandayLinkedServiceType, PlandayDatasetSettingsType],
):
    """Planday Dataset implementation."""

    linked_service: PlandayLinkedServiceType
    settings: PlandayDatasetSettingsType

    serializer: PandasSerializer | None = field(
        default_factory=lambda: PandasSerializer(format=DatasetStorageFormatType.JSON),
    )
    deserializer: PandasDeserializer | None = field(
        default_factory=lambda: PandasDeserializer(format=DatasetStorageFormatType.JSON),
    )

    @property
    def type(self) -> ResourceType:
        return ResourceType.PLANDAY_DATASET

    @property
    def supports_checkpoint(self) -> bool:
        """
        Whether this provider supports incremental loads via ``self.checkpoint``.

        This implementation uses a simple dictionary-based checkpoint structure to
        support resuming paginated reads:

        - On a full load, ``self.checkpoint`` is expected to be empty (``{}``) or
          ``None``. In this case, :meth:`read` starts from offset ``0``.
        - After each successfully read, :meth:`read` sets
          ``self.checkpoint = {"offset": offset, ...}``, where ``offset`` is the
          next offset to fetch from.
        - On a subsequent run, if ``self.checkpoint`` contains an ``"offset"``
          entry, :meth:`read` resumes from that offset and continues
          fetching data from the Planday API.

        This allows consumers to perform incremental loads by persisting and
        reusing the checkpoint between executions, avoiding re-reading offsets that
        were already processed successfully.

        Returns:
             bool: True if checkpointing is supported, False otherwise.
        """
        return True

    def read(self) -> None:
        """
        Read data from a Planday API endpoint using offset-based pagination.

        Fetches complete dataset from the specified endpoint, handling pagination
        internally. Supports incremental loads via checkpoint.

        Builds query parameters from ReadSettings and sets them on self.settings.params
        for the HTTP layer to use.

        If a request fails (e.g., network error, API error):
        - Saves any data fetched so far to self.output (partial result)
        - Updates checkpoint with current offset (allows resuming from failure point)
        - Raises ReadError with details

        Raises:
            ReadError: If reading data fails.
        """
        if self.settings.data_product is None:
            raise ReadError(
                message="Data product must be specified in settings to read from Planday API.",
                details={"data_product": None},
            )

        all_data: list[Any] = []
        offset = 0

        try:
            endpoint = self._get_endpoint()
            logger.info(f"Reading from Planday API endpoint: {endpoint}")

            offset = self.checkpoint.get("offset", self.settings.read.offset) if self.checkpoint else self.settings.read.offset

            while True:
                # Build params from ReadSettings and set on settings
                # HTTP layer will use these params
                self.settings.params = self._build_read_params(offset)  # type: ignore[attr-defined]

                response = self.linked_service.session.get(endpoint, params=self.settings.params)  # type: ignore[attr-defined]

                if not response.ok:
                    raise ReadError(
                        message=f"Failed to read data from Planday API at offset {offset}.",
                        details={
                            "status_code": response.status_code,
                            "response_text": response.text,
                            "endpoint": endpoint,
                            "params": self.settings.params,  # type: ignore[attr-defined]
                            "records_fetched_before_error": len(all_data),
                        },
                    )

                data_page = response.json().get("data", [])
                all_data.extend(data_page)

                # Track offset for checkpoint
                offset += len(data_page)

                if len(data_page) < self.settings.read.limit:
                    # Last page reached - all records fetched
                    break

        except ReadError:
            raise
        except Exception as exc:
            raise ReadError(
                message=f"Unexpected error reading from Planday API at offset {offset}: {exc}",
                details={
                    "offset": offset,
                    "records_fetched": len(all_data),
                    "error_type": type(exc).__name__,
                },
            ) from exc

        finally:
            # Always save checkpoint and output (even on error with partial data)
            self.checkpoint = {"offset": offset}
            try:
                self.output = pd.DataFrame(all_data)
            except Exception as df_exc:
                # Dataframe conversion failed - set empty and log
                self.output = pd.DataFrame()
                logger.error(f"Failed to create DataFrame from {len(all_data)} records: {df_exc}")

    def _get_endpoint(self) -> str:
        """
        Load endpoint from query.json for the data product.

        Returns:
            str: Endpoint path like 'hr/v1.0/employees'

        Raises:
            ReadError: If data product is not specified or not found in query.json
        """
        if self.settings.data_product is None:
            raise ReadError(
                message="Data product must be specified",
                details={"data_product": None},
            )

        query_file = Path(__file__).parent / "query.json"
        with query_file.open() as f:
            query_config = json.load(f)

        product_key = self.settings.data_product.value
        if product_key not in query_config:
            raise ReadError(
                message=f"Data product '{product_key}' not found in query.json",
                details={"data_product": product_key},
            )

        endpoint_config = query_config[product_key]
        endpoint = endpoint_config.get("endpoint", "")
        # Substitute path parameters if present
        return self._resolve_endpoint_with_path_params(endpoint)

    def _get_endpoint_config(self) -> dict[str, Any]:
        """
        Load full endpoint config from query.json.

        Returns:
            dict: Full config including methods, endpoint, etc.

        Raises:
            ReadError: If endpoint not found
        """
        if self.settings.data_product is None:
            raise ReadError(
                message="Data product must be specified",
                details={"data_product": None},
            )

        query_file = Path(__file__).parent / "query.json"
        with query_file.open() as f:
            query_config = json.load(f)

        product_key = self.settings.data_product.value
        if product_key not in query_config:
            raise ReadError(
                message=f"Data product '{product_key}' not found in query.json",
                details={"data_product": product_key},
            )

        return query_config[product_key]  # type: ignore[no-any-return]

    def _get_supported_methods(self) -> list[str]:
        """
        Get supported HTTP methods for the endpoint.

        Returns:
            list[str]: List of HTTP methods (GET, POST, PUT, DELETE, etc.)
        """
        try:
            endpoint_config = self._get_endpoint_config()
            return endpoint_config.get("methods", ["GET"])  # type: ignore[no-any-return]
        except ReadError:
            return []

    def _has_pagination(self) -> bool:
        """
        Check if endpoint supports pagination.

        Returns:
            bool: True if endpoint has pagination enabled (pages=true in query.json)
        """
        try:
            endpoint_config = self._get_endpoint_config()
            return endpoint_config.get("pages", False)  # type: ignore[no-any-return]
        except ReadError:
            return False

    def _has_path_parameters(self, endpoint: str) -> bool:
        """
        Check if endpoint has path parameters.

        Args:
            endpoint: Endpoint URL template (e.g., 'hr/v1.0/employees/{employeeId}')

        Returns:
            bool: True if endpoint contains {param} placeholders
        """
        return "{" in endpoint and "}" in endpoint

    def _resolve_endpoint_with_path_params(self, endpoint: str, row_data: dict[str, Any] | None = None) -> str:
        """
        Substitute path parameters into endpoint URL placeholders.

        Path parameter resolution based on pagination and HTTP methods:
        - If endpoint has path params AND supports GET method (GET has no self.input):
          Read path params from settings (self.settings.read.path_params)
        - If endpoint has path params AND NO pagination AND supports other methods (PUT/POST/DELETE):
          Read path params from row_data (self.input row, passed as row_data parameter)

        Args:
            endpoint: Base endpoint like 'hr/v1.0/employees/{employeeId}'
            row_data: Optional row data from self.input (for write operations)

        Returns:
            str: Resolved endpoint with path params substituted,
                 e.g. 'hr/v1.0/employees/12345'

        Raises:
            ReadError: If required path parameter is missing
        """
        # If no path params needed, return endpoint as-is
        if not self._has_path_parameters(endpoint):
            return endpoint

        # Determine where to read path params from
        # Case 1: row_data provided (write operations) - use row_data for path params
        # Case 2: No row_data (read operations) - use settings
        path_params: dict[str, Any] = row_data or (self.settings.read.path_params or {})

        # Find all {param} placeholders and substitute
        placeholders = re.findall(r"\{([^}]+)\}", endpoint)
        resolved = endpoint

        for placeholder in placeholders:
            if placeholder not in path_params:
                raise ReadError(
                    message=f"Required path parameter '{placeholder}' not provided",
                    details={
                        "endpoint_template": endpoint,
                        "required_params": placeholders,
                        "provided_params": list(path_params.keys()),
                        "source": "row_data" if row_data else "settings.read.path_params",
                    },
                )
            resolved = resolved.replace(f"{{{placeholder}}}", str(path_params[placeholder]))

        return resolved

    def _build_read_params(self, offset: int) -> dict[str, Any]:
        """Build query parameters for Planday API using offset-based pagination.

        Includes standard parameters:
        - offset: starting position in result set
        - limit: records per page (max 50)

        Maps ReadSettings fields to Planday API parameter names if provided:
        - modified_from → modifiedFrom: for incremental loads
        - modified_to → modifiedTo: upper bound for modifications
        - created_from → createdFrom: filter by creation date
        - created_to → createdTo: upper bound for creation date
        - department_ids → departmentIds: filter by departments (comma-separated)

        Additional parameters from ReadSettings.additional_params are merged last
        and will override any of the above if there are conflicts.
        """
        params: dict[str, Any] = {
            "offset": offset,
            "limit": self.settings.read.limit,
        }

        # Add common optional parameters if provided
        if self.settings.read.modified_from:
            params["modifiedFrom"] = self.settings.read.modified_from

        if self.settings.read.modified_to:
            params["modifiedTo"] = self.settings.read.modified_to

        if self.settings.read.created_from:
            params["createdFrom"] = self.settings.read.created_from
        if self.settings.read.created_to:
            params["createdTo"] = self.settings.read.created_to

        if self.settings.read.department_ids:
            params["departmentIds"] = ",".join(self.settings.read.department_ids)

        # Merge any additional parameters passed by user (these override the above)
        if self.settings.read.additional_params:
            params.update(self.settings.read.additional_params)

        return params

    def create(self) -> None:
        """
        Insert rows into the target via POST.

        Per DATASET_CONTRACT: self.input drives the operation. Each row
        is sent as POST body to the endpoint. For endpoints with path
        parameters (e.g. /employees/{companyId}), extract the path param
        value from self.input row data.

        Raises:
            CreateError: If creation fails or endpoint doesn't support POST.
            NotSupportedError: If endpoint doesn't support POST method.
        """
        try:
            base_endpoint = self._get_endpoint_config().get("endpoint", "")
            supported_methods = self._get_supported_methods()

            if "POST" not in supported_methods:
                raise NotSupportedError(
                    f"Endpoint '{base_endpoint}' does not support create (POST not available). "
                    f"Supported methods: {', '.join(supported_methods)}"
                )

            if self.input is None or self.input.empty:
                self.output = pd.DataFrame()
                return

            created_records: list[dict[str, Any]] = []

            # Insert each row
            for row_dict in self.input.to_dict(orient="records"):
                # Resolve path parameters from row data if endpoint has them
                endpoint = self._resolve_endpoint_with_path_params(base_endpoint, row_dict)

                response = self.linked_service.session.post(endpoint, json=row_dict)  # type: ignore[attr-defined]

                if not response.ok:
                    raise CreateError(
                        message=f"Failed to create record at {endpoint}",
                        details={
                            "status_code": response.status_code,
                            "response_text": response.text,
                            "endpoint": endpoint,
                            "records_created_before_error": len(created_records),
                        },
                    )

                # Track created records from response
                try:
                    created_records.append(response.json())
                except Exception:
                    # If response isn't JSON, use input row
                    created_records.append(row_dict)

            # Per DATASET_CONTRACT: output = affected rows from backend or input copy
            self.output = pd.DataFrame(created_records) if created_records else self.input.copy()

        except (CreateError, NotSupportedError):
            raise
        except Exception as exc:
            raise CreateError(
                message=f"Unexpected error creating records: {exc}",
                details={"error_type": type(exc).__name__},
            ) from exc

    def update(self) -> None:
        """
        Update existing rows via PUT.

        Per DATASET_CONTRACT: self.input drives the operation. Row identity
        (typically 'id' column) is extracted from self.input to construct
        the resource URL. Path parameters come from row data.

        For endpoints with path parameters (e.g., /employees/{employeeId}/details),
        the path params are extracted from row data. For endpoints without path
        parameters, appends ID to the endpoint.

        Assumes 'id' column contains the resource identifier.
        Updates matching rows by ID.

        Raises:
            UpdateError: If update fails or endpoint doesn't support PUT.
            NotSupportedError: If endpoint doesn't support PUT method.
        """
        try:
            base_endpoint = self._get_endpoint_config().get("endpoint", "")
            supported_methods = self._get_supported_methods()

            if "PUT" not in supported_methods:
                raise NotSupportedError(
                    f"Endpoint '{base_endpoint}' does not support update (PUT not available). "
                    f"Supported methods: {', '.join(supported_methods)}"
                )

            # Empty input = no-op (per DATASET_CONTRACT)
            if self.input is None or self.input.empty:
                self.output = pd.DataFrame()
                return

            updated_records: list[dict[str, Any]] = []

            # Update each row
            for row_dict in self.input.to_dict(orient="records"):
                # Extract ID (assume 'id' column exists)
                item_id = row_dict.get("id")
                if not item_id:
                    raise UpdateError(
                        message="Cannot update: 'id' column required but not found",
                        details={"row": row_dict},
                    )

                # Resolve path parameters from row data if endpoint has them
                endpoint = self._resolve_endpoint_with_path_params(base_endpoint, row_dict)

                # If endpoint has no path parameters, append ID
                if not self._has_path_parameters(base_endpoint):
                    endpoint = f"{endpoint}/{item_id}"

                response = self.linked_service.session.put(endpoint, json=row_dict)  # type: ignore[attr-defined]

                if not response.ok:
                    raise UpdateError(
                        message=f"Failed to update record {item_id} at {endpoint}",
                        details={
                            "status_code": response.status_code,
                            "response_text": response.text,
                            "endpoint": endpoint,
                            "records_updated_before_error": len(updated_records),
                        },
                    )

                # Track updated records
                try:
                    updated_records.append(response.json())
                except Exception:
                    updated_records.append(row_dict)

            # Per DATASET_CONTRACT: output = affected rows from backend or input copy
            self.output = pd.DataFrame(updated_records) if updated_records else self.input.copy()

        except (UpdateError, NotSupportedError):
            raise
        except Exception as exc:
            raise UpdateError(
                message=f"Unexpected error updating records: {exc}",
                details={"error_type": type(exc).__name__},
            ) from exc

    def delete(self) -> None:
        """
        Delete specific rows via DELETE.

        Per DATASET_CONTRACT: self.input drives the operation. Row identity
        (typically 'id' column) is extracted from self.input to construct
        the resource URL. Path parameters come from row data.

        For endpoints with path parameters (e.g., /employees/{employeeId}/details),
        the path params are extracted from row data. For endpoints without path
        parameters, appends ID to the endpoint.

        Assumes 'id' column contains the resource identifier.
        Deletes matching rows by ID.

        Raises:
            DeleteError: If deletion fails or endpoint doesn't support DELETE.
            NotSupportedError: If endpoint doesn't support DELETE method.
        """
        try:
            base_endpoint = self._get_endpoint_config().get("endpoint", "")
            supported_methods = self._get_supported_methods()

            if "DELETE" not in supported_methods:
                raise NotSupportedError(
                    f"Endpoint '{base_endpoint}' does not support delete (DELETE not available). "
                    f"Supported methods: {', '.join(supported_methods)}"
                )

            # Empty input = no-op (per DATASET_CONTRACT)
            if self.input is None or self.input.empty:
                self.output = pd.DataFrame()
                return

            deleted_records: list[dict[str, Any]] = []

            # Delete each row
            for row_dict in self.input.to_dict(orient="records"):
                item_id = row_dict.get("id")
                if not item_id:
                    raise DeleteError(
                        message="Cannot delete: 'id' column required but not found",
                        details={"row": row_dict},
                    )

                # Resolve path parameters from row data if endpoint has them
                endpoint = self._resolve_endpoint_with_path_params(base_endpoint, row_dict)

                # If endpoint has no path parameters, append ID
                if not self._has_path_parameters(base_endpoint):
                    endpoint = f"{endpoint}/{item_id}"

                response = self.linked_service.session.delete(endpoint)  # type: ignore[attr-defined]

                if not response.ok:
                    raise DeleteError(
                        message=f"Failed to delete record {item_id} at {endpoint}",
                        details={
                            "status_code": response.status_code,
                            "response_text": response.text,
                            "endpoint": endpoint,
                            "records_deleted_before_error": len(deleted_records),
                        },
                    )

                deleted_records.append(row_dict)

            # Per DATASET_CONTRACT: output = affected rows (input copy for DELETE)
            self.output = self.input.copy()

        except (DeleteError, NotSupportedError):
            raise
        except Exception as exc:
            raise DeleteError(
                message=f"Unexpected error deleting records: {exc}",
                details={"error_type": type(exc).__name__},
            ) from exc

    def close(self) -> None:
        """Release any resources held by the dataset.

        For Planday, the dataset holds no resources directly.
        Connection lifecycle is managed by the linked service.
        """

    def rename(self) -> None:
        raise NotSupportedError("Method (rename) not supported by Planday provider.")

    def list(self) -> None:
        raise NotSupportedError("Method (list) not supported by Planday provider.")

    def upsert(self) -> None:
        raise NotSupportedError("Method (upsert) not supported by Planday provider.")

    def purge(self) -> None:
        raise NotSupportedError("Method (purge) not supported by Planday provider.")
