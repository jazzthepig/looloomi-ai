import { useEffect } from "react";

export default function BottomSheet({ isOpen, onClose, children }) {
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [isOpen]);

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: "fixed", inset: 0,
          background: "rgba(1,1,9,0.45)",
          backdropFilter: "blur(3px)",
          zIndex: 200,
          opacity: isOpen ? 1 : 0,
          pointerEvents: isOpen ? "auto" : "none",
          transition: "opacity 0.3s ease"
        }}
      />
      {/* Panel */}
      <div style={{
        position: "fixed",
        bottom: 0, left: 0, right: 0,
        height: "38vh",
        minHeight: "260px",
        maxHeight: "420px",
        background: "rgba(8,8,22,0.97)",
        border: "1px solid rgba(6,182,212,0.15)",
        borderBottom: "none",
        borderRadius: "16px 16px 0 0",
        boxShadow: "0 -20px 60px rgba(6,182,212,0.08), 0 -1px 0 rgba(6,182,212,0.1)",
        zIndex: 201,
        transform: isOpen ? "translateY(0)" : "translateY(100%)",
        transition: "transform 0.35s cubic-bezier(0.32, 0.72, 0, 1)",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column"
      }}>
        {/* Handle bar */}
        <div style={{
          width: "40px", height: "4px",
          background: "rgba(255,255,255,0.12)",
          borderRadius: "2px",
          margin: "12px auto 0",
          flexShrink: 0
        }} />
        {/* Close button */}
        <button
          onClick={onClose}
          style={{
            position: "absolute", top: "16px", right: "20px",
            background: "transparent",
            border: "1px solid rgba(255,255,255,0.08)",
            color: "#64748b", width: "28px", height: "28px",
            borderRadius: "6px", cursor: "pointer",
            fontSize: "14px", display: "flex",
            alignItems: "center", justifyContent: "center"
          }}
        >×</button>
        {/* Scrollable content */}
        <div style={{
          flex: 1, overflowY: "auto",
          padding: "12px 32px 24px",
        }}>
          {children}
        </div>
      </div>

      {/* Responsive styles injected into page */}
      <style>{`
        @media (max-width: 768px) {
          div[style*="position: fixed"][style*="bottom: 0"] {
            height: 52vh !important;
            min-height: 280px !important;
            max-height: 60vh !important;
            border-radius: 12px 12px 0 0 !important;
          }
          div[style*="position: fixed"][style*="bottom: 0"] > div:last-child {
            padding: 10px 20px 20px !important;
          }
          div[style*="position: fixed"][style*="bottom: 0"] > div:last-child > div {
            grid-template-columns: repeat(2, 1fr) !important;
            gap: 10px !important;
          }
          div[style*="position: fixed"][style*="bottom: 0"] > div:last-child h3 {
            font-size: 16px !important;
          }
          div[style*="position: fixed"][style*="bottom: 0"] > div:last-child > div > div {
            font-size: 14px !important;
          }
        }

        @media (min-width: 769px) and (max-width: 1024px) {
          div[style*="position: fixed"][style*="bottom: 0"] {
            height: 42vh !important;
            max-height: 50vh !important;
          }
        }

        @media (min-width: 1400px) {
          div[style*="position: fixed"][style*="bottom: 0"] > div:last-child {
            padding: 16px 48px 28px !important;
          }
        }
      `}</style>
    </>
  );
}
