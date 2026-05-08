"""
Unit tests for PlandayLinkedService and PlandayLinkedServiceSettings.

This module tests:
- PlandayLinkedServiceSettings initialization and OAuth2 configuration
- PlandayLinkedService type and properties
- Custom auth settings setup
- Credentials masking
"""

from dataclasses import fields
from uuid import uuid4

import pytest
from ds_protocol_http_py_lib import HttpLinkedService
from ds_protocol_http_py_lib.enums import AuthType

from ds_provider_planday_py_lib.enums import PlandayConstants, ResourceType
from ds_provider_planday_py_lib.linked_service.planday import (
    PlandayLinkedService,
    PlandayLinkedServiceSettings,
)


class TestPlandayLinkedServiceSettings:
    """Test cases for PlandayLinkedServiceSettings configuration."""

    @pytest.fixture
    def valid_settings(self):
        """Fixture providing valid Planday settings."""
        return PlandayLinkedServiceSettings(
            client_id="test_client_id",
            code="test_authorization_code",
            redirect_uri="https://example.com/callback",
        )

    def test_settings_initialization(self, valid_settings):
        """Test that settings can be initialized with required parameters."""
        assert valid_settings.client_id == "test_client_id"
        assert valid_settings.code == "test_authorization_code"
        assert valid_settings.redirect_uri == "https://example.com/callback"

    def test_settings_host_defaults_to_planday_constant(self, valid_settings):
        """Test that host defaults to PlandayConstants.API_HOST."""
        assert valid_settings.host == PlandayConstants.API_HOST
        assert valid_settings.host == "https://openapi.planday.com/"

    def test_settings_auth_type_set_to_custom(self, valid_settings):
        """Test that auth_type is set to CUSTOM in __post_init__."""
        assert valid_settings.auth_type == AuthType.CUSTOM

    def test_settings_custom_auth_configured(self, valid_settings):
        """Test that CustomAuthSettings is properly configured."""
        assert valid_settings.custom is not None
        assert valid_settings.custom.token_endpoint == PlandayConstants.TOKEN_ENDPOINT
        assert valid_settings.custom.token_endpoint == "https://openapi.planday.com/oauth/token"

    def test_settings_custom_auth_data_structure(self, valid_settings):
        """Test that custom auth data contains correct OAuth2 fields."""
        auth_data = valid_settings.custom.data

        assert auth_data["grant_type"] == "authorization_code"
        assert auth_data["client_id"] == "test_client_id"
        assert auth_data["code"] == "test_authorization_code"
        assert auth_data["redirect_uri"] == "https://example.com/callback"

    def test_settings_credentials_masked_in_repr(self, valid_settings):
        """Test that sensitive fields are marked with mask metadata."""
        # Get field metadata
        field_map = {f.name: f for f in fields(PlandayLinkedServiceSettings)}

        assert field_map["client_id"].metadata.get("mask") is True
        assert field_map["code"].metadata.get("mask") is True
        assert field_map["redirect_uri"].metadata.get("mask") is True

    def test_settings_with_custom_host(self):
        """Test that custom host can be provided."""
        custom_host = "https://custom.example.com/"
        settings = PlandayLinkedServiceSettings(
            client_id="test_client_id",
            code="test_code",
            redirect_uri="https://example.com/callback",
            host=custom_host,
        )
        assert settings.host == custom_host

    def test_settings_required_parameters_validation(self):
        """Test that required parameters must be provided."""
        with pytest.raises(TypeError):
            # Missing required parameters
            PlandayLinkedServiceSettings()


class TestPlandayLinkedService:
    """Test cases for PlandayLinkedService."""

    @pytest.fixture
    def linked_service_settings(self):
        """Fixture providing valid settings."""
        return PlandayLinkedServiceSettings(
            client_id="test_client_id",
            code="test_authorization_code",
            redirect_uri="https://example.com/callback",
        )

    @pytest.fixture
    def linked_service(self, linked_service_settings):
        """Fixture providing a PlandayLinkedService instance."""
        service_id = uuid4()
        return PlandayLinkedService(
            settings=linked_service_settings,
            id=service_id,
            name="test-planday-service",
            version="1.0.0",
            description="Test Planday connection",
        )

    def test_linked_service_initialization(self, linked_service):
        """Test that linked service initializes with correct properties."""
        assert linked_service.name == "test-planday-service"
        assert linked_service.version == "1.0.0"
        assert linked_service.description == "Test Planday connection"

    def test_linked_service_type_property(self, linked_service):
        """Test that type property returns correct ResourceType."""
        assert linked_service.type == ResourceType.PLANDAY_LINKED_SERVICE
        assert linked_service.type == "ds.resource.linked-service.planday"

    def test_linked_service_settings_accessible(self, linked_service, linked_service_settings):
        """Test that settings are accessible through the service."""
        assert linked_service.settings == linked_service_settings
        assert linked_service.settings.client_id == "test_client_id"
        assert linked_service.settings.code == "test_authorization_code"

    def test_linked_service_inherits_from_http_linked_service(self, linked_service):
        """Test that PlandayLinkedService is instance of HttpLinkedService."""
        assert isinstance(linked_service, HttpLinkedService)

    def test_linked_service_with_minimal_configuration(self):
        """Test creating a linked service with minimal configuration."""
        settings = PlandayLinkedServiceSettings(
            client_id="minimal_client",
            code="minimal_code",
            redirect_uri="https://example.com/callback",
        )
        service = PlandayLinkedService(
            settings=settings,
            id=uuid4(),
            name="minimal-service",
            version="1.0.0",
        )

        assert service.name == "minimal-service"
        assert service.type == ResourceType.PLANDAY_LINKED_SERVICE

    def test_linked_service_settings_integrity(self, linked_service):
        """Test that settings maintain integrity through service."""
        original_settings = linked_service.settings

        # Verify OAuth2 configuration is maintained
        assert original_settings.auth_type == AuthType.CUSTOM
        assert original_settings.custom.token_endpoint == PlandayConstants.TOKEN_ENDPOINT

        # Verify credentials are preserved
        assert original_settings.client_id == "test_client_id"
        assert original_settings.code == "test_authorization_code"


class TestOAuth2Configuration:
    """Test cases for OAuth2 configuration in PlandayLinkedService."""

    def test_oauth2_token_endpoint_constant(self):
        """Test that OAuth2 token endpoint is correctly configured."""
        assert PlandayConstants.TOKEN_ENDPOINT == "https://openapi.planday.com/oauth/token"

    def test_oauth2_api_host_constant(self):
        """Test that API host constant is correctly configured."""
        assert PlandayConstants.API_HOST == "https://openapi.planday.com/"

    def test_oauth2_auth_type_constant(self):
        """Test that auth type is CUSTOM."""
        assert PlandayConstants.AUTH_TYPE == AuthType.CUSTOM

    def test_authorization_code_grant_flow_setup(self):
        """Test that authorization code grant flow is properly configured."""
        settings = PlandayLinkedServiceSettings(
            client_id="oauth_client",
            code="oauth_code",
            redirect_uri="https://example.com/oauth/callback",
        )

        auth_data = settings.custom.data
        assert auth_data["grant_type"] == "authorization_code"
        assert "client_id" in auth_data
        assert "code" in auth_data
        assert "redirect_uri" in auth_data


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_settings_with_special_characters_in_credentials(self):
        """Test that credentials with special characters are handled."""
        settings = PlandayLinkedServiceSettings(
            client_id="client_with!@#$%special",
            code="code_with_/=+special",
            redirect_uri="https://example.com/callback?param=value&other=123",
        )

        assert settings.client_id == "client_with!@#$%special"
        assert settings.code == "code_with_/=+special"
        assert "param=value" in settings.redirect_uri

    def test_settings_with_empty_description(self):
        """Test linked service can be created without description."""
        settings = PlandayLinkedServiceSettings(
            client_id="test",
            code="test",
            redirect_uri="https://example.com/callback",
        )
        service = PlandayLinkedService(
            settings=settings,
            id=uuid4(),
            name="test-service",
            version="1.0.0",
        )

        # Description might be None or empty depending on parent class
        assert service.name == "test-service"

    def test_settings_preserves_redirect_uri_with_query_params(self):
        """Test that redirect URI with query parameters is preserved."""
        redirect_with_params = "https://example.com/callback?state=xyz&client=abc"
        settings = PlandayLinkedServiceSettings(
            client_id="test",
            code="test",
            redirect_uri=redirect_with_params,
        )

        assert settings.redirect_uri == redirect_with_params
        assert settings.custom.data["redirect_uri"] == redirect_with_params
