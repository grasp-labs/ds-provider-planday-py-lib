"""
**File:** ``__init__.py``
**Region:** ``ds-provider-planday-py-lib``

Description
-----------
A Python package from the ds-provider-planday-py-lib library.

This package provides:
- Planday Linked Service for OAuth 2.0 authorization-code flow authentication
- Planday Data Products enumeration for available data endpoints
- Support for reading and writing data to Planday APIs via authenticated HTTP sessions

Example
-------
    >>> from uuid import uuid4
    >>> from ds_provider_planday_py_lib import PlandayLinkedService, PlandayLinkedServiceSettings, PlandayDataProducts
    >>> linked_service = PlandayLinkedService(
    ...     settings=PlandayLinkedServiceSettings(
    ...         client_id="your_client_id",
    ...         code="authorization_code",
    ...         redirect_uri="https://yourdomain.com/callback",
    ...     ),
    ...     id=uuid4(),
    ...     name="planday-connection",
    ...     version="1.0.0",
    ...     description="Planday API connection"
    ... )
    >>> # For testing credentials
    >>> success, message = linked_service.test_connection()
    >>> # For actual usage with persistent connection
    >>> linked_service.connect()
    >>> try:
    ...     session = linked_service.session  # Use session for API calls
    ... finally:
    ...     linked_service.close()
"""

from importlib.metadata import version

from .enums import PlandayDataProducts
from .linked_service import PlandayLinkedService, PlandayLinkedServiceSettings

__version__ = version("ds-provider-planday-py-lib")
__all__ = [
    "PlandayDataProducts",
    "PlandayLinkedService",
    "PlandayLinkedServiceSettings",
    "__version__",
]
