import { useDeferredValue } from "react";

import type { PanelMeta } from "../types";

type PanelLibraryProps = {
  filter: string;
  onFilterChange: (value: string) => void;
  panels: PanelMeta[];
  onPick: (panel: PanelMeta) => void;
};

export function PanelLibrary(props: PanelLibraryProps) {
  const deferredFilter = useDeferredValue(props.filter);
  const normalized = deferredFilter.trim().toLowerCase();
  const panels = props.panels.filter((panel) => {
    if (!normalized) {
      return true;
    }
    return [panel.display_name, panel.panel_id, panel.panel_type]
      .join(" ")
      .toLowerCase()
      .includes(normalized);
  });

  return (
    <section className="panel-library card-surface">
      <div className="section-head">
        <div>
          <p className="eyebrow">Panel Library</p>
          <h3>Registered surfaces</h3>
        </div>
        <input
          className="ghost-input"
          onChange={(event) => props.onFilterChange(event.currentTarget.value)}
          placeholder="filter panels"
          value={props.filter}
        />
      </div>
      <div className="library-list">
        {panels.map((panel) => (
          <button className="library-chip" key={panel.panel_id} onClick={() => props.onPick(panel)} type="button">
            <span>{panel.display_name}</span>
            <strong>{panel.panel_id}</strong>
            <em>{panel.panel_type}</em>
          </button>
        ))}
      </div>
    </section>
  );
}

