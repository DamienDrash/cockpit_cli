import { startTransition, useEffect, useState } from "react";

import { cloneLayout as cloneLayoutApi, fetchLayoutCollection, fetchLayoutDocument, saveLayout, validateLayout } from "./api/layoutEditor";
import { Inspector } from "./components/Inspector";
import { LayoutCanvas } from "./components/LayoutCanvas";
import { PanelLibrary } from "./components/PanelLibrary";
import {
  addTab,
  cloneLayout,
  defaultPanel,
  duplicateTab,
  moveNode,
  removeSelected,
  renameTab,
  replacePanel,
  removeTab,
  setRatio,
  splitSelected,
  toggleOrientation,
  type NodePath,
} from "./state/editor";
import type { LayoutDocument, LayoutSummary, PanelMeta } from "./types";

const INITIAL_PATH: NodePath = [];

export function App() {
  const [layouts, setLayouts] = useState<LayoutSummary[]>([]);
  const [panels, setPanels] = useState<PanelMeta[]>([]);
  const [activeLayoutId, setActiveLayoutId] = useState<string>("");
  const [savedLayout, setSavedLayout] = useState<LayoutDocument | null>(null);
  const [draftLayout, setDraftLayout] = useState<LayoutDocument | null>(null);
  const [selectedTabId, setSelectedTabId] = useState<string>("work");
  const [selectedPath, setSelectedPath] = useState<NodePath>(INITIAL_PATH);
  const [draggedPath, setDraggedPath] = useState<NodePath | null>(null);
  const [panelFilter, setPanelFilter] = useState("");
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [status, setStatus] = useState("Loading layout catalog...");

  useEffect(() => {
    startTransition(() => {
      void loadCollection();
    });
  }, []);

  async function loadCollection(preferredLayoutId?: string) {
    const collection = await fetchLayoutCollection();
    setLayouts(collection.layouts);
    setPanels(collection.panels);
    const nextLayoutId = preferredLayoutId ?? activeLayoutId ?? collection.layouts[0]?.id ?? "";
    if (!nextLayoutId) {
      setStatus("No saved layouts are available yet.");
      return;
    }
    await openLayout(nextLayoutId, collection.panels);
  }

  async function openLayout(layoutId: string, nextPanels: PanelMeta[] = panels) {
    setPending(true);
    try {
      const response = await fetchLayoutDocument(layoutId);
      setActiveLayoutId(layoutId);
      setPanels(nextPanels.length ? nextPanels : response.panels);
      setSavedLayout(response.layout);
      setDraftLayout(cloneLayout(response.layout));
      setSelectedTabId(response.layout.tabs[0]?.id ?? "work");
      setSelectedPath(INITIAL_PATH);
      setValidationErrors([]);
      setStatus(`Loaded layout ${response.layout.name}.`);
    } finally {
      setPending(false);
    }
  }

  if (!draftLayout) {
    return <main className="layout-editor loading-state">{status}</main>;
  }

  const dirty = JSON.stringify(savedLayout) !== JSON.stringify(draftLayout);

  function commit(nextLayout: LayoutDocument, message: string) {
    setDraftLayout(nextLayout);
    setValidationErrors([]);
    setStatus(message);
  }

  function pickPanel(panel: PanelMeta) {
    if (!draftLayout) {
      return;
    }
    const nextLayout = replacePanel(draftLayout, selectedTabId, selectedPath, {
      panel_id: panel.panel_id,
      panel_type: panel.panel_type,
    });
    commit(nextLayout, `Replaced selected node with ${panel.display_name}.`);
  }

  async function handleValidate() {
    if (!draftLayout) {
      return;
    }
    const result = await validateLayout(draftLayout);
    setValidationErrors(result.errors);
    setStatus(result.ok ? "Layout validation passed." : "Layout validation found issues.");
  }

  async function handleSave() {
    if (!draftLayout) {
      return;
    }
    setPending(true);
    try {
      await saveLayout(draftLayout);
      setSavedLayout(cloneLayout(draftLayout));
      setStatus(`Saved layout ${draftLayout.name}.`);
      await loadCollection(draftLayout.id);
    } finally {
      setPending(false);
    }
  }

  async function handleClone() {
    if (!draftLayout) {
      return;
    }
    const target_layout_id = `${draftLayout.id}-variant`;
    const cloned = await cloneLayoutApi(draftLayout.id, target_layout_id, `${draftLayout.name} Variant`);
    setStatus(`Cloned ${draftLayout.id} to ${cloned.id}.`);
    await loadCollection(cloned.id);
  }

  return (
    <main className="layout-editor">
      <section className="hero card-surface">
        <div>
          <p className="eyebrow">Cockpit // Layout Forge</p>
          <h1>Canvas-grade split editing for the operator plane.</h1>
          <p className="hero-copy">
            Move panels, carve new splits, validate the full document, then save once and reload the
            TUI when you are ready to apply.
          </p>
        </div>
        <div className="hero-actions">
          <select onChange={(event) => void openLayout(event.currentTarget.value)} value={activeLayoutId}>
            {layouts.map((layout) => (
              <option key={layout.id} value={layout.id}>
                {layout.name} ({layout.id})
              </option>
            ))}
          </select>
          <button onClick={() => void handleClone()} type="button">
            Clone active layout
          </button>
        </div>
      </section>

      <section className="editor-grid">
        <PanelLibrary
          filter={panelFilter}
          onFilterChange={setPanelFilter}
          onPick={pickPanel}
          panels={panels}
        />

        <section className="workspace-shell">
          <div className="tab-ribbon card-surface">
            {draftLayout.tabs.map((tab) => (
              <button
                className={`tab-chip${selectedTabId === tab.id ? " active" : ""}`}
                key={tab.id}
                onClick={() => {
                  setSelectedTabId(tab.id);
                  setSelectedPath(INITIAL_PATH);
                }}
                type="button"
              >
                <span>{tab.name}</span>
                <strong>{tab.id}</strong>
              </button>
            ))}
            <div className="tab-tools">
              <input
                className="ghost-input compact"
                onChange={(event) =>
                  commit(
                    renameTab(draftLayout, selectedTabId, event.currentTarget.value),
                    `Renamed tab ${selectedTabId}.`,
                  )
                }
                value={draftLayout.tabs.find((tab) => tab.id === selectedTabId)?.name ?? ""}
              />
              <button
                onClick={() => {
                  const nextLayout = addTab(
                    draftLayout,
                    `Tab ${draftLayout.tabs.length + 1}`,
                    defaultPanel(panels),
                  );
                  const nextTabId = nextLayout.tabs[nextLayout.tabs.length - 1]?.id ?? selectedTabId;
                  commit(nextLayout, `Added tab ${nextTabId}.`);
                  setSelectedTabId(nextTabId);
                  setSelectedPath(INITIAL_PATH);
                }}
                type="button"
              >
                Add tab
              </button>
              <button
                onClick={() => {
                  const nextLayout = duplicateTab(draftLayout, selectedTabId);
                  const nextTabId = nextLayout.tabs[nextLayout.tabs.length - 1]?.id ?? selectedTabId;
                  commit(nextLayout, `Duplicated tab ${selectedTabId} to ${nextTabId}.`);
                  setSelectedTabId(nextTabId);
                  setSelectedPath(INITIAL_PATH);
                }}
                type="button"
              >
                Duplicate
              </button>
              <button
                onClick={() => {
                  const nextLayout = removeTab(draftLayout, selectedTabId);
                  const nextTabId = nextLayout.tabs[0]?.id ?? selectedTabId;
                  commit(nextLayout, `Removed tab ${selectedTabId}.`);
                  setSelectedTabId(nextTabId);
                  setSelectedPath(INITIAL_PATH);
                }}
                type="button"
              >
                Remove
              </button>
            </div>
            <div className="status-copy">{status}</div>
          </div>

          <LayoutCanvas
            draggedPath={draggedPath}
            layout={draftLayout}
            onAdjustRatio={(path, ratio) =>
              commit(
                setRatio(draftLayout, selectedTabId, path, ratio),
                `Adjusted canvas split ratio to ${Math.round(ratio * 100)}%.`,
              )
            }
            onClearDrag={() => setDraggedPath(null)}
            onDropNode={(sourcePath, targetPath) => {
              if (JSON.stringify(sourcePath) === JSON.stringify(targetPath)) {
                return;
              }
              commit(
                moveNode(draftLayout, selectedTabId, sourcePath, targetPath),
                "Moved node inside the split tree.",
              );
              setDraggedPath(null);
            }}
            onSelect={setSelectedPath}
            onStartDrag={setDraggedPath}
            panels={panels}
            selectedPath={selectedPath}
            selectedTabId={selectedTabId}
          />
        </section>

        <Inspector
          dirty={dirty}
          layout={draftLayout}
          onRemove={() => commit(removeSelected(draftLayout, selectedTabId, selectedPath), "Removed selected node.")}
          onReplace={(panelId) => {
            const panel = panels.find((candidate) => candidate.panel_id === panelId);
            if (!panel) {
              return;
            }
            commit(
              replacePanel(draftLayout, selectedTabId, selectedPath, {
                panel_id: panel.panel_id,
                panel_type: panel.panel_type,
              }),
              `Replaced selected panel with ${panel.display_name}.`,
            );
          }}
          onReset={() => {
            if (!savedLayout) {
              return;
            }
            setDraftLayout(cloneLayout(savedLayout));
            setValidationErrors([]);
            setStatus(`Reset draft for ${savedLayout.name}.`);
          }}
          onSave={() => void handleSave()}
          onSetRatio={(ratio) => commit(setRatio(draftLayout, selectedTabId, selectedPath, ratio), `Adjusted split ratio to ${Math.round(ratio * 100)}%.`)}
          onSplitHorizontal={() =>
            commit(
              splitSelected(draftLayout, selectedTabId, selectedPath, "horizontal", defaultPanel(panels)),
              "Added a horizontal split around the selected node.",
            )
          }
          onSplitVertical={() =>
            commit(
              splitSelected(draftLayout, selectedTabId, selectedPath, "vertical", defaultPanel(panels)),
              "Added a vertical split around the selected node.",
            )
          }
          onToggleOrientation={() =>
            commit(toggleOrientation(draftLayout, selectedTabId, selectedPath), "Toggled split orientation.")
          }
          onValidate={() => void handleValidate()}
          panels={panels}
          pending={pending}
          selectedPath={selectedPath}
          selectedTabId={selectedTabId}
          validationErrors={validationErrors}
        />
      </section>
    </main>
  );
}

export default App;
