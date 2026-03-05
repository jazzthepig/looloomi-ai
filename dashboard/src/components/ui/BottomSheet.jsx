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
          background: "rgba(1,1,9,0.20)",
          backdropFilter: "blur(1px)",
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
            height: 50vh !important;
            min-height: 280px !important;
            max-height: 60vh !important;
            border-radius: 12px 12px 0 0 !important;
          }
          div[style*="position: fixed"][style*="bottom: 0"] > div:last-child {
            padding: 6px 12px 12px !important;
          }
          /* Reduce spacing between elements */
          div[style*="position: fixed"][style*="bottom: 0"] > div:last-child > div {
            gap: 4px !important;
            margin-bottom: 4px !important;
            padding-bottom: 4px !important;
          }
          /* Keep fonts readable, reduce line-height instead */
          div[style*="position: fixed"][style*="bottom: 0"] > div:last-child h3 {
            font-size: 15px !important;
            margin-bottom: 2px !important;
          }
          div[style*="position: fixed"][style*="bottom: 0"] > div:last-child > div > div {
            font-size: 12px !important;
            line-height: 1.2 !important;
          }
          /* Grid layouts - compact */
          div[style*="position: fixed"][style*="bottom: 0"] > div:last-child > div[style*="grid"] {
            gap: 4px !important;
          }
          div[style*="position: fixed"][style*="bottom: 0"] > div:last-child > div[style*="repeat(4"] {
            grid-template-columns: repeat(2, 1fr) !important;
          }
          div[style*="position: fixed"][style*="bottom: 0"] > div:last-child > div[style*="repeat(5"] {
            grid-template-columns: repeat(3, 1fr) !important;
          }
        }

        @media (max-width: 480px) {
          div[style*="position: fixed"][style*="bottom: 0"] {
            height: 55vh !important;
            max-height: 65vh !important;
          }
        }

        @media (min-width: 769px) and (max-width: 1024px) {
          div[style*="position: fixed"][style*="bottom: 0"] {
            height: 38vh !important;
            max-height: 45vh !important;
          }
        }

        @media (min-width: 1400px) {
          div[style*="position: fixed"][style*="bottom: 0"] > div:last-child {
            padding: 14px 48px 26px !important;
          }
        }
      `}</style>
    </>
  );
}
