import type { DragEvent } from "react";

import type { LayoutDocument, PanelMeta, PanelRef, SplitNode } from "../types";
import { describePath, getTab, isPanelRef, type NodePath } from "../state/editor";

type LayoutCanvasProps = {
  layout: LayoutDocument;
  panels: PanelMeta[];
  selectedTabId: string;
  selectedPath: NodePath;
  draggedPath: NodePath | null;
  onSelect: (path: NodePath) => void;
  onDropPanel: (sourcePath: NodePath, targetPath: NodePath) => void;
  onStartDrag: (path: NodePath) => void;
  onClearDrag: () => void;
};

function panelLabel(panel: PanelRef, panels: PanelMeta[]): string {
  const match = panels.find((candidate) => candidate.panel_id === panel.panel_id);
  return match?.display_name ?? panel.panel_type;
}

export function LayoutCanvas(props: LayoutCanvasProps) {
  const tab = getTab(props.layout, props.selectedTabId);
  return (
    <div className="canvas-shell">
      <div className="canvas-header">
        <div>
          <p className="eyebrow">Canvas</p>
          <h2>{tab.name}</h2>
        </div>
        <div className="canvas-pill">{props.layout.id}</div>
      </div>
      <div className="canvas">
        {renderNode(tab.root_split, [], props)}
      </div>
    </div>
  );
}

function renderNode(
  node: SplitNode | PanelRef,
  path: NodePath,
  props: LayoutCanvasProps,
) {
  const selected = describePath(path) === describePath(props.selectedPath);
  if (isPanelRef(node)) {
    return (
      <button
        className={`panel-card${selected ? " selected" : ""}`}
        draggable
        onClick={() => props.onSelect(path)}
        onDragStart={() => props.onStartDrag(path)}
        onDragEnd={() => props.onClearDrag()}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          if (props.draggedPath) {
            props.onDropPanel(props.draggedPath, path);
          }
        }}
        type="button"
      >
        <span className="panel-card__label">{panelLabel(node, props.panels)}</span>
        <strong>{node.panel_id}</strong>
        <span>{node.panel_type}</span>
      </button>
    );
  }
  const directionClass = node.orientation === "horizontal" ? "split-row" : "split-column";
  return (
    <div
      className={`split-card ${directionClass}${selected ? " selected" : ""}`}
      onClick={() => props.onSelect(path)}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event: DragEvent<HTMLDivElement>) => {
        event.preventDefault();
        if (props.draggedPath) {
          props.onDropPanel(props.draggedPath, path);
        }
      }}
    >
      <div className="split-card__meta">
        <span>{node.orientation ?? "vertical"}</span>
        <span>{Math.round((node.ratio ?? 0.5) * 100)} / {Math.round((1 - (node.ratio ?? 0.5)) * 100)}</span>
      </div>
      <div className={`split-card__children ${directionClass}`}>
        {node.children.map((child, index) => (
          <div className="split-card__child" key={`${describePath(path)}-${index}`}>
            {renderNode(child, [...path, index], props)}
          </div>
        ))}
      </div>
    </div>
  );
}

