"""Leaflet map with clustered CRM/parking objects."""
from __future__ import annotations

import json

import streamlit.components.v1 as components

from src.services.map_export import DEFAULT_CENTER


def render_map(
    geojson: dict,
    center: tuple[float, float] = DEFAULT_CENTER,
    zoom: int = 11,
    height: int = 620,
    highlight_ogrn: str | None = None,
) -> None:
    """Render an interactive OpenStreetMap + MarkerCluster map in Streamlit."""
    geojson_str = json.dumps(geojson, ensure_ascii=False)
    center_lat, center_lon = center
    highlight_js = json.dumps(highlight_ogrn or "")

    html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"/>
  <style>
    html, body, #map {{ margin: 0; padding: 0; height: 100%; width: 100%; }}
    .leaflet-popup-content {{ font-family: system-ui, sans-serif; font-size: 12px; line-height: 1.45; }}
    .popup-title {{ font-weight: 700; font-size: 13px; margin-bottom: 6px; color: #1E293B; }}
    .popup-row {{ color: #475569; margin: 2px 0; }}
    .popup-badge {{
      display: inline-block; padding: 1px 8px; border-radius: 999px;
      font-size: 10px; font-weight: 700; margin-top: 4px;
      background: #F1F5F9; color: #334155;
    }}
    .hydro-marker {{
      width: 30px; height: 30px; border-radius: 999px;
      display: flex; align-items: center; justify-content: center;
      color: #fff; border: 2px solid #fff;
      box-shadow: 0 2px 8px rgba(15,23,42,.35);
      font-size: 16px; line-height: 1;
    }}
    .hydro-marker-small {{ width: 24px; height: 24px; font-size: 13px; }}
  </style>
</head>
<body>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
  <script>
    const geojson = {geojson_str};
    const highlightOgrn = {highlight_js};

    const map = L.map('map').setView([{center_lat}, {center_lon}], {zoom});
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap'
    }}).addTo(map);

    const clusters = L.markerClusterGroup({{
      maxClusterRadius: 50,
      spiderfyOnMaxZoom: true,
      showCoverageOnHover: false,
    }});

    function value(v, fallback='—') {{
      return v === null || v === undefined || v === '' ? fallback : v;
    }}

    function popupHtml(p) {{
      const src = p.source_label || p.source_layer || '';
      const color = p.marker_color || '#94A3B8';
      const srcBadge = src
        ? `<span class="popup-badge" style="background:${{color}}22;color:${{color}};border:1px solid ${{color}}">${{src}}</span> `
        : '';
      const uk = p.uk_name ? `<div class="popup-row"><b>УК/контур:</b> ${{p.uk_name}}</div>` : '';
      const ogrn = p.uk_ogrn ? `<div class="popup-row">ОГРН ${{p.uk_ogrn}}</div>` : '';
      const ukErr = p.uk_error ? `<div class="popup-row" style="color:#B45309;font-size:11px;">${{p.uk_error}}</div>` : '';
      const floors = p.floors_underground != null
        ? `<div class="popup-row">Подземных этажей: <b>${{p.floors_underground}}</b></div>` : '';
      const totalFloors = p.floors_total != null ? `<div class="popup-row">Этажей всего: ${{p.floors_total}}</div>` : '';
      const area = p.area_total != null ? `<div class="popup-row">Площадь: ${{Number(p.area_total).toLocaleString('ru-RU')}} м²</div>` : '';
      const purpose = p.purpose ? `<div class="popup-row">Назначение: ${{p.purpose}}</div>` : '';
      const buildYear = p.building_year != null
        ? `<div class="popup-row">??? ?????????/?????: <b>${{p.building_year}}</b>${{p.building_age != null ? ` ? ${{p.building_age}} ???` : ''}}</div>` : '';
      const management = p.management_type ? `<div class="popup-row">Управление: ${{p.management_type}}</div>` : '';
      const material = p.wall_material ? `<div class="popup-row">Материал стен: ${{p.wall_material}}</div>` : '';
      const hydro = p.hydro_label
        ? `<div class="popup-row"><b>${{p.hydro_icon || '🅿️'}} ${{p.hydro_label}}</b> · score ${{p.hydro_score || 0}} · grade ${{p.hydro_grade || '—'}}</div>`
        : '';
      const reasons = p.hydro_reasons ? `<div class="popup-row" style="font-size:11px;color:#64748B;">${{p.hydro_reasons}}</div>` : '';
      const conf = p.confidence_score != null ? `<div class="popup-row">Confidence: ${{Number(p.confidence_score).toFixed(2)}}</div>` : '';
      const statusMap = {{
        'DONE': 'УК найдена',
        'TSG': 'ТСЖ',
        'UK_NOT_FOUND': 'УК не найдена',
        'HOUSE_NOT_FOUND': 'Дом не найден',
        'PENDING': 'Ожидает обогащения',
        'FAILED': 'Ошибка обогащения',
        'SKIPPED': 'Пропущено',
      }};
      const status = statusMap[p.uk_status] || p.uk_status || p.status || '—';
      return `
        <div class="popup-title">${{value(p.name || p.address, 'Объект')}}</div>
        <div class="popup-row">${{value(p.address, '')}}</div>
        <div class="popup-row">КН: ${{value(p.cadastral_number)}}</div>
        ${{hydro}}${{reasons}}${{purpose}}${{buildYear}}${{floors}}${{totalFloors}}${{area}}${{material}}${{conf}}${{uk}}${{management}}${{ogrn}}${{ukErr}}
        <div style="margin-top:6px;">${{srcBadge}}<span class="popup-badge">${{status}}</span></div>
      `;
    }}

    L.geoJSON(geojson, {{
      pointToLayer: function(feature, latlng) {{
        const p = feature.properties || {{}};
        if (highlightOgrn && p.uk_ogrn !== highlightOgrn) {{
          return L.circleMarker(latlng, {{
            radius: 4, fillColor: '#E2E8F0', color: '#CBD5E1',
            weight: 1, fillOpacity: 0.35, opacity: 0.5,
          }});
        }}
        if (p.source_layer === 'nspd' && p.hydro_icon) {{
          const radius = p.marker_radius || 8;
          const sizeClass = radius <= 8 ? ' hydro-marker-small' : '';
          const bg = p.marker_color || '#64748B';
          return L.marker(latlng, {{
            icon: L.divIcon({{
              className: '',
              html: `<div class="hydro-marker${{sizeClass}}" style="background:${{bg}}">${{p.hydro_icon}}</div>`,
              iconSize: [radius * 4, radius * 4],
              iconAnchor: [radius * 2, radius * 2],
              popupAnchor: [0, -radius * 2],
            }})
          }});
        }}
        const radius = p.marker_radius || 6;
        const weight = (p.confidence_score || 0) >= 0.9 ? 2 : 1;
        return L.circleMarker(latlng, {{
          radius: radius,
          fillColor: p.marker_color || '#94A3B8',
          color: '#ffffff',
          weight: weight,
          fillOpacity: 0.88,
        }});
      }},
      onEachFeature: function(feature, layer) {{
        layer.bindPopup(popupHtml(feature.properties || {{}}));
      }},
    }}).addTo(clusters);

    map.addLayer(clusters);
    if (geojson.features && geojson.features.length) {{
      try {{
        const bounds = clusters.getBounds();
        if (bounds.isValid()) {{
          const sw = bounds.getSouthWest();
          const ne = bounds.getNorthEast();
          if (sw.lat > 54 && ne.lat < 57 && sw.lng > 35 && ne.lng < 40) {{
            map.fitBounds(bounds.pad(0.05));
          }}
        }}
      }} catch (e) {{}}
    }}
  </script>
</body>
</html>
"""
    components.html(html, height=height, scrolling=False)
