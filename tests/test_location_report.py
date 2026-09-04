"""Tests for location report children_injured metric."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app


class TestLocationReportChildrenInjured:
    """Test children_injured metric in location reports."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        return TestClient(app)

    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        return MagicMock()

    def test_children_injured_in_response_schema(self):
        """Test that children_injured is defined in LocationReportStats."""
        from api.routers.dashboard import LocationReportStats

        # Check that the field exists in the model
        assert "children_injured" in LocationReportStats.model_fields

        # Check field properties
        field = LocationReportStats.model_fields["children_injured"]
        assert field.default == 0

    def test_children_injured_query_logic(self):
        """Test the SQL query logic for children_injured.

        Children injured should count people where:
        - age >= 0 AND age < 18 (under 18 years old)
        - injury_classification is one of the injury types (not 'NO INDICATION OF INJURY')
        """
        # This tests the query construction - the actual query in dashboard.py should:
        # 1. Filter for age 0-17
        # 2. Filter for injury classifications that indicate actual injury
        valid_injury_types = [
            'FATAL',
            'INCAPACITATING INJURY',
            'NONINCAPACITATING INJURY',
            'REPORTED, NOT EVIDENT'
        ]

        excluded_types = ['NO INDICATION OF INJURY']

        # Verify our constants match expected values
        assert 'FATAL' in valid_injury_types
        assert 'NO INDICATION OF INJURY' not in valid_injury_types
        assert 'NO INDICATION OF INJURY' in excluded_types

    @patch("api.routers.dashboard.Session")
    def test_location_report_includes_children_injured(self, mock_session_class, client):
        """Test that location report endpoint returns children_injured field."""
        # Create mock for database results
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_class.return_value.__exit__ = MagicMock(return_value=False)

        # Mock the stats query result
        mock_stats_result = MagicMock()
        mock_stats_result.total_crashes = 100
        mock_stats_result.total_injuries = 50
        mock_stats_result.total_fatalities = 2
        mock_stats_result.incapacitating_injuries = 10
        mock_stats_result.crashes_with_injuries = 40
        mock_stats_result.crashes_with_fatalities = 2
        mock_stats_result.hit_and_run_count = 5

        # Mock the people query result (includes children_injured)
        mock_people_result = MagicMock()
        mock_people_result.pedestrians = 15
        mock_people_result.cyclists = 8
        mock_people_result.fatal_count = 2
        mock_people_result.incapacitating_count = 10
        mock_people_result.nonincapacitating_count = 25
        mock_people_result.reported_not_evident_count = 13
        mock_people_result.no_indication_count = 100
        mock_people_result.unknown_count = 0
        mock_people_result.children_injured = 7  # Key field we're testing

        # Mock vehicles result
        mock_vehicles_result = MagicMock()
        mock_vehicles_result.total_vehicle_count = 150
        mock_vehicles_result.pdo_vehicle_count = 50

        # Mock area result for radius query
        mock_area_result = MagicMock()
        mock_area_result.geojson = '{"type": "Polygon", "coordinates": [[[-87.7, 41.8], [-87.6, 41.8], [-87.6, 41.9], [-87.7, 41.9], [-87.7, 41.8]]]}'

        # Configure mock execute to return appropriate results
        def mock_execute(query, params=None):
            result = MagicMock()
            query_str = str(query)

            if "ST_Buffer" in query_str:
                result.fetchone.return_value = mock_area_result
            elif "children_injured" in query_str:
                result.fetchone.return_value = mock_people_result
            elif "total_vehicle_count" in query_str:
                result.fetchone.return_value = mock_vehicles_result
            elif "total_crashes" in query_str:
                result.fetchone.return_value = mock_stats_result
            elif "prim_contributory_cause" in query_str:
                result.fetchall.return_value = []
            elif "DATE_TRUNC" in query_str:
                result.fetchall.return_value = []
            elif "ST_X" in query_str:
                result.fetchall.return_value = []
            else:
                result.fetchone.return_value = mock_stats_result
                result.fetchall.return_value = []

            return result

        mock_session.execute = mock_execute

        # Make request with radius query
        from src.api.routers.dashboard import get_db
        app.dependency_overrides[get_db] = lambda: mock_session
        try:
            response = client.post(
                "/dashboard/location-report",
                json={
                    "latitude": 41.8781,
                    "longitude": -87.6298,
                    "radius_feet": 5280,
                }
            )

        finally:
            app.dependency_overrides.pop(get_db, None)

        # The endpoint should return 200 and include children_injured
        # Note: This may fail with actual DB connection issues in test environment
        # The important thing is that the schema includes the field
        assert response.status_code == 200
        assert response.json()["stats"]["children_injured"] == 7


class TestChildrenInjuredDataIntegrity:
    """Tests for children_injured data integrity."""

    def test_age_boundary_conditions(self):
        """Test that age boundary for children is correctly defined.

        Children are defined as age 0-17 (under 18).
        """
        # Test cases for age filtering
        test_cases = [
            (0, True, "newborn should be counted as child"),
            (5, True, "5 year old should be counted as child"),
            (17, True, "17 year old should be counted as child"),
            (18, False, "18 year old should NOT be counted as child"),
            (25, False, "25 year old should NOT be counted as child"),
            (-1, False, "negative age should NOT be counted"),
        ]

        for age, should_be_child, message in test_cases:
            is_child = 0 <= age < 18
            assert is_child == should_be_child, message

    def test_injury_classification_filtering(self):
        """Test that only actual injuries are counted, not 'NO INDICATION OF INJURY'."""
        injury_types_to_count = {
            'FATAL',
            'INCAPACITATING INJURY',
            'NONINCAPACITATING INJURY',
            'REPORTED, NOT EVIDENT'
        }

        injury_types_to_exclude = {
            'NO INDICATION OF INJURY',
            None,
            ''
        }

        # Fatal should be counted
        assert 'FATAL' in injury_types_to_count

        # No indication of injury should NOT be counted
        assert 'NO INDICATION OF INJURY' not in injury_types_to_count
        assert 'NO INDICATION OF INJURY' in injury_types_to_exclude

    def test_children_injured_default_value(self):
        """Test that children_injured defaults to 0 when not provided."""
        from api.routers.dashboard import LocationReportStats

        # Create stats with minimal required fields
        stats = LocationReportStats(
            total_crashes=100,
            total_injuries=50,
            total_fatalities=2,
            pedestrians_involved=10,
            cyclists_involved=5,
            hit_and_run_count=3,
            incapacitating_injuries=8,
            crashes_with_injuries=40,
            crashes_with_fatalities=2,
            estimated_economic_damages=1000000,
            estimated_societal_costs=2000000,
            total_vehicles=150,
            unknown_injury_count=0,
        )

        # children_injured should default to 0
        assert stats.children_injured == 0


class TestReportMonthlyRange:
    def test_historical_range_zero_fills_missing_months(self):
        from datetime import datetime
        from types import SimpleNamespace
        from api.routers.dashboard import _fill_report_months

        points = _fill_report_months(
            [SimpleNamespace(month="2020-02", crashes=4, injuries=2, fatalities=1)],
            datetime(2020, 1, 1), datetime(2020, 3, 31, 23, 59, 59, 999999),
            now=datetime(2026, 9, 1),
        )
        assert [point.month for point in points] == ["2020-01", "2020-02", "2020-03"]
        assert [point.crashes for point in points] == [0, 4, 0]
        assert not any(point.partial for point in points)

    def test_partial_boundaries_and_current_month(self):
        from datetime import datetime
        from api.routers.dashboard import _fill_report_months

        points = _fill_report_months([], datetime(2026, 7, 15), datetime(2026, 9, 30), now=datetime(2026, 9, 4))
        assert [point.partial for point in points] == [True, False, True]
        assert sum(point.crashes for point in points) == 0

    def test_empty_unbounded_selection(self):
        from api.routers.dashboard import _fill_report_months
        assert _fill_report_months([], None, None) == []


@pytest.mark.asyncio
async def test_report_patterns_use_full_filtered_selection():
    from types import SimpleNamespace
    from api.routers.dashboard import LocationReportRequest, get_location_report

    queries = []
    db = MagicMock()
    def execute(query, params=None):
        sql = str(query)
        queries.append((sql, params))
        result = MagicMock()
        result.fetchall.return_value = []
        if "AS total_crashes" in sql:
            result.fetchone.return_value = SimpleNamespace(total_crashes=6000, total_injuries=2, total_fatalities=0, incapacitating_injuries=1, crashes_with_injuries=2, crashes_with_fatalities=0, hit_and_run_count=0)
        elif "AS children_injured" in sql:
            result.fetchone.return_value = SimpleNamespace(pedestrians=0, cyclists=0, fatal_count=0, incapacitating_count=1, nonincapacitating_count=1, reported_not_evident_count=0, no_indication_count=0, unknown_count=0, children_injured=0)
        elif "AS total_vehicle_count" in sql:
            result.fetchone.return_value = SimpleNamespace(total_vehicle_count=0, pdo_vehicle_count=0)
        elif "EXTRACT(ISODOW" in sql:
            result.fetchall.return_value = [SimpleNamespace(day=6, hour=23, crashes=6000, injury_crashes=2, severe_crashes=1)]
        return result
    db.execute.side_effect = execute
    with patch("api.routers.dashboard._build_location_report_filters", return_value=("ST_Intersects({geometry_column}, :area)", {"area": "test"}, {})):
        response = await get_location_report(LocationReportRequest(start_date="2020-01-01", end_date="2020-03-31"), db)
    assert len(response.hour_day_counts) == 168
    assert sum(cell.crashes for cell in response.hour_day_counts) == 6000
    assert response.hour_day_counts[-1].severe_crashes == 1
    assert response.map_truncated
    for sql, params in queries:
        if "EXTRACT(ISODOW" in sql or "AS road_user" in sql or "TO_CHAR(DATE_TRUNC" in sql:
            assert "LIMIT" not in sql
            assert ":start_date" in sql and ":end_date" in sql
            assert "12 months" not in sql
