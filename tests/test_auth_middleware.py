"""Tests for API Key authentication middleware."""

import os
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.middleware.auth import (
    APIKeyMiddleware,
    DEFAULT_PUBLIC_ROUTES,
    PROTECTED_ROUTES,
    generate_api_key,
    get_api_key,
    get_api_key_header,
    get_public_routes,
    is_public_route,
)


class TestIsPublicRoute:
    """Tests for the is_public_route function."""

    def test_root_path_is_public(self):
        """Root path should be public."""
        assert is_public_route("/") is True

    def test_root_path_does_not_match_all_paths(self):
        """The '/' route should only match exactly '/', not as a prefix."""
        # This was the security vulnerability - these should NOT be public
        assert is_public_route("/arbitrary/path") is False
        assert is_public_route("/some-endpoint") is False

    def test_health_endpoint_is_public(self):
        """Health check endpoint should be public."""
        assert is_public_route("/health") is True

    def test_docs_endpoints_are_public(self):
        """Documentation endpoints should be public."""
        assert is_public_route("/docs") is True
        assert is_public_route("/redoc") is True
        assert is_public_route("/openapi.json") is True

    def test_dashboard_stats_is_public(self):
        """Dashboard stats should be public."""
        assert is_public_route("/dashboard/stats") is True
        assert is_public_route("/dashboard/trends") is True
        assert is_public_route("/dashboard/crashes/geojson") is True

    def test_dashboard_location_report_is_public(self):
        """Location report endpoint should be public (read-only crash data)."""
        assert is_public_route("/dashboard/location-report") is True

    def test_dashboard_location_report_export_is_protected(self):
        """Location report export should require authentication."""
        assert is_public_route("/dashboard/location-report/export") is False

    def test_places_endpoints_are_public(self):
        """Places API endpoints should be public."""
        assert is_public_route("/places/") is True
        assert is_public_route("/places/chicago") is True
        assert is_public_route("/places/illinois/chicago") is True

    def test_admin_static_is_public(self):
        """Admin static assets should be public."""
        assert is_public_route("/admin") is True

    def test_protected_routes_require_auth(self):
        """Explicitly protected routes should require authentication."""
        assert is_public_route("/sync/trigger") is False
        assert is_public_route("/sync/test") is False
        assert is_public_route("/jobs") is False
        assert is_public_route("/jobs/123") is False
        assert is_public_route("/spatial/layers") is False
        assert is_public_route("/spatial/layers/upload") is False
        assert is_public_route("/dashboard/location-report/export") is False

    def test_unprotected_non_public_routes_require_auth(self):
        """Routes not in public list should require authentication."""
        assert is_public_route("/spatial/load") is False
        assert is_public_route("/sync/counts") is False
        assert is_public_route("/some/random/path") is False
        assert is_public_route("/api/private") is False

    def test_version_endpoint_is_public(self):
        """Version endpoint should be public."""
        assert is_public_route("/version") is True

    def test_documentation_endpoint_is_public(self):
        """Documentation endpoint should be public."""
        assert is_public_route("/documentation") is True


class TestGetApiKey:
    """Tests for the get_api_key function."""

    def test_returns_none_when_not_set(self):
        """Should return None when API_KEY is not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Make sure API_KEY is not in environment
            os.environ.pop("API_KEY", None)
            assert get_api_key() is None

    def test_returns_key_when_set(self):
        """Should return the API key when set."""
        with patch.dict(os.environ, {"API_KEY": "test-secret-key"}):
            assert get_api_key() == "test-secret-key"


class TestGetPublicRoutes:
    """Tests for the get_public_routes function."""

    def test_returns_defaults_when_not_customized(self):
        """Should return default routes when PUBLIC_ROUTES is not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PUBLIC_ROUTES", None)
            routes = get_public_routes()
            assert routes == DEFAULT_PUBLIC_ROUTES

    def test_returns_custom_routes_when_set(self):
        """Should return custom routes when PUBLIC_ROUTES is set."""
        with patch.dict(os.environ, {"PUBLIC_ROUTES": "/custom,/another"}):
            routes = get_public_routes()
            assert routes == ["/custom", "/another"]

    def test_handles_whitespace_in_custom_routes(self):
        """Should trim whitespace from custom routes."""
        with patch.dict(os.environ, {"PUBLIC_ROUTES": " /custom , /another "}):
            routes = get_public_routes()
            assert routes == ["/custom", "/another"]

    def test_filters_empty_routes(self):
        """Should filter out empty routes."""
        with patch.dict(os.environ, {"PUBLIC_ROUTES": "/custom,,/another,"}):
            routes = get_public_routes()
            assert routes == ["/custom", "/another"]


class TestGetApiKeyHeader:
    """Tests for the get_api_key_header function."""

    def test_returns_correct_header_name(self):
        """Should return 'X-API-Key' as the header name."""
        assert get_api_key_header() == "X-API-Key"


class TestGenerateApiKey:
    """Tests for the generate_api_key function."""

    def test_generates_string(self):
        """Should generate a string key."""
        key = generate_api_key()
        assert isinstance(key, str)

    def test_generates_non_empty_key(self):
        """Should generate a non-empty key."""
        key = generate_api_key()
        assert len(key) > 0

    def test_generates_unique_keys(self):
        """Should generate unique keys each time."""
        keys = [generate_api_key() for _ in range(10)]
        assert len(set(keys)) == 10  # All keys should be unique

    def test_respects_length_parameter(self):
        """Should respect the length parameter."""
        short_key = generate_api_key(length=16)
        long_key = generate_api_key(length=64)
        # URL-safe base64 encoding produces ~4/3 chars per byte
        assert len(short_key) < len(long_key)


class TestAPIKeyMiddleware:
    """Integration tests for the APIKeyMiddleware."""

    @pytest.fixture
    def app_with_middleware(self):
        """Create a FastAPI app with the auth middleware."""
        app = FastAPI()
        app.add_middleware(APIKeyMiddleware)

        @app.get("/")
        def root():
            return {"message": "root"}

        @app.get("/health")
        def health():
            return {"status": "healthy"}

        @app.get("/docs")
        def docs():
            return {"docs": True}

        @app.get("/protected")
        def protected():
            return {"secret": "data"}

        @app.post("/sync/trigger")
        def sync_trigger():
            return {"triggered": True}

        @app.get("/jobs")
        def jobs():
            return {"jobs": []}

        @app.get("/spatial/layers")
        def spatial_layers():
            return {"layers": []}

        @app.get("/dashboard/stats")
        def dashboard_stats():
            return {"stats": {}}

        @app.get("/places/chicago")
        def places():
            return {"place": "chicago"}

        return app

    def test_no_auth_when_api_key_not_set(self, app_with_middleware):
        """When API_KEY is not set, all routes should be accessible."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("API_KEY", None)
            client = TestClient(app_with_middleware)

            # All routes should work without authentication
            assert client.get("/").status_code == 200
            assert client.get("/protected").status_code == 200
            assert client.post("/sync/trigger").status_code == 200

    def test_public_routes_accessible_without_key(self, app_with_middleware):
        """Public routes should be accessible without an API key."""
        with patch.dict(os.environ, {"API_KEY": "test-secret"}):
            client = TestClient(app_with_middleware)

            assert client.get("/").status_code == 200
            assert client.get("/health").status_code == 200
            assert client.get("/dashboard/stats").status_code == 200
            assert client.get("/places/chicago").status_code == 200

    def test_protected_routes_require_key(self, app_with_middleware):
        """Protected routes should require an API key."""
        with patch.dict(os.environ, {"API_KEY": "test-secret"}):
            client = TestClient(app_with_middleware)

            # These should fail without API key
            response = client.get("/protected")
            assert response.status_code == 401
            assert "unauthorized" in response.json()["error"]

            response = client.post("/sync/trigger")
            assert response.status_code == 401

            response = client.get("/jobs")
            assert response.status_code == 401

            response = client.get("/spatial/layers")
            assert response.status_code == 401

    def test_protected_routes_accessible_with_valid_key(self, app_with_middleware):
        """Protected routes should be accessible with a valid API key."""
        with patch.dict(os.environ, {"API_KEY": "test-secret"}):
            client = TestClient(app_with_middleware)
            headers = {"X-API-Key": "test-secret"}

            assert client.get("/protected", headers=headers).status_code == 200
            assert client.post("/sync/trigger", headers=headers).status_code == 200
            assert client.get("/jobs", headers=headers).status_code == 200
            assert client.get("/spatial/layers", headers=headers).status_code == 200

    def test_invalid_key_rejected(self, app_with_middleware):
        """Invalid API keys should be rejected."""
        with patch.dict(os.environ, {"API_KEY": "correct-key"}):
            client = TestClient(app_with_middleware)
            headers = {"X-API-Key": "wrong-key"}

            response = client.get("/protected", headers=headers)
            assert response.status_code == 401
            assert "Invalid or missing API key" in response.json()["detail"]

    def test_options_requests_allowed(self, app_with_middleware):
        """OPTIONS requests should be allowed for CORS preflight."""
        with patch.dict(os.environ, {"API_KEY": "test-secret"}):
            client = TestClient(app_with_middleware)

            # OPTIONS should work without API key (for CORS preflight)
            response = client.options("/protected")
            # FastAPI might return 405 if OPTIONS not explicitly handled
            assert response.status_code in [200, 405]

    def test_unauthorized_response_format(self, app_with_middleware):
        """Unauthorized response should have correct format."""
        with patch.dict(os.environ, {"API_KEY": "test-secret"}):
            client = TestClient(app_with_middleware)

            response = client.get("/protected")
            assert response.status_code == 401

            data = response.json()
            assert "detail" in data
            assert "error" in data
            assert "hint" in data
            assert data["error"] == "unauthorized"
            assert "X-API-Key" in data["hint"]


class TestSecurityVulnerabilityRegression:
    """Regression tests for the auth bypass vulnerability."""

    def test_slash_in_public_routes_does_not_bypass_auth(self):
        """Verify that '/' in public routes doesn't make all paths public.

        This is a regression test for the security vulnerability where having
        '/' in DEFAULT_PUBLIC_ROUTES caused all paths to be treated as public
        because every URL starts with '/'.
        """
        # Verify "/" is in DEFAULT_PUBLIC_ROUTES (the config that caused the bug)
        assert "/" in DEFAULT_PUBLIC_ROUTES

        # These should NOT be public even though they all start with "/"
        non_public_paths = [
            "/spatial/load",
            "/sync/counts",
            "/api/internal",
            "/arbitrary/endpoint",
            "/a",
            "/ab",
            "/abc",
        ]

        for path in non_public_paths:
            assert is_public_route(path) is False, (
                f"Path '{path}' should NOT be public. "
                f"This indicates the auth bypass vulnerability has regressed."
            )

    def test_only_exact_root_is_public(self):
        """Only the exact '/' path should match, not paths starting with '/'."""
        assert is_public_route("/") is True
        assert is_public_route("//") is False  # Double slash is not root
        assert is_public_route("/a") is False  # Single char path
        assert is_public_route("/ ") is False  # Root with space


class TestProtectedRoutesConfig:
    """Tests for protected routes configuration."""

    def test_all_protected_routes_block_correctly(self):
        """All routes in PROTECTED_ROUTES should require auth."""
        for route in PROTECTED_ROUTES:
            assert is_public_route(route) is False, (
                f"Protected route '{route}' is incorrectly marked as public"
            )

    def test_protected_route_subpaths_also_protected(self):
        """Subpaths of protected routes should also be protected."""
        subpaths = [
            "/sync/trigger/now",
            "/sync/test/crashes",
            "/jobs/123",
            "/jobs/456/status",
            "/spatial/layers/upload",
            "/spatial/layers/1/delete",
            "/dashboard/location-report/export/pdf",
        ]

        for path in subpaths:
            assert is_public_route(path) is False, (
                f"Protected route subpath '{path}' should require auth"
            )
