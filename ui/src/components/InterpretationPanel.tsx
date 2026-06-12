import type { Extraction } from "../types";
import type { EditableMapping } from "../mappings";
import { fmtUsd } from "../format";

/* The editable "what the AI thought you meant" panel.
   Mapped provisions expose their numeric lever; edits flow up and re-run
   (debounced in App). Unmapped or rejected provisions render as warnings. */

interface Props {
  extraction: Extraction | null;
  mappings: EditableMapping[];
  unrunWarnings: string[];
  onEdit: (index: number, value: number) => void;
}

export function InterpretationPanel({ extraction, mappings, unrunWarnings, onEdit }: Props) {
  if (!extraction && mappings.length === 0) {
    return (
      <div className="empty">
        No AI interpretation yet.
        <br />
        Type a policy in the command bar and hit enter.
      </div>
    );
  }
  const unmapped = (extraction?.provisions ?? []).filter((p) => p.mapping_type === "unmapped");

  return (
    <>
      <div className="helper">
        What the AI mapped each provision to. Every value is editable — edits re-run the simulation.
      </div>
      {mappings.map((m, i) => (
        <div className="prov" key={`${m.kind}:${m.key}`}>
          <div className="desc">{m.provision?.description ?? m.key}</div>
          <div className="target">
            <span className="dim">{m.kind === "parameter" ? "param" : "spend"}</span>
            <span>{m.key}</span>
            {m.kind === "parameter" ? (
              <input
                type="number"
                step="any"
                aria-label={`value for ${m.key}`}
                value={m.value}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  if (!Number.isNaN(v)) onEdit(i, v);
                }}
              />
            ) : (
              <>
                <input
                  type="number"
                  step="1000000"
                  aria-label={`annual dollars for ${m.key}`}
                  value={m.value}
                  onChange={(e) => {
                    const v = parseFloat(e.target.value);
                    if (!Number.isNaN(v)) onEdit(i, v);
                  }}
                />
                <span className="dim">{fmtUsd(m.value)}/yr</span>
              </>
            )}
            {m.provision && <span className={`tag ${m.provision.confidence}`}>{m.provision.confidence} conf</span>}
          </div>
          {m.provision?.confidence === "low" && (
            <div className="warnbox" style={{ margin: "4px 0 0" }}>
              Low-confidence mapping — verify this lever: {m.provision.rationale}
            </div>
          )}
        </div>
      ))}
      {unmapped.map((p, i) => (
        <div className="prov" key={`un:${i}`}>
          <div className="desc dim">{p.description}</div>
          <div className="target">
            <span className="tag unmapped">not modeled</span>
            <span className="dim">{p.rationale}</span>
          </div>
        </div>
      ))}
      {unrunWarnings.map((w, i) => (
        <div className="warnbox" key={i}>
          {w}
        </div>
      ))}
    </>
  );
}
