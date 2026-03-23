import type { LayoutDocument, PanelMeta } from "../types";
import { describePath, getNode, getTab, isPanelRef, type NodePath } from "../state/editor";

type InspectorProps = {
  layout: LayoutDocument;
  panels: PanelMeta[];
  selectedTabId: string;
  selectedPath: NodePath;
  dirty: boolean;
  validationErrors: string[];
  pending: boolean;
  onSetRatio: (ratio: number) => void;
  onToggleOrientation: () => void;
  onSplitHorizontal: () => void;
  onSplitVertical: () => void;
  onRemove: () => void;
  onReplace: (panelId: string) => void;
  onValidate: () => void;
  onSave: () => void;
  onReset: () => void;
};

export function Inspector(props: InspectorProps) {
  const node = getNode(getTab(props.layout, props.selectedTabId).root_split, props.selectedPath);
  const isLeaf = isPanelRef(node);
  return (
    <aside className="inspector card-surface">
      <div className="section-head">
        <div>
          <p className="eyebrow">Inspector</p>
          <h3>{isLeaf ? "Panel node" : "Split node"}</h3>
        </div>
        <span className={`status-pill${props.dirty ? " dirty" : ""}`}>{props.dirty ? "unsaved" : "clean"}</span>
      </div>
      <dl className="inspector-grid">
        <div>
          <dt>Path</dt>
          <dd>{describePath(props.selectedPath)}</dd>
        </div>
        <div>
          <dt>Tab</dt>
          <dd>{props.selectedTabId}</dd>
        </div>
        {isLeaf ? (
          <>
            <div>
              <dt>Panel</dt>
              <dd>{node.panel_id}</dd>
            </div>
            <div>
              <dt>Type</dt>
              <dd>{node.panel_type}</dd>
            </div>
          </>
        ) : (
          <>
            <div>
              <dt>Orientation</dt>
              <dd>{node.orientation ?? "vertical"}</dd>
            </div>
            <div>
              <dt>Ratio</dt>
              <dd>{Math.round((node.ratio ?? 0.5) * 100)}%</dd>
            </div>
          </>
        )}
      </dl>
      {!isLeaf ? (
        <label className="slider-label">
          Split ratio
          <input
            max="0.8"
            min="0.2"
            onChange={(event) => props.onSetRatio(Number(event.currentTarget.value))}
            step="0.05"
            type="range"
            value={node.ratio ?? 0.5}
          />
        </label>
      ) : null}
      <div className="action-grid">
        <button onClick={props.onToggleOrientation} type="button">
          Toggle orientation
        </button>
        <button onClick={props.onSplitHorizontal} type="button">
          Split horizontal
        </button>
        <button onClick={props.onSplitVertical} type="button">
          Split vertical
        </button>
        <button onClick={props.onRemove} type="button">
          Remove node
        </button>
      </div>
      {isLeaf ? (
        <label className="replace-label">
          Replace panel
          <select onChange={(event) => props.onReplace(event.currentTarget.value)} value={node.panel_id}>
            {props.panels.map((panel) => (
              <option key={panel.panel_id} value={panel.panel_id}>
                {panel.display_name} ({panel.panel_type})
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <div className="action-grid footer-actions">
        <button onClick={props.onValidate} type="button">
          Validate
        </button>
        <button disabled={props.pending} onClick={props.onSave} type="button">
          Save layout
        </button>
        <button disabled={props.pending} onClick={props.onReset} type="button">
          Reset draft
        </button>
      </div>
      <div className="validation-stack">
        {props.validationErrors.length ? (
          props.validationErrors.map((error) => (
            <div className="validation-error" key={error}>
              {error}
            </div>
          ))
        ) : (
          <div className="validation-ok">Validation is currently clean.</div>
        )}
      </div>
    </aside>
  );
}

