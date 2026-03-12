const API_BASE = "/api";

// ---------------------------------------------------------------------------
// Single File Mode: start cascade + SSE progress streaming
// ---------------------------------------------------------------------------

export interface CascadeEvent {
  defense_line?: number;
  label?: string;
  status: string;
  error?: string;
  result?: any;
}

export interface ExtractedFields {
  permit_type: string;
  license_number: string;
  trade_name: string;
  address: string;
  city: string;
  state: string;
}

export async function startVerification(
  licenseNumber: string,
  state: string,
  fields?: ExtractedFields,
  defenseLine?: number | null
): Promise<{ status: string; license_number: string; state: string }> {
  const formData = new FormData();
  formData.append("license_number", licenseNumber);
  formData.append("state", state);
  if (fields) {
    formData.append("permit_type", fields.permit_type);
    formData.append("trade_name", fields.trade_name);
    formData.append("address", fields.address);
    formData.append("city", fields.city);
  }
  if (defenseLine) {
    formData.append("defense_line", String(defenseLine));
  }

  const resp = await fetch(`${API_BASE}/verify/start`, {
    method: "POST",
    body: formData,
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`API error ${resp.status}: ${text}`);
  }

  return resp.json();
}

export function subscribeVerifyStatus(
  onEvent: (event: CascadeEvent) => void,
  onError: () => void
): AbortController {
  const ctrl = new AbortController();
  const eventSource = new EventSource(`${API_BASE}/verify/status`);

  eventSource.onmessage = (e) => {
    try {
      const event: CascadeEvent = JSON.parse(e.data);
      if (event.status === "keepalive") return;
      onEvent(event);
      if (event.status === "complete") {
        eventSource.close();
      }
    } catch {
      // ignore parse errors
    }
  };

  eventSource.onerror = () => {
    eventSource.close();
    onError();
  };

  ctrl.signal.addEventListener("abort", () => {
    eventSource.close();
  });

  return ctrl;
}

// ---------------------------------------------------------------------------
// Batch Mode: start batch + SSE streaming
// ---------------------------------------------------------------------------

interface BatchLicense {
  license_number: string;
  state?: string;
}

export interface BatchEvent {
  license_number?: string;
  status: string;
  defense_line_used?: number;
  result_count?: number;
  error?: string;
}

export async function startBatch(
  licenses: BatchLicense[],
  defenseLine: number | null
): Promise<{ batch_id: string; license_count: number }> {
  const resp = await fetch(`${API_BASE}/batch/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      licenses,
      defense_line: defenseLine,
    }),
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`API error ${resp.status}: ${text}`);
  }

  return resp.json();
}

export function subscribeBatchStatus(
  onEvent: (event: BatchEvent) => void,
  onError: () => void
): AbortController {
  const ctrl = new AbortController();
  const eventSource = new EventSource(`${API_BASE}/batch/status`);

  eventSource.onmessage = (e) => {
    try {
      const event: BatchEvent = JSON.parse(e.data);
      if (event.status === "keepalive") return;
      onEvent(event);
      if (event.status === "complete") {
        eventSource.close();
      }
    } catch {
      // ignore parse errors
    }
  };

  eventSource.onerror = () => {
    eventSource.close();
    onError();
  };

  ctrl.signal.addEventListener("abort", () => {
    eventSource.close();
  });

  return ctrl;
}

export async function cancelBatch(): Promise<void> {
  await fetch(`${API_BASE}/batch/cancel`, { method: "POST" });
}
