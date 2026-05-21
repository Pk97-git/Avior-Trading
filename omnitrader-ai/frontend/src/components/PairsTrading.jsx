import React, { useState, useEffect } from 'react';
import {
    GitCompare, ChevronDown, ChevronUp, RefreshCw, TrendingUp,
    TrendingDown, Minus, Star, Clock, Activity, AlertCircle,
} from 'lucide-react';
import { pairsApi } from '../api';

// ── Helpers ──────────────────────────────────────────────────────────────────

function zscoreColor(z) {
    const abs = Math.abs(z);
    if (abs >= 2.0) return 'text-red-400';
    if (abs >= 1.5) return 'text-amber-400';
    if (abs <= 0.5) return 'text-emerald-400';
    return 'text-slate-300';
}

function zscoreBg(z) {
    const abs = Math.abs(z);
    if (abs >= 2.0) return 'bg-red-500/15 border-red-500/30';
    if (abs >= 1.5) return 'bg-amber-500/15 border-amber-500/30';
    if (abs <= 0.5) return 'bg-emerald-500/15 border-emerald-500/30';
    return 'bg-slate-700/50 border-slate-600/30';
}

function SignalBadge({ signal }) {
    const cfg = {
        SHORT_A_LONG_B: { label: 'TRADE SIGNAL', cls: 'bg-red-500/20 text-red-300 border border-red-500/40' },
        LONG_A_SHORT_B: { label: 'TRADE SIGNAL', cls: 'bg-sky-500/20 text-sky-300 border border-sky-500/40' },
        CONVERGED:      { label: 'CONVERGED',    cls: 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40' },
        NEUTRAL:        { label: 'NEUTRAL',      cls: 'bg-slate-600/40 text-slate-400 border border-slate-600/40' },
    };
    const { label, cls } = cfg[signal] || cfg.NEUTRAL;
    return (
        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider ${cls}`}>
            {label}
        </span>
    );
}

function StrengthStars({ strength }) {
    return (
        <span className="flex gap-0.5 items-center" title={`Signal strength: ${strength}/5`}>
            {Array.from({ length: 5 }, (_, i) => (
                <Star
                    key={i}
                    size={11}
                    className={i < strength ? 'text-amber-400 fill-amber-400' : 'text-slate-600'}
                />
            ))}
        </span>
    );
}

function MiniZscoreBar({ zscores }) {
    if (!zscores || zscores.length === 0) return null;
    const max = Math.max(...zscores.map(Math.abs), 2.5);
    return (
        <div className="flex items-end gap-[2px] h-8 mt-2">
            {zscores.map((z, i) => {
                const pct = Math.min(Math.abs(z) / max, 1);
                const isNeg = z < 0;
                return (
                    <div
                        key={i}
                        title={`z=${z}`}
                        className={`w-full rounded-sm transition-all ${
                            Math.abs(z) >= 2
                                ? isNeg ? 'bg-sky-500' : 'bg-red-500'
                                : 'bg-slate-500'
                        }`}
                        style={{ height: `${Math.max(pct * 100, 8)}%` }}
                    />
                );
            })}
        </div>
    );
}

// ── Skeleton card ─────────────────────────────────────────────────────────────

function SkeletonCard() {
    return (
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 animate-pulse space-y-3">
            <div className="flex justify-between">
                <div className="h-4 bg-slate-700 rounded w-32" />
                <div className="h-4 bg-slate-700 rounded w-16" />
            </div>
            <div className="h-3 bg-slate-700 rounded w-24" />
            <div className="h-8 bg-slate-700 rounded w-full" />
            <div className="h-3 bg-slate-700 rounded w-48" />
        </div>
    );
}

// ── Pair Card ─────────────────────────────────────────────────────────────────

function PairCard({ pair }) {
    const {
        ticker_a, ticker_b, correlation, current_zscore,
        signal, signal_label, direction, strength,
        half_life_days, price_a, price_b, is_tradeable,
        recent_zscores, data_points,
    } = pair;

    const zColor  = zscoreColor(current_zscore);
    const cardCls = zscoreBg(current_zscore);

    const SignalIcon = current_zscore > 0 ? TrendingDown : current_zscore < 0 ? TrendingUp : Minus;

    return (
        <div className={`border rounded-xl p-4 transition-all hover:shadow-lg hover:shadow-black/30 ${cardCls}`}>
            {/* Header row */}
            <div className="flex items-start justify-between gap-2 mb-2">
                <div className="flex items-center gap-2 min-w-0">
                    <GitCompare size={14} className="text-slate-400 shrink-0" />
                    <span className="font-bold text-sm text-slate-100 truncate">
                        {ticker_a}
                        <span className="text-slate-500 mx-1">/</span>
                        {ticker_b}
                    </span>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                    <SignalBadge signal={signal} />
                </div>
            </div>

            {/* Prices + Correlation */}
            <div className="flex items-center gap-3 mb-3 text-xs text-slate-400">
                <span>{ticker_a}: <span className="text-slate-200 font-medium">{price_a?.toFixed(2)}</span></span>
                <span>{ticker_b}: <span className="text-slate-200 font-medium">{price_b?.toFixed(2)}</span></span>
                <span className="ml-auto bg-slate-700/60 px-1.5 py-0.5 rounded text-slate-300">
                    {(correlation * 100).toFixed(0)}% corr
                </span>
            </div>

            {/* Z-score display */}
            <div className="flex items-center gap-3 mb-2">
                <div className="flex items-baseline gap-1">
                    <span className={`text-3xl font-black tabular-nums leading-none ${zColor}`}>
                        {current_zscore > 0 ? '+' : ''}{current_zscore.toFixed(2)}
                    </span>
                    <span className="text-xs text-slate-500">z-score</span>
                </div>
                <div className="flex-1 flex flex-col gap-1">
                    <StrengthStars strength={strength} />
                    {half_life_days && (
                        <span className="flex items-center gap-1 text-[10px] text-slate-400">
                            <Clock size={9} />
                            ~{half_life_days}d mean reversion
                        </span>
                    )}
                </div>
            </div>

            {/* Signal label */}
            {is_tradeable && (
                <div className="flex items-center gap-1.5 mb-2 text-xs font-semibold">
                    <SignalIcon size={12} className={zColor} />
                    <span className={zColor}>{signal_label}</span>
                </div>
            )}

            {/* Direction explanation */}
            <p className="text-[11px] text-slate-400 leading-relaxed mb-2">{direction}</p>

            {/* Mini z-score bar chart */}
            <MiniZscoreBar zscores={recent_zscores} />

            {/* Footer */}
            <div className="flex items-center justify-between mt-2 pt-2 border-t border-slate-700/40">
                <span className="text-[10px] text-slate-500">{data_points} trading days</span>
                <span className="text-[10px] text-slate-500">β={pair.hedge_ratio}</span>
            </div>
        </div>
    );
}

// ── Explainer ─────────────────────────────────────────────────────────────────

function Explainer() {
    const [open, setOpen] = useState(false);
    return (
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl mb-5">
            <button
                onClick={() => setOpen(o => !o)}
                className="w-full flex items-center justify-between px-4 py-3 text-sm font-semibold text-slate-200 hover:text-white transition-colors"
            >
                <span className="flex items-center gap-2">
                    <Activity size={14} className="text-sky-400" />
                    What is Pairs Trading?
                </span>
                {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
            {open && (
                <div className="px-4 pb-4 text-sm text-slate-400 space-y-2 border-t border-slate-700/40 pt-3">
                    <p className="flex gap-2">
                        <span className="text-sky-400 font-bold shrink-0">1.</span>
                        When two stocks normally move together but suddenly diverge, we can profit from
                        them converging back to their historical relationship.
                    </p>
                    <p className="flex gap-2">
                        <span className="text-sky-400 font-bold shrink-0">2.</span>
                        We go long (buy) the underperformer and short (sell) the overperformer — market
                        direction doesn't matter because the trade is market-neutral.
                    </p>
                    <p className="flex gap-2">
                        <span className="text-sky-400 font-bold shrink-0">3.</span>
                        A z-score above 2 means the spread is 2 standard deviations away from its
                        historical norm — statistically, this tends to revert. The half-life tells you
                        how many days it typically takes to snap back.
                    </p>
                </div>
            )}
        </div>
    );
}

// ── Main Component ────────────────────────────────────────────────────────────

const SECTOR_OPTIONS = [
    { id: 'IN_BANKS', label: 'India Banks' },
    { id: 'IN_IT',    label: 'India IT' },
    { id: 'IN_AUTO',  label: 'India Auto' },
    { id: 'US_TECH',  label: 'US Tech' },
    { id: 'US_BANKS', label: 'US Banks' },
    { id: 'US_OIL',   label: 'US Oil' },
];

export default function PairsTrading() {
    const [sector, setSector]     = useState('IN_BANKS');
    const [minZ, setMinZ]         = useState(1.5);
    const [loading, setLoading]   = useState(false);
    const [data, setData]         = useState(null);
    const [error, setError]       = useState(null);

    const scan = async () => {
        setLoading(true);
        setError(null);
        setData(null);
        try {
            const res = await pairsApi.getCandidates(sector, minZ);
            setData(res.data);
        } catch (e) {
            const detail = e?.response?.data?.detail;
            setError(detail || 'Failed to fetch pairs. Please try again.');
        } finally {
            setLoading(false);
        }
    };

    // Auto-scan on mount
    useEffect(() => { scan(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const tradeable = data?.pairs?.filter(p => p.is_tradeable) ?? [];
    const others    = data?.pairs?.filter(p => !p.is_tradeable) ?? [];

    return (
        <div className="max-w-5xl mx-auto space-y-5">
            <Explainer />

            {/* Controls */}
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
                <div className="flex flex-wrap gap-3 items-end">
                    {/* Sector picker */}
                    <div className="flex flex-col gap-1">
                        <label className="text-[10px] text-slate-400 uppercase tracking-wider font-semibold">
                            Sector
                        </label>
                        <select
                            value={sector}
                            onChange={e => setSector(e.target.value)}
                            className="bg-slate-700 border border-slate-600 text-slate-200 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-sky-500 cursor-pointer"
                        >
                            {SECTOR_OPTIONS.map(s => (
                                <option key={s.id} value={s.id}>{s.label}</option>
                            ))}
                        </select>
                    </div>

                    {/* Min z-score */}
                    <div className="flex flex-col gap-1">
                        <label className="text-[10px] text-slate-400 uppercase tracking-wider font-semibold">
                            Min Z-Score
                        </label>
                        <select
                            value={minZ}
                            onChange={e => setMinZ(parseFloat(e.target.value))}
                            className="bg-slate-700 border border-slate-600 text-slate-200 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-sky-500 cursor-pointer"
                        >
                            <option value={1.0}>1.0 — Wide net</option>
                            <option value={1.5}>1.5 — Default</option>
                            <option value={2.0}>2.0 — Strong signals only</option>
                        </select>
                    </div>

                    {/* Scan button */}
                    <button
                        onClick={scan}
                        disabled={loading}
                        className="flex items-center gap-2 px-5 py-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-60 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-lg transition-colors"
                    >
                        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                        {loading ? 'Scanning…' : 'Scan Pairs'}
                    </button>

                    {/* Summary badges */}
                    {data && !loading && (
                        <div className="flex items-center gap-2 ml-auto flex-wrap">
                            <span className="text-xs text-slate-400">
                                {data.pairs_scanned} pairs scanned
                            </span>
                            <span className="bg-slate-700 text-slate-200 text-xs px-2 py-0.5 rounded-full">
                                {data.pairs_found} found
                            </span>
                            {data.tradeable > 0 && (
                                <span className="bg-red-500/20 text-red-300 border border-red-500/30 text-xs px-2 py-0.5 rounded-full font-semibold">
                                    {data.tradeable} tradeable
                                </span>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {/* Error */}
            {error && (
                <div className="flex items-center gap-2 bg-red-500/10 border border-red-500/30 text-red-300 rounded-xl px-4 py-3 text-sm">
                    <AlertCircle size={15} className="shrink-0" />
                    {error}
                </div>
            )}

            {/* Loading skeletons */}
            {loading && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {Array.from({ length: 4 }, (_, i) => <SkeletonCard key={i} />)}
                </div>
            )}

            {/* Tradeable pairs */}
            {!loading && tradeable.length > 0 && (
                <section>
                    <h3 className="text-xs font-bold uppercase tracking-wider text-red-400 mb-3 flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />
                        Active Trade Signals ({tradeable.length})
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {tradeable.map(pair => (
                            <PairCard key={`${pair.ticker_a}-${pair.ticker_b}`} pair={pair} />
                        ))}
                    </div>
                </section>
            )}

            {/* Other pairs */}
            {!loading && others.length > 0 && (
                <section>
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">
                        Other Correlated Pairs ({others.length})
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {others.map(pair => (
                            <PairCard key={`${pair.ticker_a}-${pair.ticker_b}`} pair={pair} />
                        ))}
                    </div>
                </section>
            )}

            {/* Empty state */}
            {!loading && !error && data && data.pairs_found === 0 && (
                <div className="text-center py-16 space-y-3">
                    <GitCompare size={36} className="mx-auto text-slate-600" />
                    <p className="text-slate-400 text-sm max-w-md mx-auto leading-relaxed">
                        No diverged pairs found in this sector — all pairs are currently trading near
                        historical norms (which is normal most of the time).
                    </p>
                    <p className="text-slate-500 text-xs">
                        Try lowering the minimum z-score or scanning a different sector.
                    </p>
                </div>
            )}
        </div>
    );
}
