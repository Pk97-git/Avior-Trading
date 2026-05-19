import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import {
    ShieldAlert, RefreshCw, TrendingDown, TrendingUp, Activity, PieChart as PieIcon,
    BarChart2, AlertTriangle, Info, ArrowUp, ArrowDown, Minus, AlertCircle, Loader2,
} from 'lucide-react';
import {
    PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
    BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from 'recharts';

// ─── Helpers ──────────────────────────────────────────────────────────────────

const COLORS = ['#6366f1','#22d3ee','#f59e0b','#10b981','#f43f5e','#a78bfa','#fb923c','#34d399'];

function fmt(n, digits = 2) {
    if (n == null) return '—';
    return Number(n).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function fmtPct(n) {
    if (n == null) return '—';
    return `${n >= 0 ? '+' : ''}${fmt(n)}%`;
}

function fmtCcy(n) {
    if (n == null) return '—';
    return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);
}

function RsTrend({ trend }) {
    if (trend === 'RISING') return <ArrowUp size={13} className="text-green-400 inline" />;
    if (trend === 'FALLING') return <ArrowDown size={13} className="text-red-400 inline" />;
    return <Minus size={13} className="text-muted-foreground inline" />;
}

function RsBadge({ rating }) {
    if (rating == null) return <span className="text-muted-foreground">—</span>;
    const color = rating >= 80 ? 'bg-green-500/20 text-green-400' :
                  rating >= 50 ? 'bg-yellow-500/20 text-yellow-400' :
                                 'bg-red-500/20 text-red-400';
    return <span className={`px-2 py-0.5 rounded text-xs font-bold ${color}`}>{rating}</span>;
}

// ─── Metric Card ──────────────────────────────────────────────────────────────

function MetricCard({ label, value, sub, icon: Icon, danger }) {
    return (
        <div className={`rounded-lg border p-4 ${danger ? 'border-red-500/30 bg-red-500/5' : 'border-border bg-card'}`}>
            <div className="flex items-center gap-2 text-xs text-muted-foreground uppercase tracking-wide mb-2">
                <Icon size={13} />
                {label}
            </div>
            <p className={`text-2xl font-bold ${danger ? 'text-red-400' : ''}`}>{value}</p>
            {sub && <p className="text-xs text-muted-foreground mt-1">{sub}</p>}
        </div>
    );
}

// ─── Correlation Heatmap ──────────────────────────────────────────────────────

function CorrelationMatrix({ tickers, matrix, high_correlations }) {
    if (!tickers || tickers.length < 2) return (
        <p className="text-sm text-muted-foreground">Need at least 2 open positions.</p>
    );

    function corrColor(v) {
        if (v == null) return '#1e293b';
        const r = v > 0 ? Math.round(v * 40) : 0;
        const g = v < 0 ? Math.round(-v * 80) : v > 0 ? Math.round(v * 120) : 0;
        const b = Math.round(30 + (1 - Math.abs(v)) * 20);
        return `rgb(${r},${g},${b})`;
    }

    return (
        <div>
            {high_correlations?.length > 0 && (
                <div className="flex items-start gap-2 mb-3 p-2 rounded bg-yellow-500/10 border border-yellow-500/20 text-xs text-yellow-400">
                    <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                    <span>High correlations: {high_correlations.map(h =>
                        `${h.ticker_a}↔${h.ticker_b} (${fmt(h.correlation)})`
                    ).join(', ')}</span>
                </div>
            )}
            <div className="overflow-x-auto">
                <table className="text-xs">
                    <thead>
                        <tr>
                            <th className="w-12" />
                            {tickers.map(t => (
                                <th key={t} className="px-1 py-0.5 text-muted-foreground font-medium text-center w-12">{t}</th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {tickers.map((rowT, ri) => (
                            <tr key={rowT}>
                                <td className="pr-2 text-muted-foreground font-medium text-right">{rowT}</td>
                                {tickers.map((_, ci) => {
                                    const v = matrix?.[ri]?.[ci];
                                    const isHigh = ri !== ci && v != null && Math.abs(v) > 0.70;
                                    return (
                                        <td key={ci}
                                            className={`w-10 h-8 text-center rounded-sm ${isHigh ? 'ring-1 ring-yellow-400' : ''}`}
                                            style={{ backgroundColor: corrColor(v) }}
                                            title={`${tickers[ri]}↔${tickers[ci]}: ${fmt(v)}`}
                                        >
                                            <span className="text-white/80 text-[10px]">
                                                {v != null ? fmt(v, 2) : ''}
                                            </span>
                                        </td>
                                    );
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

// ─── RS Rankings Table ────────────────────────────────────────────────────────

function RsTable({ data, loading }) {
    if (loading) return <div className="animate-pulse h-40 bg-muted rounded" />;
    if (!data?.length) return <p className="text-sm text-muted-foreground">No RS data available.</p>;

    return (
        <div className="overflow-x-auto">
            <table className="w-full text-sm">
                <thead>
                    <tr className="text-xs text-muted-foreground uppercase border-b border-border">
                        <th className="text-left pb-2">Rank</th>
                        <th className="text-left pb-2">Ticker</th>
                        <th className="text-center pb-2">RS Rating</th>
                        <th className="text-left pb-2 hidden md:table-cell">Sector</th>
                        <th className="text-right pb-2">1Q Ret</th>
                        <th className="text-center pb-2">Trend</th>
                    </tr>
                </thead>
                <tbody>
                    {data.slice(0, 20).map((r, i) => (
                        <tr key={r.ticker} className="border-b border-border/40 hover:bg-muted/20">
                            <td className="py-1.5 text-muted-foreground text-xs">#{i + 1}</td>
                            <td className="py-1.5 font-semibold">{r.ticker}</td>
                            <td className="py-1.5 text-center"><RsBadge rating={r.rs_rating} /></td>
                            <td className="py-1.5 text-xs text-muted-foreground hidden md:table-cell">{r.sector}</td>
                            <td className={`py-1.5 text-right text-xs ${r.return_1q >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                {fmtPct(r.return_1q)}
                            </td>
                            <td className="py-1.5 text-center"><RsTrend trend={r.trend} /></td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function RiskDashboard() {
    const [risk, setRisk]           = useState(null);
    const [corr, setCorr]           = useState(null);
    const [rs, setRs]               = useState([]);
    const [loadingRisk, setLR]      = useState(true);
    const [loadingCorr, setLC]      = useState(true);
    const [loadingRs, setLRS]       = useState(true);
    const [rsCountry, setRsCountry] = useState('ALL');
    const [error, setError]         = useState(null);
    const [lastUpdated, setLastUpdated] = useState(null);

    const fetchRisk = useCallback(async () => {
        setLR(true);
        try {
            const r = await axios.get('/api/v1/risk/portfolio-risk');
            setRisk(r.data);
        } catch { setRisk(null); }
        finally { setLR(false); }
    }, []);

    const fetchCorr = useCallback(async () => {
        setLC(true);
        try {
            const r = await axios.get('/api/v1/risk/correlation-matrix');
            setCorr(r.data);
        } catch { setCorr(null); }
        finally { setLC(false); }
    }, []);

    const fetchRs = useCallback(async () => {
        setLRS(true);
        try {
            const r = await axios.get('/api/v1/risk/rs-rankings', {
                params: { country: rsCountry, limit: 100 },
            });
            const raw = r.data;
            setRs(Array.isArray(raw) ? raw : (raw?.rankings ?? raw?.results ?? []));
        } catch { setRs([]); }
        finally { setLRS(false); }
    }, [rsCountry]);

    const handleRefresh = useCallback(() => {
        setLastUpdated(new Date());
        fetchRisk();
        fetchCorr();
    }, [fetchRisk, fetchCorr]);

    useEffect(() => { fetchRisk(); fetchCorr(); setLastUpdated(new Date()); }, [fetchRisk, fetchCorr]);
    useEffect(() => { fetchRs(); }, [fetchRs]);

    const hasPositions = !loadingRisk && (risk?.total_positions > 0 || risk?.sector_exposure);

    // Sector exposure for pie chart
    const sectorData = risk?.sector_exposure
        ? Object.entries(risk.sector_exposure).map(([name, pct]) => ({ name, value: pct }))
        : [];

    return (
        <div className="space-y-6 max-w-screen-xl">

            {/* ── Header ── */}
            <div className="flex items-center justify-between flex-wrap gap-3">
                <div>
                    <h2 className="text-xl font-bold flex items-center gap-2">
                        <ShieldAlert size={20} className="text-primary" />
                        Risk Dashboard
                    </h2>
                    <p className="text-sm text-muted-foreground mt-0.5">
                        Portfolio VaR, exposure, correlations, and RS rankings
                    </p>
                </div>
                <button
                    onClick={() => { fetchRisk(); fetchCorr(); fetchRs(); }}
                    className="flex items-center gap-1.5 text-xs border border-border rounded px-3 py-1.5 hover:bg-accent transition-colors"
                >
                    <RefreshCw size={13} />
                    Refresh
                </button>
            </div>

            {/* ── No positions placeholder ── */}
            {!loadingRisk && !hasPositions && (
                <div className="rounded-lg border border-border bg-card p-10 text-center">
                    <ShieldAlert size={40} className="mx-auto text-muted-foreground mb-3 opacity-40" />
                    <p className="text-muted-foreground">Open positions to see risk analytics.</p>
                </div>
            )}

            {/* ── VaR Cards ── */}
            {(loadingRisk || hasPositions) && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <MetricCard
                        label="VaR 95% (1-day)"
                        value={loadingRisk ? '…' : fmtCcy(risk?.var_95)}
                        sub={risk?.var_95_pct != null ? `${fmtPct(risk.var_95_pct)} of portfolio` : null}
                        icon={TrendingDown}
                        danger={!loadingRisk && risk?.var_95_pct != null && Math.abs(risk.var_95_pct) > 3}
                    />
                    <MetricCard
                        label="VaR 99% (1-day)"
                        value={loadingRisk ? '…' : fmtCcy(risk?.var_99)}
                        sub={risk?.var_99_pct != null ? `${fmtPct(risk.var_99_pct)} of portfolio` : null}
                        icon={TrendingDown}
                        danger={!loadingRisk && risk?.var_99_pct != null && Math.abs(risk.var_99_pct) > 5}
                    />
                    <MetricCard
                        label="Ann. Volatility"
                        value={loadingRisk ? '…' : (risk?.volatility_annualized != null ? `${fmt(risk.volatility_annualized)}%` : '—')}
                        sub="portfolio-level"
                        icon={Activity}
                    />
                    <MetricCard
                        label="Max Drawdown (90d)"
                        value={loadingRisk ? '…' : (risk?.max_drawdown != null ? `${fmt(risk.max_drawdown)}%` : '—')}
                        sub="historical"
                        icon={TrendingDown}
                        danger={!loadingRisk && risk?.max_drawdown != null && risk.max_drawdown < -10}
                    />
                </div>
            )}

            {/* ── Exposure + Correlation ── */}
            {hasPositions && (
                <div className="grid md:grid-cols-2 gap-6">

                    {/* Sector Pie */}
                    <div className="rounded-lg border border-border bg-card p-4">
                        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                            <PieIcon size={14} className="text-primary" />
                            Sector Exposure
                        </h3>
                        {sectorData.length > 0 ? (
                            <div className="flex gap-4 items-center">
                                <ResponsiveContainer width={160} height={160}>
                                    <PieChart>
                                        <Pie data={sectorData} dataKey="value" cx="50%" cy="50%" outerRadius={70} strokeWidth={0}>
                                            {sectorData.map((_, i) => (
                                                <Cell key={i} fill={COLORS[i % COLORS.length]} />
                                            ))}
                                        </Pie>
                                        <Tooltip formatter={(v) => `${fmt(v)}%`} />
                                    </PieChart>
                                </ResponsiveContainer>
                                <div className="space-y-1 flex-1">
                                    {sectorData.map((s, i) => (
                                        <div key={s.name} className="flex items-center gap-2 text-xs">
                                            <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                                            <span className="flex-1 truncate text-muted-foreground">{s.name}</span>
                                            <span className="font-medium">{fmt(s.value)}%</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        ) : (
                            <p className="text-sm text-muted-foreground">No sector data.</p>
                        )}

                        {/* Country split */}
                        {risk?.country_exposure && (
                            <div className="mt-4 pt-3 border-t border-border">
                                <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2">Country</p>
                                <div className="flex gap-4">
                                    {Object.entries(risk.country_exposure).map(([country, pct]) => (
                                        <div key={country} className="text-center">
                                            <p className="text-lg font-bold">{fmt(pct)}%</p>
                                            <p className="text-xs text-muted-foreground">{country}</p>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Correlation Matrix */}
                    <div className="rounded-lg border border-border bg-card p-4">
                        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                            <BarChart2 size={14} className="text-primary" />
                            Correlation Matrix
                            {corr?.diversification_score != null && (
                                <span className={`ml-auto text-xs px-2 py-0.5 rounded ${
                                    corr.diversification_score > 0.6 ? 'bg-green-500/20 text-green-400' :
                                    corr.diversification_score > 0.3 ? 'bg-yellow-500/20 text-yellow-400' :
                                    'bg-red-500/20 text-red-400'
                                }`}>
                                    Diversification: {fmt(corr.diversification_score * 100, 0)}%
                                </span>
                            )}
                        </h3>
                        {loadingCorr ? (
                            <div className="animate-pulse h-32 bg-muted rounded" />
                        ) : corr ? (
                            <CorrelationMatrix
                                tickers={corr.tickers}
                                matrix={corr.matrix}
                                high_correlations={corr.high_correlations}
                            />
                        ) : (
                            <p className="text-sm text-muted-foreground">Could not compute correlations.</p>
                        )}
                    </div>
                </div>
            )}

            {/* ── RS Rankings ── */}
            <div className="rounded-lg border border-border bg-card p-4">
                <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
                    <h3 className="text-sm font-semibold flex items-center gap-2">
                        <BarChart2 size={14} className="text-primary" />
                        Relative Strength Rankings
                        <span className="text-xs text-muted-foreground font-normal">(IBD-style, 1–99)</span>
                    </h3>
                    <div className="flex items-center gap-2">
                        {['ALL', 'US', 'IN'].map(c => (
                            <button
                                key={c}
                                onClick={() => setRsCountry(c)}
                                className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                                    rsCountry === c
                                        ? 'bg-primary text-primary-foreground'
                                        : 'bg-muted text-muted-foreground hover:bg-accent'
                                }`}
                            >
                                {c}
                            </button>
                        ))}
                    </div>
                </div>
                <RsTable data={rs} loading={loadingRs} />
            </div>

            {/* ── CVaR note ── */}
            {risk?.cvar_95 != null && (
                <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                    <Info size={11} />
                    Expected Shortfall (CVaR 95%): {fmtCcy(risk.cvar_95)} — mean loss in worst 5% of days over 90-day window.
                </p>
            )}
        </div>
    );
}
