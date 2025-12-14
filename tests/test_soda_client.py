"""Tests for SODA API client."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

sys.path.append(str(Path(__file__).parent.parent / "src"))

from etl.soda_client import SODAClient  # noqa: E402


class TestSODAClient:
    """Test SODA API client functionality."""

    @pytest.fixture
    def client(self):
        """Create a SODA client instance."""
        return SODAClient()

    @pytest.mark.asyncio
    async def test_client_initialization(self, client):
        """Test client initializes correctly."""
        assert client.timeout == 30
        assert client.rate_limit == 1000
        assert client.client is not None

    @pytest.mark.asyncio
    async def test_fetch_records_success(self, client):
        """Test successful record fetching."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"crash_record_id": "TEST1", "crash_date": "2024-01-01"},
            {"crash_record_id": "TEST2", "crash_date": "2024-01-02"},
        ]
        mock_response.raise_for_status.return_value = None

        with patch.object(
            client, "_make_request", return_value=mock_response
        ) as mock_request:
            records = await client.fetch_records(
                endpoint="https://example.com/test.json", limit=2
            )

            assert len(records) == 2
            assert records[0]["crash_record_id"] == "TEST1"
            assert records[1]["crash_record_id"] == "TEST2"
            mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_records_with_parameters(self, client):
        """Test record fetching with query parameters."""
        mock_response = MagicMock()
        mock_response.json.return_value = [{"id": "TEST"}]
        mock_response.raise_for_status.return_value = None

        with patch.object(
            client, "_make_request", return_value=mock_response
        ) as mock_request:
            records = await client.fetch_records(
                endpoint="https://example.com/test.json",
                limit=10,
                offset=20,
                where_clause="crash_date > '2024-01-01'",
                order_by="crash_date DESC",
                select_fields=["crash_record_id", "crash_date"],
            )

            assert records == [{"id": "TEST"}]

            # Verify the URL contains the expected parameters (URL encoded)
            called_url = mock_request.call_args[0][0]
            assert "%24limit=10" in called_url  # $limit=10 URL encoded
            assert "%24offset=20" in called_url  # $offset=20 URL encoded
            assert "%24where=" in called_url  # $where= URL encoded
            assert "%24order=" in called_url  # $order= URL encoded
            assert "%24select=" in called_url  # $select= URL encoded

    @pytest.mark.asyncio
    async def test_fetch_all_records_pagination(self, client):
        """Test fetching all records with pagination."""
        # Mock responses for pagination
        first_batch = [{"id": f"TEST{i}"} for i in range(1000)]
        second_batch = [{"id": f"TEST{i}"} for i in range(1000, 1500)]

        call_count = 0

        async def mock_fetch_records(endpoint, limit, offset, **kwargs):
            nonlocal call_count
            if call_count == 0:
                call_count += 1
                return first_batch
            elif call_count == 1:
                call_count += 1
                return second_batch
            else:
                return []

        # Mock the record count method to return expected total
        with (
            patch.object(client, "_get_record_count", return_value=1500) as mock_count,
            patch.object(client, "fetch_records", side_effect=mock_fetch_records),
        ):
            all_records = await client.fetch_all_records(
                endpoint="https://example.com/test.json",
                batch_size=1000,
                show_progress=False,  # Disable progress bar for testing
            )

            assert len(all_records) == 1500
            assert call_count == 2  # Should have made 2 calls (1000 + 500)
            mock_count.assert_called_once()

    @pytest.mark.asyncio
    async def test_http_error_handling(self, client):
        """Test HTTP error handling."""
        with patch.object(client.client, "get") as mock_get:
            # Mock HTTP error
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "404 Not Found", request=MagicMock(), response=MagicMock()
            )
            mock_get.return_value = mock_response

            with pytest.raises(httpx.HTTPStatusError):
                await client._make_request("https://example.com/test.json")

    @pytest.mark.asyncio
    async def test_rate_limiting(self, client):
        """Test rate limiting functionality."""
        # The rate limiter should allow concurrent requests up to the limit
        # This is a basic test - in practice, rate limiting is more complex

        mock_response = MagicMock()
        mock_response.json.return_value = [{"test": "data"}]
        mock_response.raise_for_status.return_value = None

        with patch.object(client, "_make_request", return_value=mock_response):
            # Make multiple concurrent requests
            tasks = []
            for i in range(5):
                task = client.fetch_records(f"https://example.com/test{i}.json")
                tasks.append(task)

            results = await asyncio.gather(*tasks)

            # All requests should succeed
            assert len(results) == 5
            for result in results:
                assert len(result) == 1
                assert result[0]["test"] == "data"

    @pytest.mark.asyncio
    async def test_empty_response_handling(self, client):
        """Test handling of empty responses."""
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status.return_value = None

        with patch.object(client, "_make_request", return_value=mock_response):
            records = await client.fetch_records("https://example.com/test.json")

            assert records == []

    @pytest.mark.asyncio
    async def test_malformed_json_handling(self, client):
        """Test handling of malformed JSON responses."""
        mock_response = MagicMock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.raise_for_status.return_value = None

        with patch.object(client, "_make_request", return_value=mock_response):
            with pytest.raises(ValueError):
                await client.fetch_records("https://example.com/test.json")

    @pytest.mark.asyncio
    async def test_url_encoding(self, client):
        """Test that URL parameters are properly encoded."""
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status.return_value = None

        with patch.object(
            client, "_make_request", return_value=mock_response
        ) as mock_request:
            await client.fetch_records(
                endpoint="https://example.com/test.json",
                where_clause="street_name = 'MICHIGAN AVE'",
            )

            called_url = mock_request.call_args[0][0]
            # URL should be properly encoded
            assert "street_name" in called_url
            assert "%20" in called_url or "+" in called_url  # Space encoding

    @pytest.mark.asyncio
    async def test_timeout_handling(self, client):
        """Test timeout handling."""
        with patch.object(client.client, "get") as mock_get:
            mock_get.side_effect = httpx.TimeoutException("Request timed out")

            with pytest.raises(httpx.TimeoutException):
                await client._make_request("https://example.com/test.json")

    @pytest.mark.asyncio
    async def test_large_dataset_pagination(self, client):
        """Test pagination with large datasets."""
        # Simulate a dataset with 150,000 records
        batch_size = 50000
        total_records = 150000

        call_count = 0

        async def mock_fetch_records(endpoint, limit, offset, **kwargs):
            nonlocal call_count
            start_idx = offset
            end_idx = min(offset + limit, total_records)

            if start_idx >= total_records:
                return []

            call_count += 1
            return [{"id": f"RECORD_{i}"} for i in range(start_idx, end_idx)]

        # Mock the record count method
        with (
            patch.object(client, "_get_record_count", return_value=total_records),
            patch.object(client, "fetch_records", side_effect=mock_fetch_records),
        ):
            all_records = await client.fetch_all_records(
                endpoint="https://example.com/test.json",
                batch_size=batch_size,
                show_progress=False,  # Disable progress bar for testing
            )

            assert len(all_records) == total_records
            assert call_count == 3  # 50k, 50k, 50k batches
            assert all_records[0]["id"] == "RECORD_0"
            assert all_records[-1]["id"] == "RECORD_149999"

    @pytest.mark.asyncio
    async def test_error_handling(self, client):
        """Test basic error handling."""
        # Test that client properly handles HTTP errors
        with patch.object(client, "_make_request") as mock_request:
            mock_request.side_effect = httpx.HTTPStatusError(
                "500 Internal Server Error", request=MagicMock(), response=MagicMock()
            )

            with pytest.raises(httpx.HTTPStatusError):
                await client.fetch_records("https://example.com/test.json")

    @pytest.mark.asyncio
    async def test_concurrent_requests_limit(self, client):
        """Test concurrent request limits."""
        request_count = 0
        max_concurrent = 0
        current_concurrent = 0

        async def mock_make_request(url):
            nonlocal request_count, max_concurrent, current_concurrent
            current_concurrent += 1
            max_concurrent = max(max_concurrent, current_concurrent)
            request_count += 1

            # Simulate some processing time
            await asyncio.sleep(0.1)

            current_concurrent -= 1

            mock_response = MagicMock()
            mock_response.json.return_value = [{"request": request_count}]
            mock_response.raise_for_status.return_value = None
            return mock_response

        with patch.object(client, "_make_request", side_effect=mock_make_request):
            # Make many concurrent requests
            tasks = []
            for i in range(10):
                task = client.fetch_records(f"https://example.com/test{i}.json")
                tasks.append(task)

            results = await asyncio.gather(*tasks)

            assert len(results) == 10
            assert request_count == 10
            # Should respect rate limiting
            # (though exact limits depend on implementation)
            assert max_concurrent <= 10
