"""Declared Puerto Rico imagery/context provider registry for ILAP calibration.

This registry is discovery/policy metadata, not a claim that every endpoint is a
direct downloadable payload. Dataset/product-specific adapters must replace catalog
URLs with frozen item URLs before fetch.
"""
from __future__ import annotations

from scripts.source_adapters.sdk import AcquisitionRights, ImagerySourceEndpoint


PROVIDERS: dict[str, ImagerySourceEndpoint] = {
    "NOAA_MARIA_2017": ImagerySourceEndpoint(
        source_id="NOAA_MARIA_2017",
        name="NOAA NGS Hurricane Maria imagery",
        url="https://storms.ngs.noaa.gov/storms/maria/index.html",
        authority="NOAA NGS",
        source_lineage_id="NOAA_MARIA_2017_CATALOG",
        imagery_provider="NOAA NGS",
        imagery_epoch="2017",
        rights=AcquisitionRights(fetch="ALLOWED", training="UNKNOWN", redistribution="UNKNOWN"),
        notes="Catalog endpoint only; bind item metadata and product URL before raw acquisition.",
    ),
    "NOAA_MARIA_2017_8507": ImagerySourceEndpoint(
        source_id="NOAA_MARIA_2017_8507",
        name="2017 NOAA NGS DSS Natural Color 8 Bit Imagery: Hurricane Maria",
        url="https://chs.coast.noaa.gov/htdata/raster6/imagery/HurricaneMaria_2017_8507/stac/noaa_imagery_item_collection_m8507.json",
        authority="NOAA National Geodetic Survey",
        source_lineage_id="NOAA_MARIA_2017_8507_CATALOG",
        imagery_provider="NOAA NGS",
        product_id="8507",
        imagery_epoch="2017-09-22/2017-09-26",
        rights=AcquisitionRights(fetch="ALLOWED", training="ALLOWED", redistribution="ALLOWED"),
        notes="590-TIFF public denominator frozen; NOAA InPort states Access Constraints: None and the federal Data.gov record publishes CC0-1.0. Item-level adapter assigns conservative acquisition-batch lineage; STAC date and source-GSD contradictions remain explicit.",
    ),
    "NOAA_DIGITAL_COAST_IMAGERY": ImagerySourceEndpoint(
        source_id="NOAA_DIGITAL_COAST_IMAGERY",
        name="NOAA Digital Coast imagery",
        url="https://coast.noaa.gov/digitalcoast/data/",
        authority="NOAA",
        source_lineage_id="NOAA_DIGITAL_COAST_CATALOG",
        imagery_provider="NOAA",
        rights=AcquisitionRights(fetch="ALLOWED", training="UNKNOWN", redistribution="UNKNOWN"),
        notes="Item-level use constraints required before calibration promotion.",
    ),
    "USGS_LANDSAT": ImagerySourceEndpoint(
        source_id="USGS_LANDSAT",
        name="USGS Landsat",
        url="https://www.usgs.gov/landsat-missions",
        authority="USGS EROS",
        source_lineage_id="USGS_LANDSAT_CATALOG",
        imagery_provider="USGS/NASA",
        rights=AcquisitionRights(fetch="ALLOWED", training="ALLOWED", redistribution="ALLOWED"),
        notes="Catalog/context source; product granule ID becomes lineage for downloaded scenes.",
    ),
    "COPERNICUS_SENTINEL_2": ImagerySourceEndpoint(
        source_id="COPERNICUS_SENTINEL_2",
        name="Copernicus Sentinel-2",
        url="https://dataspace.copernicus.eu/data-collections/copernicus-sentinel-missions/sentinel-2",
        authority="EU Copernicus / ESA",
        source_lineage_id="COPERNICUS_SENTINEL_2_CATALOG",
        imagery_provider="Copernicus/ESA",
        rights=AcquisitionRights(fetch="ALLOWED", training="ALLOWED", redistribution="ALLOWED"),
        notes="Source notice still required; product/granule lineage must be frozen per scene.",
    ),
    "USGS_3DEP_TERRAIN": ImagerySourceEndpoint(
        source_id="USGS_3DEP_TERRAIN",
        name="USGS 3DEP terrain",
        url="https://www.usgs.gov/3d-elevation-program",
        authority="USGS",
        source_lineage_id="USGS_3DEP_CATALOG",
        imagery_provider="USGS",
        rights=AcquisitionRights(fetch="ALLOWED", training="ALLOWED", redistribution="ALLOWED"),
        notes="Terrain context only; item metadata must be frozen before acquisition.",
    ),
    "SIGE_FOTO_PR_2017": ImagerySourceEndpoint(
        source_id="SIGE_FOTO_PR_2017",
        name="SIGE Foto PR 2017",
        url="https://sige.pr.gov/server/rest/services/foto_pr_2017/MapServer",
        authority="Junta de Planificacion / SIGE",
        source_lineage_id="SIGE_FOTO_PR_2017_SERVICE",
        imagery_provider="SIGE",
        imagery_epoch="2017",
        rights=AcquisitionRights(fetch="UNKNOWN", training="UNKNOWN", redistribution="UNKNOWN"),
        notes="Public endpoint is discovery/review only until rights are affirmatively bound.",
    ),
    "SIGE_BASEMAP_2010": ImagerySourceEndpoint(
        source_id="SIGE_BASEMAP_2010",
        name="SIGE Basemap 2010",
        url="https://sige.pr.gov/server/rest/services/basemap2010/MapServer",
        authority="Junta de Planificacion / SIGE",
        source_lineage_id="SIGE_BASEMAP_2010_SERVICE",
        imagery_provider="SIGE",
        imagery_epoch="2010",
        rights=AcquisitionRights(fetch="UNKNOWN", training="UNKNOWN", redistribution="UNKNOWN"),
        notes="Public endpoint is not a license grant.",
    ),
    "USGS_TNM_IMAGERY_PR": ImagerySourceEndpoint(
        source_id="USGS_TNM_IMAGERY_PR",
        name="The National Map imagery for Puerto Rico",
        url="https://www.usgs.gov/media/images/tnmcorps-national-map-imagery-layer",
        authority="USGS / third-party imagery",
        source_lineage_id="USGS_TNM_PR_VIEWER",
        imagery_provider="USGS viewer / third-party",
        rights=AcquisitionRights(fetch="UNKNOWN", training="UNKNOWN", redistribution="UNKNOWN"),
        notes="Discovery only until underlying third-party imagery rights are bound.",
    ),
}


def get_provider(source_id: str) -> ImagerySourceEndpoint:
    return PROVIDERS[source_id]
