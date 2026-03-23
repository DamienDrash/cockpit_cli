import { describe, expect, it } from "vitest";

import { cloneLayout, moveNode } from "./editor";
import type { LayoutDocument } from "../types";


function baseLayout(): LayoutDocument {
  return {
    id: "layout-default",
    name: "Default Layout",
    focus_path: [],
    tabs: [
      {
        id: "work",
        name: "Work",
        root_split: {
          orientation: "vertical",
          ratio: 0.5,
          children: [
            { panel_id: "work-panel", panel_type: "work" },
            {
              orientation: "horizontal",
              ratio: 0.5,
              children: [
                { panel_id: "git-panel", panel_type: "git" },
                { panel_id: "logs-panel", panel_type: "logs" },
              ],
            },
            { panel_id: "db-panel", panel_type: "db" },
          ],
        },
      },
    ],
  };
}

describe("moveNode", () => {
  it("moves split subtrees onto another panel target", () => {
    const next = moveNode(cloneLayout(baseLayout()), "work", [1], [0]);
    const children = next.tabs[0].root_split.children;
    expect(children).toHaveLength(2);
    expect("panel_id" in children[0]).toBe(false);
    expect("panel_id" in children[1] ? children[1].panel_id : null).toBe("db-panel");

    const wrapped = children[0];
    expect("panel_id" in wrapped).toBe(false);
    if ("panel_id" in wrapped) {
      throw new Error("Expected split wrapper.");
    }
    expect(wrapped.orientation).toBe("horizontal");
    expect("panel_id" in wrapped.children[0] ? wrapped.children[0].panel_id : null).toBe("work-panel");
  });

  it("adjusts the target path after removing an earlier sibling", () => {
    const next = moveNode(cloneLayout(baseLayout()), "work", [0], [2]);
    const children = next.tabs[0].root_split.children;
    expect("panel_id" in children[0]).toBe(false);
    expect("panel_id" in children[1]).toBe(false);
    const wrapped = children[1];
    if ("panel_id" in wrapped) {
      throw new Error("Expected wrapped target panel.");
    }
    expect("panel_id" in wrapped.children[0] ? wrapped.children[0].panel_id : null).toBe("db-panel");
    expect("panel_id" in wrapped.children[1] ? wrapped.children[1].panel_id : null).toBe("work-panel");
  });

  it("ignores attempts to drop a subtree into its own descendant", () => {
    const original = cloneLayout(baseLayout());
    const next = moveNode(cloneLayout(original), "work", [1], [1, 0]);
    expect(next).toEqual(original);
  });
});
