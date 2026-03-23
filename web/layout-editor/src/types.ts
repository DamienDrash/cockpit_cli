export type PanelRef = {
  panel_id: string;
  panel_type: string;
};

export type SplitNode = {
  orientation: "horizontal" | "vertical" | null;
  ratio: number | null;
  children: Array<SplitNode | PanelRef>;
};

export type TabLayout = {
  id: string;
  name: string;
  root_split: SplitNode;
};

export type LayoutDocument = {
  id: string;
  name: string;
  focus_path: string[];
  tabs: TabLayout[];
  schema_version?: number;
};

export type LayoutSummary = {
  id: string;
  name: string;
  tab_count: number;
  tabs: Array<{ id: string; name: string }>;
};

export type PanelMeta = {
  panel_id: string;
  panel_type: string;
  display_name: string;
};

export type ValidationResult = {
  ok: boolean;
  errors: string[];
  layout: LayoutDocument;
};

