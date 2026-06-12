import { useState } from "react";
import { msaBreakdown, type MSAEffect } from "../api";
import type { IOResult } from "../types";
import { fmtNum, fmtSigned, fmtUsd } from "../format";

const SCENARIOS = ["low", "central", "high"] as const;

function MSADrilldown({ io }: { io: IOResult }) {
  const [rows, setRows] = useState<MSAEffect[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = async () => {
    setBusy(true);
    setErr(null);
    try {
      setRows(
        await msaBreakdown({
          state: io.state,
          shock_kind: io.shock_kind,
          shock_total_usd: io.shock_total_usd,
          spending_vector: io.spending_vector,
        }),
      );
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  if (rows == null) {
    return (
      <div style={{ marginTop: 8 }}>
        <button className="tag" style={{ cursor: "pointer", background: "none" }} onClick={load} disabled={busy}>
          {busy ? "loading MSAs…" : `▸ drill into ${io.state} metro areas`}
        </button>
        {err && <div className="errbox">{err}</div>}
      </div>
    );
  }
  return (
    <>
      <div className="helper" style={{ marginTop: 8 }}>
        Metro drill-down — the state shock apportioned by each MSA's employment share, with MSA-specific
        multipliers. Shares don't sum to 100% (rural areas; multi-state metros matched whole).
      </div>
      <table>
        <thead>
          <tr>
            <th>MSA</th>
            <th>share</th>
            <th>jobs I</th>
            <th>jobs II</th>
            <th>output II</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td className="dim" colSpan={5}>no MSA data available</td>
            </tr>
          )}
          {rows.map((r) => (
            <tr key={r.area} className="rowline">
              <td className="muted" title={r.title}>
                {r.title.length > 30 ? r.title.slice(0, 28) + "…" : r.title}
              </td>
              <td className="dim">{(r.employment_share * 100).toFixed(0)}%</td>
              <td className={r.jobs_type1 >= 0 ? "pos" : "neg"}>{fmtSigned(r.jobs_type1)}</td>
              <td className={r.jobs_type2 >= 0 ? "pos" : "neg"}>{fmtSigned(r.jobs_type2)}</td>
              <td className="dim">{fmtUsd(r.output_type2_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function EconomyPanel({ io }: { io: IOResult }) {
  const topIndustries = (io.by_industry["II"] ?? [])
    .slice()
    .sort((a, b) => Math.abs(b.jobs) - Math.abs(a.jobs))
    .slice(0, 5);

  return (
    <>
      <div className="helper">
        Regional input–output effects in {io.state}. Type I = direct + indirect (supply chains); Type II adds
        induced household re-spending — shown separately, never summed. Low/high are sensitivity bands.
      </div>
      {(["I", "II"] as const).map((t) => {
        const scens = io.effects[t];
        if (!scens) return null;
        return (
          <table key={t} style={{ marginBottom: 8 }}>
            <thead>
              <tr>
                <th>{t === "I" ? "Type I (dir+indir)" : "Type II (+induced)"}</th>
                <th>jobs</th>
                <th>output</th>
                <th>earnings</th>
                <th>mult</th>
              </tr>
            </thead>
            <tbody>
              {SCENARIOS.map((s) => {
                const e = scens[s];
                if (!e) return null;
                const central = s === "central";
                return (
                  <tr key={s} className="rowline">
                    <td className={central ? "amber" : "dim"}>{s}</td>
                    <td className={central ? (e.jobs >= 0 ? "pos" : "neg") : "dim"}>{fmtSigned(e.jobs)}</td>
                    <td className={central ? "" : "dim"}>{fmtUsd(e.output_usd)}</td>
                    <td className={central ? "" : "dim"}>{fmtUsd(e.earnings_usd)}</td>
                    <td className="dim">×{fmtNum(e.output_multiplier, 2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        );
      })}
      {topIndustries.length > 0 && (
        <>
          <div className="helper">Top sectors by jobs (Type II, central):</div>
          <table>
            <tbody>
              {topIndustries.map((ind) => (
                <tr key={ind.sector} className="rowline">
                  <td className="muted" title={ind.sector_name}>
                    {ind.sector_name.length > 38 ? ind.sector_name.slice(0, 36) + "…" : ind.sector_name}
                  </td>
                  <td className={ind.jobs >= 0 ? "pos" : "neg"}>{fmtSigned(ind.jobs)}</td>
                  <td className="dim">{fmtUsd(ind.output_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {/* keyed so the drill-down resets when the run changes */}
      <MSADrilldown key={`${io.state}:${io.shock_kind}:${io.shock_total_usd}`} io={io} />
    </>
  );
}
