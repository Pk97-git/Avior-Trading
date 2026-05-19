import React, { useEffect, useState, useCallback } from 'react';
import { watchlistApi } from '../api';
import { Loader2, RefreshCw, Plus, Trash2, Star, ChevronUp, ChevronDown } from 'lucide-react';
import { SignalBadge } from './shared/SignalCard';
import { useLivePrices } from '../hooks/useLivePrices';

const PRIORITY_CONFIG = {
    HIGH:   { label: 'High',   cls: 'bg-red-500/10 text-red-400 border-red-500/20' },
    MEDIUM: { label: 'Medium', cls: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20' },
    LOW:    { label: 'Low',    cls: 'bg-muted text-muted-foreground border-border' },
};

function PriorityBadge({ priority }) {
    const cfg = PRIORITY_CONFIG[priority] || PRIORITY_CONFIG.MEDIUM;
    return (
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border ${cfg.cls}`}>
            {cfg.label}
        </span>
    );
}

function AddTickerForm({ onAdd }) {
    const [ticker, setTicker]     = useState('');
    const [priority, setPriority] = useState('MEDIUM');
    const [notes, setNotes]       = useState('');
    const [adding, setAdding]     = useState(false);
    const [err, setErr]           = useState(null);

    const submit = async (e) => {
        e.preventDefault();
        const t = ticker.trim().toUpperCase();
        if (!t) return;
        setAdding(true);
        setErr(null);
        try {
            await watchlistApi.addTicker(t, priority, notes || null);
            setTicker('');
            setNotes('');
            onAdd();
        } catch (error) {
            setErr(error?.response?.data?.detail || `${t} not found in universe. Ensure it has been ingested first.`);
        } finally {
            setAdding(false);
        }
    };

    return (
        <form onSubmit={submit} className="rounded-xl border border-border bg-card/50 p-4">
            <h3 className="font-semibold text-sm mb-3 flex items-center gap-2">
                <Plus className="h-4 w-4" /> Add to Watchlist
            </h3>
            <div className="flex flex-wrap gap-3">
                <input
                    type="text"
                    placeholder="Ticker (e.g. AAPL, RELIANCE.NS)"
                    value={ticker}
                    onChange={e => setTicker(e.target.value.toUpperCase())}
                    className="flex-1 min-w-[160px] px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                />
                <select
                    value={priority}
                    onChange={e => setPriority(e.target.value)}
                    className="px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                >
                    <option value="HIGH">High Priority</option>
                    <option value="MEDIUM">Medium Priority</option>
                    <option value="LOW">Low Priority</option>
                </select>
                <input
                    type="text"
                    placeholder="Notes (optional)"
                    value={notes}
                    onChange={e => setNotes(e.target.value)}
                    className="flex-1 min-w-[160px] px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                />
                <button
                    type="submit"
                    disabled={adding || !ticker.trim()}
                    className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50 hover:opacity-90 transition-opacity"
                >
                    {adding ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
                    Add
                </button>
            </div>
            {err && <p className="mt-2 text-xs text-red-400">{err}</p>}
        </form>
    );
}

export default function Watchlist({ onNavigate }) {
    const [items, setItems]       = useState([]);
    const [total, setTotal]       = useState(0);
    const [loading, setLoading]   = useState(true);
    const [error, setError]       = useState(null);
    const [removing, setRemoving] = useState(null);
    const [sortBy, setSortBy]     = useState('priority'); // priority | signal | score
    const [sortDir, setSortDir]   = useState('desc');

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await watchlistApi.getWatchlist();
            setItems(res.data.items || []);
            setTotal(res.data.total || 0);
        } catch (e) {
            setError(e?.response?.data?.detail || 'Failed to load watchlist.');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const remove = async (ticker) => {
        setRemoving(ticker);
        try {
            await watchlistApi.removeTicker(ticker);
            setItems(prev => prev.filter(i => i.ticker !== ticker));
            setTotal(prev => prev - 1);
        } catch (e) {
            console.error('Remove failed:', e);
        } finally {
            setRemoving(null);
        }
    };

    const toggleSort = (field) => {
        if (sortBy === field) {
            setSortDir(d => d === 'asc' ? 'desc' : 'asc');
        } else {
            setSortBy(field);
            setSortDir('desc');
        }
    };

    const PRIORITY_ORDER = { HIGH: 3, MEDIUM: 2, LOW: 1 };
    const SIGNAL_ORDER   = { STRONG_BUY: 4, ACCUMULATE: 3, AVOID: 2, DISTRIBUTION: 1 };

    const sorted = [...items].sort((a, b) => {
        let cmp = 0;
        if (sortBy === 'priority') cmp = (PRIORITY_ORDER[a.priority] || 0) - (PRIORITY_ORDER[b.priority] || 0);
        if (sortBy === 'signal')   cmp = (SIGNAL_ORDER[a.signal] || 0) - (SIGNAL_ORDER[b.signal] || 0);
        if (sortBy === 'score')    cmp = (a.final_score || 0) - (b.final_score || 0);
        return sortDir === 'asc' ? cmp : -cmp;
    });

    const liveTickers = items.map(i => i.ticker);
    const { prices: livePrices } = useLivePrices(liveTickers);

    const SortIcon = ({ field }) => {
        if (sortBy !== field) return null;
        return sortDir === 'asc'
            ? <ChevronUp className="h-3 w-3 inline ml-0.5" />
            : <ChevronDown className="h-3 w-3 inline ml-0.5" />;
    };

    return (
        <div className="space-y-5">

            {/* ── Header ── */}
            <div className="flex items-center justify-between flex-wrap gap-3">
                <div>
                    <h2 className="text-xl font-bold flex items-center gap-2">
                        <Star className="h-5 w-5 text-yellow-400" /> Watchlist
                    </h2>
                    <p className="text-sm text-muted-foreground">
                        {total} ticker{total !== 1 ? 's' : ''} · sorted by {sortBy}
                    </p>
                </div>
                <button
                    onClick={load}
                    className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground px-3 py-1.5 rounded-md border border-border hover:bg-accent transition-colors"
                >
                    <RefreshCw className="h-4 w-4" /> Refresh
                </button>
            </div>

            {/* ── Add form ── */}
            <AddTickerForm onAdd={load} />

            {/* ── Table ── */}
            <div className="rounded-xl border border-border overflow-hidden bg-card/50">
                {loading ? (
                    <div className="flex items-center justify-center h-48 gap-2 text-muted-foreground">
                        <Loader2 className="animate-spin h-5 w-5" /> Loading watchlist…
                    </div>
                ) : error ? (
                    <div className="flex flex-col items-center justify-center h-48 gap-2 text-red-400">
                        <p>{error}</p>
                        <button onClick={load} className="text-sm text-muted-foreground underline">Retry</button>
                    </div>
                ) : sorted.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-48 text-muted-foreground space-y-2">
                        <Star className="h-8 w-8 opacity-20" />
                        <p className="text-sm">No tickers in watchlist. Add one above.</p>
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead className="bg-muted/40 border-b border-border text-muted-foreground text-xs">
                                <tr>
                                    <th className="text-left px-4 py-3 font-medium">Ticker</th>
                                    <th
                                        className="text-left px-4 py-3 font-medium cursor-pointer hover:text-foreground select-none"
                                        onClick={() => toggleSort('priority')}
                                    >
                                        Priority <SortIcon field="priority" />
                                    </th>
                                    <th
                                        className="text-left px-4 py-3 font-medium cursor-pointer hover:text-foreground select-none"
                                        onClick={() => toggleSort('signal')}
                                    >
                                        Signal <SortIcon field="signal" />
                                    </th>
                                    <th
                                        className="text-right px-4 py-3 font-medium cursor-pointer hover:text-foreground select-none"
                                        onClick={() => toggleSort('score')}
                                    >
                                        Score <SortIcon field="score" />
                                    </th>
                                    <th className="text-right px-4 py-3 font-medium">Price</th>
                                    <th className="text-left px-4 py-3 font-medium hidden md:table-cell">Notes</th>
                                    <th className="text-right px-4 py-3 font-medium">Action</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border/40">
                                {sorted.map(item => (
                                    <tr
                                        key={item.ticker}
                                        className="hover:bg-muted/20 transition-colors cursor-pointer"
                                        onClick={() => onNavigate?.('hub', item.ticker)}
                                    >
                                        <td className="px-4 py-3">
                                            <div className="font-bold text-sm">{item.ticker}</div>
                                            {item.name && (
                                                <div className="text-[11px] text-muted-foreground truncate max-w-[160px]">
                                                    {item.name}
                                                </div>
                                            )}
                                            {item.country && (
                                                <span className={`text-[9px] px-1.5 py-0.5 rounded-sm font-bold uppercase ${
                                                    item.country === 'IN'
                                                        ? 'bg-orange-500/10 text-orange-500'
                                                        : 'bg-blue-500/10 text-blue-500'
                                                }`}>
                                                    {item.country}
                                                </span>
                                            )}
                                        </td>
                                        <td className="px-4 py-3">
                                            <PriorityBadge priority={item.priority} />
                                        </td>
                                        <td className="px-4 py-3">
                                            {item.signal
                                                ? <SignalBadge signal={item.signal} size="sm" />
                                                : <span className="text-xs text-muted-foreground/50">—</span>
                                            }
                                        </td>
                                        <td className="px-4 py-3 text-right">
                                            {item.final_score != null ? (
                                                <span className={`inline-flex items-center justify-center min-w-[2rem] px-2 h-7 rounded-full text-xs font-bold ${
                                                    item.final_score >= 70 ? 'bg-emerald-500/15 text-emerald-500' :
                                                    item.final_score >= 50 ? 'bg-blue-500/15 text-blue-500' :
                                                    'bg-yellow-500/15 text-yellow-600'
                                                }`}>
                                                    {item.final_score}
                                                </span>
                                            ) : <span className="text-muted-foreground/50 text-xs">—</span>}
                                        </td>
                                        <td className="px-4 py-3 text-right tabular-nums text-xs font-semibold">
                                            {(() => {
                                                const live = livePrices[item.ticker];
                                                const displayPrice = live?.price ?? item.current_price;
                                                const changeColor = live?.change_pct > 0 ? 'text-emerald-400' : live?.change_pct < 0 ? 'text-red-400' : '';
                                                if (displayPrice == null) return <span className="text-muted-foreground/50">—</span>;
                                                return (
                                                    <span>
                                                        ${displayPrice.toLocaleString()}
                                                        {live?.change_pct != null && (
                                                            <span className={`ml-1 ${changeColor}`}>
                                                                ({live.change_pct >= 0 ? '+' : ''}{live.change_pct.toFixed(2)}%)
                                                            </span>
                                                        )}
                                                    </span>
                                                );
                                            })()}
                                        </td>
                                        <td className="px-4 py-3 text-xs text-muted-foreground hidden md:table-cell max-w-[200px] truncate">
                                            {item.notes || '—'}
                                        </td>
                                        <td className="px-4 py-3 text-right" onClick={e => e.stopPropagation()}>
                                            <button
                                                onClick={() => remove(item.ticker)}
                                                disabled={removing === item.ticker}
                                                className="p-1.5 text-muted-foreground hover:text-red-400 hover:bg-red-500/10 rounded transition-colors disabled:opacity-50"
                                                title="Remove from watchlist"
                                            >
                                                {removing === item.ticker
                                                    ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                                    : <Trash2 className="h-3.5 w-3.5" />
                                                }
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {/* ── Tip ── */}
            <p className="text-xs text-muted-foreground px-1">
                Click any row to open the Intelligence Hub deep-dive for that ticker.
            </p>
        </div>
    );
}
