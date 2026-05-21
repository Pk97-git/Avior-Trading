import React, { useState, useEffect, useCallback } from 'react';
import {
    Layers, TrendingDown, RefreshCw, AlertTriangle, Info,
    Loader2, BarChart2, ShieldAlert,
} from 'lucide-react';
import { factorApi, shortCandidatesApi } from '../api';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(n, digits = 2) {
    if (n == null) return '—';
    return Number(n).toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    });
}

function fmtScore(n) {
    if (n == null) return '—';
    return `${n >= 0 ? '+' : ''}${fmt(n, 2)}`;
}

// ─── Factor Bar ───────────────────────────────────────────────────────────────

function FactorBar({ name, value, interpretation, riskLevel }) {
    // value is z-score, clamped -3 to +3
    const clamped = Math.max(-3, Math.min(3, value ?? 0));
    const pct = ((clamped + 3) / 6) * 100;   // 0% = -3, 50% = 0, 100% = +3
    const isPositive = clamped >= 0;

    const barColor = isPositive
        ? 'bg-gradient-to-r from-blue-500 to-teal-400'
        : 'bg-gradient-to-r from-amber-500 to-red-500';

    const riskBadge = riskLevel === 'HIGH'
        ? 'bg-red-500/20 text-red-400'
        : riskLevel === 'LOW'
            ? 'bg-green-500/20 text-green-400'
            : 'bg-yellow-500/20 text-yellow-400';

    const FACTOR_LABELS = {
        momentum:   'Momentum',
        volatility: 'Volatility',
        value:      'Value',
        trend:      'Trend',
        quality:    'Quality',
    };

    return (
        <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-foreground">{FACTOR_LABELS[name] ?? name}</span>
                <div className="flex items-center gap-2">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${riskBadge}`}>
                        {riskLevel}
                    </span>
                    <span className="font-mono text-muted-foreground w-12 text-right">
                        {fmtScore(value)}σ
                    </span>
                </div>
            </div>
            {/* Bar track */}
            <div className="relative h-3 rounded-full bg-muted overflow-hidden">
                {/* Centre marker */}
                <div className="absolute left-1/2 top-0 bottom-0 w-px bg-border/60 z-10" />
                {/* Filled portion */}
                {isPositive ? (
                    <div
                        className={`absolute top-0 bottom-0 rounded-full ${barColor}`}
                        style={{ left: '50%', width: `${(pct - 50)}%` }}
                    />
                ) : (
                    <div
                        className={`absolute top-0 bottom-0 rounded-full ${barColor}`}
                        style={{ left: `${pct}%`, width: `${50 - pct}%` }}
                    />
                )}
            </div>
            {interpretation && (
                <p className="text-[10px] text-muted-foreground leading-snug">{interpretation}</p>
            )}
        </div>
    );
}

// ─── Factor Dot (mini sparkline per holding) ──────────────────────────────────

function FactorDot({ value }) {
    const v = value ?? 0;
    const color = v > 0.5
        ? 'bg-teal-400'
        : v < -0.5
            ? 'bg-red-400'
            : 'bg-yellow-400';
    return (
        <span
            className={`inline-block w-3 h-3 rounded-full ${color}`}
            title={fmtScore(v)}
        />
    );
}

// ─── Holdings Table ───────────────────────────────────────────────────────────

function HoldingsTable({ holdings }) {
    if (!holdings?.length) return null;
    const FACTORS = ['momentum', 'volatility', 'value', 'trend', 'quality'];

    return (
        <div className="overflow-x-auto mt-4">
            <table className="w-full text-xs">
                <thead>
                    <tr className="text-muted-foreground uppercase border-b border-border">
                        <th className="text-left pb-2 font-medium">Ticker</th>
                        <th className="text-right pb-2 font-medium">Weight</th>
                        <th className="text-center pb-2 font-medium">Mom</th>
                        <th className="text-center pb-2 font-medium">Vol</th>
                        <th className="text-center pb-2 font-medium">Val</th>
                        <th className="text-center pb-2 font-medium">Trend</th>
                        <th className="text-center pb-2 font-medium">Qual</th>
                    </tr>
                </thead>
                <tbody>
                    {holdings.map(h => (
                        <tr key={h.ticker} className="border-b border-border/30 hover:bg-muted/10">
                            <td className="py-1.5 font-semibold text-foreground">{h.ticker}</td>
                            <td className="py-1.5 text-right text-muted-foreground">{fmt(h.weight_pct)}%</td>
                            {FACTORS.map(f => (
                                <td key={f} className="py-1.5 text-center">
                                    <FactorDot value={h[f]} />
                                </td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
            <p className="mt-2 text-[10px] text-muted-foreground flex items-center gap-1">
                <Info size={10} />
                Dots: teal = positive exposure, red = negative, yellow = neutral (z-score relative to universe)
            </p>
        </div>
    );
}

// ─── Short Candidates Section ─────────────────────────────────────────────────

function SignalBadge({ signal, color }) {
    const cls = color === 'red'
        ? 'bg-red-500/20 text-red-400 border-red-500/30'
        : color === 'orange'
            ? 'bg-orange-500/20 text-orange-400 border-orange-500/30'
            : 'bg-amber-500/20 text-amber-400 border-amber-500/30';
    return (
        <span className={`px-2 py-0.5 rounded border text-[10px] font-semibold ${cls}`}>
            {signal}
        </span>
    );
}

function ScoreBar({ score }) {
    const pct = Math.max(0, Math.min(100, score ?? 0));
    const barColor = pct < 30 ? 'bg-red-500' : pct < 50 ? 'bg-orange-500' : 'bg-yellow-500';
    return (
        <div className="flex items-center gap-2">
            <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                <div className={`h-full rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
            </div>
            <span className="text-xs font-mono w-6 text-right text-muted-foreground">{pct}</span>
        </div>
    );
}

function ShortCandidatesSection() {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [country, setCountry] = useState('ALL');
    const [error, setError] = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await shortCandidatesApi.get({ country, limit: 20 });
            setData(res.data);
        } catch (e) {
            setError(e?.response?.data?.detail || 'Failed to load short candidates');
        } finally {
            setLoading(false);
        }
    }, [country]);

    useEffect(() => { load(); }, [load]);

    return (
        <div className="rounded-lg border border-border bg-card p-4 space-y-4">
            {/* Header */}
            <div className="flex items-center justify-between flex-wrap gap-2">
                <h3 className="text-sm font-semibold flex items-center gap-2">
                    <TrendingDown size={14} className="text-red-400" />
                    Short Candidates
                    <span className="text-xs text-muted-foreground font-normal">
                        — bearish signals ranked by conviction
                    </span>
                </h3>
                <div className="flex items-center gap-2">
                    {['ALL', 'US', 'IN'].map(c => (
                        <button
                            key={c}
                            onClick={() => setCountry(c)}
                            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                                country === c
                                    ? 'bg-primary text-primary-foreground'
                                    : 'bg-muted text-muted-foreground hover:bg-accent'
                            }`}
                        >
                            {c}
                        </button>
                    ))}
                    <button
                        onClick={load}
                        disabled={loading}
                        className="flex items-center gap-1 px-2 py-1 rounded text-xs border border-border text-muted-foreground hover:text-foreground hover:bg-muted/30 disabled:opacity-50 transition-colors"
                    >
                        <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
                    </button>
                </div>
            </div>

            {/* Loading */}
            {loading && (
                <div className="flex items-center justify-center py-8 text-muted-foreground gap-2">
                    <Loader2 size={16} className="animate-spin" />
                    <span className="text-sm">Scanning for short candidates…</span>
                </div>
            )}

            {/* Error */}
            {!loading && error && (
                <div className="flex items-start gap-2 p-3 rounded bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
                    <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                    {error}
                </div>
            )}

            {/* Empty */}
            {!loading && !error && !data?.candidates?.length && (
                <div className="text-center py-8">
                    <ShieldAlert size={32} className="mx-auto text-muted-foreground opacity-30 mb-2" />
                    <p className="text-sm text-muted-foreground">No short candidates found with current filters.</p>
                    <p className="text-xs text-muted-foreground/60 mt-1">
                        Short candidates require AI signal in SELL / DISTRIBUTION / AVOID with score below threshold.
                    </p>
                </div>
            )}

            {/* Table */}
            {!loading && data?.candidates?.length > 0 && (
                <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="text-xs text-muted-foreground uppercase border-b border-border">
                                <th className="text-left pb-2">Ticker</th>
                                <th className="text-left pb-2 hidden md:table-cell">Signal</th>
                                <th className="text-left pb-2">AI Score</th>
                                <th className="text-right pb-2 hidden sm:table-cell">Conviction</th>
                                <th className="text-left pb-2 hidden lg:table-cell">Short Stop / Target</th>
                                <th className="text-left pb-2 hidden xl:table-cell">Thesis</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.candidates.map(c => (
                                <tr key={c.ticker} className="border-b border-border/30 hover:bg-muted/10">
                                    <td className="py-2 pr-3">
                                        <div className="font-semibold text-foreground">{c.ticker}</div>
                                        <div className="text-[10px] text-muted-foreground truncate max-w-[120px]">
                                            {c.name}
                                        </div>
                                        <div className="md:hidden mt-1">
                                            <SignalBadge signal={c.signal_strength} color={c.color} />
                                        </div>
                                    </td>
                                    <td className="py-2 pr-3 hidden md:table-cell">
                                        <SignalBadge signal={c.signal_strength} color={c.color} />
                                        {c.regime && (
                                            <div className="text-[10px] text-muted-foreground mt-1">
                                                {c.regime}
                                            </div>
                                        )}
                                    </td>
                                    <td className="py-2 pr-3 min-w-[100px]">
                                        <ScoreBar score={c.ai_score} />
                                    </td>
                                    <td className="py-2 pr-3 text-right hidden sm:table-cell">
                                        <span className="text-xs font-mono font-semibold text-red-400">
                                            {c.conviction}
                                        </span>
                                    </td>
                                    <td className="py-2 pr-3 hidden lg:table-cell">
                                        {c.stop_for_short != null || c.target_for_short != null ? (
                                            <div className="text-xs space-y-0.5">
                                                <div className="text-red-400">
                                                    Stop: {c.stop_for_short != null ? fmt(c.stop_for_short) : '—'}
                                                </div>
                                                <div className="text-green-400">
                                                    Target: {c.target_for_short != null ? fmt(c.target_for_short) : '—'}
                                                </div>
                                            </div>
                                        ) : (
                                            <span className="text-muted-foreground text-xs">—</span>
                                        )}
                                    </td>
                                    <td className="py-2 hidden xl:table-cell">
                                        {Array.isArray(c.thesis) && c.thesis.length > 0 ? (
                                            <p className="text-[11px] text-muted-foreground max-w-[240px] truncate">
                                                {c.thesis[0]}
                                            </p>
                                        ) : (
                                            <span className="text-muted-foreground text-xs">—</span>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Disclaimer */}
            {data?.disclaimer && (
                <div className="flex items-start gap-2 p-3 rounded bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs">
                    <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                    <span>{data.disclaimer}</span>
                </div>
            )}
        </div>
    );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function FactorExposure({ view = 'factors' }) {
    const [portfolioData, setPortfolioData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [lastUpdated, setLastUpdated] = useState(null);

    const loadPortfolio = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await factorApi.getPortfolio();
            setPortfolioData(res.data);
            setLastUpdated(new Date());
        } catch (e) {
            setError(e?.response?.data?.detail || 'Failed to load factor data');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (view === 'factors') {
            loadPortfolio();
        }
    }, [view, loadPortfolio]);

    // ── Short Candidates Tab ──────────────────────────────────────────────────
    if (view === 'shorts') {
        return (
            <div className="space-y-6 max-w-screen-xl">
                <div className="flex items-center gap-2">
                    <TrendingDown size={20} className="text-red-400" />
                    <h2 className="text-lg font-bold">Short Candidates</h2>
                </div>
                <ShortCandidatesSection />
            </div>
        );
    }

    // ── Factor Exposure Tab ───────────────────────────────────────────────────
    const exposures = portfolioData?.exposures ?? {};
    const interpretations = portfolioData?.interpretations ?? {};
    const dominantFactor = portfolioData?.dominant_factor;
    const holdings = portfolioData?.holdings ?? [];
    const FACTORS = ['momentum', 'volatility', 'value', 'trend', 'quality'];

    return (
        <div className="space-y-6 max-w-screen-xl">

            {/* Header */}
            <div className="flex items-center justify-between flex-wrap gap-3">
                <div className="flex items-center gap-2">
                    <Layers size={20} className="text-primary" />
                    <h2 className="text-lg font-bold">Factor Exposure Analysis</h2>
                    {lastUpdated && (
                        <span className="text-xs text-muted-foreground">
                            Updated {lastUpdated.toLocaleTimeString()}
                        </span>
                    )}
                </div>
                <button
                    onClick={loadPortfolio}
                    disabled={loading}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors text-xs font-medium disabled:opacity-50"
                >
                    <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
                    Refresh
                </button>
            </div>

            {/* Loading */}
            {loading && (
                <div className="flex items-center justify-center py-16 text-muted-foreground gap-2">
                    <Loader2 size={20} className="animate-spin" />
                    <span className="text-sm">Computing factor exposures…</span>
                </div>
            )}

            {/* Error */}
            {!loading && error && (
                <div className="flex items-start gap-2 p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                    <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                    {error}
                </div>
            )}

            {/* No positions */}
            {!loading && !error && portfolioData?.message && (
                <div className="rounded-xl border border-border bg-card/50 p-10 text-center">
                    <BarChart2 size={40} className="mx-auto text-muted-foreground mb-3 opacity-30" />
                    <p className="text-base font-medium text-muted-foreground">{portfolioData.message}</p>
                    <p className="text-xs text-muted-foreground/60 mt-1">
                        Factor exposure requires at least one open portfolio position with 60+ days of price history.
                    </p>
                </div>
            )}

            {/* Factor Exposure Content */}
            {!loading && !error && Object.keys(exposures).length > 0 && (
                <>
                    {/* Portfolio summary strip */}
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                        <div className="rounded-lg border border-border bg-card p-3">
                            <p className="text-xs text-muted-foreground uppercase tracking-wide">Positions</p>
                            <p className="text-2xl font-bold mt-1">{portfolioData.position_count ?? '—'}</p>
                        </div>
                        <div className="rounded-lg border border-border bg-card p-3">
                            <p className="text-xs text-muted-foreground uppercase tracking-wide">Portfolio Value</p>
                            <p className="text-2xl font-bold mt-1">
                                {portfolioData.portfolio_value != null
                                    ? new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(portfolioData.portfolio_value)
                                    : '—'}
                            </p>
                        </div>
                        {dominantFactor && (
                            <div className="rounded-lg border border-primary/30 bg-primary/5 p-3">
                                <p className="text-xs text-muted-foreground uppercase tracking-wide">Dominant Factor</p>
                                <p className="text-lg font-bold mt-1 capitalize text-primary">{dominantFactor}</p>
                                <p className="text-[10px] text-muted-foreground">Highest absolute z-score</p>
                            </div>
                        )}
                    </div>

                    {/* Factor bars */}
                    <div className="rounded-lg border border-border bg-card p-4 space-y-5">
                        <h3 className="text-sm font-semibold flex items-center gap-2">
                            <BarChart2 size={14} className="text-primary" />
                            Portfolio Factor Exposures
                            <span className="text-xs text-muted-foreground font-normal">
                                (z-score vs universe, 0 = market neutral)
                            </span>
                        </h3>
                        <div className="space-y-4">
                            {FACTORS.map(f => (
                                <FactorBar
                                    key={f}
                                    name={f}
                                    value={exposures[f]}
                                    interpretation={interpretations[f]?.interpretation}
                                    riskLevel={interpretations[f]?.risk_level}
                                />
                            ))}
                        </div>
                        {/* Scale legend */}
                        <div className="flex items-center justify-between text-[10px] text-muted-foreground pt-1 border-t border-border">
                            <span>-3σ (max underweight)</span>
                            <span>0 (neutral)</span>
                            <span>+3σ (max overweight)</span>
                        </div>
                    </div>

                    {/* Per-holding breakdown */}
                    {holdings.length > 0 && (
                        <div className="rounded-lg border border-border bg-card p-4">
                            <h3 className="text-sm font-semibold flex items-center gap-2 mb-1">
                                <Layers size={14} className="text-primary" />
                                Per-Holding Factor Breakdown
                            </h3>
                            <p className="text-xs text-muted-foreground mb-2">
                                Each dot shows the stock's factor z-score relative to the universe.
                            </p>
                            <HoldingsTable holdings={holdings} />
                        </div>
                    )}
                </>
            )}

            {/* Short Candidates — always shown below factors */}
            <ShortCandidatesSection />
        </div>
    );
}
