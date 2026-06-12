import { memo, useMemo, useState } from "react";
import { ComposableMap, Geographies, Geography } from "react-simple-maps";
import type { SimulationResult } from "../types";
import { FIPS_TO_STATE, STATE_NAMES, fmtPct, fmtSigned, fmtUsd } from "../format";

export type MapLayer = "income_pct" | "income_hh" | "jobs" | "output" | "earnings";

const LAYERS: { key: MapLayer; label: string; help: string }[] = [
  { key: "income_pct", label: "NET INCOME Δ%", help: "% change in aggregate household net income (microsim)" },
  { key: "income_hh", label: "$/HOUSEHOLD", help: "average net-income change per household (microsim)" },
  { key: "jobs", label: "JOBS", help: "jobs supported, Type II central (I-O on each state's share of the gain)" },
  { key: "output", label: "OUTPUT", help: "output effect, Type II central (I-O)" },
  { key: "earnings", label: "EARNINGS", help: "earnings effect, Type II central (I-O)" },
];

function lerp(a: number, b: number, t: number) {
  return Math.round(a + (b - a) * t);
}
function hexToRgb(h: string): [number, number, number] {
  return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
}
const LOSS = hexToRgb("#5b8def");
const ZERO = hexToRgb("#1d2024");
const GAIN = hexToRgb("#ffb000");

function divergingColor(v: number, maxAbs: number): string {
  if (!maxAbs || Number.isNaN(v)) return "#1d2024";
  const t = Math.max(-1, Math.min(1, v / maxAbs));
  const [from, to] = t < 0 ? [ZERO, LOSS] : [ZERO, GAIN];
  const k = Math.abs(t) ** 0.6; // perceptual boost for small values
  return `rgb(${lerp(from[0], to[0], k)},${lerp(from[1], to[1], k)},${lerp(from[2], to[2], k)})`;
}

function layerValue(result: SimulationResult | null, layer: MapLayer, st: string): number | null {
  if (!result) return null;
  if (layer === "income_pct" || layer === "income_hh") {
    const imp = result.microsim?.state_breakdown?.[st];
    if (!imp) return null;
    return layer === "income_pct" ? imp.pct_change : imp.avg_change_per_household_usd;
  }
  const sj = result.io_by_state?.[st];
  if (!sj) return null;
  if (layer === "jobs") return sj.jobs_type2;
  if (layer === "output") return sj.output_type2_usd;
  return sj.earnings_type2_usd;
}

function fmtLayer(layer: MapLayer, v: number | null): string {
  if (v == null) return "—";
  if (layer === "income_pct") return fmtPct(v);
  if (layer === "jobs") return fmtSigned(v);
  return fmtUsd(v);
}

interface Props {
  result: SimulationResult | null;
  selected: string;
  onSelect: (state: string) => void;
}

export const USMap = memo(function USMap({ result, selected, onSelect }: Props) {
  const [layer, setLayer] = useState<MapLayer>("income_pct");
  const [hovered, setHovered] = useState<string | null>(null);

  const ioMissing = result != null && result.io_by_state == null;
  const effLayer: MapLayer = ioMissing && layer !== "income_pct" && layer !== "income_hh" ? "income_pct" : layer;

  const maxAbs = useMemo(() => {
    if (!result) return 0;
    let m = 0;
    for (const f of Object.values(FIPS_TO_STATE)) {
      const v = layerValue(result, effLayer, f);
      if (v != null) m = Math.max(m, Math.abs(v));
    }
    return m;
  }, [result, effLayer]);

  const focus = hovered ?? selected;
  const imp = result?.microsim?.state_breakdown?.[focus];
  let sj = result?.io_by_state?.[focus];
  // Spending-only runs have no national breakdown, but the run state itself
  // has full I-O results — surface them in the readout.
  if (!sj && result?.io && result.io.state === focus) {
    const eff = result.io.effects;
    if (eff.I?.central && eff.II?.central && eff.II.low && eff.II.high) {
      sj = {
        shock_usd: result.io.shock_total_usd,
        jobs_type1: eff.I.central.jobs,
        jobs_type2: eff.II.central.jobs,
        jobs_type2_low: eff.II.low.jobs,
        jobs_type2_high: eff.II.high.jobs,
        output_type2_usd: eff.II.central.output_usd,
        earnings_type2_usd: eff.II.central.earnings_usd,
      };
    }
  }
  const layerMeta = LAYERS.find((l) => l.key === effLayer)!;

  return (
    <>
      <div className="map-layers" role="tablist" aria-label="Map layer">
        {LAYERS.map((l) => {
          const disabled = (l.key === "jobs" || l.key === "output" || l.key === "earnings") && ioMissing;
          return (
            <button
              key={l.key}
              role="tab"
              aria-selected={effLayer === l.key}
              className={effLayer === l.key ? "active" : ""}
              disabled={disabled}
              title={disabled ? "needs a budget-delta run (national I-O breakdown)" : l.help}
              onClick={() => setLayer(l.key)}
            >
              {l.label}
            </button>
          );
        })}
      </div>
      <div className="helper">{layerMeta.help}. Click a state to focus it.</div>
      <div className="map-wrap">
        <ComposableMap projection="geoAlbersUsa" style={{ width: "100%", height: "100%" }}>
          <Geographies geography="/states-10m.json">
            {({ geographies }) =>
              geographies.map((geo) => {
                const st = FIPS_TO_STATE[String(geo.id).padStart(2, "0")];
                if (!st) return null;
                const v = layerValue(result, effLayer, st);
                const isSel = st === selected;
                return (
                  <Geography
                    key={geo.rsmKey}
                    geography={geo}
                    onMouseEnter={() => setHovered(st)}
                    onMouseLeave={() => setHovered(null)}
                    onClick={() => onSelect(st)}
                    tabIndex={-1}
                    style={{
                      default: {
                        fill: v == null ? "#141414" : divergingColor(v, maxAbs),
                        stroke: isSel ? "#ffb000" : "#2a2e33",
                        strokeWidth: isSel ? 1.4 : 0.5,
                        outline: "none",
                      },
                      hover: { fill: "#3a3f45", stroke: "#ffb000", strokeWidth: 1, outline: "none", cursor: "pointer" },
                      pressed: { fill: "#ffb000", outline: "none" },
                    }}
                  />
                );
              })
            }
          </Geographies>
        </ComposableMap>
      </div>
      <div className="legend">
        <span>loss</span>
        <span className="bar" />
        <span>gain</span>
        <span style={{ marginLeft: 10 }}>
          scale ±{fmtLayer(effLayer, maxAbs)} · colorblind-safe diverging
        </span>
      </div>
      <div className="map-readout">
        <table>
          <tbody>
            <tr>
              <td className="amber" style={{ fontSize: 14, fontWeight: 700 }}>
                {STATE_NAMES[focus] ?? focus} ({focus})
              </td>
              <td className="dim">{hovered ? "hover" : "selected"}</td>
            </tr>
            <tr className="rowline">
              <td className="muted">net income Δ</td>
              <td className={imp && imp.total_change_usd >= 0 ? "pos" : "neg"}>
                {imp ? fmtUsd(imp.total_change_usd) : "—"}
              </td>
            </tr>
            <tr className="rowline">
              <td className="muted">Δ% / per household</td>
              <td>
                {imp ? `${fmtPct(imp.pct_change)} · ${fmtUsd(imp.avg_change_per_household_usd, 0)}/hh` : "—"}
              </td>
            </tr>
            <tr className="rowline">
              <td className="muted">jobs (Type I / II)</td>
              <td>{sj ? `${fmtSigned(sj.jobs_type1)} / ${fmtSigned(sj.jobs_type2)}` : "—"}</td>
            </tr>
            <tr className="rowline">
              <td className="muted">jobs II band (low–high)</td>
              <td className="dim">{sj ? `${fmtSigned(sj.jobs_type2_low)} – ${fmtSigned(sj.jobs_type2_high)}` : "—"}</td>
            </tr>
            <tr>
              <td className="muted">output / earnings (II)</td>
              <td>{sj ? `${fmtUsd(sj.output_type2_usd)} / ${fmtUsd(sj.earnings_type2_usd)}` : "—"}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </>
  );
});
