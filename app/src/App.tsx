import { useState } from "react";
import Header, { type AppMode } from "./components/Header";
import SingleFilePanel from "./components/SingleFilePanel";
import BatchList from "./components/BatchList";

function App() {
  const [mode, setMode] = useState<AppMode>("single");
  const [resetKey, setResetKey] = useState(0);

  const handleReset = () => {
    setMode("single");
    setResetKey((k) => k + 1);
  };

  return (
    <>
      <Header mode={mode} onModeChange={setMode} onReset={handleReset} />
      <main className="flex flex-1 overflow-hidden">
        {mode === "single" ? (
          <SingleFilePanel key={resetKey} />
        ) : (
          <BatchList key={resetKey} />
        )}
      </main>
    </>
  );
}

export default App;
