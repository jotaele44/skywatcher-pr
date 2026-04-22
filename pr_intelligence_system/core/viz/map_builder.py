"""
Interactive HTML map builder for PR Intelligence System outputs.

Generates a standalone Leaflet map (via Folium) from final_anomaly_ranked.csv.
Three toggleable layers:

  1. Top anomaly clusters  — CircleMarkers at cluster centroids, red = high score
  2. Anomaly heatmap       — density surface for all points, off by default
  3. Top 50 labeled        — rank numbers for the highest-scoring points
"""

import logging
import os

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Colour palette for classification labels (used in popups)
_CLASS_COLOUR = {
    'anomaly':        '#d73027',
    'infrastructure': '#fc8d59',
    'natural':        '#91bfdb',
    'noise':          '#aaaaaa',
}

_PR_CENTER = [18.20, -66.50]
_PR_ZOOM   = 9


def _safe(row: pd.Series, col: str, default=0):
    v = row.get(col, default)
    return default if (v is None or (isinstance(v, float) and np.isnan(v))) else v


def _add_cluster_layer(m, df: pd.DataFrame, colormap) -> None:
    """Layer 1 — top 200 cluster centroids, coloured by final_score."""
    try:
        import folium
    except ImportError:
        return

    fg = folium.FeatureGroup(name='Top anomaly clusters', show=True)

    # Keep only real clusters (noise = -1 has no meaningful centroid)
    clusters = df[df['cluster'] >= 0].copy() if 'cluster' in df.columns else df.copy()

    if len(clusters) == 0:
        clusters = df.copy()

    # One representative row per cluster (highest final_score wins)
    if 'cluster' in clusters.columns:
        clusters = (clusters
                    .sort_values('final_score', ascending=False)
                    .drop_duplicates('cluster')
                    .head(200))
    else:
        clusters = clusters.nlargest(200, 'final_score')

    for _, row in clusters.iterrows():
        score  = float(_safe(row, 'final_score', 0.5))
        color  = colormap(score)
        c_size = max(1, int(_safe(row, 'cluster_size', 1)))
        radius = min(5 + 3.0 * np.log1p(c_size), 25)

        lat = float(_safe(row, 'cluster_lat_centroid', row['lat']))
        lon = float(_safe(row, 'cluster_lon_centroid', row['lon']))

        cls   = str(row.get('classification', 'unknown'))
        rank  = int(_safe(row, 'anomaly_rank', 0))
        phys  = float(_safe(row, 'cluster_avg_physics_score', _safe(row, 'physics_score', 0)))

        popup_html = (
            f"<b>Rank #{rank}</b><br>"
            f"Score: <b>{score:.3f}</b><br>"
            f"Class: <span style='color:{_CLASS_COLOUR.get(cls, '#555')}'><b>{cls}</b></span><br>"
            f"Cluster size: {c_size} pts<br>"
            f"Physics: {phys:.3f}"
        )

        folium.CircleMarker(
            location=[lat, lon],
            radius=radius,
            color='#333',
            weight=0.8,
            fill=True,
            fill_color=color,
            fill_opacity=0.75,
            popup=folium.Popup(popup_html, max_width=220),
            tooltip=f"Score {score:.2f} — {cls}",
        ).add_to(fg)

    fg.add_to(m)


def _add_heatmap_layer(m, df: pd.DataFrame) -> None:
    """Layer 2 — heat map of all points weighted by final_score (off by default)."""
    try:
        import folium
        from folium.plugins import HeatMap
    except ImportError:
        return

    fg = folium.FeatureGroup(name='Anomaly heatmap (all points)', show=False)

    heat_data = (
        df[['lat', 'lon', 'final_score']]
        .dropna()
        .values
        .tolist()
    )

    HeatMap(
        heat_data,
        min_opacity=0.25,
        radius=18,
        blur=12,
        max_zoom=13,
    ).add_to(fg)

    fg.add_to(m)


def _add_top50_layer(m, df: pd.DataFrame, colormap) -> None:
    """Layer 3 — top 50 anomalies with visible rank labels."""
    try:
        import folium
    except ImportError:
        return

    fg   = folium.FeatureGroup(name='Top 50 ranked anomalies', show=True)
    top50 = df.nlargest(50, 'final_score').reset_index(drop=True)

    for rank, (_, row) in enumerate(top50.iterrows(), start=1):
        score = float(_safe(row, 'final_score', 0.5))
        color = colormap(score)
        lat   = float(row['lat'])
        lon   = float(row['lon'])
        cls   = str(row.get('classification', ''))

        # Outer ring marker
        folium.CircleMarker(
            location=[lat, lon],
            radius=10,
            color=color,
            weight=2,
            fill=False,
            tooltip=f"#{rank} — {cls} ({score:.3f})",
        ).add_to(fg)

        # Rank number label
        folium.Marker(
            location=[lat, lon],
            icon=folium.DivIcon(
                html=(
                    f'<div style="'
                    f'font-size:9px;font-weight:bold;color:#fff;'
                    f'background:{color};'
                    f'border-radius:50%;width:18px;height:18px;'
                    f'display:flex;align-items:center;justify-content:center;'
                    f'border:1px solid #333;'
                    f'">{rank}</div>'
                ),
                icon_size=(18, 18),
                icon_anchor=(9, 9),
            ),
        ).add_to(fg)

    fg.add_to(m)


def build_pr_map(df: pd.DataFrame, output_path: str) -> str | None:
    """Build an interactive Folium map from the pipeline output DataFrame.

    Parameters
    ----------
    df          : final_anomaly_ranked DataFrame (42 standard columns)
    output_path : where to write the .html file

    Returns
    -------
    output_path on success, None if folium is not installed.
    """
    try:
        import folium
        import branca.colormap as cm
    except ImportError:
        logger.warning(
            "Visualization skipped — folium not installed. "
            "Run: pip install folium branca"
        )
        return None

    logger.info(f"Building PR intelligence map for {len(df)} observations…")

    colormap = cm.linear.YlOrRd_09.scale(0.0, 1.0)
    colormap.caption = 'Final anomaly score  (0 = low  →  1 = high priority)'

    m = folium.Map(
        location=_PR_CENTER,
        zoom_start=_PR_ZOOM,
        tiles='CartoDB positron',
        prefer_canvas=True,
    )

    _add_cluster_layer(m, df, colormap)
    _add_heatmap_layer(m, df)
    _add_top50_layer(m, df, colormap)

    colormap.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    m.save(output_path)

    logger.info(f"Map written → {output_path}")
    return output_path
