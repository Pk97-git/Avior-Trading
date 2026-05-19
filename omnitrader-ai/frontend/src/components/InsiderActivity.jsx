import React, { useEffect, useState, useCallback, useRef } from 'react';
import axios from 'axios';
import {
    RefreshCw, Loader2, Search, AlertCircle, User,
    TrendingUp, TrendingDown, Info, X, ChevronUp, ChevronDown,
    Award, Zap, BarChart2,
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

function fmtValue(n) {
    if (n == null) return '—';
    if (Math.abs(n) >= 1_000_000_000) return '$' + (n / 1_000_000_000).toFixed(2) + 'B';
    if (Math.abs(n) >= 1_000_000)     return '$' + (n / 1_000_000).toFixed(2) + 'M';
    if (Math.abs(n) >= 1_000)         return '$' + (n / 1_000).toFixed(1) + 'K';
    return '$' + Number(n).toLocaleString();
}

function fmtShares(n) {
    if (n == null) return '—';
    if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M';
    if (Math.abs(n) >= 1_000)     return (n / 1_000).toFixed(1) + 'K';
    return Number(n).toLocaleString();
}

function fmtPrice(n) {
    if (n == null) return '—';
    return '$' + Number(n).toFixed(2);
}

// action code -> normalised label
function normaliseAction(code) {
    if (!code) return { label: '—', type: 'other' };
    const c = String(code).toUpperCase();
    if (c === 'P' || c.includes('PURCH') || c.includes('BUY')) return { label: 'BUY',   type: 'buy' };
    if (c === 'S' || c.includes('SALE') || c.includes('SELL')) return { label: 'SELL',  type: 'sell' };
    if (c === 'A' || c.includes('AWARD') || c.includes('GRANT')) return { label: 'AWARD', type: 'award' };
    return { label: code.toUpperCase().slice(0, 6), type: 'other' };
}

function actionBadge(action) {
    const { label, type } = normaliseAction(action);
    const cls = {
        buy:   'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
        sell:  'bg-red-500/20 text-red-400 border-red-500/30',
        award: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
        other: 'bg-muted/20 text-muted-foreground border-border',
    }[type];
    const icon = type === 'buy'
        ? <TrendingUp size={10} />
        : type === 'sell'
            ? <TrendingDown size={10} />
            : type === 'award'
                ? <Award size={10} />
                : null;
    return { label, type, cls, icon };
}

function signalBadge(signal) {
    if (!signal) return null;
    const s = String(signal).toUpperCase();
    if (s.includes('CLUSTER') || s.includes('STRONG'))
        return { text: signal, cls: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' };
    if (s.includes('BULLISH') || s.includes('POSITIVE'))
        return { text: signal, cls: 'bg-blue-500/20 text-blue-400 border-blue-500/30' };
    if (s.includes('BEARISH') || s.includes('SELL'))
        return { text: signal, cls: 'bg-red-500/20 text-red-400 border-red-500/30' };
    return { text: signal, cls: 'bg-muted/20 text-muted-foreground border-border' };
}

function rowHighlight(action, value) {
    const { type } = normaliseAction(action);
    const v = Number(value) || 0;
    if (type === 'buy'  && v >= 100_000) return 'bg-emerald-500/5 hover:bg-emerald-500/10';
    if (type === 'sell' && v >= 500_000) return 'bg-red-500/5 hover:bg-red-500/10';
    return 'hover:bg-muted/10';
}

// ── Loading Skeleton ────────────────────────────────────────────────────────

function SkeletonRow({ cols = 11 }) {
    return (
        <tr className="border-b border-border/40 animate-pulse">
            {[...Array(cols)].map((_, i) => (
                <td key={i} className="px-3 py-3">
                    <div className="h-3 bg-muted/40 rounded w-full" />
                </td>
            ))}
        </tr>
    );
}

// ── Universe Stats Strip ────────────────────────────────────────────────────

function UniverseStats({ stats, loading }) {
    if (loading) {
        return (
            <div className="flex items-center gap-2 animate-pulse">
                {[...Array(4)].map((_, i) => (
                    <div key={i} className="h-8 w-36 rounded-lg bg-muted/30" />
                ))}
            </div>
        );
    }
    if (!stats) return null;

    const clusterBuys  = stats.cluster_buys ?? stats.cluster_buy_count ?? 0;
    const topBought    = stats.top_bought  ?? stats.top_bought_ticker  ?? null;
    const topSold      = stats.top_sold    ?? stats.top_sold_ticker    ?? null;
    const totalTxns    = stats.total_transactions ?? stats.total_txns  ?? null;

    return (
        <div className="flex items-center gap-2 flex-wrap">
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                <Zap size={12} className="text-emerald-400" />
                <span className="text-xs font-semibold text-emerald-400">
                    {clusterBuys} Cluster Buys
                </span>
                <span className="text-[10px] text-muted-foreground">(3+ insiders)</span>
            </div>
            {topBought && (
                <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-500/10 border border-blue-500/20">
                    <TrendingUp size={12} className="text-blue-400" />
                    <span className="text-[10px] text-muted-foreground">Top Bought</span>
                    <span className="text-xs font-bold text-blue-400">
                        {typeof topBought === 'object' ? (topBought.ticker ?? topBought.symbol ?? JSON.stringify(topBought)) : topBought}
                    </span>
                </div>
            )}
            {topSold && (
                <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/20">
                    <TrendingDown size={12} className="text-red-400" />
                    <span className="text-[10px] text-muted-foreground">Top Sold</span>
                    <span className="text-xs font-bold text-red-400">
                        {typeof topSold === 'object' ? (topSold.ticker ?? topSold.symbol ?? JSON.stringify(topSold)) : topSold}
                    </span>
                </div>
            )}
            {totalTxns != null && (
                <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-muted/20 border border-border">
                    <BarChart2 size={12} className="text-muted-foreground" />
                    <span className="text-xs text-muted-foreground">
                        <span className="text-foreground font-medium">{Number(totalTxns).toLocaleString()}</span> total txns
                    </span>
                </div>
            )}
        </div>
    );
}

// ── Signal Legend ───────────────────────────────────────────────────────────

function SignalLegend() {
    const [open, setOpen] = useState(false);
    return (
        <div className="rounded-xl border border-border/60 bg-card/40 overflow-hidden">
            <button
                onClick={() => setOpen(o => !o)}
                className="w-full flex items-center justify-between px-4 py-2.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
                <div className="flex items-center gap-1.5">
                    <Info size={12} />
                    <span className="font-medium">Signal Legend — How to Read Insider Signals</span>
                </div>
                {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </button>
            {open && (
                <div className="px-4 py-3 border-t border-border/40 grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                    <div className="space-y-2">
                        <div className="flex items-start gap-2">
                            <span className="mt-0.5 px-1.5 py-0.5 rounded border text-[10px] font-semibold bg-emerald-500/20 text-emerald-400 border-emerald-500/30 shrink-0">CLUSTER BUY</span>
                            <p className="text-muted-foreground">3 or more insiders at the same company bought shares within a short window. Historically one of the strongest bullish signals.</p>
                        </div>
                        <div className="flex items-start gap-2">
                            <span className="mt-0.5 px-1.5 py-0.5 rounded border text-[10px] font-semibold bg-blue-500/20 text-blue-400 border-blue-500/30 shrink-0">BULLISH</span>
                            <p className="text-muted-foreground">Open-market purchase by an officer or director. Insiders only buy when they believe the stock is undervalued.</p>
                        </div>
                    </div>
                    <div className="space-y-2">
                        <div className="flex items-start gap-2">
                            <span className="mt-0.5 px-1.5 py-0.5 rounded border text-[10px] font-semibold bg-red-500/20 text-red-400 border-red-500/30 shrink-0">BEARISH</span>
                            <p className="text-muted-foreground">Large open-market sale ≥ $500K. Note: insiders sell for many reasons (diversification, tax), so treat sells with less conviction than buys.</p>
                        </div>
                        <div className="flex items-start gap-2">
                            <span className="mt-0.5 px-1.5 py-0.5 rounded border text-[10px] font-semibold bg-slate-500/20 text-slate-400 border-slate-500/30 shrink-0">AWARD</span>
                            <p className="text-muted-foreground">Compensation award or grant — not a discretionary trade. Generally neutral signal.</p>
                        </div>
                    </div>
                    <div className="sm:col-span-2 pt-1 border-t border-border/30 text-muted-foreground/70">
                        Row highlighted <span className="text-emerald-400">green</span> = purchase ≥ $100K &nbsp;·&nbsp; Row highlighted <span className="text-red-400">red</span> = sale ≥ $500K
                    </div>
                </div>
            )}
        </div>
    );
}

// ── Ticker Detail Panel ─────────────────────────────────────────────────────

function TickerDetail({ ticker, onClose }) {
    const [data, setData]       = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError]     = useState(null);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError(null);
        axios.get(`/api/v1/insiders/${encodeURIComponent(ticker)}`)
            .then(res => {
                if (!cancelled) {
                    const raw = Array.isArray(res.data) ? res.data : (res.data?.transactions ?? res.data?.results ?? res.data?.data ?? []);
                    setData(raw);
                }
            })
            .catch(e => { if (!cancelled) setError(e?.response?.data?.detail || 'Failed to load ticker data.'); })
            .finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
    }, [ticker]);

    return (
        <div className="rounded-xl border border-primary/30 bg-card/80 p-4 space-y-3">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <User size={15} className="text-primary" />
                    <span className="text-sm font-bold text-foreground">Insider History — {ticker.toUpperCase()}</span>
                    {!loading && <span className="text-xs text-muted-foreground">({data.length} transactions)</span>}
                </div>
                <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
                    <X size={14} />
                </button>
            </div>

            {loading && (
                <div className="flex items-center justify-center py-6 gap-2 text-muted-foreground">
                    <Loader2 size={15} className="animate-spin" />
                    <span className="text-sm">Loading insider history…</span>
                </div>
            )}
            {error && (
                <div className="flex items-center gap-2 text-red-400 text-sm p-2 rounded-lg bg-red-500/10">
                    <AlertCircle size={14} /> {error}
                </div>
            )}
            {!loading && !error && data.length === 0 && (
                <p className="text-sm text-muted-foreground py-4 text-center">No insider transactions found for {ticker.toUpperCase()}.</p>
            )}
            {!loading && !error && data.length > 0 && (
                <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                        <thead>
                            <tr className="border-b border-border text-muted-foreground">
                                <th className="px-2 py-2 text-left font-semibold">Filed</th>
                                <th className="px-2 py-2 text-left font-semibold">Insider</th>
                                <th className="px-2 py-2 text-left font-semibold">Role</th>
                                <th className="px-2 py-2 text-left font-semibold">Action</th>
                                <th className="px-2 py-2 text-right font-semibold">Shares</th>
                                <th className="px-2 py-2 text-right font-semibold">Price</th>
                                <th className="px-2 py-2 text-right font-semibold">Value</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.map((row, i) => {
                                const { label, cls, icon } = actionBadge(row.action ?? row.transaction_type);
                                return (
                                    <tr key={i} className={`border-b border-border/30 ${rowHighlight(row.action ?? row.transaction_type, row.total_value ?? row.value)}`}>
                                        <td className="px-2 py-2 text-muted-foreground whitespace-nowrap">{fmtDate(row.filed_date ?? row.date)}</td>
                                        <td className="px-2 py-2 text-foreground font-medium max-w-[140px] truncate">{row.insider_name ?? row.name ?? '—'}</td>
                                        <td className="px-2 py-2 text-muted-foreground max-w-[100px] truncate">{row.role ?? row.title ?? '—'}</td>
                                        <td className="px-2 py-2">
                                            <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-semibold ${cls}`}>
                                                {icon}{label}
                                            </span>
                                        </td>
                                        <td className="px-2 py-2 text-right tabular-nums text-foreground">{fmtShares(row.shares ?? row.quantity)}</td>
                                        <td className="px-2 py-2 text-right tabular-nums text-muted-foreground">{fmtPrice(row.price ?? row.trade_price)}</td>
                                        <td className="px-2 py-2 text-right tabular-nums font-medium text-foreground">{fmtValue(row.total_value ?? row.value)}</td>
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

export default function InsiderActivity() {
    const [country, setCountry]         = useState('US');
    const [action, setAction]           = useState('all');
    const [days, setDays]               = useState(14);
    const [minValue, setMinValue]       = useState(50000);
    const [transactions, setTransactions] = useState([]);
    const [stats, setStats]             = useState(null);
    const [loading, setLoading]         = useState(true);
    const [statsLoading, setStatsLoading] = useState(true);
    const [error, setError]             = useState(null);
    const [lastUpdated, setLastUpdated] = useState(null);
    const [sortKey, setSortKey]         = useState('filed_date');
    const [sortDir, setSortDir]         = useState('desc');
    const [searchInput, setSearchInput] = useState('');
    const [activeTicker, setActiveTicker] = useState(null);
    const searchRef = useRef(null);

    const fetchTransactions = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = { days, min_value: minValue, action };
            if (country !== 'ALL') params.country = country;
            const res = await axios.get('/api/v1/insiders/recent', { params });
            const raw = Array.isArray(res.data) ? res.data : (res.data?.transactions ?? res.data?.results ?? res.data?.data ?? []);
            setTransactions(raw);
            setLastUpdated(new Date());
        } catch (e) {
            setError(e?.response?.data?.detail || 'Failed to load insider transactions.');
        } finally {
            setLoading(false);
        }
    }, [country, action, days, minValue]);

    const fetchStats = useCallback(async () => {
        setStatsLoading(true);
        try {
            const res = await axios.get('/api/v1/insiders/stats/universe');
            setStats(res.data ?? null);
        } catch {
            setStats(null);
        } finally {
            setStatsLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchTransactions();
        fetchStats();
    }, [fetchTransactions, fetchStats]);

    const handleRefresh = () => { fetchTransactions(); fetchStats(); };

    const handleSort = (key) => {
        if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
        else { setSortKey(key); setSortDir('desc'); }
    };

    const handleSearch = (e) => {
        e.preventDefault();
        const t = searchInput.trim().toUpperCase();
        if (t) setActiveTicker(t);
    };

    const sorted = [...transactions].sort((a, b) => {
        let av = a[sortKey] ?? '', bv = b[sortKey] ?? '';
        if (sortKey === 'filed_date') {
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

    const minValueOptions = [
        { label: '$0',    value: 0 },
        { label: '$10K',  value: 10_000 },
        { label: '$50K',  value: 50_000 },
        { label: '$100K', value: 100_000 },
        { label: '$500K', value: 500_000 },
    ];

    return (
        <div className="space-y-5 p-5 min-h-screen">

            {/* ── Header ── */}
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    <User size={20} className="text-primary" />
                    <h1 className="text-lg font-bold text-foreground">Insider Transactions</h1>
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
                    {/* Action */}
                    <div className="flex rounded-lg border border-border overflow-hidden text-xs font-medium">
                        {[
                            { label: 'All',       value: 'all' },
                            { label: 'Purchases', value: 'P' },
                            { label: 'Sales',     value: 'S' },
                        ].map(opt => (
                            <button key={opt.value} onClick={() => setAction(opt.value)}
                                className={`px-3 py-1.5 transition-colors ${action === opt.value ? 'bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted/30'}`}>
                                {opt.label}
                            </button>
                        ))}
                    </div>
                    {/* Days */}
                    <div className="flex rounded-lg border border-border overflow-hidden text-xs font-medium">
                        {[7, 14, 30, 90].map(d => (
                            <button key={d} onClick={() => setDays(d)}
                                className={`px-3 py-1.5 transition-colors ${days === d ? 'bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted/30'}`}>
                                {d}d
                            </button>
                        ))}
                    </div>
                    {/* Min value */}
                    <div className="flex rounded-lg border border-border overflow-hidden text-xs font-medium">
                        {minValueOptions.map(opt => (
                            <button key={opt.value} onClick={() => setMinValue(opt.value)}
                                className={`px-2.5 py-1.5 transition-colors ${minValue === opt.value ? 'bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted/30'}`}>
                                {opt.label}
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
                                placeholder="Ticker history…"
                                className="pl-7 pr-2.5 py-1.5 rounded-lg border border-border bg-card text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 w-32"
                            />
                        </div>
                        <button type="submit" className="px-2.5 py-1.5 rounded-lg border border-border bg-card text-xs text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors">Go</button>
                    </form>
                    {/* Refresh */}
                    <button onClick={handleRefresh} disabled={loading}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors text-xs font-medium disabled:opacity-50">
                        <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
                        Refresh
                    </button>
                </div>
            </div>

            {/* ── Universe Stats Strip ── */}
            <div className="space-y-1.5">
                <p className="text-xs font-semibold text-muted-foreground flex items-center gap-1">
                    <Zap size={11} className="text-yellow-400" />
                    Universe Statistics
                </p>
                <UniverseStats stats={stats} loading={statsLoading} />
            </div>

            {/* ── Signal Legend ── */}
            <SignalLegend />

            {/* ── Ticker Detail Panel ── */}
            {activeTicker && (
                <TickerDetail
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
                                    { key: 'filed_date',   label: 'Filed Date' },
                                    { key: 'ticker',       label: 'Ticker / Company' },
                                    { key: 'sector',       label: 'Sector' },
                                    { key: 'insider_name', label: 'Insider Name' },
                                    { key: 'role',         label: 'Role' },
                                    { key: 'action',       label: 'Action' },
                                    { key: 'shares',       label: 'Shares' },
                                    { key: 'price',        label: 'Price' },
                                    { key: 'total_value',  label: 'Total Value' },
                                    { key: 'signal',       label: 'Signal' },
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
                                    <td colSpan={10} className="px-4 py-12 text-center">
                                        <div className="flex flex-col items-center gap-2 text-muted-foreground">
                                            <User size={28} className="opacity-30" />
                                            <p className="text-sm">No insider transactions found for the selected filters.</p>
                                            <p className="text-xs opacity-60">Try adjusting the days range or lowering the minimum value.</p>
                                        </div>
                                    </td>
                                </tr>
                            )}
                            {!loading && sorted.map((row, idx) => {
                                const actionCode = row.action ?? row.transaction_type ?? row.type;
                                const value      = row.total_value ?? row.value ?? row.amount;
                                const { label, cls, icon } = actionBadge(actionCode);
                                const sig = signalBadge(row.signal ?? row.signal_type);
                                return (
                                    <tr
                                        key={idx}
                                        className={`border-b border-border/40 transition-colors ${rowHighlight(actionCode, value)}`}
                                    >
                                        <td className="px-3 py-2.5 text-xs text-muted-foreground whitespace-nowrap">
                                            {fmtDate(row.filed_date ?? row.date ?? row.transaction_date)}
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
                                                    {row.company_name ?? row.company ?? ''}
                                                </span>
                                            </div>
                                        </td>
                                        <td className="px-3 py-2.5 text-xs text-muted-foreground max-w-[100px] truncate">
                                            {row.sector ?? '—'}
                                        </td>
                                        <td className="px-3 py-2.5 text-xs text-foreground max-w-[140px] truncate">
                                            {row.insider_name ?? row.name ?? '—'}
                                        </td>
                                        <td className="px-3 py-2.5 text-xs text-muted-foreground max-w-[110px] truncate">
                                            {row.role ?? row.title ?? '—'}
                                        </td>
                                        <td className="px-3 py-2.5">
                                            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[11px] font-semibold ${cls}`}>
                                                {icon}{label}
                                            </span>
                                        </td>
                                        <td className="px-3 py-2.5 text-xs text-foreground tabular-nums font-medium">
                                            {fmtShares(row.shares ?? row.quantity ?? row.num_shares)}
                                        </td>
                                        <td className="px-3 py-2.5 text-xs text-muted-foreground tabular-nums">
                                            {fmtPrice(row.price ?? row.trade_price)}
                                        </td>
                                        <td className="px-3 py-2.5 text-xs font-bold tabular-nums">
                                            <span className={
                                                normaliseAction(actionCode).type === 'buy'
                                                    ? 'text-emerald-400'
                                                    : normaliseAction(actionCode).type === 'sell'
                                                        ? 'text-red-400'
                                                        : 'text-foreground'
                                            }>
                                                {fmtValue(value)}
                                            </span>
                                        </td>
                                        <td className="px-3 py-2.5">
                                            {sig ? (
                                                <span className={`inline-block px-1.5 py-0.5 rounded border text-[10px] font-semibold ${sig.cls}`}>
                                                    {sig.text}
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
                {!loading && transactions.length > 0 && (
                    <div className="px-4 py-2 border-t border-border/40 flex items-center justify-between">
                        <span className="text-xs text-muted-foreground/60">
                            {sorted.length} transaction{sorted.length !== 1 ? 's' : ''}
                        </span>
                        <span className="text-xs text-muted-foreground/50 flex items-center gap-1">
                            <Info size={10} />
                            Form 4 filings. Not investment advice.
                        </span>
                    </div>
                )}
            </div>
        </div>
    );
}
