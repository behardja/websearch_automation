import { useState, useRef, useEffect } from "react";

export type AppMode = "single" | "batch";

interface HeaderProps {
  mode: AppMode;
  onModeChange: (mode: AppMode) => void;
  onReset: () => void;
}

const Header: React.FC<HeaderProps> = ({ mode, onModeChange, onReset }) => {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const modeLabel = mode === "single" ? "Single File Mode" : "Batch Mode";
  const modeIcon = mode === "single" ? "upload_file" : "checklist";

  return (
    <header className="flex items-center justify-between whitespace-nowrap border-b border-[#2a2d35] px-6 py-3 bg-[#22252b] flex-shrink-0 z-20">
      <div className="flex items-center gap-4">
        <button
          onClick={onReset}
          className="size-8 flex items-center justify-center text-primary hover:text-blue-400 transition-colors"
          title="Reset to home"
        >
          <span className="material-symbols-outlined text-3xl">verified</span>
        </button>
        <h2 className="text-slate-100 text-lg font-bold leading-tight tracking-[-0.015em]">
          Alcohol License Verification
        </h2>
      </div>
      <div className="flex items-center gap-2">
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="flex items-center justify-between min-w-[170px] h-9 px-3 rounded-lg bg-[#2a2d35] text-slate-200 text-sm font-bold border border-[#3a3d45] hover:border-slate-500 transition-all"
          >
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-[20px] text-primary">{modeIcon}</span>
              <span>{modeLabel}</span>
            </div>
            <span className="material-symbols-outlined text-[18px] text-slate-400">expand_more</span>
          </button>
          {dropdownOpen && (
            <div className="absolute right-0 mt-1 w-52 bg-[#2a2d35] rounded-lg shadow-lg border border-[#3a3d45] z-50 overflow-hidden">
              <button
                onClick={() => { onModeChange("single"); setDropdownOpen(false); }}
                className={`w-full flex items-center gap-2 px-4 py-2.5 text-sm text-left hover:bg-[#33363e] transition-colors ${
                  mode === "single" ? "text-primary font-bold" : "text-slate-300"
                }`}
              >
                <span className="material-symbols-outlined text-[18px]">upload_file</span>
                Single File Mode
                {mode === "single" && (
                  <span className="material-symbols-outlined text-[16px] ml-auto">check</span>
                )}
              </button>
              <button
                onClick={() => { onModeChange("batch"); setDropdownOpen(false); }}
                className={`w-full flex items-center gap-2 px-4 py-2.5 text-sm text-left hover:bg-[#33363e] transition-colors ${
                  mode === "batch" ? "text-primary font-bold" : "text-slate-300"
                }`}
              >
                <span className="material-symbols-outlined text-[18px]">checklist</span>
                Batch Mode
                {mode === "batch" && (
                  <span className="material-symbols-outlined text-[16px] ml-auto">check</span>
                )}
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};

export default Header;
