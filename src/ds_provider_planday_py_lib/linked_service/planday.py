"""
**File:** ``planday.py``
**Region:** ``ds_provider_planday_py_lib/linked_service/planday.py``

Planday Linked Service

This module implements a linked service for Planday, allowing users to connect to and interact with
Planday API using OAuth 2.0 authorization code grant flow.

Authentication:
    Users provide OAuth2 credentials to connect to Planday:
    - client_id: OAuth 2.0 client identifier
    - code: Authorization code (one-time use)
    - redirect_uri: Redirect URI registered in Planday

The base class HttpLinkedService handles:
- OAuth2 token exchange and management
- Bearer token serialization
- Automatic token refresh

Example usage:
    >>> from uuid import uuid4
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

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from ds_protocol_http_py_lib import HttpLinkedService, HttpLinkedServiceSettings
from ds_protocol_http_py_lib.enums import AuthType
from ds_protocol_http_py_lib.linked_service import CustomAuthSettings

from ..enums import PlandayConstants, ResourceType


@dataclass(kw_only=True)
class PlandayLinkedServiceSettings(HttpLinkedServiceSettings):
    """
    Settings required to connect to Planday API using OAuth2 authorization code flow.

    The base class HttpLinkedService handles token exchange and Bearer token management
    using CustomAuthSettings to support the authorization code grant flow.

    Attributes:
        client_id: OAuth2 Client ID from Planday Developer Portal
        code: OAuth2 Authorization Code (one-time use)
        redirect_uri: OAuth2 Redirect URI registered in Planday
    """

    client_id: str = field(repr=False, metadata={"mask": True})
    """
    OAuth2 Client ID from Planday Developer Portal.

    Get it from: https://planday.com/account/integrations
    """

    code: str = field(repr=False, metadata={"mask": True})
    """
    OAuth2 Authorization Code (one-time use).

    Obtained from Planday OAuth flow when user authorizes the application.
    This code is exchanged for an access token.
    """

    redirect_uri: str = field(repr=False, metadata={"mask": True})
    """
    OAuth2 Redirect URI registered in Planday Developer Portal.

    Must match exactly what's registered in your Planday OAuth application.
    Example: https://yourdomain.com/auth/planday/callback
    """

    # Pre-filled Planday endpoints
    host: str = PlandayConstants.API_HOST
    """ Planday API host (pre-filled: https://openapi.planday.com/) """

    auth_type: AuthType = field(default=AuthType.CUSTOM)
    """ OAuth2 authentication type (pre-filled: CUSTOM) """

    def __post_init__(self) -> None:
        """
        Configure OAuth2 Custom Auth settings for Planday authorization code flow.

        Sets up the custom auth handler with the authorization code grant flow data.
        """
        self.custom = CustomAuthSettings(
            token_endpoint=PlandayConstants.TOKEN_ENDPOINT,
            data={
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "code": self.code,
                "redirect_uri": self.redirect_uri,
            },
        )


PlandayLinkedServiceSettingsType = TypeVar("PlandayLinkedServiceSettingsType", bound=PlandayLinkedServiceSettings)


@dataclass(kw_only=True)
class PlandayLinkedService(HttpLinkedService[PlandayLinkedServiceSettingsType], Generic[PlandayLinkedServiceSettingsType]):
    """
    Linked service for connecting to a Planday instance using OAuth 2.0 authorization code flow.

    This class extends HttpLinkedService which provides:
    - Automatic OAuth2 token exchange
    - Secure credential serialization
    - Bearer token management
    - Session handling
    """

    settings: PlandayLinkedServiceSettingsType
    """ The settings required to connect to the Planday instance. """

    @property
    def type(self) -> ResourceType:  # type: ignore[override]
        """
        Get the type of the linked service.

        Returns:
            ResourceType: The resource type for the Planday linked service.
        """
        return ResourceType.PLANDAY_LINKED_SERVICE
