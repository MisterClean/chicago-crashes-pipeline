"""SODA API client for Chicago Open Data Portal."""
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
from tqdm.asyncio import tqdm

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
from utils.config import settings
from utils.logging import get_logger

logger = get_logger(__name__)


class SODAClient:
    """Async client for Chicago Open Data SODA API."""
    
    def __init__(self, timeout: int = 30, rate_limit: int = 1000):
        """Initialize SODA client.
        
        Args:
            timeout: Request timeout in seconds
            rate_limit: Requests per hour limit
        """
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.rate_limiter = asyncio.Semaphore(rate_limit)
        
        # Request session with timeout and retry configuration
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(max_connections=settings.api.max_concurrent)
        )
        
        # Headers for API requests
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "ChicagoCrashPipeline/1.0"
        }
        
        # Add API token if available
        if settings.api.token:
            self.headers["X-App-Token"] = settings.api.token
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.client.aclose()
    
    async def fetch_records(
        self,
        endpoint: str,
        limit: int = 50000,
        offset: int = 0,
        where_clause: Optional[str] = None,
        order_by: Optional[str] = None,
        select_fields: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Fetch records from SODA API endpoint.
        
        Args:
            endpoint: API endpoint URL
            limit: Maximum records to fetch per request
            offset: Number of records to skip
            where_clause: SQL WHERE clause for filtering
            order_by: SQL ORDER BY clause
            select_fields: List of fields to select
            
        Returns:
            List of record dictionaries
        """
        params = {
            "$limit": str(limit),
            "$offset": str(offset)
        }
        
        if where_clause:
            params["$where"] = where_clause
        
        if order_by:
            params["$order"] = order_by
        
        if select_fields:
            params["$select"] = ",".join(select_fields)
        
        # Build URL with parameters
        url = f"{endpoint}?{urlencode(params)}"
        
        # Rate limiting
        async with self.rate_limiter:
            try:
                response = await self._make_request(url)
                return response.json()
                
            except httpx.TimeoutException:
                logger.error("Request timed out", url=url)
                raise
            except httpx.HTTPError as e:
                logger.error("HTTP error", url=url, error=str(e))
                raise
    
    async def fetch_all_records(
        self,
        endpoint: str,
        batch_size: int = 50000,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        date_field: str = "crash_date",
        order_by: Optional[str] = None,
        show_progress: bool = True
    ) -> List[Dict[str, Any]]:
        """Fetch all records from endpoint with pagination.
        
        Args:
            endpoint: API endpoint URL
            batch_size: Records per batch
            start_date: Start date filter (YYYY-MM-DD)
            end_date: End date filter (YYYY-MM-DD)
            date_field: Field name for date filtering
            order_by: SQL ORDER BY clause
            show_progress: Whether to show progress bar
            
        Returns:
            List of all record dictionaries
        """
        logger.info("Starting data fetch", endpoint=endpoint, batch_size=batch_size)
        
        # Build WHERE clause for date filtering
        where_clauses = []
        if start_date:
            where_clauses.append(f"{date_field} >= '{start_date}T00:00:00'")
        if end_date:
            where_clauses.append(f"{date_field} < '{end_date}T23:59:59'")
        
        where_clause = " AND ".join(where_clauses) if where_clauses else None
        
        # Default ordering for consistent pagination
        if not order_by:
            order_by = date_field
        
        # Get total count first
        total_count = await self._get_record_count(endpoint, where_clause)
        logger.info("Total records to fetch", count=total_count)
        
        if total_count == 0:
            return []
        
        # Calculate number of batches
        num_batches = (total_count + batch_size - 1) // batch_size
        
        all_records = []
        
        # Progress bar setup
        if show_progress:
            progress = tqdm(
                total=total_count,
                desc=f"Fetching {endpoint.split('/')[-1].replace('.json', '')}",
                unit="records"
            )
        
        # Fetch data in batches
        for batch_num in range(num_batches):
            offset = batch_num * batch_size
            
            try:
                batch_records = await self.fetch_records(
                    endpoint=endpoint,
                    limit=batch_size,
                    offset=offset,
                    where_clause=where_clause,
                    order_by=order_by
                )
                
                all_records.extend(batch_records)
                
                if show_progress:
                    progress.update(len(batch_records))
                
                logger.debug("Fetched batch", 
                           batch=batch_num + 1,
                           batch_size=len(batch_records),
                           total_fetched=len(all_records))
                
                # Small delay to be respectful to API
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error("Error fetching batch",
                           batch=batch_num + 1,
                           offset=offset,
                           error=str(e))
                # Continue with next batch rather than failing completely
                continue
        
        if show_progress:
            progress.close()
        
        logger.info("Data fetch completed", 
                   total_records=len(all_records),
                   expected=total_count)
        
        return all_records
    
    async def fetch_incremental_records(
        self,
        endpoint: str,
        last_modified: datetime,
        batch_size: int = 50000,
        show_progress: bool = True
    ) -> List[Dict[str, Any]]:
        """Fetch records modified since last sync.
        
        Args:
            endpoint: API endpoint URL  
            last_modified: DateTime of last successful sync
            batch_size: Records per batch
            show_progress: Whether to show progress bar
            
        Returns:
            List of modified record dictionaries
        """
        # Format datetime for SODA API
        last_modified_str = last_modified.strftime('%Y-%m-%dT%H:%M:%S')
        
        logger.info("Starting incremental fetch",
                   endpoint=endpoint,
                   last_modified=last_modified_str)
        
        # Use :updated_at system field for incremental sync
        where_clause = f":updated_at > '{last_modified_str}'"
        
        return await self.fetch_all_records(
            endpoint=endpoint,
            batch_size=batch_size,
            order_by=":updated_at",
            show_progress=show_progress
        )
    
    async def _make_request(self, url: str) -> httpx.Response:
        """Make HTTP request with retry logic.
        
        Args:
            url: Request URL
            
        Returns:
            HTTP response
        """
        for attempt in range(settings.api.max_retries + 1):
            try:
                response = await self.client.get(url, headers=self.headers)
                response.raise_for_status()
                return response
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:  # Rate limited
                    wait_time = settings.api.backoff_factor ** attempt
                    logger.warning("Rate limited, retrying",
                                 attempt=attempt,
                                 wait_time=wait_time)
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error("HTTP error", 
                               status_code=e.response.status_code,
                               url=url)
                    raise
                    
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt < settings.api.max_retries:
                    wait_time = settings.api.backoff_factor ** attempt
                    logger.warning("Request failed, retrying",
                                 attempt=attempt,
                                 wait_time=wait_time,
                                 error=str(e))
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error("Request failed after all retries", error=str(e))
                    raise
        
        raise Exception(f"Failed to fetch data after {settings.api.max_retries} retries")
    
    async def _get_record_count(
        self,
        endpoint: str, 
        where_clause: Optional[str] = None
    ) -> int:
        """Get total record count for endpoint.
        
        Args:
            endpoint: API endpoint URL
            where_clause: SQL WHERE clause for filtering
            
        Returns:
            Total number of records
        """
        params = {
            "$select": "COUNT(*) as count"
        }
        
        if where_clause:
            params["$where"] = where_clause
        
        url = f"{endpoint}?{urlencode(params)}"
        
        try:
            response = await self._make_request(url)
            data = response.json()
            return int(data[0]["count"]) if data else 0
            
        except Exception as e:
            logger.warning("Could not get record count, using fallback",
                         error=str(e))
            # Fallback: try to fetch first batch to estimate
            try:
                first_batch = await self.fetch_records(
                    endpoint=endpoint,
                    limit=1000,
                    where_clause=where_clause
                )
                # If we got a full batch, there are likely more records
                # This is just an estimate for progress bar
                return len(first_batch) * 10 if len(first_batch) == 1000 else len(first_batch)
            except:
                return 0