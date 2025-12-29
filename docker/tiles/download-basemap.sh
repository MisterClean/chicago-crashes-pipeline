#!/bin/bash
# =============================================================================
# Download Chicago PMTiles Basemap
# =============================================================================
# Downloads and extracts Chicago-area vector tiles from Protomaps
#
# Prerequisites:
#   - curl
#   - pmtiles CLI (https://github.com/protomaps/go-pmtiles)
#     Install: go install github.com/protomaps/go-pmtiles/cmd/pmtiles@latest
#     Or: brew install pmtiles
#
# Chicago bounding box: -87.94,41.64,-87.52,42.02
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_FILE="${SCRIPT_DIR}/chicago-basemap.pmtiles"

# Chicago bounding box (slightly expanded for cleaner edges)
MIN_LON="-87.95"
MIN_LAT="41.63"
MAX_LON="-87.51"
MAX_LAT="42.03"

# Check for pmtiles CLI
if ! command -v pmtiles &> /dev/null; then
    echo "Error: pmtiles CLI not found."
    echo ""
    echo "Install with one of:"
    echo "  brew install pmtiles"
    echo "  go install github.com/protomaps/go-pmtiles/cmd/pmtiles@latest"
    echo "  npm install -g pmtiles"
    exit 1
fi

echo "=== Chicago PMTiles Basemap Downloader ==="
echo ""
echo "This will download Chicago-area vector tiles from Protomaps."
echo "Bounding box: ${MIN_LON},${MIN_LAT} to ${MAX_LON},${MAX_LAT}"
echo ""

# Option 1: Download from Protomaps build (if available)
# Protomaps provides daily planet builds
PROTOMAPS_BUILD="https://build.protomaps.com/20241201.pmtiles"

# Option 2: Use a pre-built US Midwest extract
# Smaller download, faster extraction
MIDWEST_URL="https://data.source.coop/protomaps/openstreetmap/tiles/v4/us_midwest.pmtiles"

echo "Downloading US Midwest extract..."
echo "Source: ${MIDWEST_URL}"
echo ""

# Download the Midwest extract
TEMP_FILE="${SCRIPT_DIR}/us_midwest_temp.pmtiles"

if [ -f "${TEMP_FILE}" ]; then
    echo "Found existing download at ${TEMP_FILE}"
else
    curl -L -# -o "${TEMP_FILE}" "${MIDWEST_URL}"
fi

echo ""
echo "Extracting Chicago area..."
echo ""

# Extract just Chicago using pmtiles extract command
pmtiles extract "${TEMP_FILE}" "${OUTPUT_FILE}" \
    --minlon="${MIN_LON}" \
    --minlat="${MIN_LAT}" \
    --maxlon="${MAX_LON}" \
    --maxlat="${MAX_LAT}"

# Get file size
FILE_SIZE=$(ls -lh "${OUTPUT_FILE}" | awk '{print $5}')

echo ""
echo "=== Complete ==="
echo "Output: ${OUTPUT_FILE}"
echo "Size: ${FILE_SIZE}"
echo ""

# Verify the file
echo "Verifying PMTiles..."
pmtiles show "${OUTPUT_FILE}"

echo ""
echo "Cleaning up temporary file..."
rm -f "${TEMP_FILE}"

echo ""
echo "Chicago basemap ready for use with Martin tile server."
