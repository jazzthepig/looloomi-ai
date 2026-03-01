import { useState } from "react";
import MarketDashboard from "./components/MarketDashboard";
import IntelligencePage from "./components/IntelligencePage";

export default function App() {
  const [activeTab, setActiveTab] = useState("Market");

  return (
    <>
      {activeTab === "Market" && (
        <MarketDashboard activeTab={activeTab} setActiveTab={setActiveTab} />
      )}
      {(activeTab === "Intelligence" || activeTab === "Quant GP") && (
        <IntelligencePage activeTab={activeTab} setActiveTab={setActiveTab} />
      )}
    </>
  );
}
