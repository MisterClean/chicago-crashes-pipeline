---
title: Welcome
slug: /
sidebar_position: 1
description: Orientation guide for the Chicago Crash Data Pipeline documentation site.
---

# Chicago Crash Data Pipeline

Welcome to the documentation hub for the Chicago Crash Data Pipeline. This site explains how to install, operate, and extend the system that ingests crash records from the City of Chicago SODA APIs, applies quality controls, and exposes the data through a managed PostGIS database, REST API, admin portal, and **public dashboard**.

**Key Features:**
- **Public Dashboard**: Interactive Next.js dashboard with crash maps, trend charts, and location-based reports with cost estimates
- **Location Reports**: Generate crash statistics for any area using radius, polygon, or predefined boundaries (wards, community areas, districts)
- **Cost Estimation**: FHWA KABCO methodology for estimating economic and societal costs of crashes
- **ETL Pipeline**: Automated data ingestion from Chicago Open Data Portal with validation and sanitization
- **Spatial Analysis**: PostGIS-powered spatial queries and boundary lookups

Use the navigation to explore targeted guides:

- **Getting Started** covers local setup, configuration, and Docker workflows.
- **User Guides** dive into the admin portal, API, and day-to-day operational tasks.
- **Data & Architecture** documents the pipeline internals, domain model, and spatial capabilities.
- **Operations** focuses on deployment, monitoring, and troubleshooting.
- **Development** explains project conventions, tooling, and contribution workflows.

If you are new to the project, start with the [Quick Start](getting-started/quickstart.md) guide, then move on to the [Admin Portal](user-guides/admin-portal.md) for a tour of the operational UI.

> Looking for the source code? Visit the [GitHub repository](https://github.com/MisterClean/chicago-crashes-pipeline).
