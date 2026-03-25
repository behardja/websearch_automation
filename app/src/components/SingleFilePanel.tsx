import { useState, useRef, useMemo } from "react";
import {
  startVerification,
  subscribeVerifyStatus,
  extractDocument,
  type CascadeEvent,
  type FieldWithConfidence,
} from "../services/apiClient";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FieldEntry {
  value: string;
  raw_value?: string;
  confidence: number;
}

interface ExtractedFields {
  license_number: FieldEntry;
  doing_business_as: FieldEntry;
  legal_name: FieldEntry;
  license_type: FieldEntry;
  expiration_date: FieldEntry;
  address: FieldEntry;
  city: FieldEntry;
  state: FieldEntry;
  jurisdiction: FieldEntry;
}

interface DefenseStep {
  line: number;
  label: string;
  description: string;
  icon: string;
  status: "idle" | "running" | "success" | "failed" | "no_results" | "skipped";
  error?: string;
  result?: any;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const INITIAL_STEPS: DefenseStep[] = [
  {
    line: 1,
    label: "HTTP Direct Request",
    description: "Programmatically POST to the state search endpoint using HTTP headers.",
    icon: "http",
    status: "idle",
  },
  {
    line: 2,
    label: "Playwright Scraper",
    description: "Fill form fields and parse the HTML results using browser automation.",
    icon: "code",
    status: "idle",
  },
  {
    line: 3,
    label: "Gemini Browser Agent",
    description: "AI agent browses the site like a human using Computer Use.",
    icon: "smart_toy",
    status: "idle",
  },
];

const STATUS_CONFIG: Record<string, { color: string; bg: string; border: string; icon: string }> = {
  idle:       { color: "text-slate-500", bg: "bg-[#22252b]",  border: "border-[#3a3d45]", icon: "radio_button_unchecked" },
  running:    { color: "text-blue-400",  bg: "bg-blue-500/10", border: "border-blue-500/40", icon: "progress_activity" },
  success:    { color: "text-green-400", bg: "bg-green-500/10", border: "border-green-500/40", icon: "check_circle" },
  failed:     { color: "text-red-400",   bg: "bg-red-500/10",  border: "border-red-500/40",  icon: "error" },
  no_results: { color: "text-amber-400", bg: "bg-amber-500/10", border: "border-amber-500/40", icon: "warning" },
  skipped:    { color: "text-slate-600", bg: "bg-[#1e2127]",  border: "border-[#2a2d35]", icon: "block" },
};

const STATE_OPTIONS = [
  { code: "TX", name: "Texas", tag: "TABC" },
  { code: "FL", name: "Florida", tag: "DBPR" },
  { code: "GA", name: "Georgia", tag: "DOR" },
];

// Type is always "License" — maps to ddlBusinessType value "2" on TABC site
const BUSINESS_TYPE = "License";

const CONFIDENCE_THRESHOLD_LOW = 0.5;
const CONFIDENCE_THRESHOLD_HIGH = 0.8;

function confidenceColor(c: number): { dot: string; border: string; label: string } {
  if (c >= CONFIDENCE_THRESHOLD_HIGH) return { dot: "bg-green-400", border: "border-green-500/40", label: "High" };
  if (c >= CONFIDENCE_THRESHOLD_LOW) return { dot: "bg-amber-400", border: "border-amber-500/40", label: "Medium" };
  return { dot: "bg-red-400", border: "border-red-500/40", label: "Low" };
}

const EMPTY_FIELD: FieldEntry = { value: "", confidence: 0 };

const EMPTY_FIELDS: ExtractedFields = {
  license_number: { ...EMPTY_FIELD },
  doing_business_as: { ...EMPTY_FIELD },
  legal_name: { ...EMPTY_FIELD },
  license_type: { ...EMPTY_FIELD },
  expiration_date: { ...EMPTY_FIELD },
  address: { ...EMPTY_FIELD },
  city: { ...EMPTY_FIELD },
  state: { ...EMPTY_FIELD },
  jurisdiction: { ...EMPTY_FIELD },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type ViewStep = "upload" | "review" | "verify";

const SingleFilePanel: React.FC = () => {
  // Navigation
  const [currentView, setCurrentView] = useState<ViewStep>("upload");

  // Upload step
  const [selectedState, setSelectedState] = useState("TX");
  const [file, setFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const filePreviewUrl = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  const isImage = file?.type.startsWith("image/");
  const isPdf = file?.type === "application/pdf";

  // Review step — extracted fields (editable)
  const [fields, setFields] = useState<ExtractedFields>(EMPTY_FIELDS);
  const [extracting, setExtracting] = useState(false);
  const [extractionError, setExtractionError] = useState<string | null>(null);

  // Method selection
  const [selectedMethod, setSelectedMethod] = useState<number | null>(null);

  // Verify step — defense cascade
  const [steps, setSteps] = useState<DefenseStep[]>(INITIAL_STEPS);
  const [processing, setProcessing] = useState(false);
  const [finalResult, setFinalResult] = useState<any>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Handlers
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) setFile(f);
  };

  const handleUploadNext = async () => {
    if (!file) {
      // No file — go to review with empty fields for manual entry
      setFields({ ...EMPTY_FIELDS, state: { value: selectedState, confidence: 1 } });
      setExtractionError(null);
      setCurrentView("review");
      return;
    }

    setExtracting(true);
    setExtractionError(null);
    try {
      const resp = await extractDocument(file, selectedState);
      if (resp.error || !resp.fields) {
        setExtractionError(resp.error || "No fields returned");
        setFields({ ...EMPTY_FIELDS, state: { value: selectedState, confidence: 1 } });
      } else {
        const f = resp.fields;
        setFields({
          license_number: f.license_number || EMPTY_FIELD,
          doing_business_as: f.doing_business_as || EMPTY_FIELD,
          legal_name: f.legal_name || EMPTY_FIELD,
          license_type: f.license_type || EMPTY_FIELD,
          expiration_date: f.expiration_date || EMPTY_FIELD,
          address: f.address || EMPTY_FIELD,
          city: f.city || EMPTY_FIELD,
          state: f.state?.value ? f.state : { value: selectedState, confidence: 1 },
          jurisdiction: f.jurisdiction || EMPTY_FIELD,
        });
      }
      setCurrentView("review");
    } catch (err: any) {
      setExtractionError(err.message || "Extraction failed");
    } finally {
      setExtracting(false);
    }
  };

  const handleBackToUpload = () => {
    setCurrentView("upload");
    setSteps(INITIAL_STEPS.map((s) => ({ ...s, status: "idle", error: undefined, result: undefined })));
    setFinalResult(null);
    setExtractionError(null);
  };

  const handleStartVerification = async () => {
    setCurrentView("verify");
    setProcessing(true);
    setFinalResult(null);
    setSteps(INITIAL_STEPS.map((s) => ({ ...s, status: "idle", error: undefined, result: undefined })));

    // Flatten fields for the verification API (which expects simple strings)
    const flatFields = {
      permit_type: fields.license_type.value,
      license_number: fields.license_number.value,
      doing_business_as: fields.doing_business_as.value,
      address: fields.address.value,
      city: fields.city.value,
      state: fields.state.value,
    };

    try {
      await startVerification(fields.license_number.value.trim(), fields.state.value, flatFields, selectedMethod);

      const ctrl = subscribeVerifyStatus(
        (event: CascadeEvent) => {
          if (event.defense_line) {
            setSteps((prev) =>
              prev.map((step) => {
                if (step.line === event.defense_line) {
                  return {
                    ...step,
                    status: event.status as DefenseStep["status"],
                    error: event.error,
                    result: event.result,
                  };
                }
                if (event.status === "success" && step.line > event.defense_line!) {
                  return { ...step, status: "skipped" };
                }
                return step;
              })
            );
          }
          if (event.status === "complete") {
            setFinalResult(event.result || null);
            setProcessing(false);
          }
        },
        () => {
          setProcessing(false);
        }
      );
      abortRef.current = ctrl;
    } catch {
      setProcessing(false);
    }
  };

  const updateField = (key: keyof ExtractedFields, value: string) => {
    setFields((prev) => ({
      ...prev,
      [key]: { ...prev[key], value },
    }));
  };

  // -------------------------------------------------------------------------
  // Render: Upload Step
  // -------------------------------------------------------------------------
  if (currentView === "upload") {
    return (
      <div className="flex flex-1 overflow-hidden bg-[#1a1d23]">
        {/* Left: Upload controls */}
        <div className={`flex flex-col justify-center p-8 overflow-y-auto ${file ? "w-[420px] flex-shrink-0 border-r border-[#2a2d35]" : "flex-1 items-center"}`}>
          <div className={`w-full ${file ? "" : "max-w-lg"} bg-[#22252b] rounded-2xl shadow-sm border border-[#2a2d35] p-8`}>
            <div className="text-center mb-6">
              <span className="material-symbols-outlined text-5xl text-primary mb-2">upload_file</span>
              <h2 className="text-xl font-bold text-slate-100">Upload License Document</h2>
              <p className="text-sm text-slate-400 mt-1">
                Upload a PDF or image of the alcohol license to verify.
              </p>
            </div>

            {/* State selector */}
            <div className="mb-5">
              <label className="block text-sm font-medium text-slate-300 mb-1.5">State</label>
              <select
                value={selectedState}
                onChange={(e) => setSelectedState(e.target.value)}
                className="w-full px-3 py-2.5 border border-[#3a3d45] rounded-lg text-sm bg-[#2a2d35] text-slate-200 focus:outline-none focus:ring-2 focus:ring-primary/50"
              >
                {STATE_OPTIONS.map((s) => (
                  <option key={s.code} value={s.code}>
                    {s.name} ({s.tag})
                  </option>
                ))}
              </select>
            </div>

            {/* File upload */}
            <div className="mb-6">
              <label className="block text-sm font-medium text-slate-300 mb-1.5">License File</label>
              <div
                onClick={() => fileInputRef.current?.click()}
                className={`w-full border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
                  file
                    ? "border-primary bg-blue-500/10"
                    : "border-[#3a3d45] hover:border-primary hover:bg-blue-500/5"
                }`}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.jpg,.jpeg,.png,.tiff,.bmp,.webp"
                  onChange={handleFileChange}
                  className="hidden"
                />
                {file ? (
                  <div className="flex flex-col items-center gap-2">
                    <span className="material-symbols-outlined text-4xl text-primary">description</span>
                    <span className="text-sm font-semibold text-slate-200 truncate max-w-[300px]">
                      {file.name}
                    </span>
                    <span className="text-xs text-slate-500">
                      {(file.size / 1024).toFixed(0)} KB — Click to change
                    </span>
                  </div>
                ) : (
                  <div className="text-slate-500">
                    <span className="material-symbols-outlined text-4xl mb-2">cloud_upload</span>
                    <p className="text-sm font-medium">Click to upload PDF, JPG, or PNG</p>
                    <p className="text-xs mt-1">or drag and drop</p>
                  </div>
                )}
              </div>
            </div>

            <button
              onClick={handleUploadNext}
              disabled={extracting}
              className="w-full py-3 bg-primary text-white font-bold text-sm rounded-lg hover:bg-blue-600 disabled:opacity-60 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
            >
              {extracting ? (
                <>
                  <span className="material-symbols-outlined text-[18px] animate-spin">progress_activity</span>
                  Extracting with Document AI...
                </>
              ) : (
                <>
                  <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
                  {file ? "Extract & Review Fields" : "Enter Fields Manually"}
                </>
              )}
            </button>

            {extractionError && (
              <div className="mt-3 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-xs text-red-400">
                <strong>Extraction error:</strong> {extractionError}
              </div>
            )}

            {!file && (
              <p className="text-xs text-center text-slate-500 mt-3">
                No file? You can still enter the license fields manually on the next step.
              </p>
            )}
          </div>
        </div>

        {/* Right: File preview (only shown when a file is selected) */}
        {file && filePreviewUrl && (
          <div className="flex-1 flex flex-col overflow-hidden p-6">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-base font-bold text-slate-100">Document Preview</h3>
              <span className="text-xs text-slate-500">{file.name}</span>
            </div>
            <div className="flex-1 bg-[#22252b] border border-[#2a2d35] rounded-xl overflow-hidden flex items-center justify-center">
              {isImage && (
                <img
                  src={filePreviewUrl}
                  alt="License preview"
                  className="max-w-full max-h-full object-contain p-4"
                />
              )}
              {isPdf && (
                <iframe
                  src={filePreviewUrl}
                  title="PDF preview"
                  className="w-full h-full border-0"
                />
              )}
              {!isImage && !isPdf && (
                <div className="text-center text-slate-500 p-8">
                  <span className="material-symbols-outlined text-5xl mb-2">description</span>
                  <p className="text-sm">Preview not available for this file type</p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // Render: Review Step — pre-filled extracted fields
  // -------------------------------------------------------------------------
  if (currentView === "review") {
    return (
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Extracted fields form */}
        <div className="w-[420px] flex-shrink-0 border-r border-[#2a2d35] bg-[#22252b] p-6 overflow-y-auto">
          <div className="flex items-center gap-2 mb-1">
            <button
              onClick={handleBackToUpload}
              className="text-slate-500 hover:text-slate-300 transition-colors"
            >
              <span className="material-symbols-outlined text-[20px]">arrow_back</span>
            </button>
            <h3 className="text-base font-bold text-slate-100">Extracted Fields</h3>
          </div>
          <p className="text-xs text-slate-500 mb-5 ml-7">
            Review and edit the fields below before running verification.
            Fields are color-coded by extraction confidence.
          </p>

          {/* Confidence legend */}
          <div className="mb-4 p-3 bg-[#1a1d23] border border-[#2a2d35] rounded-lg">
            <div className="flex items-center gap-4 text-xs text-slate-400">
              <span className="text-slate-500 font-medium">AI Confidence:</span>
              <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-green-400"></span> High</span>
              <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-amber-400"></span> Medium</span>
              <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-red-400"></span> Low</span>
            </div>
          </div>

          {/* File info */}
          {file && (
            <div className="mb-4 flex items-center gap-2 p-3 bg-[#1a1d23] rounded-lg border border-[#2a2d35]">
              <span className="material-symbols-outlined text-[20px] text-primary">description</span>
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-200 truncate">{file.name}</p>
                <p className="text-xs text-slate-500">{(file.size / 1024).toFixed(0)} KB</p>
              </div>
            </div>
          )}

          {/* Quick search by license # only */}
          <button
            onClick={() => {
              // Start verification with only license_number and state (no extra fields)
              setCurrentView("verify");
              setProcessing(true);
              setFinalResult(null);
              setSteps(INITIAL_STEPS.map((s) => ({ ...s, status: "idle", error: undefined, result: undefined })));

              startVerification(fields.license_number.value.trim(), fields.state.value, undefined, selectedMethod)
                .then(() => {
                  const ctrl = subscribeVerifyStatus(
                    (event: CascadeEvent) => {
                      if (event.defense_line) {
                        setSteps((prev) =>
                          prev.map((step) => {
                            if (step.line === event.defense_line) {
                              return { ...step, status: event.status as DefenseStep["status"], error: event.error, result: event.result };
                            }
                            if (event.status === "success" && step.line > event.defense_line!) {
                              return { ...step, status: "skipped" };
                            }
                            return step;
                          })
                        );
                      }
                      if (event.status === "complete") {
                        setFinalResult(event.result || null);
                        setProcessing(false);
                      }
                    },
                    () => setProcessing(false)
                  );
                  abortRef.current = ctrl;
                })
                .catch(() => setProcessing(false));
            }}
            disabled={!fields.license_number.value.trim()}
            className="w-full mb-4 py-2.5 bg-success text-white font-bold text-sm rounded-lg hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
          >
            <span className="material-symbols-outlined text-[18px]">play_arrow</span>
            Quick Search by License / Permit Number
          </button>

          <div className="space-y-4">
            {/* License Number */}
            {(() => {
              const cc = confidenceColor(fields.license_number.confidence);
              return (
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <label className="text-sm font-medium text-slate-300">License / Permit Number</label>
                    <span className={`w-2 h-2 rounded-full ml-auto ${cc.dot}`}></span>
                  </div>
                  <input
                    type="text"
                    value={fields.license_number.value}
                    onChange={(e) => updateField("license_number", e.target.value)}
                    className={`w-full px-3 py-2 border ${cc.border} rounded-lg text-sm font-mono bg-[#2a2d35] text-slate-200 focus:outline-none focus:ring-2 focus:ring-primary/50`}
                  />
                  {fields.license_number.raw_value && fields.license_number.raw_value !== fields.license_number.value && (
                    <p className="text-[10px] text-slate-500 mt-0.5">Raw: {fields.license_number.raw_value}</p>
                  )}
                </div>
              );
            })()}

            {/* Doing Business As (DBA) */}
            {(() => {
              const cc = confidenceColor(fields.doing_business_as.confidence);
              return (
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <label className="text-sm font-medium text-slate-300">Doing Business As</label>
                    <span className={`w-2 h-2 rounded-full ml-auto ${cc.dot}`}></span>
                  </div>
                  <input
                    type="text"
                    value={fields.doing_business_as.value}
                    onChange={(e) => updateField("doing_business_as", e.target.value)}
                    className={`w-full px-3 py-2 border ${cc.border} rounded-lg text-sm bg-[#2a2d35] text-slate-200 focus:outline-none focus:ring-2 focus:ring-primary/50`}
                  />
                </div>
              );
            })()}

            {/* Legal Name */}
            {(() => {
              const cc = confidenceColor(fields.legal_name.confidence);
              return (
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <label className="text-sm font-medium text-slate-300">Legal Name</label>
                    <span className={`w-2 h-2 rounded-full ml-auto ${cc.dot}`}></span>
                  </div>
                  <input
                    type="text"
                    value={fields.legal_name.value}
                    onChange={(e) => updateField("legal_name", e.target.value)}
                    className={`w-full px-3 py-2 border ${cc.border} rounded-lg text-sm bg-[#2a2d35] text-slate-200 focus:outline-none focus:ring-2 focus:ring-primary/50`}
                  />
                </div>
              );
            })()}

            {/* License Type */}
            {(() => {
              const cc = confidenceColor(fields.license_type.confidence);
              return (
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <label className="text-sm font-medium text-slate-300">License Type</label>
                    <span className={`w-2 h-2 rounded-full ml-auto ${cc.dot}`}></span>
                  </div>
                  <input
                    type="text"
                    value={fields.license_type.value}
                    onChange={(e) => updateField("license_type", e.target.value)}
                    className={`w-full px-3 py-2 border ${cc.border} rounded-lg text-sm bg-[#2a2d35] text-slate-200 focus:outline-none focus:ring-2 focus:ring-primary/50`}
                  />
                </div>
              );
            })()}

            {/* Expiration Date */}
            {(() => {
              const cc = confidenceColor(fields.expiration_date.confidence);
              return (
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <label className="text-sm font-medium text-slate-300">Expiration Date</label>
                    <span className={`w-2 h-2 rounded-full ml-auto ${cc.dot}`}></span>
                  </div>
                  <input
                    type="text"
                    value={fields.expiration_date.value}
                    onChange={(e) => updateField("expiration_date", e.target.value)}
                    className={`w-full px-3 py-2 border ${cc.border} rounded-lg text-sm bg-[#2a2d35] text-slate-200 focus:outline-none focus:ring-2 focus:ring-primary/50`}
                  />
                </div>
              );
            })()}

            {/* Address */}
            {(() => {
              const cc = confidenceColor(fields.address.confidence);
              return (
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <label className="text-sm font-medium text-slate-300">Location Address</label>
                    <span className={`w-2 h-2 rounded-full ml-auto ${cc.dot}`}></span>
                  </div>
                  <input
                    type="text"
                    value={fields.address.value}
                    onChange={(e) => updateField("address", e.target.value)}
                    className={`w-full px-3 py-2 border ${cc.border} rounded-lg text-sm bg-[#2a2d35] text-slate-200 focus:outline-none focus:ring-2 focus:ring-primary/50`}
                  />
                </div>
              );
            })()}

            {/* City + State */}
            <div className="flex gap-3">
              {(() => {
                const cc = confidenceColor(fields.city.confidence);
                return (
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`w-2 h-2 rounded-full ${cc.dot}`}></span>
                      <label className="text-sm font-medium text-slate-300">City</label>
                    </div>
                    <input
                      type="text"
                      value={fields.city.value}
                      onChange={(e) => updateField("city", e.target.value)}
                      className={`w-full px-3 py-2 border ${cc.border} rounded-lg text-sm bg-[#2a2d35] text-slate-200 focus:outline-none focus:ring-2 focus:ring-primary/50`}
                    />
                  </div>
                );
              })()}
              <div className="w-20">
                <div className="flex items-center gap-2 mb-1">
                  <label className="text-sm font-medium text-slate-300">State</label>
                </div>
                <input
                  type="text"
                  value={fields.state.value}
                  disabled
                  className="w-full px-3 py-2 border border-[#2a2d35] rounded-lg text-sm bg-[#1a1d23] text-slate-500 font-mono"
                />
              </div>
            </div>

            {/* Jurisdiction (read-only context) */}
            {fields.jurisdiction.value && (
              <div>
                <label className="block text-sm font-medium text-slate-500 mb-1">Jurisdiction</label>
                <input
                  type="text"
                  value={fields.jurisdiction.value}
                  disabled
                  className="w-full px-3 py-2 border border-[#2a2d35] rounded-lg text-sm bg-[#1a1d23] text-slate-500"
                />
              </div>
            )}
          </div>

          {/* Verification method selector */}
          <div className="mt-5">
            <label className="block text-sm font-medium text-slate-300 mb-1">
              Verification Method
            </label>
            <select
              value={selectedMethod ?? ""}
              onChange={(e) =>
                setSelectedMethod(e.target.value ? Number(e.target.value) : null)
              }
              className="w-full px-3 py-2 border border-[#3a3d45] rounded-lg text-sm bg-[#2a2d35] text-slate-200 focus:outline-none focus:ring-2 focus:ring-primary/50"
            >
              <option value="">Sequence all methods (default)</option>
              <option value="1">Method 1 — HTTP Direct</option>
              <option value="2">Method 2 — Playwright</option>
              <option value="3">Method 3 — Gemini Computer Use</option>
            </select>
          </div>

          <button
            onClick={handleStartVerification}
            disabled={!fields.license_number.value.trim()}
            className="w-full mt-4 py-3 bg-success text-white font-bold text-sm rounded-lg hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
          >
            <span className="material-symbols-outlined text-[18px]">play_arrow</span>
            Run Verification on All Fields
          </button>
        </div>

        {/* Right: Preview of what will be searched */}
        <div className="flex-1 overflow-y-auto bg-[#1a1d23] p-6">
          <div className="max-w-lg mx-auto">
            <h3 className="text-base font-bold text-slate-100 mb-4">Search Preview</h3>
            <div className="bg-[#22252b] border border-[#2a2d35] rounded-xl p-5 space-y-3">
              <div className="flex items-center gap-2 text-sm">
                <span className="text-slate-500 w-32">Website:</span>
                <span className="font-mono text-xs text-primary">
                  {fields.state.value === "TX"
                    ? "tabcaims.elicense365.com"
                    : fields.state.value === "FL"
                    ? "myfloridalicense.com"
                    : "dor.georgia.gov"}
                </span>
              </div>
              <hr className="border-[#2a2d35]" />
              {[
                { label: "Type", value: BUSINESS_TYPE },
                { label: "License #", value: fields.license_number.value },
                { label: "Doing Business As", value: fields.doing_business_as.value },
                { label: "Legal Name", value: fields.legal_name.value },
                { label: "License Type", value: fields.license_type.value },
                { label: "Expiration", value: fields.expiration_date.value },
                { label: "Address", value: fields.address.value },
                { label: "City", value: fields.city.value },
                { label: "State", value: fields.state.value },
              ].map((row) => (
                <div key={row.label} className="flex items-start gap-2 text-sm">
                  <span className="text-slate-500 w-32 flex-shrink-0">{row.label}:</span>
                  <span className="font-medium text-slate-200">{row.value || "—"}</span>
                </div>
              ))}
            </div>

            <div className="mt-6 p-4 bg-blue-500/10 border border-blue-500/30 rounded-xl">
              <div className="flex items-start gap-2">
                <span className="material-symbols-outlined text-[18px] text-blue-400 mt-0.5">info</span>
                <div className="text-xs text-blue-300">
                  <strong>How it works:</strong> Clicking "Run Verification" will cascade
                  through verification methods. Method 1 sends direct HTTP requests.
                  Method 2 uses browser automation via Playwright.
                  Method 3 uses a Gemini AI agent to visually browse the state website.
                  The cascade stops at the first successful verification.
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // Render: Verify Step — defense cascade progress + results
  // -------------------------------------------------------------------------
  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Left: Fields summary (read-only) */}
      <div className="w-[380px] flex-shrink-0 border-r border-[#2a2d35] bg-[#22252b] p-6 overflow-y-auto">
        <div className="flex items-center gap-2 mb-4">
          <button
            onClick={() => { setCurrentView("review"); setProcessing(false); abortRef.current?.abort(); }}
            disabled={processing}
            className="text-slate-500 hover:text-slate-300 transition-colors disabled:opacity-30"
          >
            <span className="material-symbols-outlined text-[20px]">arrow_back</span>
          </button>
          <h3 className="text-base font-bold text-slate-100">Verification</h3>
        </div>

        {/* Compact field summary */}
        <div className="bg-[#1a1d23] border border-[#2a2d35] rounded-xl p-4 space-y-2 text-sm">
          {[
            { label: "Type", value: BUSINESS_TYPE },
            { label: "License #", value: fields.license_number.value },
            { label: "Doing Business As", value: fields.doing_business_as.value },
            { label: "Address", value: fields.address.value },
            { label: "City, State", value: `${fields.city.value}, ${fields.state.value}` },
          ].map((row) => (
            <div key={row.label} className="flex gap-2">
              <span className="text-slate-500 w-24 flex-shrink-0 text-xs">{row.label}</span>
              <span className="text-slate-300 font-medium text-xs">{row.value}</span>
            </div>
          ))}
        </div>

        {/* New search button */}
        {!processing && finalResult && (
          <button
            onClick={handleBackToUpload}
            className="w-full mt-4 py-2.5 bg-[#2a2d35] text-slate-300 font-semibold text-sm rounded-lg hover:bg-[#33363e] transition-colors flex items-center justify-center gap-2"
          >
            <span className="material-symbols-outlined text-[18px]">restart_alt</span>
            New Verification
          </button>
        )}
      </div>

      {/* Right: Defense cascade flow + results */}
      <div className="flex-1 overflow-y-auto bg-[#1a1d23] p-6">
        <div className="max-w-2xl mx-auto">
          <h3 className="text-base font-bold text-slate-100 mb-6">Verification Methods</h3>

          <div className="space-y-0">
            {steps.map((step, idx) => {
              const cfg = STATUS_CONFIG[step.status];
              return (
                <div key={step.line}>
                  {/* Step card */}
                  <div
                    className={`relative border rounded-xl p-5 transition-all duration-300 ${cfg.bg} ${cfg.border} ${step.status === "running" ? "shadow-md shadow-blue-500/10" : ""}`}
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-3">
                        <div
                          className="flex items-center justify-center w-10 h-10 rounded-lg bg-[#2a2d35] border border-[#3a3d45]"
                        >
                          <span className={`material-symbols-outlined text-[22px] ${cfg.color}`}>
                            {step.icon}
                          </span>
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className={`text-xs font-bold uppercase tracking-wide ${cfg.color}`}>
                              {`Method ${step.line}`}
                            </span>
                          </div>
                          <h4 className="text-sm font-bold text-slate-200">{step.label}</h4>
                        </div>
                      </div>
                      <span
                        className={`material-symbols-outlined text-[24px] ${cfg.color} ${
                          step.status === "running" ? "animate-spin" : ""
                        }`}
                      >
                        {cfg.icon}
                      </span>
                    </div>
                    <p className="text-xs ml-[52px] text-slate-500">{step.description}</p>

                    {step.error && (
                      <div className="mt-3 ml-[52px] text-xs text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
                        {step.error}
                      </div>
                    )}

                    {step.status === "success" && step.result && (
                      <div className="mt-3 ml-[52px] text-xs bg-green-500/10 border border-green-500/30 rounded-lg px-3 py-2">
                        <span className="font-bold text-green-400">
                          Verified — {step.result.results?.length || 0} result(s) found
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Connector */}
                  {idx < steps.length - 1 && (
                    <div className="flex flex-col items-center py-1">
                      <div
                        className={`w-px h-4 ${
                          steps[idx + 1].status === "idle" || steps[idx + 1].status === "skipped"
                            ? "bg-[#2a2d35]"
                            : "bg-slate-500"
                        }`}
                      />
                      <span className="text-[10px] font-semibold text-slate-600">
                        {step.status === "failed" || step.status === "no_results"
                          ? "IF BLOCKED / FAILS"
                          : ""}
                      </span>
                      <div
                        className={`w-px h-4 ${
                          steps[idx + 1].status === "idle" || steps[idx + 1].status === "skipped"
                            ? "bg-[#2a2d35]"
                            : "bg-slate-500"
                        }`}
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Final result */}
          {finalResult && (
            <div className="mt-8">
              <div
                className={`p-4 rounded-xl border ${
                  finalResult.verified
                    ? "bg-green-500/10 border-green-500/30"
                    : "bg-amber-500/10 border-amber-500/30"
                }`}
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`material-symbols-outlined text-3xl ${
                      finalResult.verified ? "text-green-400" : "text-amber-400"
                    }`}
                  >
                    {finalResult.verified ? "task_alt" : "warning"}
                  </span>
                  <div>
                    <h3 className="text-base font-bold text-slate-100">
                      License {finalResult.license_number}:{" "}
                      {finalResult.verified ? "Verified" : "Not Verified"}
                    </h3>
                    <p className="text-xs text-slate-500">
                      State: {finalResult.state} | Method Used:{" "}
                      {finalResult.defense_line_used}
                    </p>
                  </div>
                </div>
              </div>

              {/* Structured JSON output */}
              <div className="mt-4 bg-[#15171c] rounded-xl p-4 overflow-x-auto border border-[#2a2d35]">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-slate-500 uppercase tracking-wide">
                    Structured Output
                  </span>
                  <button
                    onClick={() =>
                      navigator.clipboard.writeText(JSON.stringify(finalResult, null, 2))
                    }
                    className="text-xs text-slate-500 hover:text-slate-300 flex items-center gap-1 transition-colors"
                  >
                    <span className="material-symbols-outlined text-[14px]">content_copy</span>
                    Copy
                  </button>
                </div>
                <pre className="text-xs text-green-400 font-mono leading-relaxed whitespace-pre-wrap">
                  {JSON.stringify(finalResult, null, 2)}
                </pre>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SingleFilePanel;
