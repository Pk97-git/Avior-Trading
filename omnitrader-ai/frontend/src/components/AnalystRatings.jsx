import React, { useEffect, useState, useCallback, useRef } from 'react';
import axios from 'axios';
import {
    RefreshCw, Loader2, Search, AlertCircle, TrendingUp,
    TrendingDown, Star, ArrowUp, ArrowDown, Info, X, Minus,
} from 'lucide-react';

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtDate(iso) {
    if (!iso) return '—';
    try {
        return new Date(iso).toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric',
        });
    } catch { return iso; }
}

function fmtPrice(n) {
    if (n == null) return null;
    return '$' + Number(n).toFixed(2);
}

// Normalise action into a category
function normaliseRatingAction(action) {
    if (!action) return 'other';
    const a = String(action).toUpperCase();
    if (a.includes('UPGRADE') || a === 'UP')                      return 'upgrade';
    if (a.includes('DOWNGRADE') || a === 'DOWN')                   return 'downgrade';
    if (a.includes('INIT') || a.includes('COVERAGE') || a === 'I') return 'init';
    if (a.includes('REIT') || a.includes('MAINTAIN') || a.includes('REAFFIRM') || a.includes('CONFIRM')) return 'reiterate';
    return 'other';
}

function actionBadgeStyle(action) {
    const cat = normaliseRatingAction(action);
    switch (cat) {
        case 'upgrade':   return { cls: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30', icon: <ArrowUp size={10} />,    label: 'UPGRADE' };
        case 'downgrade': return { cls: 'bg-red-500/20 text-red-400 border-red-500/30',             icon: <ArrowDown size={10} />,  label: 'DOWNGRADE' };
        case 'init':      return { cls: 'bg-blue-500/20 text-blue-400 border-blue-500/30',           icon: <Star size={10} />,       label: 'INITIATION' };
        case 'reiterate': return { cls: 'bg-slate-500/20 text-slate-400 border-slate-500/30',        icon: <Minus size={10} />,      label: 'REITERATE' };
        default:          return { cls: 'bg-muted/20 text-muted-foreground border-border',           icon: <Minus size={10} />,      label: String(action).slice(0, 10) };
    }
}

// Determine catalyst signal badge
function catalystBadge(action, toGrade) {
    const cat = normaliseRatingAction(action);
    const g   = String(toGrade ?? '').toUpperCase();
    const bullishGrades = ['BUY', 'STRONG BUY', 'OVERWEIGHT', 'OUTPERFORM', 'POSITIVE', 'CONVICTION BUY'];
    const bearishGrades = ['SELL', 'STRONG SELL', 'UNDERWEIGHT', 'UNDERPERFORM', 'NEGATIVE'];

    if (cat === 'upgrade' && bullishGrades.some(b => g.includes(b))) {
        return { text: 'BULLISH CATALYST', cls: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' };
    }
    if (cat === 'downgrade' && bearishGrades.some(b => g.includes(b))) {
        return { text: 'BEARISH CATALYST', cls: 'bg-red-500/20 text-red-400 border-red-500/30' };
    }
    if (cat === 'init' && bullishGrades.some(b => g.includes(b))) {
        return { text: 'NEW BULLISH COVERAGE', cls: 'bg-blue-500/20 text-blue-400 border-blue-500/30' };
    }
    return null;
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

// ── Summary Chips ───────────────────────────────────────────────────────────

function SummaryChips({ ratings }) {
    const week = ratings.filter(r => {
        const d = new Date(r.date ?? r.published_date ?? r.created_at ?? 0);
        return !isNaN(d) && (Date.now() - d.getTime()) < 7 * 86_400_000;
    });

    const upgrades   = week.filter(r => normaliseRatingAction(r.action ?? r.type) === 'upgrade').length;
    const downgrades = week.filter(r => normaliseRatingAction(r.action ?? r.type) === 'downgrade').length;
    const inits      = week.filter(r => normaliseRatingAction(r.action ?? r.type) === 'init').length;

    return (
        <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-muted-foreground">Last 7 days:</span>
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                <ArrowUp size={12} className="text-emerald-400" />
                <span className="text-xs font-bold text-emerald-400">{upgrades}</span>
                <span className="text-xs text-muted-foreground">Upgrades</span>
            </div>
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/20">
                <ArrowDown size={12} className="text-red-400" />
                <span className="text-xs font-bold text-red-400">{downgrades}</span>
                <span className="text-xs text-muted-foreground">Downgrades</span>
            </div>
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-500/10 border border-blue-500/20">
                <Star size={12} className="text-blue-400" />
                <span className="text-xs font-bold text-blue-400">{inits}</span>
                <span className="text-xs text-muted-foreground">Initiations</span>
            </div>
        </div>
    );
}

// ── Ticker Lookup Panel ─────────────────────────────────────────────────────

function TickerLookup({ ticker, onClose }) {
    const [data, setData]       = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError]     = useState(null);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError(null);
        axios.get(`/api/v1/analysts/${encodeURIComponent(ticker)}`)
            .then(res => {
                if (!cancelled) {
                    const raw = Array.isArray(res.data) ? res.data : (res.data?.ratings ?? res.data?.results ?? res.data?.data ?? []);
                    setData(raw);
                }
            })
            .catch(e => { if (!cancelled) setError(e?.response?.data?.detail || 'Failed to load analyst ratings.'); })
            .finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
    }, [ticker]);

    return (
        <div className="rounded-xl border border-primary/30 bg-card/80 p-4 space-y-3">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <TrendingUp size={15} className="text-primary" />
                    <span className="text-sm font-bold text-foreground">All Analyst Ratings — {ticker.toUpperCase()}</span>
                    {!loading && <span className="text-xs text-muted-foreground">({data.length} ratings)</span>}
                </div>
                <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
                    <X size={14} />
                </button>
            </div>

            {loading && (
                <div className="flex items-center justify-center py-6 gap-2 text-muted-foreground">
                    <Loader2 size={15} className="animate-spin" />
                    <span className="text-sm">Loading ratings…</span>
                </div>
            )}
            {error && (
                <div className="flex items-center gap-2 text-red-400 text-sm p-2 rounded-lg bg-red-500/10">
                    <AlertCircle size={14} /> {error}
                </div>
            )}
            {!loading && !error && data.length === 0 && (
                <p className="text-sm text-muted-foreground py-4 text-center">No analyst ratings found for {ticker.toUpperCase()}.</p>
            )}
            {!loading && !error && data.length > 0 && (
                <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                        <thead>
                            <tr className="border-b border-border text-muted-foreground">
                                <th className="px-2 py-2 text-left font-semibold">Date</th>
                                <th className="px-2 py-2 text-left font-semibold">Firm</th>
                                <th className="px-2 py-2 text-left font-semibold">Action</th>
                                <th className="px-2 py-2 text-left font-semibold">From → To</th>
                                <th className="px-2 py-2 text-right font-semibold">Price Target</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.map((row, i) => {
                                const badge = actionBadgeStyle(row.action ?? row.type ?? row.rating_change);
                                return (
                                    <tr key={i} className="border-b border-border/30 hover:bg-muted/10">
                                        <td className="px-2 py-2 text-muted-foreground whitespace-nowrap">{fmtDate(row.date ?? row.published_date)}</td>
                                        <td className="px-2 py-2 text-foreground font-medium max-w-[140px] truncate">{row.firm ?? row.analyst_firm ?? row.analyst ?? '—'}</td>
                                        <td className="px-2 py-2">
                                            <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-semibold ${badge.cls}`}>
                                                {badge.icon}{badge.label}
                                            </span>
                                        </td>
                                        <td className="px-2 py-2">
                                            <span className="text-muted-foreground">{row.from_grade ?? row.previous_rating ?? '—'}</span>
                                            {(row.from_grade ?? row.previous_rating) && <span className="text-muted-foreground/40 mx-1">→</span>}
                                            <span className="text-foreground font-medium">{row.to_grade ?? row.current_rating ?? row.rating ?? '—'}</span>
                                        </td>
                                        <td className="px-2 py-2 text-right tabular-nums text-foreground font-medium">
                                            {fmtPrice(row.price_target ?? row.target_price) ?? '—'}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}

// ── Main Component ──────────────────────────────────────────────────────────

export default function AnalystRatings() {
    const [country, setCountry]           = useState('US');
    const [action, setAction]             = useState('all');
    const [days, setDays]                 = useState(14);
    const [ratings, setRatings]           = useState([]);
    const [loading, setLoading]           = useState(true);
    const [error, setError]               = useState(null);
    const [lastUpdated, setLastUpdated]   = useState(null);
    const [sortKey, setSortKey]           = useState('date');
    const [sortDir, setSortDir]           = useState('desc');
    const [searchInput, setSearchInput]   = useState('');
    const [activeTicker, setActiveTicker] = useState(null);
    const searchRef = useRef(null);

    const fetchRatings = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = { days, action };
            if (country !== 'ALL') params.country = country;
            const res = await axios.get('/api/v1/analysts/recent', { params });
            const raw = Array.isArray(res.data) ? res.data : (res.data?.ratings ?? res.data?.results ?? res.data?.data ?? []);
            setRatings(raw);
            setLastUpdated(new Date());
        } catch (e) {
            setError(e?.response?.data?.detail || 'Failed to load analyst ratings.');
        } finally {
            setLoading(false);
        }
    }, [country, action, days]);

    useEffect(() => { fetchRatings(); }, [fetchRatings]);

    const handleSearch = (e) => {
        e.preventDefault();
        const t = searchInput.trim().toUpperCase();
        if (t) setActiveTicker(t);
    };

    const handleSort = (key) => {
        if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
        else { setSortKey(key); setSortDir('desc'); }
    };

    const sorted = [...ratings].sort((a, b) => {
        let av = a[sortKey] ?? '', bv = b[sortKey] ?? '';
        if (sortKey === 'date') {
            av = new Date(av).getTime() || 0;
            bv = new Date(bv).getTime() || 0;
        } else if (typeof av === 'string') {
            av = av.toLowerCase(); bv = (bv ?? '').toString().toLowerCase();
        }
        if (av < bv) return sortDir === 'asc' ? -1 : 1;
        if (av > bv) return sortDir === 'asc' ? 1 : -1;
        return 0;
    });

    const SortIcon = ({ col }) => (
        <span className={`ml-1 text-[10px] ${sortKey === col ? 'text-primary' : 'text-muted-foreground/40'}`}>
            {sortKey === col ? (sortDir === 'asc' ? '↑' : '↓') : '↕'}
        </span>
    );

    const actionOptions = [
        { label: 'All',          value: 'all' },
        { label: 'Upgrades',     value: 'upgrade' },
        { label: 'Downgrades',   value: 'downgrade' },
        { label: 'Initiations',  value: 'init' },
    ];

    return (
        <div className="space-y-5 p-5 min-h-screen">

            {/* ── Header ── */}
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    <TrendingUp size={20} className="text-primary" />
                    <h1 className="text-lg font-bold text-foreground">Analyst Ratings</h1>
                    {lastUpdated && (
                        <span className="text-xs text-muted-foreground">
                            Updated {lastUpdated.toLocaleTimeString()}
                        </span>
                    )}
                </div>

                <div className="flex items-center gap-2 flex-wrap">
                    {/* Country */}
                    <div className="flex rounded-lg border border-border overflow-hidden text-xs font-medium">
                        {['US', 'IN', 'ALL'].map(c => (
                            <button key={c} onClick={() => setCountry(c)}
                                className={`px-3 py-1.5 transition-colors ${country === c ? 'bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted/30'}`}>
                                {c}
                            </button>
                        ))}
                    </div>
                    {/* Action filter */}
                    <div className="flex rounded-lg border border-border overflow-hidden text-xs font-medium">
                        {actionOptions.map(opt => (
                            <button key={opt.value} onClick={() => setAction(opt.value)}
                                className={`px-3 py-1.5 transition-colors ${action === opt.value ? 'bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted/30'}`}>
                                {opt.label}
                            </button>
                        ))}
                    </div>
                    {/* Days */}
                    <div className="flex rounded-lg border border-border overflow-hidden text-xs font-medium">
                        {[7, 30, 90].map(d => (
                            <button key={d} onClick={() => setDays(d)}
                                className={`px-3 py-1.5 transition-colors ${days === d ? 'bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted/30'}`}>
                                {d}d
                            </button>
                        ))}
                    </div>
                    {/* Ticker lookup */}
                    <form onSubmit={handleSearch} className="flex items-center gap-1">
                        <div className="relative">
                            <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
                            <input
                                ref={searchRef}
                                type="text"
                                value={searchInput}
                                onChange={e => setSearchInput(e.target.value.toUpperCase())}
                                placeholder="Ticker lookup…"
                                className="pl-7 pr-2.5 py-1.5 rounded-lg border border-border bg-card text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 w-32"
                            />
                        </div>
                        <button type="submit" className="px-2.5 py-1.5 rounded-lg border border-border bg-card text-xs text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors">Go</button>
                    </form>
                    {/* Refresh */}
                    <button onClick={fetchRatings} disabled={loading}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors text-xs font-medium disabled:opacity-50">
                        <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
                        Refresh
                    </button>
                </div>
            </div>

            {/* ── Summary Chips ── */}
            {!loading && ratings.length > 0 && <SummaryChips ratings={ratings} />}
            {loading && (
                <div className="flex items-center gap-2 animate-pulse">
                    {[...Array(3)].map((_, i) => <div key={i} className="h-8 w-36 rounded-lg bg-muted/30" />)}
                </div>
            )}

            {/* ── Ticker Lookup Panel ── */}
            {activeTicker && (
                <TickerLookup
                    ticker={activeTicker}
                    onClose={() => { setActiveTicker(null); setSearchInput(''); }}
                />
            )}

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
                                    { key: 'date',         label: 'Date' },
                                    { key: 'ticker',       label: 'Ticker / Name' },
                                    { key: 'firm',         label: 'Firm' },
                                    { key: 'action',       label: 'Action' },
                                    { key: 'from_grade',   label: 'Grade Change' },
                                    { key: 'price_target', label: 'Price Target' },
                                    { key: 'signal',       label: 'Signal Impact' },
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
                                    <td colSpan={7} className="px-4 py-12 text-center">
                                        <div className="flex flex-col items-center gap-2 text-muted-foreground">
                                            <TrendingUp size={28} className="opacity-30" />
                                            <p className="text-sm">No analyst ratings found for the selected filters.</p>
                                            <p className="text-xs opacity-60">Try expanding the days range or changing the action filter.</p>
                                        </div>
                                    </td>
                                </tr>
                            )}
                            {!loading && sorted.map((row, idx) => {
                                const actionCode = row.action ?? row.type ?? row.rating_change;
                                const badge      = actionBadgeStyle(actionCode);
                                const fromGrade  = row.from_grade ?? row.previous_rating ?? null;
                                const toGrade    = row.to_grade   ?? row.current_rating  ?? row.rating ?? null;
                                const pt         = row.price_target ?? row.target_price  ?? null;
                                const catalyst   = catalystBadge(actionCode, toGrade);
                                const cat        = normaliseRatingAction(actionCode);

                                const rowBg = cat === 'upgrade'
                                    ? 'hover:bg-emerald-500/5'
                                    : cat === 'downgrade'
                                        ? 'hover:bg-red-500/5'
                                        : 'hover:bg-muted/10';

                                return (
                                    <tr key={idx} className={`border-b border-border/40 transition-colors ${rowBg}`}>
                                        <td className="px-3 py-2.5 text-xs text-muted-foreground whitespace-nowrap">
                                            {fmtDate(row.date ?? row.published_date ?? row.created_at)}
                                        </td>
                                        <td className="px-3 py-2.5">
                                            <div className="flex flex-col">
                                                <button
                                                    onClick={() => setActiveTicker(row.ticker ?? row.symbol)}
                                                    className="font-bold text-foreground hover:text-primary transition-colors text-left"
                                                >
                                                    {row.ticker ?? row.symbol ?? '—'}
                                                </button>
                                                <span className="text-[11px] text-muted-foreground truncate max-w-[140px]">
                                                    {row.company_name ?? row.company ?? row.name ?? ''}
                                                </span>
                                            </div>
                                        </td>
                                        <td className="px-3 py-2.5 text-xs text-muted-foreground max-w-[150px] truncate">
                                            {row.firm ?? row.analyst_firm ?? row.analyst ?? '—'}
                                        </td>
                                        <td className="px-3 py-2.5">
                                            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[11px] font-semibold ${badge.cls}`}>
                                                {badge.icon}{badge.label}
                                            </span>
                                        </td>
                                        <td className="px-3 py-2.5 text-xs">
                                            {fromGrade || toGrade ? (
                                                <div className="flex items-center gap-1">
                                                    {fromGrade && <span className="text-muted-foreground">{fromGrade}</span>}
                                                    {fromGrade && toGrade && <span className="text-muted-foreground/40">→</span>}
                                                    {toGrade && (
                                                        <span className={`font-semibold ${
                                                            cat === 'upgrade' ? 'text-emerald-400' :
                                                            cat === 'downgrade' ? 'text-red-400' :
                                                            cat === 'init' ? 'text-blue-400' :
                                                            'text-foreground'
                                                        }`}>
                                                            {toGrade}
                                                        </span>
                                                    )}
                                                </div>
                                            ) : (
                                                <span className="text-muted-foreground/40">—</span>
                                            )}
                                        </td>
                                        <td className="px-3 py-2.5 text-xs font-medium text-foreground tabular-nums">
                                            {fmtPrice(pt) ?? <span className="text-muted-foreground/40">—</span>}
                                        </td>
                                        <td className="px-3 py-2.5">
                                            {catalyst ? (
                                                <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-bold ${catalyst.cls}`}>
                                                    {catalyst.text.includes('BULLISH') ? <TrendingUp size={9} /> : <TrendingDown size={9} />}
                                                    {catalyst.text}
                                                </span>
                                            ) : (
                                                <span className="text-muted-foreground/40 text-[11px]">—</span>
                                            )}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
                {!loading && ratings.length > 0 && (
                    <div className="px-4 py-2 border-t border-border/40 flex items-center justify-between">
                        <span className="text-xs text-muted-foreground/60">
                            {sorted.length} rating{sorted.length !== 1 ? 's' : ''}
                        </span>
                        <span className="text-xs text-muted-foreground/50 flex items-center gap-1">
                            <Info size={10} />
                            Analyst ratings are opinions. Not investment advice.
                        </span>
                    </div>
                )}
            </div>
        </div>
    );
}
