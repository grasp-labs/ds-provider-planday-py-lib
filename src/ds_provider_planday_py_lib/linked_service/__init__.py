"""
**File:** ``__init__.py``
**Region:** ``ds_provider_planday_py_lib/linked_service``

Planday Linked Service

This module implements a linked service for Planday and provides a session.

Example:
    >>> from uuid import UUID
    >>> linked_service = PlandayLinkedService(
    ...     id=UUID("00000000-0000-0000-0000-000000000000"),
    ...     name="test-name",
    ...     version="1.0.0",
    ...     settings=PlandayLinkedServiceSettings(
    ...         client_id="your_client_id",
    ...         code="authorization_code",
    ...         redirect_uri="https://yourdomain.com/callback",
    ...     ),
    ... )
    >>> linked_service.connect()
    >>> linked_service.test_connection()
"""

from .planday import PlandayLinkedService, PlandayLinkedServiceSettings

__all__ = [
    "PlandayLinkedService",
    "PlandayLinkedServiceSettings",
]
