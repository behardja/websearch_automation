export interface LicenseResult {
  label_id?: string;
  product_name?: string;
  product_type?: string;
  alcohol_by_volume?: string;
  date_registered?: string;
  ttb_cola_number?: string;
  license_id?: string;
  lic_dba?: string;
}

export interface VerificationResult {
  license_number: string;
  verified: boolean;
  defense_line_used: number;
  results: LicenseResult[];
  error?: string;
}

const DEFENSE_LABELS: Record<number, string> = {
  1: "1st Line — HTTP Direct",
  2: "2nd Line — Playwright Scraper",
  3: "3rd Line — Gemini Computer Use Agent",
};

interface ResultsPanelProps {
  result: VerificationResult | null;
  loading: boolean;
}

const ResultsPanel: React.FC<ResultsPanelProps> = ({ result, loading }) => {
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-400">
        <span className="material-symbols-outlined text-5xl mb-3 animate-spin">progress_activity</span>
        <p className="text-sm font-semibold">Verifying license...</p>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-400">
        <span className="material-symbols-outlined text-5xl mb-3">policy</span>
        <p className="text-sm">Enter a license number and click Verify</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Status banner */}
      <div
        className={`p-4 rounded-lg border ${
          result.verified
            ? "bg-green-50 border-green-200"
            : "bg-amber-50 border-amber-200"
        }`}
      >
        <div className="flex items-center gap-3">
          <span
            className={`material-symbols-outlined text-3xl ${
              result.verified ? "text-green-600" : "text-amber-600"
            }`}
          >
            {result.verified ? "verified" : "warning"}
          </span>
          <div>
            <h3 className="text-lg font-bold text-slate-900">
              License {result.license_number}:{" "}
              {result.verified ? "Verified" : "Not Found"}
            </h3>
            <p className="text-sm text-slate-600">
              Defense line used: {DEFENSE_LABELS[result.defense_line_used]}
            </p>
          </div>
        </div>
      </div>

      {result.error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
          <strong>Error:</strong> {result.error}
        </div>
      )}

      {/* Results table */}
      {result.results.length > 0 && (
        <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-200 bg-slate-50">
            <h4 className="text-sm font-bold text-slate-700">
              {result.results.length} Result{result.results.length !== 1 ? "s" : ""} Found
            </h4>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 text-left">
                  <th className="px-4 py-2 font-semibold text-slate-600">Label ID</th>
                  <th className="px-4 py-2 font-semibold text-slate-600">Product Name</th>
                  <th className="px-4 py-2 font-semibold text-slate-600">Product Type</th>
                  <th className="px-4 py-2 font-semibold text-slate-600">ABV</th>
                  <th className="px-4 py-2 font-semibold text-slate-600">Date Registered</th>
                  <th className="px-4 py-2 font-semibold text-slate-600">TTB Cola #</th>
                  <th className="px-4 py-2 font-semibold text-slate-600">License ID</th>
                </tr>
              </thead>
              <tbody>
                {result.results.map((r, idx) => (
                  <tr key={idx} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-2 font-mono">{r.label_id || "—"}</td>
                    <td className="px-4 py-2">{r.product_name || "—"}</td>
                    <td className="px-4 py-2">{r.product_type || "—"}</td>
                    <td className="px-4 py-2">{r.alcohol_by_volume || "—"}</td>
                    <td className="px-4 py-2">{r.date_registered || "—"}</td>
                    <td className="px-4 py-2 font-mono">{r.ttb_cola_number || "—"}</td>
                    <td className="px-4 py-2 font-mono">{r.license_id || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

export default ResultsPanel;
