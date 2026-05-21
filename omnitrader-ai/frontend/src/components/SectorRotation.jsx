import React, { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import {
    RefreshCw, Loader2, TrendingUp, TrendingDown,
    BarChart2, AlertCircle, Layers,
} from 'lucide-react';
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
    ResponsiveContainer, Cell,
} from 'recharts';

// ── Static ETF → Name mapping ───────────────────────────────────────────────

const SECTOR_NAMES = {
    XLK:  'Technology',
    XLF:  'Financials',
    XLV:  'Healthcare',
    XLE:  'Energy',
    XLI:  'Industrials',
    XLY:  'Consumer Discretionary',
    XLP:  'Consumer Staples',
    XLU:  'Utilities',
    XLRE: 'Real Estate',
    XLB:  'Materials',
    XLC:  'Communication Services',
};

// ── Helpers ─────────────────────────────────────────────────────────────────

function fmt(val, decimals = 1) {
    if (val == null) return '—';
    const n = Number(val);
    return (n >= 0 ? '+' : '') + n.toFixed(decimals) + '%';
}

function scoreBarColor(score) {
    if (score >= 67) return '#10b981'; // emerald
    if (score >= 34) return '#f59e0b'; // amber
    return '#ef4444';                  // red
}

function signalBadge(signal) {
    switch ((signal ?? '').toUpperCase()) {
        case 'BUY':   return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30';
        case 'HOLD':  return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
        case 'AVOID': return 'bg-red-500/20 text-red-400 border-red-500/30';
        default:      return 'bg-muted/20 text-muted-foreground border-border';
    }
}

function pctColor(v) {
    if (v == null) return 'text-muted-foreground';
    return Number(v) >= 0 ? 'text-emerald-400' : 'text-red-400';
}

// ── Custom Tooltip ───────────────────────────────────────────────────────────

function ChartTooltip({ active, payload }) {
    if (!active || !payload?.length) return null;
    const d = payload[0].payload;
    return (
        <div className="bg-card border border-border rounded-lg px-3 py-2 text-xs shadow-xl">
            <p className="font-bold text-foreground">{d.etf} — {d.name}</p>
            <p className="text-muted-foreground">Score: <span className="text-foreground font-semibold">{d.composite_score?.toFixed(1)}</span></p>
        </div>
    );
}

// ── Main Component ───────────────────────────────────────────────────────────

export default function SectorRotation() {
    const [data, setData]           = useState([]);
    const [loading, setLoading]     = useState(true);
    const [error, setError]         = useState(null);
    const [lastUpdated, setLastUpdated] = useState(null);

    const fetchData = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await axios.get('/api/v1/sectors/rotation');
            const raw = Array.isArray(res.data)
                ? res.data
                : (res.data?.sectors ?? res.data?.results ?? []);
            // Enrich with sector names
            const enriched = raw.map(item => ({
                ...item,
                name: SECTOR_NAMES[item.etf ?? item.sector_etf] ?? item.sector_name ?? item.name ?? item.etf ?? '—',
                etf:  item.etf ?? item.sector_etf ?? '—',
            }));
            setData(enriched);
            setLastUpdated(new Date());
        } catch (e) {
            setError(e?.response?.data?.detail || 'Failed to load sector rotation data.');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { fetchData(); }, [fetchData]);

    const sorted = [...data].sort((a, b) => (b.composite_score ?? 0) - (a.composite_score ?? 0));
    const ranked = sorted.map((item, i) => ({ ...item, rank: i + 1 }));

    const top3    = ranked.slice(0, 3);
    const bottom3 = [...ranked].reverse().slice(0, 3).reverse();

    // For chart: sorted by score ascending (so bars go low → high from bottom)
    const chartData = [...ranked]
        .sort((a, b) => (a.composite_score ?? 0) - (b.composite_score ?? 0))
        .map(d => ({
            etf:             d.etf,
            name:            d.name,
            composite_score: d.composite_score ?? 0,
        }));

    return (
        <div className="space-y-5 p-5 min-h-screen">
            {/* ── Header ── */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <Layers size={20} className="text-primary" />
                    <h1 className="text-lg font-bold text-foreground">Sector Rotation</h1>
                    {lastUpdated && (
                        <span className="text-xs text-muted-foreground">
                            Updated {lastUpdated.toLocaleTimeString()}
                        </span>
                    )}
                </div>
                <button
                    onClick={fetchData}
                    disabled={loading}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors text-xs font-medium disabled:opacity-50"
                >
                    <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
                    Refresh
                </button>
            </div>

            {/* ── Error ── */}
            {error && (
                <div className="flex items-center gap-2 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
                    <AlertCircle size={15} /> {error}
                </div>
            )}

            {/* ── Loading ── */}
            {loading && (
                <div className="flex items-center justify-center py-16 text-muted-foreground gap-2">
                    <Loader2 size={20} className="animate-spin" />
                    <span className="text-sm">Loading sector data…</span>
                </div>
            )}

            {/* ── Top 3 / Bottom 3 Cards ── */}
            {!loading && ranked.length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {/* Rotating IN */}
                    <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
                        <div className="flex items-center gap-2 mb-3">
                            <TrendingUp size={15} className="text-emerald-400" />
                            <span className="text-sm font-semibold text-emerald-400">Rotating In (Top 3)</span>
                        </div>
                        <div className="space-y-2">
                            {top3.map((s, i) => (
                                <div key={i} className="flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                        <span className="text-[10px] font-bold text-emerald-400/60 w-4">#{s.rank}</span>
                                        <span className="font-bold text-sm text-foreground">{s.etf}</span>
                                        <span className="text-xs text-muted-foreground truncate max-w-[120px]">{s.name}</span>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <span className={`text-xs font-semibold tabular-nums ${pctColor(s.return_4w ?? s.return_1m)}`}>
                                            {fmt(s.return_4w ?? s.return_1m)}
                                        </span>
                                        <TrendingUp size={13} className="text-emerald-400" />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Rotating OUT */}
                    <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-4">
                        <div className="flex items-center gap-2 mb-3">
                            <TrendingDown size={15} className="text-red-400" />
                            <span className="text-sm font-semibold text-red-400">Rotating Out (Bottom 3)</span>
                        </div>
                        <div className="space-y-2">
                            {bottom3.map((s, i) => (
                                <div key={i} className="flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                        <span className="text-[10px] font-bold text-red-400/60 w-4">#{s.rank}</span>
                                        <span className="font-bold text-sm text-foreground">{s.etf}</span>
                                        <span className="text-xs text-muted-foreground truncate max-w-[120px]">{s.name}</span>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <span className={`text-xs font-semibold tabular-nums ${pctColor(s.return_4w ?? s.return_1m)}`}>
                                            {fmt(s.return_4w ?? s.return_1m)}
                                        </span>
                                        <TrendingDown size={13} className="text-red-400" />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {/* ── Main Ranking Table ── */}
            {!loading && ranked.length > 0 && (
                <div className="rounded-xl border border-border bg-card/50 overflow-hidden">
                    <div className="px-4 py-2.5 border-b border-border flex items-center gap-2">
                        <BarChart2 size={14} className="text-primary" />
                        <span className="text-sm font-semibold text-foreground">Sector Rankings</span>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-border bg-muted/20">
                                    <th className="px-3 py-2.5 text-left text-xs font-semibold text-muted-foreground">Rank</th>
                                    <th className="px-3 py-2.5 text-left text-xs font-semibold text-muted-foreground">ETF</th>
                                    <th className="px-3 py-2.5 text-left text-xs font-semibold text-muted-foreground">Sector</th>
                                    <th className="px-3 py-2.5 text-right text-xs font-semibold text-muted-foreground">4-Week Return</th>
                                    <th className="px-3 py-2.5 text-right text-xs font-semibold text-muted-foreground">12-Week Return</th>
                                    <th className="px-3 py-2.5 text-left text-xs font-semibold text-muted-foreground min-w-[140px]">Composite Score</th>
                                    <th className="px-3 py-2.5 text-left text-xs font-semibold text-muted-foreground">Signal</th>
                                </tr>
                            </thead>
                            <tbody>
                                {ranked.map((row) => {
                                    const isTop3    = row.rank <= 3;
                                    const isBottom3 = row.rank > ranked.length - 3;
                                    return (
                                        <tr
                                            key={row.etf}
                                            className={`border-b border-border/40 transition-colors hover:bg-muted/10 ${
                                                isTop3    ? 'bg-emerald-500/[0.03]' :
                                                isBottom3 ? 'bg-red-500/[0.03]' : ''
                                            }`}
                                        >
                                            <td className="px-3 py-2.5">
                                                <span className={`text-xs font-bold tabular-nums ${
                                                    isTop3    ? 'text-emerald-400' :
                                                    isBottom3 ? 'text-red-400'     : 'text-muted-foreground'
                                                }`}>
                                                    #{row.rank}
                                                </span>
                                            </td>
                                            <td className="px-3 py-2.5 font-bold text-foreground text-sm">{row.etf}</td>
                                            <td className="px-3 py-2.5 text-xs text-muted-foreground">{row.name}</td>
                                            <td className={`px-3 py-2.5 text-xs font-semibold tabular-nums text-right ${pctColor(row.return_4w ?? row.return_1m)}`}>
                                                {fmt(row.return_4w ?? row.return_1m)}
                                            </td>
                                            <td className={`px-3 py-2.5 text-xs font-semibold tabular-nums text-right ${pctColor(row.return_12w ?? row.return_3m)}`}>
                                                {fmt(row.return_12w ?? row.return_3m)}
                                            </td>
                                            <td className="px-3 py-2.5">
                                                <div className="flex items-center gap-2">
                                                    <div className="flex-1 h-1.5 bg-muted/40 rounded-full overflow-hidden">
                                                        <div
                                                            className="h-full rounded-full transition-all"
                                                            style={{
                                                                width: `${Math.min(100, row.composite_score ?? 0)}%`,
                                                                background: scoreBarColor(row.composite_score ?? 0),
                                                            }}
                                                        />
                                                    </div>
                                                    <span className="text-xs font-bold tabular-nums text-foreground w-8 text-right">
                                                        {row.composite_score?.toFixed(1) ?? '—'}
                                                    </span>
                                                </div>
                                            </td>
                                            <td className="px-3 py-2.5">
                                                <span className={`inline-block px-2 py-0.5 rounded text-[11px] font-semibold border ${signalBadge(row.signal)}`}>
                                                    {(row.signal ?? '—').toUpperCase()}
                                                </span>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* ── Bar Chart ── */}
            {!loading && chartData.length > 0 && (
                <div className="rounded-xl border border-border bg-card/50 p-4">
                    <div className="flex items-center gap-2 mb-4">
                        <BarChart2 size={14} className="text-primary" />
                        <span className="text-sm font-semibold text-foreground">Composite Score by Sector</span>
                    </div>
                    <div style={{ height: Math.max(220, chartData.length * 30) }}>
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart
                                data={chartData}
                                layout="vertical"
                                margin={{ top: 0, right: 30, bottom: 0, left: 0 }}
                            >
                                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="rgba(255,255,255,0.05)" />
                                <XAxis
                                    type="number"
                                    domain={[0, 100]}
                                    tick={{ fontSize: 10, fill: '#6b7280' }}
                                    axisLine={false}
                                    tickLine={false}
                                />
                                <YAxis
                                    type="category"
                                    dataKey="etf"
                                    width={44}
                                    tick={{ fontSize: 11, fill: '#9ca3af', fontWeight: 600 }}
                                    axisLine={false}
                                    tickLine={false}
                                />
                                <Tooltip content={<ChartTooltip />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
                                <Bar dataKey="composite_score" radius={[0, 4, 4, 0]} maxBarSize={18}>
                                    {chartData.map((entry, i) => (
                                        <Cell key={i} fill={scoreBarColor(entry.composite_score)} fillOpacity={0.85} />
                                    ))}
                                </Bar>
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            )}

            {!loading && data.length === 0 && !error && (
                <div className="text-center py-12 text-muted-foreground text-sm">
                    No sector rotation data available.
                </div>
            )}
        </div>
    );
}
