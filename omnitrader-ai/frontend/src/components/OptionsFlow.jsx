import React, { useEffect, useState, useCallback, useRef } from 'react';
import axios from 'axios';
import {
    RefreshCw, Loader2, Search, AlertCircle, Activity,
    TrendingUp, TrendingDown, Minus, X,
} from 'lucide-react';

// ── Helpers ────────────────────────────────────────────────────────────────

function fmt(val, decimals = 2) {
    if (val == null) return '—';
    return Number(val).toFixed(decimals);
}

function fmtDate(iso) {
    if (!iso) return '—';
    try {
        return new Date(iso).toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', year: '2-digit',
        });
    } catch {
        return iso;
    }
}

function urgencyStyle(score) {
    if (score >= 70) return 'bg-red-500/20 text-red-400 border-red-500/30';
    if (score >= 40) return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
    return 'bg-muted/20 text-muted-foreground border-border';
}

function moneynessStyle(m) {
    switch ((m ?? '').toUpperCase()) {
        case 'ITM': return 'bg-emerald-500/20 text-emerald-400';
        case 'ATM': return 'bg-blue-500/20 text-blue-400';
        case 'OTM': return 'bg-muted/20 text-muted-foreground';
        default:    return 'bg-muted/20 text-muted-foreground';
    }
}

function fmtVol(n) {
    if (n == null) return '—';
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
    return String(n);
}

// ── Loading Skeleton ────────────────────────────────────────────────────────

function SkeletonRow() {
    return (
        <tr className="border-b border-border/40 animate-pulse">
            {[...Array(11)].map((_, i) => (
                <td key={i} className="px-3 py-3">
                    <div className="h-3 bg-muted/40 rounded w-full" />
                </td>
            ))}
        </tr>
    );
}

// ── Put/Call Gauge ──────────────────────────────────────────────────────────

function PutCallPanel({ ticker, onClose }) {
    const [data, setData]       = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError]     = useState(null);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError(null);
        axios.get(`/api/v1/options/put-call/${encodeURIComponent(ticker)}`)
            .then(res => { if (!cancelled) setData(res.data); })
            .catch(e  => { if (!cancelled) setError(e?.response?.data?.detail || 'Failed to load data.'); })
            .finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
    }, [ticker]);

    const signal = data?.signal ?? data?.sentiment ?? null;
    const ratio  = data?.put_call_ratio ?? data?.ratio ?? null;

    const signalStyle = () => {
        switch ((signal ?? '').toUpperCase()) {
            case 'BULLISH': return { text: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30', icon: <TrendingUp size={16} /> };
            case 'BEARISH': return { text: 'text-red-400', bg: 'bg-red-500/10 border-red-500/30', icon: <TrendingDown size={16} /> };
            default:        return { text: 'text-yellow-400', bg: 'bg-yellow-500/10 border-yellow-500/30', icon: <Minus size={16} /> };
        }
    };

    const ss = signalStyle();

    return (
        <div className="rounded-xl border border-border bg-card/80 p-4 flex flex-col gap-3">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <Activity size={15} className="text-primary" />
                    <span className="text-sm font-semibold text-foreground">Put/Call Ratio — {ticker.toUpperCase()}</span>
                </div>
                <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
                    <X size={14} />
                </button>
            </div>

            {loading && (
                <div className="flex items-center justify-center py-6 text-muted-foreground gap-2">
                    <Loader2 size={16} className="animate-spin" />
                    <span className="text-sm">Loading…</span>
                </div>
            )}
            {error && (
                <div className="flex items-center gap-2 text-red-400 text-sm p-2 rounded-lg bg-red-500/10">
                    <AlertCircle size={14} /> {error}
                </div>
            )}
            {!loading && !error && data && (
                <div className="flex items-center gap-6 flex-wrap">
                    {/* Big ratio number */}
                    <div className="flex flex-col items-center">
                        <span className={`text-5xl font-black tabular-nums ${
                            ratio != null
                                ? ratio > 1.2 ? 'text-red-400' : ratio < 0.8 ? 'text-emerald-400' : 'text-yellow-400'
                                : 'text-foreground'
                        }`}>
                            {ratio != null ? Number(ratio).toFixed(2) : '—'}
                        </span>
                        <span className="text-xs text-muted-foreground mt-1">Put/Call Ratio</span>
                    </div>
                    {/* Signal badge */}
                    {signal && (
                        <div className={`flex items-center gap-2 px-4 py-2 rounded-xl border font-semibold text-sm ${ss.bg} ${ss.text}`}>
                            {ss.icon}
                            {signal.toUpperCase()}
                        </div>
                    )}
                    {/* Interpretation */}
                    <div className="flex-1 min-w-[180px]">
                        <p className="text-xs text-muted-foreground leading-relaxed">
                            {data.interpretation ?? (
                                ratio == null ? '' :
                                ratio > 1.2
                                    ? 'Heavy put buying relative to calls — suggests bearish positioning or hedging activity.'
                                    : ratio < 0.8
                                        ? 'Elevated call activity — options traders are positioned for upside.'
                                        : 'Balanced put/call activity — no clear directional bias detected.'
                            )}
                        </p>
                        {data.total_volume != null && (
                            <p className="text-xs text-muted-foreground/60 mt-1">
                                Total volume: {fmtVol(data.total_volume)} contracts
                            </p>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

// ── Main Component ──────────────────────────────────────────────────────────

export default function OptionsFlow() {
    const [country, setCountry]         = useState('US');
    const [minScore, setMinScore]       = useState(30);
    const [searchInput, setSearchInput] = useState('');
    const [activeTicker, setActiveTicker] = useState(null);
    const [flow, setFlow]               = useState([]);
    const [loading, setLoading]         = useState(true);
    const [error, setError]             = useState(null);
    const [lastUpdated, setLastUpdated] = useState(null);
    const [sortKey, setSortKey]         = useState('urgency_score');
    const [sortDir, setSortDir]         = useState('desc');
    const searchRef = useRef(null);

    const fetchFlow = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await axios.get('/api/v1/options/unusual', {
                params: { country, min_score: minScore },
            });
            const raw = Array.isArray(res.data) ? res.data : (res.data?.results ?? res.data?.flow ?? []);
            setFlow(raw);
            setLastUpdated(new Date());
        } catch (e) {
            setError(e?.response?.data?.detail || 'Failed to load unusual options activity.');
        } finally {
            setLoading(false);
        }
    }, [country, minScore]);

    useEffect(() => { fetchFlow(); }, [fetchFlow]);

    const handleSearch = (e) => {
        e.preventDefault();
        const t = searchInput.trim().toUpperCase();
        if (t) setActiveTicker(t);
    };

    const handleSort = (key) => {
        if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
        else { setSortKey(key); setSortDir('desc'); }
    };

    const sorted = [...flow].sort((a, b) => {
        let av = a[sortKey] ?? 0, bv = b[sortKey] ?? 0;
        if (typeof av === 'string') { av = av.toLowerCase(); bv = (bv ?? '').toString().toLowerCase(); }
        if (av < bv) return sortDir === 'asc' ? -1 : 1;
        if (av > bv) return sortDir === 'asc' ? 1 : -1;
        return 0;
    });

    const SortIcon = ({ col }) => (
        <span className={`ml-1 text-[10px] ${sortKey === col ? 'text-primary' : 'text-muted-foreground/40'}`}>
            {sortKey === col ? (sortDir === 'asc' ? '↑' : '↓') : '↕'}
        </span>
    );

    return (
        <div className="space-y-5 p-5 min-h-screen">
            {/* ── Header ── */}
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    <Activity size={20} className="text-primary" />
                    <h1 className="text-lg font-bold text-foreground">Options Flow</h1>
                    {lastUpdated && (
                        <span className="text-xs text-muted-foreground">
                            Updated {lastUpdated.toLocaleTimeString()}
                        </span>
                    )}
                </div>

                <div className="flex items-center gap-2 flex-wrap">
                    {/* Country toggle */}
                    <div className="flex rounded-lg border border-border overflow-hidden text-xs font-medium">
                        {['US', 'IN'].map(c => (
                            <button
                                key={c}
                                onClick={() => setCountry(c)}
                                className={`px-3 py-1.5 transition-colors ${
                                    country === c
                                        ? 'bg-primary text-primary-foreground'
                                        : 'bg-card text-muted-foreground hover:bg-muted/30'
                                }`}
                            >
                                {c}
                            </button>
                        ))}
                    </div>

                    {/* Ticker search */}
                    <form onSubmit={handleSearch} className="flex items-center gap-1">
                        <div className="relative">
                            <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
                            <input
                                ref={searchRef}
                                type="text"
                                value={searchInput}
                                onChange={e => setSearchInput(e.target.value.toUpperCase())}
                                placeholder="Ticker P/C ratio…"
                                className="pl-7 pr-3 py-1.5 rounded-lg border border-border bg-card text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 w-36"
                            />
                        </div>
                        <button
                            type="submit"
                            className="px-2.5 py-1.5 rounded-lg border border-border bg-card text-xs text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors"
                        >
                            Go
                        </button>
                    </form>

                    <button
                        onClick={fetchFlow}
                        disabled={loading}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors text-xs font-medium disabled:opacity-50"
                    >
                        <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
                        Refresh
                    </button>
                </div>
            </div>

            {/* ── Urgency Score Slider ── */}
            <div className="flex items-center gap-3 px-1">
                <span className="text-xs text-muted-foreground shrink-0">Min Urgency Score:</span>
                <input
                    type="range"
                    min={0}
                    max={100}
                    value={minScore}
                    onChange={e => setMinScore(Number(e.target.value))}
                    className="flex-1 max-w-48 accent-primary h-1.5 cursor-pointer"
                />
                <span className={`text-xs font-bold tabular-nums w-6 ${
                    minScore >= 70 ? 'text-red-400' : minScore >= 40 ? 'text-yellow-400' : 'text-muted-foreground'
                }`}>{minScore}</span>
            </div>

            {/* ── Put/Call Panel ── */}
            {activeTicker && (
                <PutCallPanel
                    ticker={activeTicker}
                    onClose={() => { setActiveTicker(null); setSearchInput(''); }}
                />
            )}

            {/* ── Error ── */}
            {error && (
                <div className="flex items-center gap-2 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
                    <AlertCircle size={15} /> {error}
                </div>
            )}

            {/* ── Table ── */}
            <div className="rounded-xl border border-border bg-card/50 overflow-hidden">
                <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-border bg-muted/20">
                                {[
                                    { key: 'urgency_score', label: 'Urgency' },
                                    { key: 'ticker',        label: 'Ticker' },
                                    { key: 'expiry',        label: 'Expiry' },
                                    { key: 'strike',        label: 'Strike' },
                                    { key: 'option_type',   label: 'Type' },
                                    { key: 'volume',        label: 'Volume' },
                                    { key: 'open_interest', label: 'OI' },
                                    { key: 'vol_oi_ratio',  label: 'Vol/OI' },
                                    { key: 'iv',            label: 'IV %' },
                                    { key: 'moneyness',     label: 'Moneyness' },
                                    { key: 'last_price',    label: 'Last' },
                                ].map(col => (
                                    <th
                                        key={col.key}
                                        onClick={() => handleSort(col.key)}
                                        className="px-3 py-2.5 text-left text-xs font-semibold text-muted-foreground cursor-pointer hover:text-foreground select-none whitespace-nowrap"
                                    >
                                        {col.label}<SortIcon col={col.key} />
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {loading && [...Array(10)].map((_, i) => <SkeletonRow key={i} />)}
                            {!loading && sorted.length === 0 && !error && (
                                <tr>
                                    <td colSpan={11} className="px-4 py-10 text-center text-muted-foreground text-sm">
                                        No unusual options activity found. Try lowering the minimum urgency score.
                                    </td>
                                </tr>
                            )}
                            {!loading && sorted.map((row, idx) => {
                                const isCall = (row.option_type ?? row.type ?? '').toUpperCase() === 'CALL';
                                const isPut  = (row.option_type ?? row.type ?? '').toUpperCase() === 'PUT';
                                return (
                                    <tr
                                        key={idx}
                                        className="border-b border-border/40 transition-colors hover:bg-muted/10"
                                    >
                                        <td className="px-3 py-2.5">
                                            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold border tabular-nums ${urgencyStyle(row.urgency_score ?? 0)}`}>
                                                {row.urgency_score ?? '—'}
                                            </span>
                                        </td>
                                        <td className="px-3 py-2.5 font-bold text-foreground">{row.ticker}</td>
                                        <td className="px-3 py-2.5 text-xs text-muted-foreground whitespace-nowrap">
                                            {fmtDate(row.expiry ?? row.expiration_date)}
                                        </td>
                                        <td className="px-3 py-2.5 text-xs font-medium text-foreground tabular-nums">
                                            ${fmt(row.strike, 0) === '—' ? '—' : Number(row.strike).toLocaleString()}
                                        </td>
                                        <td className="px-3 py-2.5">
                                            <span className={`inline-block px-2 py-0.5 rounded text-[11px] font-bold ${
                                                isCall
                                                    ? 'bg-emerald-500/20 text-emerald-400'
                                                    : isPut
                                                        ? 'bg-red-500/20 text-red-400'
                                                        : 'bg-muted/20 text-muted-foreground'
                                            }`}>
                                                {(row.option_type ?? row.type ?? '—').toUpperCase()}
                                            </span>
                                        </td>
                                        <td className="px-3 py-2.5 text-xs text-foreground font-medium tabular-nums">
                                            {fmtVol(row.volume)}
                                        </td>
                                        <td className="px-3 py-2.5 text-xs text-muted-foreground tabular-nums">
                                            {fmtVol(row.open_interest ?? row.oi)}
                                        </td>
                                        <td className="px-3 py-2.5 text-xs text-muted-foreground tabular-nums">
                                            {row.vol_oi_ratio != null ? Number(row.vol_oi_ratio).toFixed(2) : '—'}
                                        </td>
                                        <td className="px-3 py-2.5 text-xs text-muted-foreground tabular-nums">
                                            {row.iv != null ? `${Number(row.iv).toFixed(1)}%` : '—'}
                                        </td>
                                        <td className="px-3 py-2.5">
                                            <span className={`inline-block px-1.5 py-0.5 rounded text-[11px] font-medium ${moneynessStyle(row.moneyness)}`}>
                                                {(row.moneyness ?? '—').toUpperCase()}
                                            </span>
                                        </td>
                                        <td className="px-3 py-2.5 text-xs font-medium text-foreground tabular-nums">
                                            {row.last_price != null ? `$${Number(row.last_price).toFixed(2)}` : '—'}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
                {!loading && flow.length > 0 && (
                    <div className="px-4 py-2 border-t border-border/40 text-xs text-muted-foreground/60">
                        Showing {sorted.length} of {flow.length} entries · sorted by {sortKey.replace(/_/g, ' ')}
                    </div>
                )}
            </div>
        </div>
    );
}
