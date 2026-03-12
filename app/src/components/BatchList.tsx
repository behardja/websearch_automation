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
  status: "pending" | "running" | "verified" | "not_found" | "error";
  license_number?: string;
  defense_line_used?: number;
  result_count?: number;
  error?: string;
}

const FILE_TYPE_ICONS: Record<string, string> = {
  pdf: "picture_as_pdf",
  image: "image",
  other: "description",
};

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-[#2a2d35] text-slate-400",
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

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const BatchList: React.FC = () => {
  const [gcsPath, setGcsPath] = useState("gs://sandbox-401718-alcohol-license/Texas Files");
  const [files, setFiles] = useState<GcsFile[]>([]);
  const [filesLoaded, setFilesLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [defenseLine, setDefenseLine] = useState<number | null>(null);
  const [previewIdx, setPreviewIdx] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

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
  };

  const toggleCheck = (idx: number) => {
    setFiles((prev) =>
      prev.map((f, i) => (i === idx ? { ...f, checked: !f.checked } : f))
    );
  };

  const selectAll = () =>
    setFiles((prev) => prev.map((f) => ({ ...f, checked: true })));
  const deselectAll = () =>
    setFiles((prev) => prev.map((f) => ({ ...f, checked: false })));

  const checkedCount = files.filter((f) => f.checked).length;
  const completedCount = files.filter(
    (f) =>
      f.status === "verified" ||
      f.status === "not_found" ||
      f.status === "error"
  ).length;

  const handleRunBatch = async () => {
    const selected = files.filter((f) => f.checked);
    if (selected.length === 0) return;

    setRunning(true);
    setFiles((prev) =>
      prev.map((f) =>
        f.checked ? { ...f, status: "pending", error: undefined } : f
      )
    );

    // In production: send selected files to Document AI batch, get extracted
    // license numbers back, then run verification cascade for each.
    // For now: simulate with placeholder license numbers extracted from filenames.
    const licenseItems = selected.map((f) => {
      const match = f.name.match(/(\d{6,9})/);
      return { license_number: match ? match[1] : "000000000" };
    });

    try {
      await startBatch(licenseItems, defenseLine);

      const ctrl = subscribeBatchStatus(
        (event: BatchEvent) => {
          if (event.license_number) {
            setFiles((prev) =>
              prev.map((f) => {
                const match = f.name.match(/(\d{6,9})/);
                const fileLicense = match ? match[1] : "";
                if (fileLicense === event.license_number) {
                  return {
                    ...f,
                    status: event.status as GcsFile["status"],
                    license_number: event.license_number,
                    defense_line_used: event.defense_line_used,
                    result_count: event.result_count,
                    error: event.error,
                  };
                }
                return f;
              })
            );
          }
          if (event.status === "complete") {
            setRunning(false);
          }
        },
        () => {
          setRunning(false);
        }
      );
      abortRef.current = ctrl;
    } catch (e: any) {
      setFiles((prev) =>
        prev.map((f) =>
          f.checked ? { ...f, status: "error", error: e.message } : f
        )
      );
      setRunning(false);
    }
  };

  const handleCancel = async () => {
    abortRef.current?.abort();
    await cancelBatch();
    setRunning(false);
  };

  const previewUrl = (file: GcsFile) =>
    `/api/gcs/preview?path=${encodeURIComponent(file.path)}`;

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Left: GCS input and controls */}
      <div className="w-[380px] flex-shrink-0 border-r border-[#2a2d35] bg-[#22252b] p-6 overflow-y-auto">
        <h3 className="text-base font-bold text-slate-100 mb-4">
          Batch Verification
        </h3>

        {/* GCS Path input */}
        <div className="mb-4">
          <label className="block text-sm font-medium text-slate-300 mb-1">
            GCS Path
          </label>
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
                  <span className="material-symbols-outlined text-[18px] animate-spin">
                    progress_activity
                  </span>
                ) : (
                  <span className="material-symbols-outlined text-[18px]">
                    folder_open
                  </span>
                )}
              </button>
            ) : (
              <button
                onClick={handleClearFiles}
                disabled={running}
                className="px-3 py-2 bg-[#2a2d35] text-slate-400 font-semibold text-sm rounded-lg hover:bg-[#33363e] disabled:opacity-50 transition-colors"
              >
                <span className="material-symbols-outlined text-[18px]">
                  close
                </span>
              </button>
            )}
          </div>
          <p className="text-xs text-slate-600 mt-1.5">
            Enter a GCS folder path containing license PDFs/images
          </p>
        </div>

        {/* Doc AI banner */}
        {filesLoaded && (
          <div className="mb-4 p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg flex items-start gap-2">
            <span className="material-symbols-outlined text-[18px] text-amber-400 mt-0.5">
              info
            </span>
            <div className="text-xs text-amber-300">
              <strong>Document AI not connected yet.</strong> License numbers
              are simulated from filenames. In production, each file will be
              processed through Doc AI to extract fields.
            </div>
          </div>
        )}

        {/* Verification method */}
        {filesLoaded && (
          <div className="mb-4">
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Verification Method
            </label>
            <select
              value={defenseLine ?? ""}
              onChange={(e) =>
                setDefenseLine(e.target.value ? Number(e.target.value) : null)
              }
              className="w-full px-3 py-2 border border-[#3a3d45] rounded-lg text-sm bg-[#2a2d35] text-slate-200"
            >
              <option value="">Sequence all methods (default)</option>
              <option value="1">Method 1 — HTTP Direct</option>
              <option value="2">Method 2 — Playwright</option>
            </select>
          </div>
        )}

        {/* Selection controls */}
        {filesLoaded && files.length > 0 && (
          <>
            <div className="flex gap-2 mb-4">
              <button
                onClick={selectAll}
                disabled={running}
                className="flex-1 py-1.5 text-xs font-semibold bg-[#2a2d35] text-slate-300 rounded hover:bg-[#33363e] disabled:opacity-50 transition-colors"
              >
                Select All
              </button>
              <button
                onClick={deselectAll}
                disabled={running}
                className="flex-1 py-1.5 text-xs font-semibold bg-[#2a2d35] text-slate-300 rounded hover:bg-[#33363e] disabled:opacity-50 transition-colors"
              >
                Deselect All
              </button>
            </div>

            {running ? (
              <button
                onClick={handleCancel}
                className="w-full py-2.5 bg-danger text-white font-bold text-sm rounded-lg hover:bg-red-600 transition-colors flex items-center justify-center gap-2"
              >
                <span className="material-symbols-outlined text-[18px]">
                  cancel
                </span>
                Cancel Batch
              </button>
            ) : (
              <button
                onClick={handleRunBatch}
                disabled={checkedCount === 0}
                className="w-full py-2.5 bg-success text-white font-bold text-sm rounded-lg hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
              >
                <span className="material-symbols-outlined text-[18px]">
                  play_arrow
                </span>
                Process {checkedCount} File{checkedCount !== 1 ? "s" : ""}
              </button>
            )}

            {/* Progress bar */}
            {running && (
              <div className="mt-4">
                <div className="flex justify-between text-xs text-slate-500 mb-1">
                  <span>Progress</span>
                  <span>
                    {completedCount} / {checkedCount}
                  </span>
                </div>
                <div className="w-full bg-[#1a1d23] rounded-full h-2">
                  <div
                    className="bg-success h-2 rounded-full transition-all"
                    style={{
                      width: `${checkedCount > 0 ? (completedCount / checkedCount) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Right: File list */}
      <div className="flex-1 overflow-y-auto bg-[#1a1d23] p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-bold text-slate-100">
            {filesLoaded ? `Files (${files.length})` : "Files"}
          </h3>
          {filesLoaded && (
            <span className="text-sm text-slate-500">
              {checkedCount} selected
            </span>
          )}
        </div>

        {!filesLoaded ? (
          <div className="flex flex-col items-center justify-center h-64 text-slate-600">
            <span className="material-symbols-outlined text-5xl mb-2">
              cloud_queue
            </span>
            <p className="text-sm">
              Enter a GCS path to browse license files
            </p>
            <p className="text-xs text-slate-700 mt-1">
              e.g. gs://sandbox-401718-alcohol-license/Texas Files
            </p>
          </div>
        ) : files.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-slate-600">
            <span className="material-symbols-outlined text-5xl mb-2">
              folder_off
            </span>
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
                  <input
                    type="checkbox"
                    checked={file.checked}
                    onChange={() => toggleCheck(idx)}
                    disabled={running}
                    className="w-4 h-4 rounded flex-shrink-0"
                  />
                  <span className={`material-symbols-outlined text-[20px] flex-shrink-0 ${
                    file.type === "pdf" ? "text-red-400" : file.type === "image" ? "text-blue-400" : "text-slate-500"
                  }`}>
                    {FILE_TYPE_ICONS[file.type]}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-slate-200 truncate">
                        {file.name}
                      </p>
                      <button
                        onClick={() => setPreviewIdx(previewIdx === idx ? null : idx)}
                        className={`p-0.5 rounded transition-colors flex-shrink-0 ${
                          previewIdx === idx
                            ? "text-primary"
                            : "text-slate-600 hover:text-slate-300"
                        }`}
                        title="Toggle preview"
                      >
                        <span className="material-symbols-outlined text-[16px]">
                          {previewIdx === idx ? "visibility_off" : "visibility"}
                        </span>
                      </button>
                    </div>
                    <p className="text-xs text-slate-600 truncate">
                      {file.size}
                      {file.license_number && (
                        <span className="ml-2 text-slate-500">
                          License: {file.license_number}
                        </span>
                      )}
                    </p>
                  </div>
                  <span
                    className={`text-xs font-bold px-2 py-0.5 rounded-full flex-shrink-0 ${
                      STATUS_STYLES[file.status]
                    }`}
                  >
                    {file.status.toUpperCase()}
                  </span>
                  {file.defense_line_used && (
                    <span className="text-xs text-slate-500 flex-shrink-0">
                      via {DEFENSE_LABELS[file.defense_line_used]}
                    </span>
                  )}
                  {file.error && (
                    <span
                      className="text-xs text-red-400 truncate max-w-[150px] flex-shrink-0"
                      title={file.error}
                    >
                      {file.error}
                    </span>
                  )}
                </div>
                {/* Inline preview panel */}
                {previewIdx === idx && (
                  <div className="bg-[#22252b] border border-[#2a2d35] border-t-0 rounded-b-lg p-4">
                    <div className="bg-[#1a1d23] rounded-lg overflow-hidden flex items-center justify-center" style={{ height: "320px" }}>
                      {file.type === "image" ? (
                        <img
                          src={previewUrl(file)}
                          alt={file.name}
                          className="max-w-full max-h-full object-contain"
                        />
                      ) : file.type === "pdf" ? (
                        <iframe
                          src={previewUrl(file)}
                          title={file.name}
                          className="w-full h-full border-0"
                        />
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
};

export default BatchList;
