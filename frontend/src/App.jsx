import { useState, useEffect, useRef, useCallback } from 'react'
import {
  LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer,
} from 'recharts'

const API = 'http://localhost:8000'

// ─── Threshold constants (mirrors alert_engine.py) ───────────────────────────
const SPREAD_THRESHOLD    = 0.01
const IMBALANCE_THRESHOLD = 0.1
const VOL_THRESHOLD       = 100
const LIQUIDITY_THRESHOLD = -5.0

// ─── Palette ─────────────────────────────────────────────────────────────────
const C = {
  bg:        '#0a0c12',
  surface:   '#111420',
  card:      '#161926',
  border:    '#1f2438',
  accent:    '#6366f1',
  accentDim: '#3d3f7a',
  text:      '#e2e8f0',
  muted:     '#64748b',
  dimmer:    '#334155',
  green:     '#22c55e',
  red:       '#ef4444',
  amber:     '#f59e0b',
  cyan:      '#06b6d4',
  violet:    '#a78bfa',
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
const toHMS = iso => {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toTimeString().slice(0, 8)
}

const toDate = iso => {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

const fmt    = (v, d = 4) => v == null ? '—' : Number(v).toFixed(d)
const fmtInt = v => v == null ? '—' : Math.round(v).toLocaleString()

// ─── useDebounce ──────────────────────────────────────────────────────────────
function useDebounce(value, ms = 300) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}

// ─── Custom Tooltip ───────────────────────────────────────────────────────────
const ChartTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: C.surface, border: `1px solid ${C.border}`,
      padding: '8px 12px', borderRadius: 4,
      fontFamily: "'IBM Plex Mono', monospace", fontSize: 11,
    }}>
      <div style={{ color: C.muted, marginBottom: 4 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color || C.text }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(4) : p.value}
        </div>
      ))}
    </div>
  )
}

// ─── StatCard ─────────────────────────────────────────────────────────────────
function StatCard({ label, value, color }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 6, padding: '10px 14px', flex: 1, minWidth: 0,
    }}>
      <div style={{
        color: C.muted, fontSize: 10,
        textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4,
      }}>
        {label}
      </div>
      <div style={{
        fontFamily: "'IBM Plex Mono', monospace",
        fontSize: 18, fontWeight: 600,
        color: color || C.text,
      }}>
        {value}
      </div>
    </div>
  )
}

// ─── MiniChart wrapper ────────────────────────────────────────────────────────
function MiniChart({ title, children }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 6, padding: '14px 16px',
    }}>
      <div style={{
        color: C.muted, fontSize: 10,
        textTransform: 'uppercase', letterSpacing: '0.08em',
        marginBottom: 10,
      }}>
        {title}
      </div>
      <ResponsiveContainer width="100%" height={180}>
        {children}
      </ResponsiveContainer>
    </div>
  )
}

const axisStyle = { fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, fill: C.dimmer }
const gridProps = { stroke: C.border, strokeDasharray: '2 4' }

// ─── MarketDetail ─────────────────────────────────────────────────────────────
function MarketDetail({ ticker }) {
  const [meta, setMeta]         = useState(null)
  const [snapshots, setSnaps]   = useState([])
  const [loading, setLoading]   = useState(true)
  const [lastPoll, setLastPoll] = useState(null)

  const fetchSnaps = useCallback(async () => {
    try {
      const r = await fetch(`${API}/markets/${ticker}/snapshots?limit=300`)
      const d = await r.json()
      const rows = (d.snapshots || []).map(s => ({ ...s, _t: toHMS(s.snapshot_time) }))
      setSnaps(rows)
      setLastPoll(new Date().toTimeString().slice(0, 8))
    } catch {}
  }, [ticker])

  useEffect(() => {
    setLoading(true)
    setSnaps([])
    setMeta(null)
    Promise.all([
      fetch(`${API}/markets/${ticker}`).then(r => r.json()),
      fetchSnaps(),
    ]).then(([m]) => {
      setMeta(m)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [ticker, fetchSnaps])

  useEffect(() => {
    const id = setInterval(fetchSnaps, 30_000)
    return () => clearInterval(id)
  }, [fetchSnaps])

  if (loading) {
    return (
      <div style={{
        color: C.muted, fontFamily: "'IBM Plex Mono', monospace",
        fontSize: 13, padding: 40, textAlign: 'center',
      }}>
        loading {ticker}...
      </div>
    )
  }

  const latest = snapshots[snapshots.length - 1] || {}

  const resultBadge = meta?.result === true
    ? { label: 'YES',  bg: '#14532d', color: C.green }
    : meta?.result === false
      ? { label: 'NO',   bg: '#450a0a', color: C.red }
      : { label: 'OPEN', bg: C.accentDim, color: C.accent }

  return (
    <div>
      {/* Header */}
      <div style={{
        background: C.surface, border: `1px solid ${C.border}`,
        borderRadius: 8, padding: '18px 24px', marginBottom: 16,
        display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16,
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 20, fontWeight: 600, color: C.text, marginBottom: 6, lineHeight: 1.3 }}>
            {meta?.title || ticker}
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{
              fontFamily: "'IBM Plex Mono', monospace", fontSize: 11,
              background: C.accentDim, color: C.accent, padding: '2px 8px', borderRadius: 4,
            }}>
              {ticker}
            </span>
            <span style={{ color: C.muted, fontSize: 12 }}>closes {toDate(meta?.close_time)}</span>
            {lastPoll && (
              <span style={{ color: C.dimmer, fontSize: 11, fontFamily: "'IBM Plex Mono', monospace" }}>
                · polled {lastPoll}
              </span>
            )}
          </div>
        </div>
        <span style={{
          fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 700,
          background: resultBadge.bg, color: resultBadge.color,
          padding: '4px 12px', borderRadius: 4, whiteSpace: 'nowrap',
        }}>
          {resultBadge.label}
        </span>
      </div>

      {/* Stats */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
        <StatCard label="Price"        value={fmt(latest.last_price, 3)} color={C.accent} />
        <StatCard label="Spread"       value={fmt(latest.spread, 4)}
          color={latest.spread > SPREAD_THRESHOLD ? C.amber : C.text} />
        <StatCard label="Imbalance"    value={fmt(latest.imbalance, 4)}
          color={Math.abs(latest.imbalance || 0) > IMBALANCE_THRESHOLD ? C.amber : C.text} />
        <StatCard label="Momentum"     value={fmt(latest.momentum, 4)}
          color={latest.momentum > 0 ? C.green : latest.momentum < 0 ? C.red : C.text} />
        <StatCard label="Liquidity"    value={fmt(latest.liquidity, 2)}
          color={(latest.liquidity || 0) <= LIQUIDITY_THRESHOLD ? C.red : C.text} />
        <StatCard label="Open Interest" value={fmtInt(latest.open_interest)} />
      </div>

      {/* Charts */}
      {snapshots.length === 0 ? (
        <div style={{
          color: C.muted, textAlign: 'center', padding: 40,
          fontFamily: "'IBM Plex Mono', monospace", fontSize: 12,
          background: C.card, border: `1px solid ${C.border}`, borderRadius: 6,
        }}>
          no snapshots yet — waiting for data
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>

          <MiniChart title="Price">
            <LineChart data={snapshots}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="_t" tick={axisStyle} tickLine={false} axisLine={false} interval="preserveStartEnd" />
              <YAxis tick={axisStyle} tickLine={false} axisLine={false} width={48} tickFormatter={v => v.toFixed(3)} />
              <Tooltip content={<ChartTooltip />} />
              <Line type="monotone" dataKey="last_price" stroke={C.accent} dot={false} strokeWidth={1.5} name="price" />
              <Line type="monotone" dataKey="yes_bid"    stroke={C.green}  dot={false} strokeWidth={1}   name="bid"   strokeDasharray="3 2" />
              <Line type="monotone" dataKey="yes_ask"    stroke={C.red}    dot={false} strokeWidth={1}   name="ask"   strokeDasharray="3 2" />
            </LineChart>
          </MiniChart>

          <MiniChart title="Spread">
            <LineChart data={snapshots}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="_t" tick={axisStyle} tickLine={false} axisLine={false} interval="preserveStartEnd" />
              <YAxis tick={axisStyle} tickLine={false} axisLine={false} width={48} tickFormatter={v => v.toFixed(3)} />
              <Tooltip content={<ChartTooltip />} />
              <ReferenceLine y={SPREAD_THRESHOLD} stroke={C.amber} strokeDasharray="4 3" strokeWidth={1}
                label={{ value: 'thresh', fill: C.amber, fontSize: 9, fontFamily: 'IBM Plex Mono' }} />
              <Line type="monotone" dataKey="spread" stroke={C.cyan} dot={false} strokeWidth={1.5} name="spread" />
            </LineChart>
          </MiniChart>

          <MiniChart title="Imbalance">
            <LineChart data={snapshots}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="_t" tick={axisStyle} tickLine={false} axisLine={false} interval="preserveStartEnd" />
              <YAxis tick={axisStyle} tickLine={false} axisLine={false} width={48} tickFormatter={v => v.toFixed(2)} />
              <Tooltip content={<ChartTooltip />} />
              <ReferenceLine y={0}                    stroke={C.dimmer} strokeDasharray="2 4" strokeWidth={1} />
              <ReferenceLine y={ IMBALANCE_THRESHOLD} stroke={C.amber}  strokeDasharray="4 3" strokeWidth={1} />
              <ReferenceLine y={-IMBALANCE_THRESHOLD} stroke={C.amber}  strokeDasharray="4 3" strokeWidth={1} />
              <Line type="monotone" dataKey="imbalance" stroke={C.violet} dot={false} strokeWidth={1.5} name="imbalance" />
            </LineChart>
          </MiniChart>

          <MiniChart title="Momentum">
            <LineChart data={snapshots}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="_t" tick={axisStyle} tickLine={false} axisLine={false} interval="preserveStartEnd" />
              <YAxis tick={axisStyle} tickLine={false} axisLine={false} width={48} tickFormatter={v => v.toFixed(3)} />
              <Tooltip content={<ChartTooltip />} />
              <ReferenceLine y={0} stroke={C.dimmer} strokeDasharray="2 4" strokeWidth={1} />
              <Line type="monotone" dataKey="momentum" stroke={C.accent} dot={false} strokeWidth={1.5} name="momentum" />
            </LineChart>
          </MiniChart>

          <MiniChart title="Volume (10s)">
            <BarChart data={snapshots}>
              <CartesianGrid {...gridProps} vertical={false} />
              <XAxis dataKey="_t" tick={axisStyle} tickLine={false} axisLine={false} interval="preserveStartEnd" />
              <YAxis tick={axisStyle} tickLine={false} axisLine={false} width={40} />
              <Tooltip content={<ChartTooltip />} />
              <ReferenceLine y={VOL_THRESHOLD} stroke={C.red} strokeDasharray="4 3" strokeWidth={1}
                label={{ value: 'thresh', fill: C.red, fontSize: 9, fontFamily: 'IBM Plex Mono' }} />
              <Bar dataKey="volume_10s" fill={C.accentDim} name="vol_10s" maxBarSize={6} />
            </BarChart>
          </MiniChart>

          <MiniChart title="Liquidity">
            <LineChart data={snapshots}>
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="_t" tick={axisStyle} tickLine={false} axisLine={false} interval="preserveStartEnd" />
              <YAxis tick={axisStyle} tickLine={false} axisLine={false} width={48} tickFormatter={v => v.toFixed(1)} />
              <Tooltip content={<ChartTooltip />} />
              <ReferenceLine y={LIQUIDITY_THRESHOLD} stroke={C.red} strokeDasharray="4 3" strokeWidth={1}
                label={{ value: 'drain', fill: C.red, fontSize: 9, fontFamily: 'IBM Plex Mono' }} />
              <Line type="monotone" dataKey="liquidity" stroke={C.green} dot={false} strokeWidth={1.5} name="liquidity" />
            </LineChart>
          </MiniChart>

        </div>
      )}
    </div>
  )
}

// ─── App ──────────────────────────────────────────────────────────────────────
export default function App() {
  const [query, setQuery]           = useState('')
  const [results, setResults]       = useState([])
  const [searching, setSearching]   = useState(false)
  const [dropdownOpen, setDropdown] = useState(false)
  const [selected, setSelected]     = useState(null)
  const inputRef = useRef(null)
  const wrapRef  = useRef(null)

  const debounced = useDebounce(query, 300)

  useEffect(() => {
    if (!debounced.trim()) { setResults([]); setDropdown(false); return }
    setSearching(true)
    fetch(`${API}/markets/search?q=${encodeURIComponent(debounced)}`)
      .then(r => r.json())
      .then(d => { setResults(d.markets || []); setDropdown(true) })
      .catch(() => setResults([]))
      .finally(() => setSearching(false))
  }, [debounced])

  useEffect(() => {
    const handler = e => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setDropdown(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const pick = market => {
    setSelected(market.ticker)
    setQuery(market.title)
    setDropdown(false)
  }

  return (
    <div style={{ minHeight: '100vh', background: C.bg, color: C.text, fontFamily: "'DM Sans', sans-serif" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;600&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: ${C.bg}; }
        ::-webkit-scrollbar-thumb { background: ${C.border}; border-radius: 2px; }
        input::placeholder { color: ${C.dimmer}; }
      `}</style>

      {/* Topbar */}
      <div style={{
        borderBottom: `1px solid ${C.border}`, padding: '0 32px',
        display: 'flex', alignItems: 'center', height: 52, gap: 16,
        background: C.surface,
      }}>
        <span style={{
          fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, fontWeight: 600,
          color: C.accent, letterSpacing: '0.04em',
        }}>
          BETMUSE
        </span>
        <span style={{ color: C.border }}>|</span>
        <span style={{ color: C.muted, fontSize: 12 }}>prediction market analytics</span>
      </div>

      {/* Main */}
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '32px 24px' }}>

        {/* Search */}
        <div ref={wrapRef} style={{ position: 'relative', marginBottom: 28 }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10,
            background: C.surface, border: `1px solid ${dropdownOpen ? C.accentDim : C.border}`,
            borderRadius: dropdownOpen && results.length ? '6px 6px 0 0' : 6,
            padding: '10px 16px', transition: 'border-color 0.15s',
          }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={C.muted} strokeWidth="2">
              <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
            </svg>
            <input
              ref={inputRef}
              value={query}
              onChange={e => { setQuery(e.target.value); setSelected(null) }}
              onFocus={() => results.length && setDropdown(true)}
              placeholder="Search markets by name..."
              style={{
                flex: 1, background: 'transparent', border: 'none', outline: 'none',
                color: C.text, fontSize: 14, fontFamily: "'DM Sans', sans-serif",
              }}
            />
            {searching && (
              <span style={{ color: C.muted, fontSize: 11, fontFamily: "'IBM Plex Mono', monospace" }}>
                searching...
              </span>
            )}
            {query && (
              <button
                onClick={() => { setQuery(''); setSelected(null); setResults([]); setDropdown(false) }}
                style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  color: C.dimmer, padding: 0, lineHeight: 1, fontSize: 14,
                }}
              >
                ✕
              </button>
            )}
          </div>

          {/* Dropdown results */}
          {dropdownOpen && results.length > 0 && (
            <div style={{
              position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 100,
              background: C.surface, border: `1px solid ${C.accentDim}`,
              borderTop: `1px solid ${C.border}`, borderRadius: '0 0 6px 6px',
              maxHeight: 320, overflowY: 'auto',
            }}>
              {results.map((m, i) => (
                <div
                  key={m.ticker}
                  onClick={() => pick(m)}
                  style={{
                    padding: '10px 16px', cursor: 'pointer',
                    borderTop: i > 0 ? `1px solid ${C.border}` : 'none',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12,
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = C.card}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <span style={{
                    fontSize: 13, color: C.text, flex: 1, minWidth: 0,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {m.title}
                  </span>
                  <span style={{
                    fontFamily: "'IBM Plex Mono', monospace", fontSize: 10,
                    color: C.accent, background: C.accentDim,
                    padding: '2px 6px', borderRadius: 3, flexShrink: 0,
                  }}>
                    {m.ticker}
                  </span>
                </div>
              ))}
              <div style={{
                padding: '6px 16px', borderTop: `1px solid ${C.border}`,
                color: C.dimmer, fontSize: 10, fontFamily: "'IBM Plex Mono', monospace",
              }}>
                {results.length} result{results.length !== 1 ? 's' : ''} · only active markets shown
              </div>
            </div>
          )}

          {dropdownOpen && results.length === 0 && !searching && query.trim() && (
            <div style={{
              position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 100,
              background: C.surface, border: `1px solid ${C.border}`,
              borderTop: 'none', borderRadius: '0 0 6px 6px',
              padding: '12px 16px', color: C.muted, fontSize: 13,
            }}>
              no markets found
            </div>
          )}
        </div>

        {/* Detail or placeholder */}
        {selected
          ? <MarketDetail key={selected} ticker={selected} />
          : (
            <div style={{
              textAlign: 'center', padding: '80px 24px',
              color: C.dimmer, fontFamily: "'IBM Plex Mono', monospace", fontSize: 13,
            }}>
              search for a market above to view analytics
            </div>
          )
        }
      </div>
    </div>
  )
}
