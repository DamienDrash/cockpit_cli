import type { LayoutDocument, PanelMeta, PanelRef, SplitNode, TabLayout } from "../types";

export type NodePath = number[];

export function isPanelRef(node: SplitNode | PanelRef): node is PanelRef {
  return "panel_id" in node;
}

export function cloneLayout(layout: LayoutDocument): LayoutDocument {
  return structuredClone(layout);
}

export function describePath(path: NodePath): string {
  return path.length ? path.join(".") : "root";
}

export function defaultPanel(panels: PanelMeta[]): PanelRef {
  const panel = panels[0] ?? {
    panel_id: "work-panel",
    panel_type: "work",
    display_name: "Work",
  };
  return {
    panel_id: panel.panel_id,
    panel_type: panel.panel_type,
  };
}

export function getTab(layout: LayoutDocument, tabId: string): TabLayout {
  const tab = layout.tabs.find((candidate) => candidate.id === tabId);
  if (!tab) {
    throw new Error(`Unknown tab '${tabId}'.`);
  }
  return tab;
}

export function getNode(root: SplitNode, path: NodePath): SplitNode | PanelRef {
  let current: SplitNode | PanelRef = root;
  for (const index of path) {
    if (isPanelRef(current)) {
      throw new Error("Cannot descend into a panel node.");
    }
    const child = current.children[index];
    if (!child) {
      throw new Error(`Invalid node path '${describePath(path)}'.`);
    }
    current = child;
  }
  return current;
}

function updateNodeInSplit(
  split: SplitNode,
  path: NodePath,
  transform: (node: SplitNode | PanelRef) => SplitNode | PanelRef,
): SplitNode {
  if (path.length === 0) {
    const next = transform(split);
    if (isPanelRef(next)) {
      return {
        orientation: "vertical",
        ratio: 1,
        children: [next],
      };
    }
    return next;
  }
  const [head, ...tail] = path;
  return {
    ...split,
    children: split.children.map((child, index) => {
      if (index !== head) {
        return child;
      }
      if (tail.length === 0) {
        return transform(child);
      }
      if (isPanelRef(child)) {
        throw new Error("Cannot descend into a panel node.");
      }
      return updateNodeInSplit(child, tail, transform);
    }),
  };
}

export function updateTabRoot(
  layout: LayoutDocument,
  tabId: string,
  updater: (root: SplitNode) => SplitNode,
): LayoutDocument {
  return {
    ...layout,
    tabs: layout.tabs.map((tab) => (tab.id === tabId ? { ...tab, root_split: updater(tab.root_split) } : tab)),
  };
}

export function toggleOrientation(layout: LayoutDocument, tabId: string, path: NodePath): LayoutDocument {
  return updateTabRoot(layout, tabId, (root) =>
    updateNodeInSplit(root, path, (node) => {
      if (isPanelRef(node)) {
        return {
          orientation: "horizontal",
          ratio: 0.5,
          children: [node, { panel_id: node.panel_id, panel_type: node.panel_type }],
        };
      }
      return {
        ...node,
        orientation: node.orientation === "horizontal" ? "vertical" : "horizontal",
      };
    }),
  );
}

export function setRatio(layout: LayoutDocument, tabId: string, path: NodePath, ratio: number): LayoutDocument {
  return updateTabRoot(layout, tabId, (root) =>
    updateNodeInSplit(root, path, (node) => {
      if (isPanelRef(node)) {
        return node;
      }
      return {
        ...node,
        ratio,
      };
    }),
  );
}

export function replacePanel(
  layout: LayoutDocument,
  tabId: string,
  path: NodePath,
  panel: PanelRef,
): LayoutDocument {
  return updateTabRoot(layout, tabId, (root) => updateNodeInSplit(root, path, () => panel));
}

export function splitSelected(
  layout: LayoutDocument,
  tabId: string,
  path: NodePath,
  orientation: "horizontal" | "vertical",
  panel: PanelRef,
): LayoutDocument {
  return updateTabRoot(layout, tabId, (root) =>
    updateNodeInSplit(root, path, (node) => ({
      orientation,
      ratio: 0.5,
      children: [node, panel],
    })),
  );
}

function collapseSplit(node: SplitNode): SplitNode | PanelRef {
  const children = node.children
    .map((child) => (isPanelRef(child) ? child : collapseSplit(child)))
    .filter(Boolean);
  if (children.length === 1) {
    return children[0];
  }
  return {
    ...node,
    children,
  };
}

function removeNodeInSplit(split: SplitNode, path: NodePath): SplitNode | PanelRef {
  if (path.length === 0) {
    return split;
  }
  const [head, ...tail] = path;
  const nextChildren = split.children
    .map((child, index) => {
      if (index !== head) {
        return child;
      }
      if (tail.length === 0) {
        return null;
      }
      if (isPanelRef(child)) {
        return child;
      }
      return removeNodeInSplit(child, tail);
    })
    .filter((child): child is SplitNode | PanelRef => child !== null);
  return collapseSplit({
    ...split,
    children: nextChildren,
  });
}

export function removeSelected(layout: LayoutDocument, tabId: string, path: NodePath): LayoutDocument {
  if (path.length === 0) {
    return layout;
  }
  return updateTabRoot(layout, tabId, (root) => {
    const next = removeNodeInSplit(root, path);
    if (isPanelRef(next)) {
      return {
        orientation: "vertical",
        ratio: 1,
        children: [next],
      };
    }
    return next;
  });
}

export function movePanel(
  layout: LayoutDocument,
  tabId: string,
  sourcePath: NodePath,
  targetPath: NodePath,
): LayoutDocument {
  const root = getTab(layout, tabId).root_split;
  const sourceNode = getNode(root, sourcePath);
  if (!isPanelRef(sourceNode)) {
    return layout;
  }
  const withoutSource = removeSelected(layout, tabId, sourcePath);
  return updateTabRoot(withoutSource, tabId, (nextRoot) =>
    updateNodeInSplit(nextRoot, targetPath, (target) => {
      if (isPanelRef(target)) {
        return {
          orientation: "horizontal",
          ratio: 0.5,
          children: [target, sourceNode],
        };
      }
      return {
        ...target,
        children: [...target.children, sourceNode],
      };
    }),
  );
}

