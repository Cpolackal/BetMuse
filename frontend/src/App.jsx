import React, { useState } from "react";
import { API_BASE_URL } from "./config";

function App() {
  const [health, setHealth] = useState(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState(null);

  const [markets, setMarkets] = useState(null);
  const [marketsLoading, setMarketsLoading] = useState(false);
  const [marketsError, setMarketsError] = useState(null);
  const [limit, setLimit] = useState(100);
  const [cursor, setCursor] = useState("");

  const callHealth = async () => {
    setHealthLoading(true);
    setHealthError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/health`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      setHealth(JSON.stringify(data, null, 2));
    } catch (err) {
      setHealthError(err.message ?? "Unknown error");
    } finally {
      setHealthLoading(false);
    }
  };

  const callMarkets = async () => {
    setMarketsLoading(true);
    setMarketsError(null);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(limit));
      if (cursor.trim()) {
        params.set("cursor", cursor.trim());
      }

      const res = await fetch(`${API_BASE_URL}/markets`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      // adjust if your response shape is { items: [...] }
      setMarkets(Array.isArray(data) ? data : data.items ?? []);
    } catch (err) {
      setMarketsError(err.message ?? "Unknown error");
    } finally {
      setMarketsLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
        backgroundColor: "#0f172a",
        color: "#e5e7eb",
        padding: "24px",
        boxSizing: "border-box",
      }}
    >
      <div
        style={{
          maxWidth: "960px",
          margin: "0 auto",
        }}
      >
        <h1 style={{ fontSize: "28px", marginBottom: "8px" }}>BetMuse API Console</h1>
        <p style={{ marginBottom: "24px", color: "#9ca3af" }}>
          Very bare-bones UI to hit your FastAPI endpoints.
        </p>

        {/* Health section */}
        <section
          style={{
            marginBottom: "24px",
            padding: "16px",
            borderRadius: "8px",
            backgroundColor: "#020617",
            border: "1px solid #1f2937",
          }}
        >
          <h2 style={{ fontSize: "20px", marginBottom: "12px" }}>Health Check</h2>
          <button
            onClick={callHealth}
            disabled={healthLoading}
            style={{
              padding: "8px 12px",
              borderRadius: "6px",
              border: "none",
              backgroundColor: "#22c55e",
              color: "#020617",
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            {healthLoading ? "Checking..." : "GET /health"}
          </button>
          {healthError && (
            <div style={{ marginTop: "12px", color: "#f97316" }}>
              Error: {healthError}
            </div>
          )}
          {health && (
            <pre
              style={{
                marginTop: "12px",
                padding: "12px",
                borderRadius: "6px",
                backgroundColor: "#020617",
                border: "1px solid #1f2937",
                fontSize: "13px",
                overflowX: "auto",
              }}
            >
              {health}
            </pre>
          )}
        </section>

        {/* Markets section */}
        <section
          style={{
            marginBottom: "24px",
            padding: "16px",
            borderRadius: "8px",
            backgroundColor: "#020617",
            border: "1px solid #1f2937",
          }}
        >
          <h2 style={{ fontSize: "20px", marginBottom: "12px" }}>Markets</h2>

          <div style={{ display: "flex", gap: "12px", marginBottom: "12px", flexWrap: "wrap" }}>
            <label style={{ fontSize: "14px" }}>
              Limit:&nbsp;
              <input
                type="number"
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value) || 0)}
                style={{
                  padding: "4px 6px",
                  borderRadius: "4px",
                  border: "1px solid #4b5563",
                  backgroundColor: "#020617",
                  color: "#e5e7eb",
                  width: "80px",
                }}
              />
            </label>

            <label style={{ fontSize: "14px" }}>
              Cursor:&nbsp;
              <input
                type="text"
                value={cursor}
                onChange={(e) => setCursor(e.target.value)}
                style={{
                  padding: "4px 6px",
                  borderRadius: "4px",
                  border: "1px solid #4b5563",
                  backgroundColor: "#020617",
                  color: "#e5e7eb",
                  minWidth: "160px",
                }}
                placeholder="optional"
              />
            </label>

            <button
              onClick={callMarkets}
              disabled={marketsLoading}
              style={{
                padding: "8px 12px",
                borderRadius: "6px",
                border: "none",
                backgroundColor: "#3b82f6",
                color: "#e5e7eb",
                cursor: "pointer",
                fontWeight: 600,
                alignSelf: "flex-end",
              }}
            >
              {marketsLoading ? "Loading..." : "GET /markets"}
            </button>
          </div>

          {marketsError && (
            <div style={{ marginTop: "12px", color: "#f97316" }}>
              Error: {marketsError}
            </div>
          )}

          {markets && (
            <pre
              style={{
                marginTop: "12px",
                padding: "12px",
                borderRadius: "6px",
                backgroundColor: "#020617",
                border: "1px solid #1f2937",
                fontSize: "13px",
                maxHeight: "320px",
                overflow: "auto",
              }}
            >
              {JSON.stringify(markets, null, 2)}
            </pre>
          )}
        </section>

        <p style={{ fontSize: "12px", color: "#6b7280" }}>
          Adjust `API_BASE_URL` in `src/config.ts` and add more sections for new endpoints as needed.
        </p>
      </div>
    </div>
  );
}

export default App;