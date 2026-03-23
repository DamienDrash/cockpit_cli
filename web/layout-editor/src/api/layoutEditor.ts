import type { LayoutDocument, LayoutSummary, PanelMeta, ValidationResult } from "../types";

type LayoutCollectionResponse = {
  layouts: LayoutSummary[];
  panels: PanelMeta[];
};

type LayoutDocumentResponse = {
  layout: LayoutDocument;
  panels: PanelMeta[];
};

async function requestJson<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    headers: {
      "Content-Type": "application/json",
    },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function fetchLayoutCollection(): Promise<LayoutCollectionResponse> {
  return requestJson<LayoutCollectionResponse>("/api/layouts");
}

export async function fetchLayoutDocument(layoutId: string): Promise<LayoutDocumentResponse> {
  return requestJson<LayoutDocumentResponse>(`/api/layouts/${layoutId}`);
}

export async function validateLayout(layout: LayoutDocument): Promise<ValidationResult> {
  return requestJson<ValidationResult>("/api/layouts/validate", {
    method: "POST",
    body: JSON.stringify({ layout }),
  });
}

export async function saveLayout(layout: LayoutDocument): Promise<LayoutDocumentResponse> {
  const response = await requestJson<{ ok: boolean; layout: LayoutDocument }>("/api/layouts/save", {
    method: "POST",
    body: JSON.stringify({ layout }),
  });
  return {
    layout: response.layout,
    panels: [],
  };
}

export async function cloneLayout(
  source_layout_id: string,
  target_layout_id: string,
  name?: string,
): Promise<LayoutDocument> {
  const response = await requestJson<{ ok: boolean; layout: LayoutDocument }>("/api/layouts/clone", {
    method: "POST",
    body: JSON.stringify({ source_layout_id, target_layout_id, name }),
  });
  return response.layout;
}

