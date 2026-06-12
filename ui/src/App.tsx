import { useCallback, useEffect, useRef, useState } from "react";
import { health, interpret, simulate } from "./api";
import { fmtUsd, STATE_NAMES } from "./format";
import type { Extraction, ReformSpec, SimulationResult } from "./types";
import { USMap } from "./components/USMap";
import { MicrosimPanel } from "./components/MicrosimPanel";
import { EconomyPanel } from "./components/EconomyPanel";
import { InterpretationPanel } from "./components/InterpretationPanel";
import { mappingsFromSpec, specWithMappings, type EditableMapping } from "./mappings";

const EXAMPLES: { label: string; spec: ReformSpec }[] = [
  {
    label: "CTC → $3,000",
    spec: {
      name: "Child Tax Credit to $3,000",
      geography: { state: "SC" },
      tax_transfer: { baseline_year: 2026, reforms: { "gov.irs.credits.ctc.amount.base[0].amount": 3000 } },
      spending: { source: "budget_delta" },
    },
  },
  {
    label: "$200M transit",
    spec: {
      name: "$200M/yr transit investment",
      geography: { state: "SC" },
      spending: {
        source: "explicit_program",
        explicit_program: [{ industry: "Transit and ground passenger transportation", amount_usd: 200_000_000 }],
      },
    },
  },
];

export default function App() {
  const [command, setCommand] = useState("");
  const [spec, setSpec] = useState<ReformSpec | null>(null);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [extraction, setExtraction] = useState<Extraction | null>(null);
  const [mappings, setMappings] = useState<EditableMapping[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [aiAvailable, setAiAvailable] = useState<boolean | null>(null);
  const [apiUp, setApiUp] = useState<boolean | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  const runSeq = useRef(0);

  const checkHealth = useCallback(() => {
    health()
      .then((h) => {
        setApiUp(true);
        setAiAvailable(h.ai_ingestion);
      })
      .catch(() => setApiUp(false));
  }, []);

  useEffect(() => {
    checkHealth();
  }, [checkHealth]);

  useEffect(() => {
    if (!loading) return;
    const started = Date.now();
    const t = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => {
      clearInterval(t);
      setElapsed(0);
    };
  }, [loading]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
        e.preventDefault();
        inputRef.current?.focus();
      }
      if (e.key === "Escape") inputRef.current?.blur();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const run = useCallback(async (s: ReformSpec, label: string, ext: Extraction | null) => {
    const seq = ++runSeq.current;
    setLoading(label);
    setError(null);
    try {
      const res = await simulate(s);
      if (seq !== runSeq.current) return; // superseded
      setSpec(s);
      setResult(res);
      setExtraction(ext);
      setMappings(mappingsFromSpec(s, ext));
      setWarnings(res.warnings);
    } catch (e) {
      if (seq !== runSeq.current) return;
      setError(String(e instanceof Error ? e.message : e));
      checkHealth(); // a failed request may mean the backend died
    } finally {
      if (seq === runSeq.current) setLoading(null);
    }
  }, [checkHealth]);

  const submitCommand = useCallback(async () => {
    const text = command.trim();
    if (!text || loading) return;
    if (text.startsWith("{")) {
      try {
        const s = JSON.parse(text) as ReformSpec;
        void run(s, `running spec: ${s.name ?? "manual"}`, null);
      } catch (e) {
        setError(`Spec JSON did not parse: ${e}`);
      }
      return;
    }
    const seq = ++runSeq.current;
    setLoading("interpreting policy text via Claude…");
    setError(null);
    try {
      const resp = await interpret(text, spec?.geography.state);
      if (seq !== runSeq.current) return;
      setExtraction(resp.extraction);
      setWarnings(resp.warnings);
      if (!resp.ran || !resp.result || !resp.spec) {
        setError(resp.message ?? "Nothing runnable was extracted — nothing was simulated.");
        setMappings([]);
        return;
      }
      setSpec(resp.spec);
      setResult(resp.result);
      setMappings(mappingsFromSpec(resp.spec, resp.extraction));
    } catch (e) {
      if (seq !== runSeq.current) return;
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      if (seq === runSeq.current) setLoading(null);
    }
  }, [command, loading, run, spec]);

  const selectState = useCallback(
    (st: string) => {
      if (!spec || loading) return;
      if (st === spec.geography.state) return;
      const next: ReformSpec = JSON.parse(JSON.stringify(spec));
      next.geography.state = st;
      void run(next, `re-running in ${STATE_NAMES[st] ?? st}…`, extraction);
    },
    [spec, loading, run, extraction],
  );

  const editMapping = useCallback(
    (index: number, value: number) => {
      if (!spec) return;
      setMappings((prev) => {
        const next = prev.map((m, i) => (i === index ? { ...m, value } : m));
        clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => {
          void run(specWithMappings(spec, next), "re-running with edited values…", extraction);
        }, 900);
        return next;
      });
    },
    [spec, run, extraction],
  );

  const selected = spec?.geography.state && spec.geography.state !== "US" ? spec.geography.state : "SC";
  const bridge = result?.bridge;
  const m = result?.microsim;

  return (
    <div className="app">
      <div className="cmdbar">
        <div className="logo">
          PSYCHOHISTORY <span>// policy impact terminal</span>
        </div>
        <input
          ref={inputRef}
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submitCommand()}
          placeholder={
            aiAvailable === false
              ? 'AI off (no ANTHROPIC_API_KEY) — paste a {"name":…} reform spec JSON, or use an example →'
              : 'type a policy ("raise the CTC to $3,000 and put $200M into transit in OK"), paste a bill, or a {spec} JSON — enter runs it'
          }
          aria-label="policy command"
          disabled={!!loading}
        />
        <select
          value={selected}
          aria-label="state"
          onChange={(e) => selectState(e.target.value)}
          disabled={!!loading || !spec}
          title="geography (also: click the map)"
        >
          {Object.keys(STATE_NAMES).map((st) => (
            <option key={st} value={st}>
              {st}
            </option>
          ))}
        </select>
        {EXAMPLES.map((ex) => (
          <button key={ex.label} disabled={!!loading} onClick={() => void run(ex.spec, `running ${ex.label}…`, null)}>
            {ex.label}
          </button>
        ))}
      </div>

      {apiUp === false && (
        <div className="errbox" style={{ margin: 0, borderLeft: "none", borderRight: "none" }}>
          Backend unreachable — start it with: uv run uvicorn api.app:app --port 8000
          &nbsp;<button className="tag" style={{ cursor: "pointer", background: "none" }} onClick={checkHealth}>
            retry
          </button>
        </div>
      )}
      <div className="grid">
        <div className="panel panel-map">
          <h2>
            United States — impact map
            <span className="hint">{result ? result.spec.name : "no run yet"}</span>
          </h2>
          {loading ? (
            <div className="loading">
              <div className="spinner">▮▮▮</div>
              <div style={{ marginTop: 8 }}>{loading}</div>
              <div className="dim" style={{ marginTop: 6 }}>
                {elapsed}s elapsed
                {elapsed > 12 && (
                  <>
                    <br />
                    microsimulation runs take a few minutes the first time
                    <br />
                    (the national household baseline is being computed; repeat runs are cached)
                  </>
                )}
              </div>
            </div>
          ) : result ? (
            <USMap result={result} selected={selected} onSelect={selectState} />
          ) : (
            <div className="empty">
              ┌─────────────────────────────────────┐
              <br />
              Run a policy to light up the map.
              <br />
              Press <kbd>/</kbd> to focus the command bar.
              <br />
              └─────────────────────────────────────┘
            </div>
          )}
          {error && <div className="errbox">{error}</div>}
          {warnings.length > 0 && !loading && (
            <div className="warnbox">
              {warnings.slice(0, 4).map((w, i) => (
                <div key={i}>⚠ {w}</div>
              ))}
              {warnings.length > 4 && <div className="dim">… {warnings.length - 4} more</div>}
            </div>
          )}
        </div>

        <div className="panel">
          <h2>
            Who it affects <span className="hint">microsimulation · {m ? `${m.state} ${m.baseline_year}` : "—"}</span>
          </h2>
          {m && (
            <div className="cards">
              <div className="card">
                <div className="label">net budget Δ (gov balance)</div>
                <div className={`value ${m.budget_delta_usd < 0 ? "neg" : "pos"}`}>{fmtUsd(m.budget_delta_usd)}</div>
                <div className="sub">{m.budget_delta_usd < 0 ? "cost to government" : "saving to government"} · national</div>
              </div>
            </div>
          )}
          {bridge?.io_shock_usd != null && (
            <div className="bridge">
              <span className="dim">BRIDGE</span>
              <span className="big">{fmtUsd(bridge.io_shock_usd)}</span>
              <span className="arrow">→</span>
              <span className="muted">
                {bridge.io_shock_source === "budget_delta"
                  ? `${selected} households' share of the change feeds the jobs model`
                  : "program spending feeds the jobs model"}
              </span>
            </div>
          )}
          {m ? (
            <MicrosimPanel m={m} />
          ) : (
            <div className="empty">No microsim in this run{result ? " (spending-only reform)" : ""}.</div>
          )}
        </div>

        <div className="panel">
          <h2>
            What it does to the economy <span className="hint">input–output · {result?.io?.state ?? "—"}</span>
          </h2>
          {result?.io ? <EconomyPanel io={result.io} /> : <div className="empty">No I-O run yet.</div>}
        </div>

        <div className="panel" style={{ gridColumn: "2 / 4" }}>
          <h2>
            Interpretation <span className="hint">editable — changes re-run automatically</span>
          </h2>
          <InterpretationPanel
            extraction={extraction}
            mappings={mappings}
            unrunWarnings={[]}
            onEdit={editMapping}
          />
        </div>
      </div>

      <div className="ticker">
        <span className={apiUp ? "live" : "dead"}>● API {apiUp == null ? "…" : apiUp ? "LIVE" : "DOWN"}</span>
        <span className={aiAvailable ? "live" : "dim"}>AI {aiAvailable == null ? "…" : aiAvailable ? "ON" : "OFF"}</span>
        <span className="dim">|</span>
        <div className="scroll">
          <div>
            {(result?.assumptions ?? [
              "STATIC MICROSIM — no behavioral response",
              "FIXED-COEFFICIENT I-O — LQ regionalization overstates multipliers",
              "TYPE I AND TYPE II REPORTED SEPARATELY — never one blended total",
              "LOW/HIGH ARE SENSITIVITY BANDS, NOT CONFIDENCE INTERVALS",
            ]).join("   ···   ")}
          </div>
        </div>
      </div>
    </div>
  );
}
