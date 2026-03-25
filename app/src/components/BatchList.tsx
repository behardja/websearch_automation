import { useState, useRef } from "react";
import {
  startBatch,
  subscribeBatchStatus,
  cancelBatch,
  type BatchEvent,
} from "../services/apiClient";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GcsFile {
  name: string;
  path: string;
  type: "pdf" | "image" | "other";
  size: string;
  checked: boolean;
  status: "pending" | "extracting" | "running" | "verified" | "not_found" | "error";
  license_number?: string;
  license_confidence?: number;
  defense_line_used?: number;
  result_count?: number;
  error?: string;
  result?: any;
}

const FILE_TYPE_ICONS: Record<string, string> = {
  pdf: "picture_as_pdf",
  image: "image",
  other: "description",
};

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-[#2a2d35] text-slate-400",
  extracting: "bg-purple-500/20 text-purple-400 animate-pulse",
  running: "bg-blue-500/20 text-blue-400 animate-pulse",
  verified: "bg-green-500/20 text-green-400",
  not_found: "bg-amber-500/20 text-amber-400",
  error: "bg-red-500/20 text-red-400",
};

const DEFENSE_LABELS: Record<number, string> = {
  1: "HTTP",
  2: "Playwright",
  3: "Gemini Agent",
};

const CONFIDENCE_THRESHOLD_HIGH = 0.8;

// Matches BATCH_CONCURRENCY in backend/config.py
const BATCH_CONCURRENCY = 5;

/** Run async tasks with a concurrency limit. */
async function pMap<T, R>(
  items: T[],
  fn: (item: T) => Promise<R>,
  concurrency: number,
): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let nextIdx = 0;

  async function worker() {
    while (nextIdx < items.length) {
      const idx = nextIdx++;
      results[idx] = await fn(items[idx]);
    }
  }

  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, () => worker()));
  return results;
}

function confidenceTag(c: number): { label: string; color: string; bg: string } {
  if (c >= CONFIDENCE_THRESHOLD_HIGH) return { label: "High", color: "text-green-400", bg: "bg-green-500/20" };
  if (c >= 0.5) return { label: "Medium", color: "text-amber-400", bg: "bg-amber-500/20" };
  return { label: "Low", color: "text-red-400", bg: "bg-red-500/20" };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type BatchView = "setup" | "processing";

const BatchList: React.FC = () => {
  // View
  const [currentView, setCurrentView] = useState<BatchView>("setup");

  // Setup state
  const [gcsPath, setGcsPath] = useState("gs://sandbox-401718-alcohol-license/Texas Files");
  const [files, setFiles] = useState<GcsFile[]>([]);
  const [filesLoaded, setFilesLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [selectedState, setSelectedState] = useState("TX");
  const [defenseMode, setDefenseMode] = useState("cascade12");
  const [previewIdx, setPreviewIdx] = useState<number | null>(null);

  // Processing state
  const [running, setRunning] = useState(false);
  const [batchPhase, setBatchPhase] = useState<"idle" | "extracting" | "verifying" | "complete">("idle");
  const [extractedCount, setExtractedCount] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  const batchComplete = batchPhase === "complete";

  const checkedCount = files.filter((f) => f.checked).length;
  const completedCount = files.filter(
    (f) => f.status === "verified" || f.status === "not_found" || f.status === "error"
  ).length;

  // -- Categorize files for results --
  const processedFiles = files.filter(
    (f) => f.checked && (f.status === "verified" || f.status === "not_found" || f.status === "error")
  );
  const verifiedFiles = processedFiles.filter((f) => f.status === "verified");
  const failedFiles = processedFiles.filter((f) => f.status === "not_found" || f.status === "error");
  const lowConfFiles = processedFiles.filter(
    (f) => f.license_confidence !== undefined && f.license_confidence < CONFIDENCE_THRESHOLD_HIGH
  );

  // -- Handlers --

  const handleListFiles = async () => {
    if (!gcsPath.trim()) return;
    setLoading(true);
    try {
      const resp = await fetch(`/api/gcs/list?path=${encodeURIComponent(gcsPath.trim())}`);
      const data = await resp.json();
      const listed: GcsFile[] = (data.files || []).map((f: any) => ({
        ...f,
        checked: false,
        status: "pending" as const,
      }));
      setFiles(listed);
      setFilesLoaded(true);
    } catch {
      setFiles([]);
      setFilesLoaded(true);
    }
    setLoading(false);
  };

  const handleClearFiles = () => {
    setFiles([]);
    setFilesLoaded(false);
    setPreviewIdx(null);
    setBatchPhase("idle");
  };

  const toggleCheck = (idx: number) => {
    setFiles((prev) =>
      prev.map((f, i) => (i === idx ? { ...f, checked: !f.checked } : f))
    );
  };

  const selectAll = () => setFiles((prev) => prev.map((f) => ({ ...f, checked: true })));
  const deselectAll = () => setFiles((prev) => prev.map((f) => ({ ...f, checked: false })));

  const handleBackToSetup = () => {
    setCurrentView("setup");
    setBatchPhase("idle");
    // Reset file statuses back to pending for re-run
    setFiles((prev) =>
      prev.map((f) => ({
        ...f,
        status: "pending" as const,
        error: undefined,
        result: undefined,
        defense_line_used: undefined,
        result_count: undefined,
      }))
    );
  };

  const handleRunBatch = async () => {
    const selected = files.filter((f) => f.checked);
    if (selected.length === 0) return;

    // Switch to processing view
    setCurrentView("processing");
    setRunning(true);
    setBatchPhase("extracting");
    setExtractedCount(0);
    setFiles((prev) =>
      prev.map((f) =>
        f.checked ? { ...f, status: "extracting", error: undefined, result: undefined, license_number: undefined, license_confidence: undefined, defense_line_used: undefined, result_count: undefined } : f
      )
    );

    // Step 1: Extract license numbers via Document AI (concurrent)
    const checkedEntries = files
      .map((f, idx) => ({ file: f, idx }))
      .filter((e) => e.file.checked);

    const licenseItems: { license_number: string; state?: string; fileIdx: number; confidence: number }[] = [];

    await pMap(
      checkedEntries,
      async ({ file, idx: i }) => {
        try {
          const blob = await fetch(`/api/gcs/preview?path=${encodeURIComponent(file.path)}`).then((r) => r.blob());
          const formData = new FormData();
          formData.append("file", blob, file.name);
          formData.append("state", selectedState);

          const extractResp = await fetch("/api/verify/upload", {
            method: "POST",
            body: formData,
          });
          const extractData = await extractResp.json();

          const licenseNum = extractData.fields?.license_number?.value || "";
          const licenseConf = extractData.fields?.license_number?.confidence ?? 0;
          const resolvedState = extractData.state || selectedState;

          setFiles((prev) =>
            prev.map((f, idx) =>
              idx === i
                ? { ...f, license_number: licenseNum, license_confidence: licenseConf, status: licenseNum ? "pending" : "error", error: licenseNum ? undefined : "No license number extracted" }
                : f
            )
          );
          setExtractedCount((c) => c + 1);

          if (licenseNum) {
            licenseItems.push({ license_number: licenseNum, state: resolvedState, fileIdx: i, confidence: licenseConf });
          }
        } catch (err: any) {
          setFiles((prev) =>
            prev.map((f, idx) =>
              idx === i ? { ...f, status: "error", error: `Extraction failed: ${err.message}` } : f
            )
          );
          setExtractedCount((c) => c + 1);
        }
      },
      BATCH_CONCURRENCY,
    );

    if (licenseItems.length === 0) {
      setRunning(false);
      setBatchPhase("complete");
      return;
    }

    // Step 2: Run batch verification
    setBatchPhase("verifying");
    setFiles((prev) =>
      prev.map((f, idx) => {
        const item = licenseItems.find((li) => li.fileIdx === idx);
        return item ? { ...f, status: "running" } : f;
      })
    );

    try {
      const batchLicenses = licenseItems.map((li) => ({
        license_number: li.license_number,
        state: li.state,
      }));
      const isSingle = ["1", "2", "3"].includes(defenseMode);
      const dlValue = isSingle ? Number(defenseMode) : null;
      const cascadeLines = defenseMode === "cascade12" ? [1, 2]
        : defenseMode === "cascade123" ? [1, 2, 3]
        : null;
      await startBatch(batchLicenses, dlValue, cascadeLines);

      const ctrl = subscribeBatchStatus(
        (event: BatchEvent) => {
          if (event.license_number) {
            setFiles((prev) =>
              prev.map((f) => {
                if (f.license_number === event.license_number) {
                  return {
                    ...f,
                    status: event.status as GcsFile["status"],
                    defense_line_used: event.defense_line_used,
                    result_count: event.result_count,
                    error: event.error,
                    result: event.result,
                  };
                }
                return f;
              })
            );
          }
          if (event.status === "complete") {
            setRunning(false);
            setBatchPhase("complete");
          }
        },
        () => {
          setRunning(false);
          setBatchPhase("complete");
        }
      );
      abortRef.current = ctrl;
    } catch (e: any) {
      setFiles((prev) =>
        prev.map((f) =>
          f.checked && f.status === "running"
            ? { ...f, status: "error", error: e.message }
            : f
        )
      );
      setRunning(false);
      setBatchPhase("complete");
    }
  };

  const handleCancel = async () => {
    abortRef.current?.abort();
    await cancelBatch();
    setRunning(false);
    setBatchPhase("complete");
  };

  const previewUrl = (file: GcsFile) =>
    `/api/gcs/preview?path=${encodeURIComponent(file.path)}`;

  // Build JSON output
  const buildJsonOutput = () =>
    processedFiles.map((f) => ({
      file: f.name,
      license_number: f.license_number,
      extraction_confidence: f.license_confidence,
      status: f.status,
      defense_line_used: f.defense_line_used ? DEFENSE_LABELS[f.defense_line_used] : null,
      error: f.error || null,
      verification: f.result || null,
    }));

  // =========================================================================
  // SETUP VIEW — file selection, state, method
  // =========================================================================
  if (currentView === "setup") {
    return (
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Controls */}
        <div className="w-[380px] flex-shrink-0 border-r border-[#2a2d35] bg-[#22252b] p-6 overflow-y-auto">
          <h3 className="text-base font-bold text-slate-100 mb-4">Batch Verification</h3>

          {/* GCS Path */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-slate-300 mb-1">GCS Path</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={gcsPath}
                onChange={(e) => setGcsPath(e.target.value)}
                placeholder="gs://bucket-name/folder/"
                disabled={filesLoaded || loading}
                className="flex-1 px-3 py-2 border border-[#3a3d45] rounded-lg text-sm font-mono bg-[#2a2d35] text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-primary/50 disabled:opacity-50"
              />
              {!filesLoaded ? (
                <button
                  onClick={handleListFiles}
                  disabled={!gcsPath.trim() || loading}
                  className="px-3 py-2 bg-primary text-white font-semibold text-sm rounded-lg hover:bg-blue-600 disabled:opacity-50 transition-colors flex items-center gap-1"
                >
                  {loading ? (
                    <span className="material-symbols-outlined text-[18px] animate-spin">progress_activity</span>
                  ) : (
                    <span className="material-symbols-outlined text-[18px]">folder_open</span>
                  )}
                </button>
              ) : (
                <button
                  onClick={handleClearFiles}
                  className="px-3 py-2 bg-[#2a2d35] text-slate-400 font-semibold text-sm rounded-lg hover:bg-[#33363e] transition-colors"
                >
                  <span className="material-symbols-outlined text-[18px]">close</span>
                </button>
              )}
            </div>
            <p className="text-xs text-slate-600 mt-1.5">Enter a GCS folder path containing license PDFs/images</p>
          </div>

          {/* State selector */}
          {filesLoaded && (
            <div className="mb-4">
              <label className="block text-sm font-medium text-slate-300 mb-1">State</label>
              <select
                value={selectedState}
                onChange={(e) => setSelectedState(e.target.value)}
                className="w-full px-3 py-2 border border-[#3a3d45] rounded-lg text-sm bg-[#2a2d35] text-slate-200 focus:outline-none focus:ring-2 focus:ring-primary/50"
              >
                <option value="TX">Texas (TABC)</option>
                <option value="FL">Florida (DBPR)</option>
                <option value="GA">Georgia (DOR)</option>
              </select>
            </div>
          )}

          {/* Method selector */}
          {filesLoaded && (
            <div className="mb-4">
              <label className="block text-sm font-medium text-slate-300 mb-1">Verification Method</label>
              <select
                value={defenseMode}
                onChange={(e) => setDefenseMode(e.target.value)}
                className="w-full px-3 py-2 border border-[#3a3d45] rounded-lg text-sm bg-[#2a2d35] text-slate-200 focus:outline-none focus:ring-2 focus:ring-primary/50"
              >
                <option value="cascade12">Sequence Methods 1 & 2 (recommended)</option>
                <option value="cascade123">Sequence all methods (1, 2 & 3)</option>
                <option value="1">Method 1 only — HTTP Direct</option>
                <option value="2">Method 2 only — Playwright</option>
                <option value="3">Method 3 only — Gemini Computer Use</option>
              </select>
              <p className="text-xs text-slate-600 mt-1">Searches by License / Permit Number only.</p>
            </div>
          )}

          {/* Info */}
          {filesLoaded && (
            <div className="mb-4 p-3 bg-blue-500/10 border border-blue-500/30 rounded-lg flex items-start gap-2">
              <span className="material-symbols-outlined text-[18px] text-blue-400 mt-0.5">info</span>
              <div className="text-xs text-blue-300">
                Each file is sent to <strong>Document AI</strong> to extract the License / Permit Number, then verified against the state website.
              </div>
            </div>
          )}

          {/* Selection controls + Process button */}
          {filesLoaded && files.length > 0 && (
            <>
              <div className="flex gap-2 mb-4">
                <button onClick={selectAll} className="flex-1 py-1.5 text-xs font-semibold bg-[#2a2d35] text-slate-300 rounded hover:bg-[#33363e] transition-colors">
                  Select All
                </button>
                <button onClick={deselectAll} className="flex-1 py-1.5 text-xs font-semibold bg-[#2a2d35] text-slate-300 rounded hover:bg-[#33363e] transition-colors">
                  Deselect All
                </button>
              </div>

              <button
                onClick={handleRunBatch}
                disabled={checkedCount === 0}
                className="w-full py-2.5 bg-success text-white font-bold text-sm rounded-lg hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
              >
                <span className="material-symbols-outlined text-[18px]">play_arrow</span>
                Process {checkedCount} File{checkedCount !== 1 ? "s" : ""}
              </button>
            </>
          )}
        </div>

        {/* Right: File list */}
        <div className="flex-1 overflow-y-auto bg-[#1a1d23] p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-base font-bold text-slate-100">
              {filesLoaded ? `Files (${files.length})` : "Files"}
            </h3>
            {filesLoaded && <span className="text-sm text-slate-500">{checkedCount} selected</span>}
          </div>

          {!filesLoaded ? (
            <div className="flex flex-col items-center justify-center h-64 text-slate-600">
              <span className="material-symbols-outlined text-5xl mb-2">cloud_queue</span>
              <p className="text-sm">Enter a GCS path to browse license files</p>
              <p className="text-xs text-slate-700 mt-1">e.g. gs://sandbox-401718-alcohol-license/Texas Files</p>
            </div>
          ) : files.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-slate-600">
              <span className="material-symbols-outlined text-5xl mb-2">folder_off</span>
              <p className="text-sm">No files found at this path</p>
            </div>
          ) : (
            <div className="space-y-2">
              {files.map((file, idx) => (
                <div key={file.path}>
                  <div
                    className={`flex items-center gap-3 bg-[#22252b] border border-[#2a2d35] rounded-lg px-4 py-3 hover:border-[#3a3d45] transition-colors ${
                      file.checked ? "border-primary/30" : ""
                    } ${previewIdx === idx ? "rounded-b-none border-b-0" : ""}`}
                  >
                    <input type="checkbox" checked={file.checked} onChange={() => toggleCheck(idx)} className="w-4 h-4 rounded flex-shrink-0" />
                    <span className={`material-symbols-outlined text-[20px] flex-shrink-0 ${file.type === "pdf" ? "text-red-400" : file.type === "image" ? "text-blue-400" : "text-slate-500"}`}>
                      {FILE_TYPE_ICONS[file.type]}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium text-slate-200 truncate">{file.name}</p>
                        <button
                          onClick={() => setPreviewIdx(previewIdx === idx ? null : idx)}
                          className={`p-0.5 rounded transition-colors flex-shrink-0 ${previewIdx === idx ? "text-primary" : "text-slate-600 hover:text-slate-300"}`}
                          title="Toggle preview"
                        >
                          <span className="material-symbols-outlined text-[16px]">{previewIdx === idx ? "visibility_off" : "visibility"}</span>
                        </button>
                      </div>
                      <p className="text-xs text-slate-600">{file.size}</p>
                    </div>
                  </div>
                  {previewIdx === idx && (
                    <div className="bg-[#22252b] border border-[#2a2d35] border-t-0 rounded-b-lg p-4">
                      <div className="bg-[#1a1d23] rounded-lg overflow-hidden flex items-center justify-center" style={{ height: "320px" }}>
                        {file.type === "image" ? (
                          <img src={previewUrl(file)} alt={file.name} className="max-w-full max-h-full object-contain" />
                        ) : file.type === "pdf" ? (
                          <iframe src={previewUrl(file)} title={file.name} className="w-full h-full border-0" />
                        ) : (
                          <div className="text-center text-slate-600">
                            <span className="material-symbols-outlined text-4xl mb-2">description</span>
                            <p className="text-xs">Preview not available</p>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // =========================================================================
  // PROCESSING VIEW — progress + results
  // =========================================================================
  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Left: Progress sidebar */}
      <div className="w-[380px] flex-shrink-0 border-r border-[#2a2d35] bg-[#22252b] p-6 overflow-y-auto">
        <div className="flex items-center gap-2 mb-4">
          <button
            onClick={handleBackToSetup}
            disabled={running}
            className="text-slate-500 hover:text-slate-300 transition-colors disabled:opacity-30"
          >
            <span className="material-symbols-outlined text-[20px]">arrow_back</span>
          </button>
          <h3 className="text-base font-bold text-slate-100">Batch Processing</h3>
        </div>

        {/* Config summary */}
        <div className="mb-4 bg-[#1a1d23] border border-[#2a2d35] rounded-xl p-4 space-y-2 text-sm">
          <div className="flex gap-2">
            <span className="text-slate-500 w-20 flex-shrink-0 text-xs">Files</span>
            <span className="text-slate-300 font-medium text-xs">{checkedCount}</span>
          </div>
          <div className="flex gap-2">
            <span className="text-slate-500 w-20 flex-shrink-0 text-xs">State</span>
            <span className="text-slate-300 font-medium text-xs">{selectedState}</span>
          </div>
          <div className="flex gap-2">
            <span className="text-slate-500 w-20 flex-shrink-0 text-xs">Method</span>
            <span className="text-slate-300 font-medium text-xs">
              {defenseMode === "cascade12" ? "Methods 1 & 2" : defenseMode === "cascade123" ? "Methods 1, 2 & 3" : `Method ${defenseMode} only`}
            </span>
          </div>
        </div>

        {/* Two-phase progress steps */}
        <div className="space-y-0 mb-4">
          {/* Step 1: Document AI */}
          <div className={`relative border rounded-xl p-4 transition-all ${
            batchPhase === "extracting" ? "bg-purple-500/10 border-purple-500/40 shadow-md shadow-purple-500/10"
              : batchPhase !== "idle" ? "bg-green-500/10 border-green-500/40"
              : "bg-[#22252b] border-[#3a3d45]"
          }`}>
            <div className="flex items-start justify-between mb-1">
              <div className="flex items-center gap-3">
                <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-[#2a2d35] border border-[#3a3d45]">
                  <span className="material-symbols-outlined text-[22px] text-purple-400">description</span>
                </div>
                <div>
                  <span className={`text-xs font-bold uppercase tracking-wide ${
                    batchPhase === "extracting" ? "text-purple-400" : batchPhase !== "idle" ? "text-green-400" : "text-slate-600"
                  }`}>Step 1</span>
                  <h4 className="text-sm font-bold text-slate-200">Document AI Extraction</h4>
                </div>
              </div>
              <span className={`material-symbols-outlined text-[24px] ${
                batchPhase === "extracting" ? "text-purple-400 animate-spin" : batchPhase !== "idle" ? "text-green-400" : "text-slate-600"
              }`}>
                {batchPhase === "extracting" ? "progress_activity" : batchPhase !== "idle" ? "check_circle" : "radio_button_unchecked"}
              </span>
            </div>
            <p className="text-xs ml-[52px] text-slate-500">Extract license numbers from uploaded documents</p>
            {batchPhase === "extracting" && (
              <div className="ml-[52px] mt-2">
                <div className="flex justify-between text-[10px] text-slate-500 mb-1">
                  <span>Extracting...</span>
                  <span>{extractedCount} / {checkedCount}</span>
                </div>
                <div className="w-full bg-[#1a1d23] rounded-full h-1.5">
                  <div className="bg-purple-500 h-1.5 rounded-full transition-all" style={{ width: `${checkedCount > 0 ? (extractedCount / checkedCount) * 100 : 0}%` }} />
                </div>
              </div>
            )}
            {batchPhase !== "idle" && batchPhase !== "extracting" && (
              <p className="text-[10px] ml-[52px] mt-1 text-green-400">{extractedCount} files extracted</p>
            )}
          </div>

          {/* Connector */}
          <div className="flex flex-col items-center py-1">
            <div className={`w-px h-4 ${batchPhase === "verifying" || batchPhase === "complete" ? "bg-slate-500" : "bg-[#2a2d35]"}`} />
          </div>

          {/* Step 2: Web Verification */}
          <div className={`relative border rounded-xl p-4 transition-all ${
            batchPhase === "verifying" ? "bg-blue-500/10 border-blue-500/40 shadow-md shadow-blue-500/10"
              : batchPhase === "complete" ? "bg-green-500/10 border-green-500/40"
              : "bg-[#22252b] border-[#3a3d45]"
          }`}>
            <div className="flex items-start justify-between mb-1">
              <div className="flex items-center gap-3">
                <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-[#2a2d35] border border-[#3a3d45]">
                  <span className="material-symbols-outlined text-[22px] text-blue-400">travel_explore</span>
                </div>
                <div>
                  <span className={`text-xs font-bold uppercase tracking-wide ${
                    batchPhase === "verifying" ? "text-blue-400" : batchPhase === "complete" ? "text-green-400" : "text-slate-600"
                  }`}>Step 2</span>
                  <h4 className="text-sm font-bold text-slate-200">Web Verification</h4>
                </div>
              </div>
              <span className={`material-symbols-outlined text-[24px] ${
                batchPhase === "verifying" ? "text-blue-400 animate-spin" : batchPhase === "complete" ? "text-green-400" : "text-slate-600"
              }`}>
                {batchPhase === "verifying" ? "progress_activity" : batchPhase === "complete" ? "check_circle" : "radio_button_unchecked"}
              </span>
            </div>
            <p className="text-xs ml-[52px] text-slate-500">Verify extracted licenses against state websites</p>
            {batchPhase === "verifying" && (
              <div className="ml-[52px] mt-2">
                <div className="flex justify-between text-[10px] text-slate-500 mb-1">
                  <span>Verifying...</span>
                  <span>{completedCount} / {checkedCount}</span>
                </div>
                <div className="w-full bg-[#1a1d23] rounded-full h-1.5">
                  <div className="bg-blue-500 h-1.5 rounded-full transition-all" style={{ width: `${checkedCount > 0 ? (completedCount / checkedCount) * 100 : 0}%` }} />
                </div>
              </div>
            )}
            {batchPhase === "complete" && (
              <p className="text-[10px] ml-[52px] mt-1 text-green-400">{completedCount} files processed</p>
            )}
          </div>
        </div>

        {/* Cancel / Summary */}
        {running && (
          <button
            onClick={handleCancel}
            className="w-full py-2.5 bg-danger text-white font-bold text-sm rounded-lg hover:bg-red-600 transition-colors flex items-center justify-center gap-2"
          >
            <span className="material-symbols-outlined text-[18px]">cancel</span>
            Cancel Batch
          </button>
        )}

        {batchComplete && (
          <>
            <div className="space-y-2 mb-4">
              <div className="flex items-center gap-2 text-xs">
                <span className="w-2.5 h-2.5 rounded-full bg-green-400"></span>
                <span className="text-slate-300">{verifiedFiles.length} Verified</span>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span className="w-2.5 h-2.5 rounded-full bg-red-400"></span>
                <span className="text-slate-300">{failedFiles.length} Failed / Not Found</span>
              </div>
              {lowConfFiles.length > 0 && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-400"></span>
                  <span className="text-slate-300">{lowConfFiles.length} Low Confidence Extraction</span>
                </div>
              )}
            </div>
            <button
              onClick={handleBackToSetup}
              className="w-full py-2.5 bg-[#2a2d35] text-slate-300 font-semibold text-sm rounded-lg hover:bg-[#33363e] transition-colors flex items-center justify-center gap-2"
            >
              <span className="material-symbols-outlined text-[18px]">restart_alt</span>
              New Batch
            </button>
          </>
        )}
      </div>

      {/* Right: Results */}
      <div className="flex-1 overflow-y-auto bg-[#1a1d23] p-6">
        <div className="max-w-4xl mx-auto">

          {/* During processing — show per-file status list */}
          {running && (
            <>
              <h3 className="text-base font-bold text-slate-100 mb-4">File Status</h3>
              <div className="space-y-2 mb-8">
                {files.filter((f) => f.checked).map((file) => (
                  <div key={file.path} className="flex items-center gap-3 bg-[#22252b] border border-[#2a2d35] rounded-lg px-4 py-3">
                    <span className={`material-symbols-outlined text-[20px] flex-shrink-0 ${file.type === "pdf" ? "text-red-400" : "text-blue-400"}`}>
                      {FILE_TYPE_ICONS[file.type]}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-slate-200 truncate">{file.name}</p>
                      <div className="flex items-center gap-2 text-xs text-slate-600">
                        {file.license_number && <span className="text-slate-500 font-mono">{file.license_number}</span>}
                        {file.license_confidence !== undefined && file.license_confidence > 0 && (
                          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${confidenceTag(file.license_confidence).bg} ${confidenceTag(file.license_confidence).color}`}>
                            {confidenceTag(file.license_confidence).label}
                          </span>
                        )}
                      </div>
                    </div>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full flex-shrink-0 ${STATUS_STYLES[file.status]}`}>
                      {file.status === "extracting" ? "EXTRACTING" : file.status.toUpperCase().replace("_", " ")}
                    </span>
                    {file.defense_line_used && (
                      <span className="text-xs text-slate-500 flex-shrink-0">via {DEFENSE_LABELS[file.defense_line_used]}</span>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}

          {/* After complete — show 3-column results + JSON */}
          {batchComplete && processedFiles.length > 0 && (
            <>
              <h3 className="text-base font-bold text-slate-100 mb-4">Batch Results</h3>

              {/* 3-column results */}
              <div className={`grid gap-4 mb-6 ${lowConfFiles.length > 0 ? "grid-cols-3" : "grid-cols-2"}`}>
                {/* Yellow — Low confidence */}
                {lowConfFiles.length > 0 && (
                  <div className="bg-[#22252b] border border-amber-500/30 rounded-xl overflow-hidden">
                    <div className="px-4 py-3 bg-amber-500/10 border-b border-amber-500/30 flex items-center gap-2">
                      <span className="material-symbols-outlined text-[18px] text-amber-400">warning</span>
                      <span className="text-sm font-bold text-amber-400">Low Confidence ({lowConfFiles.length})</span>
                    </div>
                    <div className="p-3 space-y-2 max-h-[400px] overflow-y-auto">
                      {lowConfFiles.map((f) => {
                        const ct = confidenceTag(f.license_confidence ?? 0);
                        return (
                          <div key={f.path} className="bg-[#1a1d23] border border-[#2a2d35] rounded-lg p-3">
                            <div className="flex items-center justify-between mb-1">
                              <p className="text-xs font-medium text-slate-300 truncate max-w-[140px]">{f.name}</p>
                              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${ct.bg} ${ct.color}`}>{ct.label}</span>
                            </div>
                            <p className="text-xs text-slate-500 font-mono">{f.license_number || "—"}</p>
                            <p className="text-[10px] text-amber-400/70 mt-1">Review extraction manually</p>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Red — Failed */}
                <div className="bg-[#22252b] border border-red-500/30 rounded-xl overflow-hidden">
                  <div className="px-4 py-3 bg-red-500/10 border-b border-red-500/30 flex items-center gap-2">
                    <span className="material-symbols-outlined text-[18px] text-red-400">cancel</span>
                    <span className="text-sm font-bold text-red-400">Failed / Not Verified ({failedFiles.length})</span>
                  </div>
                  <div className="p-3 space-y-2 max-h-[400px] overflow-y-auto">
                    {failedFiles.length === 0 ? (
                      <p className="text-xs text-slate-600 text-center py-4">None</p>
                    ) : (
                      failedFiles.map((f) => (
                        <div key={f.path} className="bg-[#1a1d23] border border-[#2a2d35] rounded-lg p-3">
                          <div className="flex items-center justify-between mb-1">
                            <p className="text-xs font-medium text-slate-300 truncate max-w-[180px]">{f.name}</p>
                            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${STATUS_STYLES[f.status]}`}>
                              {f.status === "not_found" ? "NOT FOUND" : "ERROR"}
                            </span>
                          </div>
                          <p className="text-xs text-slate-500 font-mono">{f.license_number || "—"}</p>
                          {f.error && <p className="text-[10px] text-red-400/80 mt-1 truncate" title={f.error}>{f.error}</p>}
                        </div>
                      ))
                    )}
                  </div>
                </div>

                {/* Green — Verified */}
                <div className="bg-[#22252b] border border-green-500/30 rounded-xl overflow-hidden">
                  <div className="px-4 py-3 bg-green-500/10 border-b border-green-500/30 flex items-center gap-2">
                    <span className="material-symbols-outlined text-[18px] text-green-400">check_circle</span>
                    <span className="text-sm font-bold text-green-400">Verified ({verifiedFiles.length})</span>
                  </div>
                  <div className="p-3 space-y-2 max-h-[400px] overflow-y-auto">
                    {verifiedFiles.length === 0 ? (
                      <p className="text-xs text-slate-600 text-center py-4">None</p>
                    ) : (
                      verifiedFiles.map((f) => (
                        <div key={f.path} className="bg-[#1a1d23] border border-[#2a2d35] rounded-lg p-3">
                          <div className="flex items-center justify-between mb-1">
                            <p className="text-xs font-medium text-slate-300 truncate max-w-[180px]">{f.name}</p>
                            {f.defense_line_used && (
                              <span className="text-[10px] text-slate-500">via {DEFENSE_LABELS[f.defense_line_used]}</span>
                            )}
                          </div>
                          <p className="text-xs text-slate-500 font-mono">{f.license_number || "—"}</p>
                          {f.result?.results?.[0] && (
                            <div className="mt-1.5 text-[10px] text-green-400/80 space-y-0.5">
                              {f.result.results[0].doing_business_as && <p>DBA: {f.result.results[0].doing_business_as}</p>}
                              {f.result.results[0].location_address && <p>Addr: {f.result.results[0].location_address}</p>}
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>

              {/* Structured JSON output */}
              <div className="bg-[#15171c] rounded-xl p-4 overflow-x-auto border border-[#2a2d35]">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-slate-500 uppercase tracking-wide">Structured Output — All Results</span>
                  <button
                    onClick={() => navigator.clipboard.writeText(JSON.stringify(buildJsonOutput(), null, 2))}
                    className="text-xs text-slate-500 hover:text-slate-300 flex items-center gap-1 transition-colors"
                  >
                    <span className="material-symbols-outlined text-[14px]">content_copy</span>
                    Copy
                  </button>
                </div>
                <pre className="text-xs text-green-400 font-mono leading-relaxed whitespace-pre-wrap max-h-[500px] overflow-y-auto">
                  {JSON.stringify(buildJsonOutput(), null, 2)}
                </pre>
              </div>
            </>
          )}

          {/* Complete but no results (all extraction failed) */}
          {batchComplete && processedFiles.length === 0 && (
            <div className="flex flex-col items-center justify-center h-64 text-slate-600">
              <span className="material-symbols-outlined text-5xl mb-2">error_outline</span>
              <p className="text-sm">No license numbers could be extracted from the selected files.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default BatchList;
