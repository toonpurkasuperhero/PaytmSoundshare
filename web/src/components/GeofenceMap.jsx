import { useEffect, useMemo } from 'react';
import L from 'leaflet';
import { Circle, CircleMarker, MapContainer, Marker, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet';
import { OSM_TILES, pinIcon } from './LocationPicker.jsx';

function ClickToMove({ onMove }) {
  useMapEvents({
    click(e) {
      onMove(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

function FitRadius({ lat, lng, radius }) {
  const map = useMap();
  useEffect(() => {
    map.fitBounds(L.latLng(lat, lng).toBounds(radius * 2.4), { animate: true, maxZoom: 17 });
    // Only refit when the radius or centre changes.
  }, [radius, lat, lng, map]);
  return null;
}

const r6 = (v) => Math.round(v * 1e6) / 1e6;

/**
 * Campaign geofence: draggable centre, radius circle and the real Soundboxes returned by
 * GET /api/geo/soundboxes (only devices whose merchants have a location).
 */
export default function GeofenceMap({ lat, lng, radius, onChange, soundboxes = [], height = 240 }) {
  const handlers = useMemo(
    () => ({
      dragend(e) {
        const p = e.target.getLatLng();
        onChange({ lat: r6(p.lat), lng: r6(p.lng) });
      },
    }),
    [onChange],
  );
  return (
    <div className="relative overflow-hidden rounded-xl border border-slate-200" style={{ height }}>
      <MapContainer center={[lat, lng]} zoom={15} scrollWheelZoom={false} className="h-full w-full">
        <TileLayer url={OSM_TILES.url} attribution={OSM_TILES.attribution} />
        <ClickToMove onMove={(la, ln) => onChange({ lat: r6(la), lng: r6(ln) })} />
        <FitRadius lat={lat} lng={lng} radius={radius} />
        <Circle center={[lat, lng]} radius={radius} pathOptions={{ color: '#00BAF2', weight: 2, dashArray: '5 5', fillColor: '#00BAF2', fillOpacity: 0.12 }} />
        <Marker position={[lat, lng]} icon={pinIcon} draggable eventHandlers={handlers} />
        {soundboxes
          .filter((s) => s.lat != null && s.lng != null)
          .map((s) => (
            <CircleMarker
              key={s.device_id}
              center={[s.lat, s.lng]}
              radius={7}
              pathOptions={{ color: '#ffffff', weight: 2, fillColor: s.online ? '#0099cc' : '#94A3B8', fillOpacity: 1 }}
            >
              <Tooltip direction="top" offset={[0, -6]} className="sb-tip">
                {s.device_id} · {s.merchant_name}
                {s.online ? '' : ' (offline)'}
              </Tooltip>
            </CircleMarker>
          ))}
      </MapContainer>
    </div>
  );
}
