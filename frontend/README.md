# Chicago Crash Dashboard

Public dashboard for visualizing Chicago traffic crash data. Built by [Lakeview Urbanists](https://lakeviewurbanists.org).

## Features

- **Interactive Map**: Visualize crash locations with severity-based color coding
- **Trend Charts**: Weekly crash trends with injury and fatality data
- **Filtering**: Filter by date range to analyze specific time periods
- **Real-time Data**: Updated daily from the Chicago Open Data Portal

## Tech Stack

- **Framework**: Next.js 15 (App Router)
- **Mapping**: react-map-gl + MapLibre GL JS
- **Charts**: Recharts
- **Styling**: Tailwind CSS
- **Backend**: FastAPI (data API) + Martin (vector tiles)
- **Database**: PostgreSQL + PostGIS

## Development

### Prerequisites

- Node.js 22+
- Docker and Docker Compose
- Backend services running (see main project README)

### Local Development

```bash
# Install dependencies
npm install

# Start development server (port 3001)
npm run dev

# Build for production
npm run build

# Run production build
npm start
```

### Environment Variables

Create `.env.local` for development:

```env
# API endpoints (defaults work with docker-compose)
NEXT_PUBLIC_API_URL=/api/backend
BACKEND_URL=http://localhost:8000
TILES_URL=http://localhost:3000
```

## Full Stack Deployment

See the main project's `docker/` directory for complete deployment:

```bash
# Download Chicago basemap tiles (one-time setup)
./docker/tiles/download-basemap.sh

# Start all services
docker-compose -f docker/docker-compose.fullstack.yml up -d

# Access the dashboard
open http://localhost
```

### Services

| Service  | Port | Description                |
|----------|------|----------------------------|
| nginx    | 80   | Reverse proxy (main entry) |
| frontend | 3000 | Next.js dashboard          |
| backend  | 8000 | FastAPI data API           |
| martin   | 3000 | Vector tile server         |
| postgres | 5432 | PostGIS database           |

## API Endpoints

The dashboard consumes these backend endpoints:

- `GET /api/dashboard/stats` - Aggregate statistics
- `GET /api/dashboard/trends/weekly` - Weekly trend data
- `GET /api/dashboard/crashes/geojson` - Crash locations as GeoJSON
- `GET /tiles/{layer}/{z}/{x}/{y}` - Vector tiles from Martin

## Contributing

This project is open source! Contributions welcome.

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - see LICENSE file in the main repository.

## Credits

- Data: [Chicago Open Data Portal](https://data.cityofchicago.org)
- Organization: [Lakeview Urbanists](https://lakeviewurbanists.org)
