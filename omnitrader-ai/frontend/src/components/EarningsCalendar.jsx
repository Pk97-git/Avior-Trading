import React, { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import {
    RefreshCw, Loader2, Calendar, TrendingUp, TrendingDown,
    ChevronDown, ChevronRight, AlertCircle, Star, Clock,
    BarChart2, Info,
} from 'lucide-react';
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
    ResponsiveContainer, Cell, ReferenceLine,
} from 'recharts';

// ── Helpers ────────────────────────────────────────────────────────────────

function fmt(val, decimals = 2) {
    if (val == null) return '—';
    return Number(val).toFixed(decimals);
}

function fmtDate(iso) {
    if (!iso) return '—';
    try {
        return new Date(iso).toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric',
        });
    } catch {
        return iso;
    }
}

function scoreColor(score) {
    if (score >= 70) return 'text-emerald-400';
    if (score >= 40) return 'text-yellow-400';
    return 'text-red-400';
}

function scoreBarColor(score) {
    if (score >= 70) return 'bg-emerald-500';
    if (score >= 40) return 'bg-yellow-500';
    return 'bg-red-500';
}

function recBadge(rec) {
    switch (rec) {
        case 'PLAY':    return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30';
        case 'NEUTRAL': return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
        case 'AVOID':   return 'bg-red-500/20 text-red-400 border-red-500/30';
        default:        return 'bg-muted/20 text-muted-foreground border-border';
    }
}

// ── Loading Skeleton ────────────────────────────────────────────────────────

function SkeletonRow() {
    return (
        <tr className="border-b border-border/40 animate-pulse">
            {[...Array(8)].map((_, i) => (
                <td key={i} className="px-3 py-3">
                    <div className="h-3 bg-muted/40 rounded w-full" />
                </td>
            ))}
        </tr>
    );
}

// ── Best Setup Card ─────────────────────────────────────────────────────────

function SetupCard({ setup }) {
    const {
        ticker, setup_score, days_until, beat_rate,
        expected_move_pct, recommendation,
    } = setup;
    const [beats, total] = Array.isArray(beat_rate)
        ? beat_rate
        : [beat_rate?.beats ?? 0, beat_rate?.total ?? 4];

    return (
        <div className={`shrink-0 w-48 rounded-xl border p-3 flex flex-col gap-2 ${
            setup_score >= 70
                ? 'border-emerald-500/30 bg-emerald-500/5'
                : setup_score >= 40
                    ? 'border-yellow-500/30 bg-yellow-500/5'
                    : 'border-red-500/30 bg-red-500/5'
        }`}>
            <div className="flex items-center justify-between">
                <span className="font-bold text-sm text-foreground">{ticker}</span>
                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border ${recBadge(recommendation)}`}>
                    {recommendation}
                </span>
            </div>
            {/* Score bar */}
            <div>
                <div className="flex justify-between text-[10px] text-muted-foreground mb-1">
                    <span>Setup Score</span>
                    <span className={`font-bold ${scoreColor(setup_score)}`}>{setup_score}</span>
                </div>
                <div className="h-1.5 bg-muted/40 rounded-full overflow-hidden">
                    <div
                        className={`h-full rounded-full transition-all ${scoreBarColor(setup_score)}`}
                        style={{ width: `${Math.min(100, setup_score)}%` }}
                    />
                </div>
            </div>
            <div className="flex justify-between text-[10px] text-muted-foreground">
                <div className="flex items-center gap-1">
                    <Clock size={10} />
                    <span className="font-medium text-foreground">{days_until}d</span>
                </div>
                <span>{beats}/{total} beats</span>
                <span className="font-medium text-foreground">±{fmt(expected_move_pct, 1)}%</span>
            </div>
        </div>
    );
}

// ── Reaction History Mini Chart ─────────────────────────────────────────────

function ReactionChart({ reactions }) {
    if (!reactions || reactions.length === 0) {
        return <p className="text-xs text-muted-foreground py-2">No reaction history available.</p>;
    }
    const data = reactions.map((r, i) => ({
        name: `Q${reactions.length - i}`,
        move: typeof r === 'object' ? (r.move ?? r.pct ?? r) : r,
    }));
    return (
        <div className="h-24 w-full mt-2">
            <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#6b7280' }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: '#6b7280' }} axisLine={false} tickLine={false} unit="%" />
                    <Tooltip
                        contentStyle={{ background: 'hsl(222.2 84% 4.9%)', border: '1px solid hsl(217.2 32.6% 17.5%)', borderRadius: 8, fontSize: 11 }}
                        formatter={(v) => [`${v >= 0 ? '+' : ''}${Number(v).toFixed(1)}%`, 'Reaction']}
                    />
                    <ReferenceLine y={0} stroke="rgba(255,255,255,0.15)" />
                    <Bar dataKey="move" radius={[3, 3, 0, 0]}>
                        {data.map((entry, i) => (
                            <Cell key={i} fill={entry.move >= 0 ? '#10b981' : '#ef4444'} />
                        ))}
                    </Bar>
                </BarChart>
            </ResponsiveContainer>
        </div>
    );
}

// ── Main Component ──────────────────────────────────────────────────────────

export default function EarningsCalendar() {
    const [country, setCountry]           = useState('ALL');
    const [daysAhead, setDaysAhead]       = useState(30);
    const [calendar, setCalendar]         = useState([]);
    const [setups, setSetups]             = useState([]);
    const [loading, setLoading]           = useState(true);
    const [setupsLoading, setSetupsLoading] = useState(true);
    const [error, setError]               = useState(null);
    const [expandedRow, setExpandedRow]   = useState(null);
    const [sortKey, setSortKey]           = useState('days_until');
    const [sortDir, setSortDir]           = useState('asc');
    const [lastUpdated, setLastUpdated]   = useState(null);

    const fetchCalendar = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = { days_ahead: daysAhead };
            if (country !== 'ALL') params.country = country;
            else params.country = 'ALL';
            const res = await axios.get('/api/v1/earnings/calendar', { params });
            const raw = Array.isArray(res.data) ? res.data : (res.data?.earnings ?? res.data?.results ?? []);
            setCalendar(raw);
            setLastUpdated(new Date());
        } catch (e) {
            setError(e?.response?.data?.detail || 'Failed to load earnings calendar.');
        } finally {
            setLoading(false);
        }
    }, [country, daysAhead]);

    const fetchSetups = useCallback(async () => {
        setSetupsLoading(true);
        try {
            const res = await axios.get('/api/v1/earnings/calendar/setups/best', {
                params: { days_ahead: 7, min_score: 60 },
            });
            const raw = Array.isArray(res.data) ? res.data : (res.data?.setups ?? res.data?.results ?? []);
            setSetups(raw.slice(0, 5));
        } catch {
            setSetups([]);
        } finally {
            setSetupsLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchCalendar();
        fetchSetups();
    }, [fetchCalendar, fetchSetups]);

    const handleRefresh = () => {
        fetchCalendar();
        fetchSetups();
    };

    const handleSort = (key) => {
        if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
        else { setSortKey(key); setSortDir('asc'); }
    };

    const sorted = [...calendar].sort((a, b) => {
        let av = a[sortKey], bv = b[sortKey];
        if (typeof av === 'string') av = av.toLowerCase();
        if (typeof bv === 'string') bv = bv.toLowerCase();
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
                    <Calendar size={20} className="text-primary" />
                    <h1 className="text-lg font-bold text-foreground">Earnings Calendar</h1>
                    {lastUpdated && (
                        <span className="text-xs text-muted-foreground">
                            Updated {lastUpdated.toLocaleTimeString()}
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                    {/* Country filter */}
                    <div className="flex rounded-lg border border-border overflow-hidden text-xs font-medium">
                        {['ALL', 'US', 'IN'].map(c => (
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
                    {/* Days ahead */}
                    <div className="flex rounded-lg border border-border overflow-hidden text-xs font-medium">
                        {[7, 14, 30].map(d => (
                            <button
                                key={d}
                                onClick={() => setDaysAhead(d)}
                                className={`px-3 py-1.5 transition-colors ${
                                    daysAhead === d
                                        ? 'bg-primary text-primary-foreground'
                                        : 'bg-card text-muted-foreground hover:bg-muted/30'
                                }`}
                            >
                                {d}d
                            </button>
                        ))}
                    </div>
                    <button
                        onClick={handleRefresh}
                        disabled={loading}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors text-xs font-medium disabled:opacity-50"
                    >
                        <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
                        Refresh
                    </button>
                </div>
            </div>

            {/* ── Best Setups Strip ── */}
            <div className="space-y-2">
                <div className="flex items-center gap-2">
                    <Star size={14} className="text-yellow-400" />
                    <span className="text-sm font-semibold text-foreground">Best Pre-Earnings Setups (Next 7 Days)</span>
                    {setupsLoading && <Loader2 size={13} className="animate-spin text-muted-foreground" />}
                </div>
                {!setupsLoading && setups.length === 0 && (
                    <p className="text-xs text-muted-foreground py-2">No high-quality setups found in the next 7 days.</p>
                )}
                {setups.length > 0 && (
                    <div className="flex gap-3 overflow-x-auto pb-2 scrollbar-none">
                        {setups.map((s, i) => <SetupCard key={i} setup={s} />)}
                    </div>
                )}
            </div>

            {/* ── Error ── */}
            {error && (
                <div className="flex items-center gap-2 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
                    <AlertCircle size={15} />
                    {error}
                </div>
            )}

            {/* ── Main Table ── */}
            <div className="rounded-xl border border-border bg-card/50 overflow-hidden">
                <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-border bg-muted/20">
                                {[
                                    { key: 'days_until',     label: 'Days Until' },
                                    { key: 'ticker',         label: 'Ticker' },
                                    { key: 'company_name',   label: 'Company' },
                                    { key: 'sector',         label: 'Sector' },
                                    { key: 'earnings_date',  label: 'Earnings Date' },
                                    { key: 'beat_rate',      label: 'Beat Rate' },
                                    { key: 'expected_move_pct', label: 'Exp. Move' },
                                    { key: 'consensus_eps',  label: 'Cons. EPS' },
                                    { key: 'recommendation', label: 'Signal' },
                                ].map(col => (
                                    <th
                                        key={col.key}
                                        onClick={() => handleSort(col.key)}
                                        className="px-3 py-2.5 text-left text-xs font-semibold text-muted-foreground cursor-pointer hover:text-foreground select-none whitespace-nowrap"
                                    >
                                        {col.label}<SortIcon col={col.key} />
                                    </th>
                                ))}
                                <th className="px-3 py-2.5 w-8" />
                            </tr>
                        </thead>
                        <tbody>
                            {loading && [...Array(8)].map((_, i) => <SkeletonRow key={i} />)}
                            {!loading && sorted.length === 0 && !error && (
                                <tr>
                                    <td colSpan={10} className="px-4 py-10 text-center text-muted-foreground text-sm">
                                        No earnings events found for the selected period.
                                    </td>
                                </tr>
                            )}
                            {!loading && sorted.map((row, idx) => {
                                const isExpanded = expandedRow === idx;
                                const beats = row.beat_rate?.beats ?? row.beats ?? null;
                                const total = row.beat_rate?.total ?? row.total ?? 4;
                                const reactions = row.last_4_reactions ?? row.reactions ?? [];
                                return (
                                    <React.Fragment key={idx}>
                                        <tr
                                            onClick={() => setExpandedRow(isExpanded ? null : idx)}
                                            className={`border-b border-border/40 cursor-pointer transition-colors hover:bg-muted/10 ${
                                                isExpanded ? 'bg-muted/10' : ''
                                            }`}
                                        >
                                            <td className="px-3 py-2.5">
                                                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                                                    (row.days_until ?? 99) <= 3
                                                        ? 'bg-red-500/20 text-red-400'
                                                        : (row.days_until ?? 99) <= 7
                                                            ? 'bg-yellow-500/20 text-yellow-400'
                                                            : 'bg-muted/20 text-muted-foreground'
                                                }`}>
                                                    <Clock size={10} />
                                                    {row.days_until ?? '?'}d
                                                </span>
                                            </td>
                                            <td className="px-3 py-2.5 font-bold text-foreground">{row.ticker}</td>
                                            <td className="px-3 py-2.5 text-muted-foreground max-w-[160px] truncate">
                                                {row.company_name ?? row.name ?? '—'}
                                            </td>
                                            <td className="px-3 py-2.5 text-xs text-muted-foreground">{row.sector ?? '—'}</td>
                                            <td className="px-3 py-2.5 text-xs text-muted-foreground whitespace-nowrap">
                                                {fmtDate(row.earnings_date ?? row.report_date)}
                                            </td>
                                            <td className="px-3 py-2.5 text-xs">
                                                {beats != null
                                                    ? <span className="text-foreground font-medium">{beats}/{total} beats</span>
                                                    : <span className="text-muted-foreground">—</span>
                                                }
                                            </td>
                                            <td className="px-3 py-2.5 text-xs font-medium text-foreground">
                                                {row.expected_move_pct != null
                                                    ? `±${fmt(row.expected_move_pct, 1)}%`
                                                    : '—'
                                                }
                                            </td>
                                            <td className="px-3 py-2.5 text-xs text-muted-foreground tabular-nums">
                                                {row.consensus_eps != null ? `$${fmt(row.consensus_eps, 2)}` : '—'}
                                            </td>
                                            <td className="px-3 py-2.5">
                                                <span className={`inline-block px-2 py-0.5 rounded text-[11px] font-semibold border ${recBadge(row.recommendation)}`}>
                                                    {row.recommendation ?? '—'}
                                                </span>
                                            </td>
                                            <td className="px-3 py-2.5 text-muted-foreground">
                                                {isExpanded
                                                    ? <ChevronDown size={14} />
                                                    : <ChevronRight size={14} />
                                                }
                                            </td>
                                        </tr>
                                        {isExpanded && (
                                            <tr className="bg-muted/5 border-b border-border/40">
                                                <td colSpan={10} className="px-6 py-4">
                                                    <div className="flex flex-col sm:flex-row gap-6">
                                                        <div className="flex-1">
                                                            <p className="text-xs font-semibold text-muted-foreground mb-1 flex items-center gap-1">
                                                                <BarChart2 size={12} />
                                                                Last 4 Post-Earnings Reactions
                                                            </p>
                                                            <ReactionChart reactions={reactions} />
                                                        </div>
                                                        <div className="sm:w-56 space-y-2 text-xs">
                                                            <div className="flex justify-between">
                                                                <span className="text-muted-foreground">Time of Report</span>
                                                                <span className="text-foreground font-medium capitalize">{row.time_of_report ?? row.report_time ?? '—'}</span>
                                                            </div>
                                                            <div className="flex justify-between">
                                                                <span className="text-muted-foreground">Country</span>
                                                                <span className={`font-semibold ${row.country === 'IN' ? 'text-orange-400' : 'text-blue-400'}`}>
                                                                    {row.country ?? 'US'}
                                                                </span>
                                                            </div>
                                                            {row.implied_volatility != null && (
                                                                <div className="flex justify-between">
                                                                    <span className="text-muted-foreground">Implied Vol</span>
                                                                    <span className="text-foreground font-medium">{fmt(row.implied_volatility, 1)}%</span>
                                                                </div>
                                                            )}
                                                            {row.market_cap != null && (
                                                                <div className="flex justify-between">
                                                                    <span className="text-muted-foreground">Market Cap</span>
                                                                    <span className="text-foreground font-medium">{row.market_cap}</span>
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>
                                                </td>
                                            </tr>
                                        )}
                                    </React.Fragment>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
                <div className="px-4 py-2 border-t border-border/40 flex items-center gap-1.5 text-xs text-muted-foreground/60">
                    <Info size={11} />
                    Earnings dates are estimates. Verify before trading.
                </div>
            </div>
        </div>
    );
}
