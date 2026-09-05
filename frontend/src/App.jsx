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
const MODEL_EDGE_THRESHOLD = 0.04

// ─── Palette ── court-at-dusk: deep grass-shadow ground, optic-ball accent ────
const C = {
  bg:        '#0a120e',
  surface:   '#101c16',
  card:      '#14211a',
  border:    '#22362a',
  accent:    '#d7f24a',
  accentDim: '#3c4a24',
  text:      '#eef2e9',
  muted:     '#7e9382',
  dimmer:    '#3d5245',
  green:     '#6fae4a',
  red:       '#c1502e',
  amber:     '#d9a441',
  cyan:      '#4a90c4',
  violet:    '#9b7fc7',
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

// ─── Tooltip ──────────────────────────────────────────────────────────────────
function HintTooltip({ text, children }) {
  const [visible, setVisible] = useState(false)
  const [pos, setPos] = useState({ top: 0, left: 0 })

  const onMove = (e) => setPos({ top: e.clientY + 14, left: e.clientX + 12 })

  return (
    <>
      <div onMouseEnter={() => setVisible(true)} onMouseLeave={() => setVisible(false)}
        onMouseMove={onMove} style={{ display: 'contents' }}>
        {children}
      </div>
      {visible && (
        <div style={{
          position: 'fixed', top: pos.top, left: pos.left, zIndex: 999,
          background: C.surface, border: `1px solid ${C.border}`,
          borderRadius: 5, padding: '8px 11px',
          maxWidth: 220, fontSize: 11, lineHeight: 1.5,
          color: C.muted, fontFamily: "'DM Sans', sans-serif",
          boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
          pointerEvents: 'none',
        }}>
          {text}
        </div>
      )}
    </>
  )
}

// ─── StatCard ─────────────────────────────────────────────────────────────────
function StatCard({ label, value, color, hint }) {
  const card = (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 6, padding: '10px 14px', flex: 1, minWidth: 0,
      cursor: hint ? 'default' : undefined,
    }}>
      <div style={{
        color: C.muted, fontSize: 10,
        textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4,
        display: 'flex', alignItems: 'center', gap: 4,
      }}>
        {label}
        {hint && (
          <span style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: 12, height: 12, borderRadius: '50%',
            border: `1px solid ${C.dimmer}`, color: C.dimmer,
            fontSize: 8, lineHeight: 1, flexShrink: 0,
          }}>?</span>
        )}
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

  return hint ? <HintTooltip text={hint}>{card}</HintTooltip> : card
}

// ─── MiniChart wrapper ────────────────────────────────────────────────────────
function MiniChart({ title, hint, children }) {
  const header = (
    <div style={{
      color: C.muted, fontSize: 10,
      textTransform: 'uppercase', letterSpacing: '0.08em',
      marginBottom: 10, display: 'flex', alignItems: 'center', gap: 4,
    }}>
      {title}
      {hint && (
        <span style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: 12, height: 12, borderRadius: '50%',
          border: `1px solid ${C.dimmer}`, color: C.dimmer,
          fontSize: 8, lineHeight: 1, flexShrink: 0,
        }}>?</span>
      )}
    </div>
  )
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 6, padding: '14px 16px',
    }}>
      {hint ? <HintTooltip text={hint}>{header}</HintTooltip> : header}
      <ResponsiveContainer width="100%" height={320}>
        {children}
      </ResponsiveContainer>
    </div>
  )
}

const axisStyle = { fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fill: C.dimmer }
const gridProps = { stroke: C.border, strokeDasharray: '2 4' }
const axisLabelStyle = { fontSize: 11, fill: C.muted, fontFamily: "'IBM Plex Mono', monospace" }
const chartMargin = { top: 8, right: 16, bottom: 18, left: 12 }
const xAxisProps = {
  dataKey: '_t', tick: axisStyle, tickLine: false, axisLine: false,
  interval: 'preserveStartEnd', minTickGap: 48,
  label: { value: 'time', position: 'insideBottom', offset: -12, ...axisLabelStyle },
}
const yAxisProps = label => ({
  tick: axisStyle, tickLine: false, axisLine: false, width: 64,
  label: { value: label, angle: -90, position: 'insideLeft', offset: 4, ...axisLabelStyle },
})
const fmtCompact = v =>
  Math.abs(v) >= 1_000_000 ? `${(v / 1_000_000).toFixed(1)}M`
    : Math.abs(v) >= 1_000 ? `${(v / 1_000).toFixed(0)}k`
      : `${v}`

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
    const id = setInterval(fetchSnaps, 5_000)
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

  // Old snapshots can have null values for series added later (e.g. liquidity).
  // Drop rows where a chart's series are all null so the data that does exist
  // fills the full chart width instead of a sliver at the right edge.
  const seriesFor = (...keys) => snapshots.filter(r => keys.some(k => r[k] != null))

  const resultBadge = meta?.result === true
    ? { label: 'YES',  bg: '#1c3320', color: C.green }
    : meta?.result === false
      ? { label: 'NO',   bg: '#3a1f16', color: C.red }
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

      {/* Alerts */}
      <MarketAlerts ticker={ticker} />

      {/* Live score */}
      <ScorePanel ticker={ticker} />

      {/* Stats */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
        <StatCard label="Price" value={fmt(latest.last_price, 3)} color={C.accent}
          hint="Last traded price in dollars. On Kalshi this represents the probability — $0.65 means the market implies a 65% chance of YES." />
        <StatCard label="Spread" value={fmt(latest.spread, 4)}
          color={latest.spread > SPREAD_THRESHOLD ? C.amber : C.text}
          hint="Difference between the best ask and best bid. A tight spread means high liquidity and low transaction cost. Amber when above the alert threshold." />
        <StatCard label="Imbalance" value={fmt(latest.imbalance, 4)}
          color={Math.abs(latest.imbalance || 0) > IMBALANCE_THRESHOLD ? C.amber : C.text}
          hint="Order book skew: (bid − ask) / (bid + ask). Positive means more buy-side pressure, negative means sell-side. Large values can precede price moves." />
        <StatCard label="Momentum" value={fmt(latest.momentum, 4)}
          color={latest.momentum > 0 ? C.green : latest.momentum < 0 ? C.red : C.text}
          hint="Short-term price velocity — difference between recent price and its 60-second moving average. Green = upward drift, red = downward drift." />
        <StatCard label="Liquidity" value={fmt(latest.liquidity, 2)}
          color={(latest.liquidity || 0) <= LIQUIDITY_THRESHOLD ? C.red : C.text}
          hint="Dollar value of open interest (contracts × price) — a proxy for market depth. Low or rapidly falling values mean capital is leaving the market, making large price moves easier to trigger." />
        <StatCard label="Open Interest" value={fmtInt(latest.open_interest)}
          hint="Total number of contracts currently held by market participants. Rising open interest alongside a price move confirms new money entering the position." />
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

          <MiniChart title="Price" hint="Last traded price in dollars. On Kalshi, price ≈ probability — $0.65 means the market implies a 65% chance of YES. Bid and ask dashes show the current best quotes. The amber line is the tennis win-probability model's fair price, when a live score is linked.">
            <LineChart data={seriesFor('last_price', 'yes_bid', 'yes_ask', 'model_price')} margin={chartMargin}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisProps('price ($)')} tickFormatter={v => v.toFixed(3)} />
              <Tooltip content={<ChartTooltip />} />
              <Line type="monotone" dataKey="last_price"  stroke={C.accent} dot={false} strokeWidth={1.5} name="price" />
              <Line type="monotone" dataKey="yes_bid"     stroke={C.green}  dot={false} strokeWidth={1}   name="bid"   strokeDasharray="3 2" />
              <Line type="monotone" dataKey="yes_ask"     stroke={C.red}    dot={false} strokeWidth={1}   name="ask"   strokeDasharray="3 2" />
              <Line type="monotone" dataKey="model_price" stroke={C.amber}  dot={false} strokeWidth={1.5} name="model" strokeDasharray="5 3" connectNulls />
            </LineChart>
          </MiniChart>

          <MiniChart title="Spread" hint="Ask minus bid. A narrow spread means tight liquidity and low transaction cost. The amber threshold line marks when the spread is wide enough to trigger an alert.">
            <LineChart data={seriesFor('spread')} margin={chartMargin}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisProps('spread ($)')} tickFormatter={v => v.toFixed(3)} />
              <Tooltip content={<ChartTooltip />} />
              <ReferenceLine y={SPREAD_THRESHOLD} stroke={C.amber} strokeDasharray="4 3" strokeWidth={1}
                label={{ value: 'thresh', fill: C.amber, fontSize: 9, fontFamily: 'IBM Plex Mono' }} />
              <Line type="monotone" dataKey="spread" stroke={C.cyan} dot={false} strokeWidth={1.5} name="spread" />
            </LineChart>
          </MiniChart>

          <MiniChart title="Imbalance" hint="Order book skew: (bid − ask) / (bid + ask). Positive means more buy pressure, negative means sell pressure. Crossing the amber thresholds can signal a coming price move.">
            <LineChart data={seriesFor('imbalance')} margin={chartMargin}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisProps('imbalance')} tickFormatter={v => v.toFixed(2)} />
              <Tooltip content={<ChartTooltip />} />
              <ReferenceLine y={0}                    stroke={C.dimmer} strokeDasharray="2 4" strokeWidth={1} />
              <ReferenceLine y={ IMBALANCE_THRESHOLD} stroke={C.amber}  strokeDasharray="4 3" strokeWidth={1} />
              <ReferenceLine y={-IMBALANCE_THRESHOLD} stroke={C.amber}  strokeDasharray="4 3" strokeWidth={1} />
              <Line type="monotone" dataKey="imbalance" stroke={C.violet} dot={false} strokeWidth={1.5} name="imbalance" />
            </LineChart>
          </MiniChart>

          <MiniChart title="Momentum" hint="Price change relative to 60 seconds ago. Positive means the market has drifted up recently; negative means it has drifted down. Near zero means the price is stable.">
            <LineChart data={seriesFor('momentum')} margin={chartMargin}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisProps('Δ price / 60s ($)')} tickFormatter={v => v.toFixed(3)} />
              <Tooltip content={<ChartTooltip />} />
              <ReferenceLine y={0} stroke={C.dimmer} strokeDasharray="2 4" strokeWidth={1} />
              <Line type="monotone" dataKey="momentum" stroke={C.accent} dot={false} strokeWidth={1.5} name="momentum" />
            </LineChart>
          </MiniChart>

          <MiniChart title="Volume (10s)" hint="Contracts traded in the last 10 seconds, computed from the cumulative Kalshi volume counter. Spikes above the red threshold line trigger a volume-spike alert.">
            <BarChart data={seriesFor('volume_10s')} margin={chartMargin}>
              <CartesianGrid {...gridProps} vertical={false} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisProps('contracts / 10s')} tickFormatter={fmtCompact} />
              <Tooltip content={<ChartTooltip />} />
              <ReferenceLine y={VOL_THRESHOLD} stroke={C.red} strokeDasharray="4 3" strokeWidth={1}
                label={{ value: 'thresh', fill: C.red, fontSize: 9, fontFamily: 'IBM Plex Mono' }} />
              <Bar dataKey="volume_10s" fill={C.accentDim} name="vol_10s" maxBarSize={6} />
            </BarChart>
          </MiniChart>

          <MiniChart title="Liquidity" hint="Dollar value of open interest (contracts × price) — a proxy for market depth when order book size isn't available. Falling values mean capital is leaving the market. Drops below the red line trigger a liquidity-drain alert.">
            <LineChart data={seriesFor('liquidity')} margin={chartMargin}>
              <CartesianGrid {...gridProps} />
              <XAxis {...xAxisProps} />
              <YAxis {...yAxisProps('open interest ($)')} tickFormatter={fmtCompact} />
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

// ─── Alert helpers ────────────────────────────────────────────────────────────
const ALERT_LABELS = {
  microprice: 'Microprice',
  volume:     'Volume Spike',
  imbalance:  'Imbalance',
  spread:     'Spread',
  liquidity:  'Liquidity',
}

const DIRECTION_COLOR = dir => {
  if (['up', 'buy', 'tightening'].includes(dir)) return C.green
  if (['down', 'sell', 'drain', 'widening'].includes(dir)) return C.red
  return C.muted
}

const fmtAlertValue = (type, value) => {
  const n = Number(value)
  if (type === 'volume') return `${n > 0 ? '+' : ''}${Math.round(n)}`
  return `${n > 0 ? '+' : ''}${n.toFixed(4)}`
}

const fmtAlertTime = ts => {
  const d = new Date(Number(ts) * 1000)
  return d.toTimeString().slice(0, 8)
}

// ─── MarketAlerts ─────────────────────────────────────────────────────────────
function MarketAlerts({ ticker }) {
  const [alerts, setAlerts] = useState([])
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    setAlerts([])
    const es = new EventSource(`${API}/alerts/stream?market=${encodeURIComponent(ticker)}`)
    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)
    es.onmessage = e => {
      try {
        const alert = JSON.parse(e.data)
        setAlerts(prev => [alert, ...prev].slice(0, 50))
      } catch {}
    }
    return () => es.close()
  }, [ticker])

  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 6, marginBottom: 16,
    }}>
      <div style={{
        padding: '10px 14px', borderBottom: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <span style={{
          fontFamily: "'IBM Plex Mono', monospace", fontSize: 10,
          textTransform: 'uppercase', letterSpacing: '0.08em', color: C.muted,
        }}>
          Signal Alerts
        </span>
        <span style={{
          width: 6, height: 6, borderRadius: '50%',
          background: connected ? C.green : C.dimmer,
          boxShadow: connected ? `0 0 5px ${C.green}` : 'none',
          transition: 'background 0.3s',
        }} />
      </div>

      {alerts.length === 0 ? (
        <div style={{
          padding: '14px 16px',
          color: C.dimmer, fontFamily: "'IBM Plex Mono', monospace", fontSize: 11,
        }}>
          listening for signals...
        </div>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, padding: '10px 14px' }}>
          {alerts.map((a, i) => {
            const col = DIRECTION_COLOR(a.direction)
            return (
              <div key={a.id || i} style={{
                background: C.surface, border: `1px solid ${col}33`,
                borderRadius: 5, padding: '6px 10px',
                display: 'flex', alignItems: 'center', gap: 8,
              }}>
                <span style={{
                  fontFamily: "'IBM Plex Mono', monospace", fontSize: 10,
                  fontWeight: 600, color: col,
                }}>
                  {ALERT_LABELS[a.type] || a.type}
                </span>
                <span style={{
                  fontSize: 10, color: col,
                  fontFamily: "'IBM Plex Mono', monospace",
                  background: col + '22', padding: '1px 5px', borderRadius: 3,
                }}>
                  {a.direction}
                </span>
                <span style={{
                  fontFamily: "'IBM Plex Mono', monospace", fontSize: 10,
                  color: col, fontWeight: 600,
                }}>
                  {fmtAlertValue(a.type, a.value)}
                </span>
                <span style={{
                  fontSize: 10, color: C.dimmer,
                  fontFamily: "'IBM Plex Mono', monospace",
                }}>
                  {fmtAlertTime(a.ts)}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─── Score helpers ────────────────────────────────────────────────────────────
const fmtEdge = v => v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(3)}`

// ─── ScorePanel ───────────────────────────────────────────────────────────────
function ScorePanel({ ticker }) {
  const [score, setScore] = useState(null)

  const fetchScore = useCallback(async () => {
    try {
      const r = await fetch(`${API}/markets/${ticker}/score`)
      setScore(await r.json())
    } catch {
      setScore(null)
    }
  }, [ticker])

  useEffect(() => {
    setScore(null)
    fetchScore()
    const id = setInterval(fetchScore, 5_000)
    return () => clearInterval(id)
  }, [fetchScore])

  const mapped = score?.mapped

  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 6, marginBottom: 16,
    }}>
      <div style={{
        padding: '10px 14px', borderBottom: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <span style={{
          fontFamily: "'IBM Plex Mono', monospace", fontSize: 10,
          textTransform: 'uppercase', letterSpacing: '0.08em', color: C.muted,
        }}>
          Live Score
        </span>
        <span style={{
          width: 6, height: 6, borderRadius: '50%',
          background: mapped ? C.green : C.dimmer,
          boxShadow: mapped ? `0 0 5px ${C.green}` : 'none',
          transition: 'background 0.3s',
        }} />
        {mapped && (
          <span style={{ color: C.dimmer, fontSize: 11, fontFamily: "'IBM Plex Mono', monospace" }}>
            {score.tournament}
          </span>
        )}
      </div>

      {!mapped ? (
        <div style={{
          padding: '14px 16px',
          color: C.dimmer, fontFamily: "'IBM Plex Mono', monospace", fontSize: 11,
        }}>
          no live match linked — this market isn't mapped to a live tennis score
        </div>
      ) : (
        <div style={{ padding: '14px 16px' }}>
          {/* Players + serve indicator */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
            {[
              { name: score.home, side: 1 },
              { name: score.away, side: 2 },
            ].map(p => (
              <div key={p.side} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  width: 6, height: 6, borderRadius: '50%',
                  background: score.serving === p.side ? C.accent : 'transparent',
                  boxShadow: score.serving === p.side ? `0 0 5px ${C.accent}` : 'none',
                  flexShrink: 0,
                }} />
                <span style={{
                  fontSize: 14, fontWeight: score.side === p.side ? 600 : 400,
                  color: score.side === p.side ? C.text : C.muted,
                }}>
                  {p.name}
                </span>
                {score.side === p.side && (
                  <span style={{
                    fontFamily: "'IBM Plex Mono', monospace", fontSize: 9,
                    color: C.accent, background: C.accentDim,
                    padding: '1px 5px', borderRadius: 3,
                  }}>
                    YES
                  </span>
                )}
                <span style={{ display: 'flex', gap: 4, marginLeft: 'auto' }}>
                  {(score.set_games || []).map((set, i) => (
                    <span key={i} style={{
                      fontFamily: "'IBM Plex Mono', monospace", fontSize: 12,
                      color: i === score.set_games.length - 1 ? C.text : C.dimmer,
                      minWidth: 14, textAlign: 'center',
                    }}>
                      {p.side === 1 ? set[0] : set[1]}
                    </span>
                  ))}
                  <span style={{
                    fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 600,
                    color: C.text, minWidth: 20, textAlign: 'center',
                    borderLeft: `1px solid ${C.border}`, paddingLeft: 8,
                  }}>
                    {(score.points || [])[p.side === 1 ? 0 : 1]}
                  </span>
                </span>
              </div>
            ))}
          </div>
          {score.tiebreak && (
            <div style={{
              fontFamily: "'IBM Plex Mono', monospace", fontSize: 9,
              color: C.violet, marginBottom: 12,
            }}>
              TIEBREAK
            </div>
          )}

          {/* Model stats */}
          <div style={{ display: 'flex', gap: 10 }}>
            <StatCard label="Model Price" value={fmt(score.model_price, 3)} color={C.amber}
              hint="Closed-form tennis win-probability model's fair price for this market's side, computed from the live score and each player's calibrated serve-win rate." />
            <StatCard label="Market Price" value={fmt(score.market_price, 3)} color={C.accent}
              hint="Current market mid-price for comparison against the model." />
            <StatCard label="Edge" value={fmtEdge(score.edge)}
              color={Math.abs(score.edge || 0) >= MODEL_EDGE_THRESHOLD ? C.amber : C.text}
              hint="Market price minus model price. Positive means the market is pricing this side richer than the model; negative means cheaper. Amber when large enough to trigger a model-divergence alert." />
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Matches overview (Live / Upcoming / Completed) ──────────────────────────
// match_date is a date only (midnight UTC, from the ticker), not a real
// moment in time — format it in UTC so the day shown never shifts with the
// viewer's timezone (a local-time conversion could roll it back a day).
const fmtMatchDate = iso => {
  if (!iso) return 'date TBD'
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
  })
}

// open_time is a real moment (when Kalshi opened trading for this market) —
// the one scheduling fact we can actually verify, unlike the match's own
// start time (frozen ticker date, subject to delays — see backend). The API
// serializes it without a timezone suffix but the value is always UTC, so
// force that reading before converting to the viewer's local time — without
// the 'Z', the browser would parse it as local time and shift it by
// whatever the viewer's UTC offset is.
const fmtOpenTime = iso => {
  if (!iso) return 'open time unknown'
  const withZone = iso.endsWith('Z') ? iso : `${iso}Z`
  return new Date(withZone).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

const cardShellStyle = {
  background: C.card, border: `1px solid ${C.border}`,
  borderRadius: 4, padding: '10px 0', textAlign: 'left', cursor: 'pointer',
  font: 'inherit', color: 'inherit', width: '100%',
  transition: 'border-color 0.15s, transform 0.15s',
}
const cardHoverIn  = e => { e.currentTarget.style.borderColor = C.accentDim; e.currentTarget.style.transform = 'translateY(-1px)' }
const cardHoverOut = e => { e.currentTarget.style.borderColor = C.border; e.currentTarget.style.transform = 'translateY(0)' }

function SectionHeader({ children, live }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
      {live && (
        <span style={{
          width: 6, height: 6, borderRadius: '50%', background: C.accent,
          animation: 'livePulse 1.8s ease-in-out infinite',
        }} />
      )}
      <span style={{ color: C.muted, fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.1em' }}>
        {children}
      </span>
    </div>
  )
}

const cardGrid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 10 }

// A row on an upcoming-match card reads like a scorebug: name left, price
// right in tabular digits, with a felt-yellow rail marking whoever the
// market favors.
function PlayerRow({ player, leading }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '8px 10px 8px 9px',
      borderLeft: `3px solid ${leading ? C.accent : 'transparent'}`,
    }}>
      <span style={{
        flex: 1, minWidth: 0, fontSize: 13,
        color: leading ? C.text : C.muted, fontWeight: leading ? 600 : 400,
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>
        {player.name}
      </span>
      <span style={{
        fontFamily: "'IBM Plex Mono', monospace", fontSize: 15, fontWeight: 600,
        fontVariantNumeric: 'tabular-nums', minWidth: 48, textAlign: 'right',
        color: player.price == null ? C.dimmer : (leading ? C.accent : C.muted),
      }}>
        {player.price == null ? '—' : fmt(player.price, 3)}
      </span>
    </div>
  )
}

// A row on a live-match card is the real scoreboard: serve dot, name, set
// columns, current-game points, price.
function LiveRow({ name, price, sets, point, serving }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px' }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
        background: serving ? C.accent : 'transparent',
        boxShadow: serving ? `0 0 5px ${C.accent}` : 'none',
      }} />
      <span style={{
        flex: 1, minWidth: 0, fontSize: 13, color: C.text,
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>
        {name}
      </span>
      {sets.map((g, i) => (
        <span key={i} style={{
          fontFamily: "'IBM Plex Mono', monospace", fontSize: 12,
          color: i === sets.length - 1 ? C.text : C.dimmer, minWidth: 12, textAlign: 'center',
        }}>
          {g}
        </span>
      ))}
      <span style={{
        fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 600, color: C.accent,
        minWidth: 18, textAlign: 'center', borderLeft: `1px solid ${C.border}`, paddingLeft: 6,
      }}>
        {point}
      </span>
      <span style={{
        fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, fontWeight: 600,
        fontVariantNumeric: 'tabular-nums', minWidth: 40, textAlign: 'right', color: C.muted,
      }}>
        {price == null ? '—' : fmt(price, 3)}
      </span>
    </div>
  )
}

function LiveMatchCard({ m, onPick }) {
  return (
    <button
      onClick={() => onPick(m.players[0]?.ticker)}
      style={cardShellStyle} onMouseEnter={cardHoverIn} onMouseLeave={cardHoverOut}
    >
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 12px 8px',
      }}>
        <span style={{ color: C.dimmer, fontSize: 10, fontFamily: "'IBM Plex Mono', monospace" }}>
          {m.tournament}
        </span>
        {m.tiebreak && (
          <span style={{
            fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, fontWeight: 600,
            color: C.violet,
          }}>
            TIEBREAK
          </span>
        )}
      </div>
      {m.players.map((p, i) => (
        <div key={p.ticker}>
          <LiveRow
            name={p.name} price={p.price} serving={m.serving === i + 1}
            sets={(m.set_games || []).map(set => set[i])}
            point={(m.points || [])[i]}
          />
          {i === 0 && <div style={{ height: 1, background: C.border, margin: '0 10px' }} />}
        </div>
      ))}
    </button>
  )
}

function UpcomingMatchCard({ m, onPick }) {
  const [p0, p1] = m.players
  const leadIdx = p0?.price != null && p1?.price != null && p0.price !== p1.price
    ? (p0.price > p1.price ? 0 : 1) : -1
  return (
    <button
      onClick={() => onPick(m.players[0]?.ticker)}
      style={cardShellStyle} onMouseEnter={cardHoverIn} onMouseLeave={cardHoverOut}
    >
      <div style={{
        display: 'flex', alignItems: 'baseline', gap: 6,
        color: C.dimmer, fontSize: 10, fontFamily: "'IBM Plex Mono', monospace",
        padding: '0 12px 8px', textTransform: 'uppercase', letterSpacing: '0.04em',
      }}>
        <span>Market Open</span>
        <span style={{ color: C.muted, textTransform: 'none', letterSpacing: 'normal' }}>
          {fmtOpenTime(m.open_time)}
        </span>
      </div>
      {m.players.map((p, i) => (
        <div key={p.ticker}>
          <PlayerRow player={p} leading={leadIdx === i} />
          {i === 0 && <div style={{ height: 1, background: C.border, margin: '0 10px' }} />}
        </div>
      ))}
    </button>
  )
}

function CompletedRow({ name, won }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '8px 10px 8px 9px',
      borderLeft: `3px solid ${won ? C.accent : 'transparent'}`,
    }}>
      <span style={{
        flex: 1, minWidth: 0, fontSize: 13,
        color: won ? C.text : C.muted, fontWeight: won ? 600 : 400,
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>
        {name}
      </span>
      {won && (
        <span style={{
          fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 600, color: C.accent,
        }}>
          W
        </span>
      )}
    </div>
  )
}

function CompletedMatchCard({ m, onPick }) {
  return (
    <button
      onClick={() => onPick(m.players[0]?.ticker)}
      style={{ ...cardShellStyle, background: C.surface, opacity: 0.8 }}
      onMouseEnter={e => { e.currentTarget.style.opacity = 1 }}
      onMouseLeave={e => { e.currentTarget.style.opacity = 0.8 }}
    >
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 12px 8px',
      }}>
        <span style={{ color: C.dimmer, fontSize: 10, fontFamily: "'IBM Plex Mono', monospace" }}>
          {fmtMatchDate(m.match_date)}
        </span>
        <span style={{
          color: C.muted, fontSize: 10, fontFamily: "'IBM Plex Mono', monospace",
          fontWeight: 600, letterSpacing: '0.04em',
        }}>
          FINAL
        </span>
      </div>
      {m.players.map((p, i) => (
        <div key={p.ticker}>
          <CompletedRow name={p.name} won={p.won} />
          {i === 0 && <div style={{ height: 1, background: C.border, margin: '0 10px' }} />}
        </div>
      ))}
    </button>
  )
}

function UpcomingMatches({ onPick }) {
  const [data, setData] = useState({ live: [], live_total: 0, upcoming: [], completed: [] })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = () => fetch(`${API}/markets/upcoming?limit=24`)
      .then(r => r.json())
      .then(d => setData({
        live: d.live || [], live_total: d.live_total || 0,
        upcoming: d.upcoming || [], completed: d.completed || [],
      }))
      .catch(() => {})
      .finally(() => setLoading(false))
    load()
    const id = setInterval(load, 10_000)
    return () => clearInterval(id)
  }, [])

  if (loading) {
    return (
      <div style={{
        color: C.dimmer, textAlign: 'center', padding: 40,
        fontFamily: "'IBM Plex Mono', monospace", fontSize: 12,
      }}>
        loading ATP matches...
      </div>
    )
  }

  const { live, live_total, upcoming, completed } = data
  const nothingAtAll = live.length === 0 && upcoming.length === 0 && completed.length === 0

  if (nothingAtAll) {
    return (
      <div style={{
        color: C.dimmer, textAlign: 'center', padding: '60px 24px',
        fontFamily: "'IBM Plex Mono', monospace", fontSize: 13,
      }}>
        no ATP matches right now — search for a market above
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
      <div>
        <SectionHeader live>Live Matches</SectionHeader>
        {live.length === 0 ? (
          <div style={{
            color: C.dimmer, fontFamily: "'IBM Plex Mono', monospace", fontSize: 12,
            padding: '14px 16px', background: C.card, border: `1px solid ${C.border}`, borderRadius: 4,
          }}>
            {live_total === 0
              ? 'no ATP matches are currently being played, per SofaScore'
              : `${live_total} ATP match${live_total === 1 ? ' is' : 'es are'} live right now, but none are mapped to a Kalshi market yet — check back shortly`}
          </div>
        ) : (
          <div style={cardGrid}>
            {live.map(m => <LiveMatchCard key={m.event_id} m={m} onPick={onPick} />)}
          </div>
        )}
      </div>

      {upcoming.length > 0 && (
        <div>
          <SectionHeader>Upcoming Matches</SectionHeader>
          <div style={cardGrid}>
            {upcoming.map(m => <UpcomingMatchCard key={m.event_ticker} m={m} onPick={onPick} />)}
          </div>
        </div>
      )}

      {completed.length > 0 && (
        <div>
          <SectionHeader>Completed Matches</SectionHeader>
          <div style={cardGrid}>
            {completed.map(m => <CompletedMatchCard key={m.event_ticker} m={m} onPick={onPick} />)}
          </div>
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

  const pickTicker = ticker => setSelected(ticker)

  return (
    <div style={{ minHeight: '100vh', background: C.bg, color: C.text, fontFamily: "'DM Sans', sans-serif" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;600&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: ${C.bg}; }
        ::-webkit-scrollbar-thumb { background: ${C.border}; border-radius: 2px; }
        input::placeholder { color: ${C.dimmer}; }
        @keyframes livePulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
      `}</style>

      {/* Topbar — a doubles sideline: two hairlines standing in for the tramlines */}
      <div style={{ background: C.surface }}>
        <div style={{
          padding: '0 32px', display: 'flex', alignItems: 'center', height: 68, gap: 14,
        }}>
          <button
            onClick={() => { setSelected(null); setQuery(''); setResults([]); setDropdown(false) }}
            style={{
              fontFamily: "'Bebas Neue', sans-serif", fontSize: 26, fontWeight: 400,
              color: C.accent, letterSpacing: '0.06em',
              background: 'none', border: 'none', cursor: 'pointer', padding: 0,
              lineHeight: 1.4, display: 'flex', alignItems: 'center',
            }}
          >
            BETMUSE
          </button>
          <span style={{ width: 1, height: 14, background: C.border }} />
          <span style={{ color: C.muted, fontSize: 12 }}>live win probability, every ATP match</span>
        </div>
        <div style={{ height: 1, background: C.border }} />
        <div style={{ height: 1, background: C.border, opacity: 0.4, marginTop: 3 }} />
      </div>

      {/* Main */}
      <div style={{ maxWidth: 1440, margin: '0 auto', padding: '32px 24px' }}>

        {/* Search — styled as a scoreboard panel: a felt-yellow edge strip */}
        <div ref={wrapRef} style={{ position: 'relative', marginBottom: 28 }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10,
            background: C.surface, border: `1px solid ${dropdownOpen ? C.accentDim : C.border}`,
            borderLeft: `3px solid ${dropdownOpen ? C.accent : C.dimmer}`,
            borderRadius: dropdownOpen && results.length ? '2px 6px 0 0' : '2px 6px 6px 2px',
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
              placeholder="Search players or matchups..."
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

        {/* Detail or landing page */}
        {selected
          ? <MarketDetail key={selected} ticker={selected} />
          : <UpcomingMatches onPick={pickTicker} />
        }

      </div>
    </div>
  )
}
