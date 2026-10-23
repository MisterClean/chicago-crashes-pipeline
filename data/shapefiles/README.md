# Local boundary inputs

Custom boundaries are supplied by each installation rather than shipped with the repository. Upload GeoJSON or a zipped shapefile through `/admin`. A shapefile ZIP must contain its `.shp`, `.shx`, `.dbf` and `.prj` components; GDAL transforms it to WGS84.

Select a label field in the upload preview to name features in location reports. Keep source archives and generated database files outside Git. See the [operations guide](../../docs/rust-migration.md) for validation and migration behavior.
