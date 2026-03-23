import { useEffect, useEffectEvent, useState, type DragEvent, type PointerEvent as ReactPointerEvent } from "react";

import type { LayoutDocument, PanelMeta, PanelRef, SplitNode } from "../types";
import { describePath, getTab, isPanelRef, type NodePath } from "../state/editor";

type LayoutCanvasProps = {
  layout: LayoutDocument;
  panels: PanelMeta[];
  selectedTabId: string;
  selectedPath: NodePath;
  draggedPath: NodePath | null;
  onAdjustRatio: (path: NodePath, ratio: number) => void;
  onSelect: (path: NodePath) => void;
  onDropNode: (sourcePath: NodePath, targetPath: NodePath) => void;
  onStartDrag: (path: NodePath) => void;
  onClearDrag: () => void;
};

type DividerDragState = {
  path: NodePath;
  orientation: "horizontal" | "vertical";
  ratio: number;
  rect: DOMRect;
};

function panelLabel(panel: PanelRef, panels: PanelMeta[]): string {
  const match = panels.find((candidate) => candidate.panel_id === panel.panel_id);
  return match?.display_name ?? panel.panel_type;
}

export function LayoutCanvas(props: LayoutCanvasProps) {
  const tab = getTab(props.layout, props.selectedTabId);
  const [dividerDrag, setDividerDrag] = useState<DividerDragState | null>(null);

  const handlePointerMove = useEffectEvent((event: PointerEvent) => {
    if (!dividerDrag) {
      return;
    }
    const span =
      dividerDrag.orientation === "horizontal" ? dividerDrag.rect.width : dividerDrag.rect.height;
    if (span <= 0) {
      return;
    }
    const cursor =
      dividerDrag.orientation === "horizontal"
        ? event.clientX - dividerDrag.rect.left
        : event.clientY - dividerDrag.rect.top;
    const rawRatio = cursor / span;
    const nextRatio = Math.max(0.2, Math.min(0.8, Number(rawRatio.toFixed(2))));
    props.onAdjustRatio(dividerDrag.path, nextRatio);
  });

  useEffect(() => {
    if (!dividerDrag) {
      return;
    }
    function handlePointerUp() {
      setDividerDrag(null);
    }
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };
  }, [dividerDrag, handlePointerMove]);

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
        {renderNode(tab.root_split, [], props, setDividerDrag)}
      </div>
    </div>
  );
}

function renderNode(
  node: SplitNode | PanelRef,
  path: NodePath,
  props: LayoutCanvasProps,
  setDividerDrag: (state: DividerDragState | null) => void,
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
            props.onDropNode(props.draggedPath, path);
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
  const orientation = node.orientation === "horizontal" ? "horizontal" : "vertical";
  const directionClass = orientation === "horizontal" ? "split-row" : "split-column";
  const childCount = node.children.length;
  return (
    <div
      className={`split-card ${directionClass}${selected ? " selected" : ""}`}
      draggable={path.length > 0}
      onClick={() => props.onSelect(path)}
      onDragStart={() => {
        if (path.length > 0) {
          props.onStartDrag(path);
        }
      }}
      onDragEnd={() => props.onClearDrag()}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event: DragEvent<HTMLDivElement>) => {
        event.preventDefault();
        if (props.draggedPath) {
          props.onDropNode(props.draggedPath, path);
        }
      }}
    >
      <div className="split-card__meta">
        <span>{orientation}</span>
        <span>
          {Math.round((node.ratio ?? 0.5) * 100)} / {Math.round((1 - (node.ratio ?? 0.5)) * 100)}
        </span>
      </div>
      <div className="split-card__toolbar">
        <span>{childCount} nodes</span>
        {path.length > 0 ? <span>drag branch</span> : <span>root</span>}
      </div>
      <div className={`split-card__children ${directionClass}`}>
        {node.children.map((child, index) => (
          <div className="split-card__segment" key={`${describePath(path)}-${index}`}>
            {index > 0 && childCount === 2 ? (
              <SplitDivider
                onPointerDown={(event) => {
                  const container = event.currentTarget.parentElement;
                  if (!container) {
                    return;
                  }
                  setDividerDrag({
                    path,
                    orientation,
                    ratio: node.ratio ?? 0.5,
                    rect: container.getBoundingClientRect(),
                  });
                  event.preventDefault();
                  event.stopPropagation();
                }}
                orientation={orientation}
              />
            ) : null}
            <div className="split-card__child">
              {renderNode(child, [...path, index], props, setDividerDrag)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

type SplitDividerProps = {
  orientation: "horizontal" | "vertical";
  onPointerDown: (event: ReactPointerEvent<HTMLButtonElement>) => void;
};

function SplitDivider(props: SplitDividerProps) {
  return (
    <button
      aria-label={`Adjust ${props.orientation} split ratio`}
      className={`split-divider ${props.orientation}`}
      onPointerDown={props.onPointerDown}
      type="button"
    >
      <span />
    </button>
  );
}
