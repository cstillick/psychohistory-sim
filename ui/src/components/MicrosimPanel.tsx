import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { MicrosimResult } from "../types";
import { fmtNum, fmtPct, fmtUsd } from "../format";

export function MicrosimPanel({ m }: { m: MicrosimResult }) {
  const data = m.decile_table.map((d) => ({
    decile: d.decile,
    pct: Number(d.avg_pct_change.toFixed(3)),
    usd: d.avg_change_usd,
  }));
  const povDelta = (m.poverty_rate_reform - m.poverty_rate_baseline) * 100;
  const giniDelta = m.gini_reform - m.gini_baseline;

  return (
    <>
      <div className="cards">
        <div className="card">
          <div className="label">poverty rate (SPM)</div>
          <div className="value">
            {(m.poverty_rate_reform * 100).toFixed(2)}%
            <span className={povDelta < 0 ? "pos" : povDelta > 0 ? "neg" : "dim"} style={{ fontSize: 12, marginLeft: 6 }}>
              {povDelta === 0 ? "±0.00pp" : `${povDelta > 0 ? "+" : ""}${povDelta.toFixed(2)}pp`}
            </span>
          </div>
          <div className="sub">was {(m.poverty_rate_baseline * 100).toFixed(2)}%</div>
        </div>
        <div className="card">
          <div className="label">gini</div>
          <div className="value">
            {m.gini_reform.toFixed(4)}
            <span className={giniDelta < 0 ? "pos" : giniDelta > 0 ? "neg" : "dim"} style={{ fontSize: 12, marginLeft: 6 }}>
              {giniDelta === 0 ? "±0" : `${giniDelta > 0 ? "+" : ""}${giniDelta.toFixed(4)}`}
            </span>
          </div>
          <div className="sub">was {m.gini_baseline.toFixed(4)}</div>
        </div>
      </div>
      <div className="cards">
        <div className="card">
          <div className="label">households better off</div>
          <div className="value pos">{fmtNum(m.households_better_off)}</div>
        </div>
        <div className="card">
          <div className="label">worse off</div>
          <div className="value neg">{fmtNum(m.households_worse_off)}</div>
        </div>
        <div className="card">
          <div className="label">unchanged</div>
          <div className="value dim">{fmtNum(m.households_unchanged)}</div>
        </div>
      </div>
      <div className="helper">
        Avg % change in household net income by baseline income decile (1 = poorest 10%), {m.state} households.
      </div>
      <div style={{ flex: 1, minHeight: 150 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 6, right: 4, bottom: 0, left: -18 }}>
            <XAxis dataKey="decile" tick={{ fill: "#5f6368", fontSize: 10, fontFamily: "inherit" }} axisLine={{ stroke: "#2a2e33" }} tickLine={false} />
            <YAxis tick={{ fill: "#5f6368", fontSize: 10, fontFamily: "inherit" }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}%`} />
            <ReferenceLine y={0} stroke="#2a2e33" />
            <Tooltip
              cursor={{ fill: "#1d2024" }}
              contentStyle={{ background: "#161616", border: "1px solid #2a2e33", fontFamily: "inherit", fontSize: 11 }}
              labelStyle={{ color: "#9aa0a6" }}
              formatter={(value, name) =>
                name === "pct" ? [fmtPct(Number(value)), "avg Δ%"] : [fmtUsd(Number(value), 0), "avg $/hh"]
              }
              labelFormatter={(l) => `decile ${String(l)}`}
            />
            <Bar dataKey="pct" isAnimationActive={false}>
              {data.map((d) => (
                <Cell key={d.decile} fill={d.pct >= 0 ? "#3df58b" : "#ff5c5c"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}
