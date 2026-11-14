import { useEffect, useMemo, useState } from 'react';
import L from 'leaflet';
import { MapContainer, Marker, TileLayer, useMap, useMapEvents } from 'react-leaflet';
import { Icon, Spinner } from './ui.jsx';

// A CSS pin (divIcon) avoids Leaflet's default marker images, which bundlers break.
export const pinIcon = L.divIcon({ className: 'geo-pin', html: '<span></span>', iconSize: [26, 30], iconAnchor: [13, 28] });

// Whole-India view until the user picks a point; not a location claim.
const INDIA = { center: [22.5, 79.0], zoom: 4 };

export const OSM_TILES = {
  url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
};

function ClickToSet({ onPick }) {
  useMapEvents({
    click(e) {
      onPick(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

function FlyTo({ target }) {
  const map = useMap();
  useEffect(() => {
    if (target) map.flyTo(target, Math.max(map.getZoom(), 16), { duration: 0.6 });
  }, [target, map]);
  return null;
}

const round6 = (v) => Math.round(v * 1e6) / 1e6;

/** Pick a point on an OSM map: click, drag the pin, or "Use my location". */
export default function LocationPicker({ lat, lng, onChange, height = 260, required = false }) {
  const has = lat !== null && lat !== undefined && lng !== null && lng !== undefined && lat !== '' && lng !== '';
  const [fly, setFly] = useState(null);
  const [locating, setLocating] = useState(false);
  const [geoErr, setGeoErr] = useState(null);
  const initial = useMemo(() => (has ? { center: [lat, lng], zoom: 16 } : INDIA), []); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (la, ln) => onChange({ lat: round6(la), lng: round6(ln) });
  const handlers = useMemo(
    () => ({
      dragend(e) {
        const p = e.target.getLatLng();
        pick(p.lat, p.lng);
      },
    }),
    [], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const locate = () => {
    if (!navigator.geolocation) {
      setGeoErr('This browser cannot share its location. Click the map instead.');
      return;
    }
    setLocating(true);
    setGeoErr(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        pick(pos.coords.latitude, pos.coords.longitude);
        setFly([pos.coords.latitude, pos.coords.longitude]);
      },
      (err) => {
        setLocating(false);
        setGeoErr(err.code === 1 ? 'Location permission denied. Click the map to place the pin.' : 'Could not get your location. Click the map instead.');
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  };

  return (
    <div className="min-w-0">
      <div className="relative overflow-hidden rounded-xl border border-outline" style={{ height }}>
        <MapContainer center={initial.center} zoom={initial.zoom} scrollWheelZoom={false} className="h-full w-full">
          <TileLayer url={OSM_TILES.url} attribution={OSM_TILES.attribution} />
          <ClickToSet onPick={pick} />
          <FlyTo target={fly} />
          {has && <Marker position={[lat, lng]} icon={pinIcon} draggable eventHandlers={handlers} />}
        </MapContainer>
        <button type="button" onClick={locate} className="btn btn-outline btn-sm absolute right-2 top-2 z-[500]" disabled={locating}>
          {locating ? <Spinner /> : <Icon name="my_location" className="text-[16px] text-paytm-cyan-dark" />}
          Use my location
        </button>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2 text-body-sm">
        {has ? (
          <span className="tnum font-mono text-[11px] text-on-surface-variant">
            {Number(lat).toFixed(5)}° N, {Number(lng).toFixed(5)}° E
          </span>
        ) : (
          <span className={required ? 'text-amber-700' : 'text-on-surface-variant'}>
            {required ? 'Required: click the map or use your location.' : 'No location set.'}
          </span>
        )}
        <span className="text-on-surface-variant">Click the map or drag the pin</span>
      </div>
      {geoErr && <div className="mt-1 text-body-sm text-amber-700">{geoErr}</div>}
    </div>
  );
}
