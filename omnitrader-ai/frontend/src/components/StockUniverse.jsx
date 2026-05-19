import React, { useEffect, useState, useCallback } from 'react';
import { ingestionApi } from '../api';
import { Loader2, Globe, Activity, CheckCircle2, Clock, AlertCircle, RefreshCw, Search, SlidersHorizontal, ChevronUp, ChevronDown, Zap } from 'lucide-react';
import StockDetailView from './shared/StockDetailView';

// ─── Utility ─────────────────────────────────────────────────────────────────

const Badge = ({ label, active, onClick, color = 'primary' }) => (
    <button
        onClick={onClick}
        className={`px-3 py-1 text-xs font-medium rounded-full border transition-all ${active
            ? 'bg-primary text-primary-foreground border-primary'
            : 'border-border text-muted-foreground hover:border-primary/50 hover:text-foreground'
            }`}
    >
        {label}
    </button>
);

const StatusBadge = ({ row }) => {
    if (!row.has_data) {
        return (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-muted text-muted-foreground border border-border">
                <Clock className="w-2.5 h-2.5" /> Pending
            </span>
        );
    }
    if (row.is_current) {
        return (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-500/10 text-emerald-500 border border-emerald-500/20">
                <CheckCircle2 className="w-2.5 h-2.5" /> Current
            </span>
        );
    }
    return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-500/10 text-amber-500 border border-amber-500/20">
            <Activity className="w-2.5 h-2.5" /> Stale
        </span>
    );
};

const HistoryBar = ({ years }) => {
    if (!years) return <span className="text-muted-foreground text-xs">—</span>;
    const pct = Math.min((years / 20) * 100, 100);
    const color = years >= 10 ? 'bg-emerald-500' : years >= 5 ? 'bg-blue-500' : years >= 1 ? 'bg-amber-400' : 'bg-orange-400';
    return (
        <div className="flex items-center gap-2">
            <div className="w-16 h-1.5 bg-muted rounded-full overflow-hidden">
                <div className={`${color} h-full rounded-full`} style={{ width: `${pct}%` }} />
            </div>
            <span className="text-xs font-mono text-muted-foreground">{years}y</span>
        </div>
    );
};

// ─── Main Component ──────────────────────────────────────────────────────────

export default function StockUniverse({ onNavigate }) {
    // Data
    const [data, setData] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [sectors, setSectors] = useState([]);

    // Filters
    const [search, setSearch] = useState('');
    const [debouncedSearch, setDebouncedSearch] = useState('');
    const [country, setCountry] = useState('ALL');
    const [sector, setSector] = useState('ALL');
    const [dataStatus, setDataStatus] = useState('ALL');   // ALL | has_data | pending | current
    const [minYears, setMinYears] = useState(0);

    // Pagination + Sort
    const [page, setPage] = useState(1);
    const [limit] = useState(100);
    const [totalPages, setTotalPages] = useState(1);
    const [sortKey, setSortKey] = useState('ticker');
    const [sortDir, setSortDir] = useState('asc');

    // Detail overlay
    const [selectedTicker, setSelectedTicker] = useState(null);
    const [toastMessage, setToastMessage] = useState(null);

    // ── Debounce search ──
    useEffect(() => {
        const h = setTimeout(() => { setDebouncedSearch(search); setPage(1); }, 400);
        return () => clearTimeout(h);
    }, [search]);

    // ── Load sectors for filter pills ──
    useEffect(() => {
        ingestionApi.getSectorBreakdown()
            .then(r => setSectors(r.data.sectors.map(s => s.sector).filter(Boolean).slice(0, 15)))
            .catch(() => { });
    }, []);

    // ── Fetch data whenever filters change ──
    const load = useCallback(async () => {
        setLoading(true);
        try {
            const filters = {};
            if (country !== 'ALL') filters.country = country;
            if (sector !== 'ALL') filters.sector = sector;
            if (dataStatus === 'has_data') filters.has_data = true;
            if (dataStatus === 'pending') filters.has_data = false;
            if (dataStatus === 'current') { filters.has_data = true; }
            if (minYears > 0) filters.min_years = minYears;

            const res = await ingestionApi.getTickers(page, limit, debouncedSearch || null, filters);
            let rows = res.data.data || [];

            // Client-side "current" filter (backend returns is_current field)
            if (dataStatus === 'current') rows = rows.filter(r => r.is_current);

            // Client-side sort
            rows = [...rows].sort((a, b) => {
                let av = a[sortKey] ?? '';
                let bv = b[sortKey] ?? '';
                if (typeof av === 'string') av = av.toLowerCase();
                if (typeof bv === 'string') bv = bv.toLowerCase();
                if (av < bv) return sortDir === 'asc' ? -1 : 1;
                if (av > bv) return sortDir === 'asc' ? 1 : -1;
                return 0;
            });

            setData(rows);
            setTotal(res.data.total || 0);
            setTotalPages(Math.ceil((res.data.total || 0) / limit) || 1);
        } catch (err) {
            console.error(err);
            setData([]);
        } finally {
            setLoading(false);
        }
    }, [page, limit, debouncedSearch, country, sector, dataStatus, minYears, sortKey, sortDir]);

    useEffect(() => { load(); }, [load]);

    const handleSort = (key) => {
        if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
        else { setSortKey(key); setSortDir('asc'); }
    };

    const SortIcon = ({ col }) => {
        if (sortKey !== col) return <ChevronUp className="w-3 h-3 opacity-20" />;
        return sortDir === 'asc' ? <ChevronUp className="w-3 h-3 text-primary" /> : <ChevronDown className="w-3 h-3 text-primary" />;
    };

    const showToast = (msg) => {
        setToastMessage(msg);
        setTimeout(() => setToastMessage(null), 3000);
    };

    const toast = (msg, dur = 3000) => { setToastMessage(msg); setTimeout(() => setToastMessage(null), dur); };

    return (
        <div className="flex flex-col h-[calc(100vh-100px)] gap-4 animate-in fade-in duration-500">
            {/* Detail Overlay */}
            {selectedTicker && <StockDetailView ticker={selectedTicker} onClose={() => setSelectedTicker(null)} />}

            {/* Header */}
            <div className="bg-card border border-border rounded-lg p-5 shrink-0">
                <div className="flex flex-col md:flex-row gap-4 justify-between">
                    <div>
                        <h2 className="text-2xl font-bold flex items-center gap-2">
                            <Globe className="h-6 w-6 text-primary" /> Stock Universe
                        </h2>
                        <p className="text-muted-foreground text-sm mt-1">
                            {total.toLocaleString()} stocks · Click any row for detailed analysis
                        </p>
                    </div>

                    {/* Search */}
                    <div className="relative w-full md:w-80">
                        <Search className="absolute left-3 top-2.5 w-4 h-4 text-muted-foreground" />
                        <input
                            type="text"
                            placeholder="Search ticker or company..."
                            value={search}
                            onChange={e => { setSearch(e.target.value); setPage(1); }}
                            className="w-full pl-9 pr-4 py-2.5 bg-background border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-primary text-sm"
                        />
                        {search && (
                            <button onClick={() => setSearch('')} className="absolute right-3 top-2.5 text-muted-foreground hover:text-foreground">✕</button>
                        )}
                    </div>
                </div>
            </div>

            {/* Filter Bar */}
            <div className="bg-card border border-border rounded-lg p-4 shrink-0 space-y-3">
                <div className="flex items-center gap-2 flex-wrap">
                    <SlidersHorizontal className="w-4 h-4 text-muted-foreground" />
                    <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Country</span>
                    {['ALL', 'US', 'IN'].map(c => (
                        <Badge key={c} label={c} active={country === c} onClick={() => { setCountry(c); setPage(1); }} />
                    ))}

                    <div className="w-px h-4 bg-border mx-1" />
                    <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Status</span>
                    {[['ALL', 'All'], ['has_data', 'Has Data'], ['current', 'Current ✓'], ['pending', 'Pending']].map(([v, l]) => (
                        <Badge key={v} label={l} active={dataStatus === v} onClick={() => { setDataStatus(v); setPage(1); }} />
                    ))}
                </div>

                <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Sector</span>
                    <Badge label="ALL" active={sector === 'ALL'} onClick={() => { setSector('ALL'); setPage(1); }} />
                    {sectors.map(s => (
                        <Badge key={s} label={s} active={sector === s} onClick={() => { setSector(s === sector ? 'ALL' : s); setPage(1); }} />
                    ))}
                </div>

                <div className="flex items-center gap-3">
                    <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">Min History</span>
                    <input
                        type="range" min={0} max={20} step={1} value={minYears}
                        onChange={e => { setMinYears(Number(e.target.value)); setPage(1); }}
                        className="w-32 accent-primary"
                    />
                    <span className="text-xs font-mono text-muted-foreground w-16">
                        {minYears === 0 ? 'Any' : `${minYears}+ yrs`}
                    </span>
                    {(country !== 'ALL' || sector !== 'ALL' || dataStatus !== 'ALL' || minYears > 0 || search) && (
                        <button
                            onClick={() => { setCountry('ALL'); setSector('ALL'); setDataStatus('ALL'); setMinYears(0); setSearch(''); setPage(1); }}
                            className="ml-auto text-xs text-muted-foreground hover:text-foreground flex items-center gap-1 border border-border rounded px-2 py-1"
                        >
                            <RefreshCw className="w-3 h-3" /> Clear filters
                        </button>
                    )}
                </div>
            </div>

            {/* Table */}
            <div className="flex-1 flex flex-col rounded-lg border border-border overflow-hidden bg-card min-h-0">
                {loading ? (
                    <div className="flex-1 flex items-center justify-center">
                        <Loader2 className="w-8 h-8 animate-spin text-primary" />
                    </div>
                ) : data.length === 0 ? (
                    <div className="flex-1 flex items-center justify-center text-muted-foreground">
                        No stocks match the current filters.
                    </div>
                ) : (
                    <div className="flex-1 overflow-auto">
                        <table className="w-full text-sm relative">
                            <thead className="bg-muted/50 border-b border-border sticky top-0 z-10 backdrop-blur-sm">
                                <tr>
                                    {[
                                        ['ticker', 'Ticker'],
                                        ['name', 'Company'],
                                        ['sector', 'Sector'],
                                        ['country', 'Country'],
                                        ['years_of_data', 'History'],
                                        ['last_date', 'Last Updated'],
                                        ['is_current', 'Status'],
                                    ].map(([key, label]) => (
                                        <th
                                            key={key}
                                            onClick={() => handleSort(key)}
                                            className="px-4 py-3 text-left font-medium text-muted-foreground whitespace-nowrap cursor-pointer hover:text-foreground select-none"
                                        >
                                            <div className="flex items-center gap-1">
                                                {label} <SortIcon col={key} />
                                            </div>
                                        </th>
                                    ))}
                                    <th className="px-4 py-3 text-right font-medium text-muted-foreground whitespace-nowrap select-none">
                                        Actions
                                    </th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border">
                                {data.map((row, i) => (
                                    <tr
                                        key={i}
                                        onClick={() => {
                                            if (!row.has_data) {
                                                toast(`${row.ticker} is pending ingestion.`);
                                                return;
                                            }
                                            setSelectedTicker(row.ticker);
                                        }}
                                        className={`group transition-colors hover:bg-muted/40 ${row.has_data ? 'cursor-pointer' : 'cursor-not-allowed opacity-60'}`}
                                    >
                                        <td className="px-4 py-2.5 font-mono font-bold text-sm group-hover:text-primary transition-colors">
                                            {row.ticker}
                                        </td>
                                        <td className="px-4 py-2.5 max-w-[200px] truncate text-sm">
                                            {row.name || '—'}
                                        </td>
                                        <td className="px-4 py-2.5 text-xs text-muted-foreground">
                                            {row.sector || '—'}
                                        </td>
                                        <td className="px-4 py-2.5">
                                            <span className={`text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded ${row.country === 'US' ? 'bg-blue-500/10 text-blue-500' : 'bg-orange-500/10 text-orange-500'
                                                }`}>
                                                {row.country}
                                            </span>
                                        </td>
                                        <td className="px-4 py-2.5">
                                            <HistoryBar years={row.years_of_data} />
                                        </td>
                                        <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">
                                            {row.last_date || '—'}
                                        </td>
                                        <td className="px-4 py-2.5">
                                            <StatusBadge row={row} />
                                        </td>
                                        <td className="px-4 py-2.5 text-right">
                                            {row.has_data && onNavigate && (
                                                <button
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        onNavigate('hub', row.ticker);
                                                    }}
                                                    className="inline-flex items-center px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wider bg-primary/10 text-primary hover:bg-primary hover:text-primary-foreground rounded transition-colors whitespace-nowrap border border-primary/20"
                                                >
                                                    <Zap className="w-3 h-3 mr-1 fill-current" />
                                                    AI Deep Dive
                                                </button>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}

                {/* Pagination */}
                <div className="shrink-0 flex items-center justify-between px-4 py-3 border-t border-border bg-muted/10">
                    <span className="text-sm text-muted-foreground">
                        Page <strong>{page}</strong> of <strong>{totalPages}</strong> · {total.toLocaleString()} total
                    </span>
                    <div className="flex gap-2">
                        <button
                            onClick={() => setPage(p => Math.max(1, p - 1))}
                            disabled={page === 1}
                            className="px-3 py-1.5 text-sm border border-border rounded-md hover:bg-muted disabled:opacity-40"
                        >
                            Previous
                        </button>
                        <button
                            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                            disabled={page >= totalPages}
                            className="px-3 py-1.5 text-sm border border-border rounded-md hover:bg-muted disabled:opacity-40"
                        >
                            Next
                        </button>
                    </div>
                </div>
            </div>

            {/* Toast */}
            {toastMessage && (
                <div className="fixed bottom-6 right-6 bg-yellow-500/10 border border-yellow-500/40 text-yellow-600 dark:text-yellow-400 px-4 py-3 rounded-md shadow-lg flex items-center gap-3 z-50 animate-in slide-in-from-bottom-4 fade-in duration-300">
                    <AlertCircle className="w-5 h-5 flex-shrink-0" />
                    <span className="text-sm font-medium">{toastMessage}</span>
                </div>
            )}
        </div>
    );
}
