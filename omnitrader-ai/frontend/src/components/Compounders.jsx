import React, { useEffect, useState, useCallback } from 'react';
import { agentsApi } from '../api';
import { Loader2, RefreshCw } from 'lucide-react';

const CLASS_CONFIG = {
    COMPOUNDER:        { label: 'Compounder',        bg: 'bg-emerald-500/15', text: 'text-emerald-400', border: 'border-emerald-500/30' },
    ACCUMULATION_ZONE: { label: 'Accumulation Zone', bg: 'bg-blue-500/15',    text: 'text-blue-400',    border: 'border-blue-500/30'    },
    OVERVALUED_WAIT:   { label: 'Overvalued — Wait', bg: 'bg-yellow-500/15',  text: 'text-yellow-400',  border: 'border-yellow-500/30'  },
    INSUFFICIENT_DATA: { label: 'Insufficient Data', bg: 'bg-muted/20',       text: 'text-muted-foreground', border: 'border-border'    },
};

const COUNTRY_OPTIONS = ['ALL', 'US', 'IN'];

function ClassBadge({ cls }) {
    const cfg = CLASS_CONFIG[cls] || CLASS_CONFIG.INSUFFICIENT_DATA;
    return (
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border ${cfg.bg} ${cfg.text} ${cfg.border}`}>
            {cfg.label}
        </span>
    );
}

function fmt(val, decimals = 1, suffix = '') {
    if (val == null) return '—';
    return `${val.toFixed(decimals)}${suffix}`;
}

export default function Compounders() {
    const [items,   setItems]   = useState([]);
    const [total,   setTotal]   = useState(0);
    const [country, setCountry] = useState('ALL');
    const [loading, setLoading] = useState(true);
    const [error,   setError]   = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = {};
            if (country !== 'ALL') params.country = country;
            const res = await agentsApi.getCompounders(params);
            setItems(res.data.items || []);
            setTotal(res.data.total || 0);
        } catch (e) {
            setError(e?.response?.data?.detail || 'Failed to load compounders screen.');
        } finally {
            setLoading(false);
        }
    }, [country]);

    useEffect(() => { load(); }, [load]);

    // Count per classification
    const counts = items.reduce((acc, item) => {
        acc[item.classification] = (acc[item.classification] || 0) + 1;
        return acc;
    }, {});

    return (
        <div className="space-y-5">

            {/* ── Header ── */}
            <div className="flex items-center justify-between flex-wrap gap-3">
                <div>
                    <h2 className="text-xl font-bold">Compounders Screen</h2>
                    <p className="text-sm text-muted-foreground">
                        Long-term quality filter · MEDIUM-tier equities · {total} stocks screened
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    {/* Country toggle */}
                    <div className="flex rounded-md border border-border overflow-hidden text-xs">
                        {COUNTRY_OPTIONS.map(c => (
                            <button
                                key={c}
                                onClick={() => setCountry(c)}
                                className={`px-3 py-1.5 font-medium transition-colors ${
                                    country === c
                                        ? 'bg-primary text-primary-foreground'
                                        : 'hover:bg-accent text-muted-foreground'
                                }`}
                            >
                                {c === 'ALL' ? 'All Markets' : c}
                            </button>
                        ))}
                    </div>
                    <button
                        onClick={load}
                        className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground px-3 py-1.5 rounded-md border border-border hover:bg-accent transition-colors"
                    >
                        <RefreshCw className="h-4 w-4" /> Refresh
                    </button>
                </div>
            </div>

            {/* ── Classification summary pills ── */}
            {!loading && items.length > 0 && (
                <div className="flex gap-2 flex-wrap">
                    {Object.entries(CLASS_CONFIG).map(([key, cfg]) => counts[key] ? (
                        <span key={key} className={`px-3 py-1 rounded-full text-xs font-semibold border ${cfg.bg} ${cfg.text} ${cfg.border}`}>
                            {counts[key]} {cfg.label}
                        </span>
                    ) : null)}
                </div>
            )}

            {/* ── Screening criteria legend ── */}
            <div className="rounded-xl border border-border bg-card/50 px-4 py-3 text-xs text-muted-foreground flex flex-wrap gap-4">
                <span><span className="text-emerald-400 font-semibold">Compounder</span> = Revenue CAGR &gt; 12% AND ROIC &gt; 15% AND D/E &lt; 1.0</span>
                <span><span className="text-blue-400 font-semibold">Accumulation Zone</span> = 2 of 3 criteria met, reasonable valuation</span>
                <span><span className="text-yellow-400 font-semibold">Overvalued — Wait</span> = Quality business but P/E &gt; 40</span>
            </div>

            {/* ── Table ── */}
            <div className="rounded-xl border border-border overflow-hidden bg-card/50">
                {loading ? (
                    <div className="flex items-center justify-center h-48 gap-2 text-muted-foreground">
                        <Loader2 className="animate-spin h-5 w-5" /> Screening {total || ''} stocks…
                    </div>
                ) : error ? (
                    <div className="flex flex-col items-center justify-center h-48 gap-2 text-red-400">
                        <p>{error}</p>
                        <button onClick={load} className="text-sm text-muted-foreground underline">Retry</button>
                    </div>
                ) : items.length === 0 ? (
                    <div className="flex items-center justify-center h-48 text-muted-foreground text-sm">
                        No data available. Ensure fundamentals have been ingested for MEDIUM-tier tickers.
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead className="bg-muted/40 border-b border-border text-muted-foreground text-xs">
                                <tr>
                                    <th className="text-left px-4 py-3 font-medium">Ticker</th>
                                    <th className="text-left px-4 py-3 font-medium">Classification</th>
                                    <th className="text-right px-4 py-3 font-medium">Rev CAGR</th>
                                    <th className="text-right px-4 py-3 font-medium">ROIC</th>
                                    <th className="text-right px-4 py-3 font-medium">D/E</th>
                                    <th className="text-right px-4 py-3 font-medium hidden sm:table-cell">P/E</th>
                                    <th className="text-right px-4 py-3 font-medium hidden md:table-cell">Periods</th>
                                    <th className="text-left px-4 py-3 font-medium hidden lg:table-cell">Reason</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border/40">
                                {items.map(item => {
                                    const cls = item.classification;
                                    const isCompounder = cls === 'COMPOUNDER';
                                    return (
                                        <tr key={item.ticker} className="hover:bg-muted/20 transition-colors">
                                            <td className="px-4 py-3">
                                                <span className={`font-bold text-xs ${isCompounder ? 'text-emerald-400' : ''}`}>
                                                    {item.ticker}
                                                </span>
                                            </td>
                                            <td className="px-4 py-3">
                                                <ClassBadge cls={cls} />
                                            </td>
                                            <td className={`px-4 py-3 text-right tabular-nums text-xs font-semibold ${item.revenue_cagr_pct > 12 ? 'text-emerald-400' : item.revenue_cagr_pct != null ? 'text-muted-foreground' : 'text-muted-foreground/50'}`}>
                                                {fmt(item.revenue_cagr_pct, 1, '%')}
                                            </td>
                                            <td className={`px-4 py-3 text-right tabular-nums text-xs font-semibold ${item.roic > 15 ? 'text-emerald-400' : item.roic != null ? 'text-muted-foreground' : 'text-muted-foreground/50'}`}>
                                                {fmt(item.roic, 1, '%')}
                                            </td>
                                            <td className={`px-4 py-3 text-right tabular-nums text-xs ${item.debt_to_equity < 1 ? 'text-emerald-400 font-semibold' : item.debt_to_equity != null ? 'text-red-400' : 'text-muted-foreground/50'}`}>
                                                {fmt(item.debt_to_equity, 2)}
                                            </td>
                                            <td className="px-4 py-3 text-right tabular-nums text-xs text-muted-foreground hidden sm:table-cell">
                                                {fmt(item.pe_ratio, 1, 'x')}
                                            </td>
                                            <td className="px-4 py-3 text-right tabular-nums text-xs text-muted-foreground hidden md:table-cell">
                                                {item.periods_available ?? '—'}
                                            </td>
                                            <td className="px-4 py-3 text-xs text-muted-foreground hidden lg:table-cell max-w-[280px] truncate" title={item.reason}>
                                                {item.reason}
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    );
}
