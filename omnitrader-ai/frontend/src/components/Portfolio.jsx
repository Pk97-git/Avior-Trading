import React, { useEffect, useState, useCallback } from 'react';
import { portfolioApi } from '../api';
import { SignalBadge } from './shared/SignalCard';
import { useLivePrices } from '../hooks/useLivePrices';
import {
    Loader2, RefreshCw, Plus, ChevronDown, ChevronUp,
    TrendingUp, TrendingDown, DollarSign, Briefcase,
    X, Check, Edit2, AlertTriangle,
} from 'lucide-react';

// ─── Formatters ────────────────────────────────────────────────────────────────

function fmt$(n, decimals = 2) {
    if (n == null) return '—';
    return `$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
}

function fmtPct(n) {
    if (n == null) return '—';
    const sign = n >= 0 ? '+' : '';
    return `${sign}${n.toFixed(2)}%`;
}

function fmtDate(d) {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

// ─── Sub-components ────────────────────────────────────────────────────────────

function SummaryCard({ label, value, sub, positive, negative, icon: Icon }) {
    const valueColor = positive
        ? 'text-emerald-400'
        : negative
        ? 'text-red-400'
        : 'text-foreground';

    return (
        <div className="rounded-xl border border-border bg-card/50 p-4 flex flex-col gap-1">
            <div className="flex items-center gap-2 text-xs text-muted-foreground font-medium">
                {Icon && <Icon className="h-3.5 w-3.5" />}
                {label}
            </div>
            <div className={`text-xl font-bold tabular-nums ${valueColor}`}>{value}</div>
            {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
        </div>
    );
}

function PnlCell({ pnl, pnlPct }) {
    if (pnl == null) return <span className="text-muted-foreground/50">—</span>;
    const pos = pnl >= 0;
    return (
        <div className={`tabular-nums text-xs font-semibold ${pos ? 'text-emerald-400' : 'text-red-400'}`}>
            <div>{pos ? '+' : '-'}{fmt$(Math.abs(pnl))}</div>
            <div className="text-[11px] opacity-80">{fmtPct(pnlPct)}</div>
        </div>
    );
}

function RiskBar({ riskPct }) {
    if (riskPct == null) return <span className="text-muted-foreground/50">—</span>;
    const w = Math.min(100, riskPct * 4); // scale: 25% risk → full bar
    return (
        <div className="flex items-center gap-1.5">
            <div className="w-12 h-1.5 bg-muted/50 rounded-full overflow-hidden">
                <div className="h-full bg-red-500/70 rounded-full" style={{ width: `${w}%` }} />
            </div>
            <span className="text-[11px] text-red-400 tabular-nums">{riskPct.toFixed(1)}%</span>
        </div>
    );
}

// ─── Add Position Form ─────────────────────────────────────────────────────────

function AddPositionForm({ onAdd }) {
    const [open, setOpen]           = useState(false);
    const [ticker, setTicker]       = useState('');
    const [entryPrice, setEntryPrice] = useState('');
    const [shares, setShares]       = useState('');
    const [stopLoss, setStopLoss]   = useState('');
    const [takeProfit, setTakeProfit] = useState('');
    const [signal, setSignal]       = useState('');
    const [notes, setNotes]         = useState('');
    const [adding, setAdding]       = useState(false);
    const [err, setErr]             = useState(null);

    const reset = () => {
        setTicker(''); setEntryPrice(''); setShares('');
        setStopLoss(''); setTakeProfit(''); setSignal(''); setNotes('');
        setErr(null);
    };

    const submit = async (e) => {
        e.preventDefault();
        const t = ticker.trim().toUpperCase();
        if (!t || !entryPrice || !shares) return;
        setAdding(true);
        setErr(null);
        try {
            await portfolioApi.openPosition(t, {
                entry_price:  parseFloat(entryPrice),
                shares:       parseFloat(shares),
                stop_loss:    stopLoss    ? parseFloat(stopLoss)   : null,
                take_profit:  takeProfit  ? parseFloat(takeProfit) : null,
                signal:       signal      || null,
                notes:        notes       || null,
            });
            reset();
            setOpen(false);
            onAdd();
        } catch (error) {
            setErr(error?.response?.data?.detail || 'Failed to open position.');
        } finally {
            setAdding(false);
        }
    };

    return (
        <div className="rounded-xl border border-border bg-card/50">
            <button
                onClick={() => setOpen(v => !v)}
                className="w-full flex items-center justify-between px-4 py-3 text-sm font-semibold hover:bg-muted/20 transition-colors rounded-xl"
            >
                <span className="flex items-center gap-2">
                    <Plus className="h-4 w-4 text-primary" />
                    Add Position
                </span>
                {open ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
            </button>

            {open && (
                <form onSubmit={submit} className="border-t border-border px-4 pb-4 pt-3">
                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                        <div className="flex flex-col gap-1">
                            <label className="text-xs text-muted-foreground">Ticker *</label>
                            <input
                                type="text"
                                required
                                placeholder="AAPL"
                                value={ticker}
                                onChange={e => setTicker(e.target.value.toUpperCase())}
                                className="px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                            />
                        </div>
                        <div className="flex flex-col gap-1">
                            <label className="text-xs text-muted-foreground">Entry Price *</label>
                            <input
                                type="number"
                                required
                                step="any"
                                min="0.0001"
                                placeholder="150.00"
                                value={entryPrice}
                                onChange={e => setEntryPrice(e.target.value)}
                                className="px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                            />
                        </div>
                        <div className="flex flex-col gap-1">
                            <label className="text-xs text-muted-foreground">Shares *</label>
                            <input
                                type="number"
                                required
                                step="any"
                                min="0.0001"
                                placeholder="10"
                                value={shares}
                                onChange={e => setShares(e.target.value)}
                                className="px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                            />
                        </div>
                        <div className="flex flex-col gap-1">
                            <label className="text-xs text-muted-foreground">Stop Loss</label>
                            <input
                                type="number"
                                step="any"
                                min="0"
                                placeholder="140.00"
                                value={stopLoss}
                                onChange={e => setStopLoss(e.target.value)}
                                className="px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                            />
                        </div>
                        <div className="flex flex-col gap-1">
                            <label className="text-xs text-muted-foreground">Take Profit</label>
                            <input
                                type="number"
                                step="any"
                                min="0"
                                placeholder="180.00"
                                value={takeProfit}
                                onChange={e => setTakeProfit(e.target.value)}
                                className="px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                            />
                        </div>
                        <div className="flex flex-col gap-1">
                            <label className="text-xs text-muted-foreground">Signal</label>
                            <select
                                value={signal}
                                onChange={e => setSignal(e.target.value)}
                                className="px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                            >
                                <option value="">— None —</option>
                                <option value="STRONG_BUY">Strong Buy</option>
                                <option value="ACCUMULATE">Accumulate</option>
                                <option value="PROACTIVE_SWING">Swing Setup</option>
                                <option value="AVOID">Avoid</option>
                                <option value="DISTRIBUTION">Distribution</option>
                            </select>
                        </div>
                        <div className="flex flex-col gap-1 col-span-2 md:col-span-1 lg:col-span-2">
                            <label className="text-xs text-muted-foreground">Notes</label>
                            <input
                                type="text"
                                placeholder="Optional notes…"
                                value={notes}
                                onChange={e => setNotes(e.target.value)}
                                className="px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                            />
                        </div>
                    </div>
                    {err && (
                        <p className="mt-2 text-xs text-red-400 flex items-center gap-1">
                            <AlertTriangle className="h-3.5 w-3.5" /> {err}
                        </p>
                    )}
                    <div className="mt-3 flex gap-2">
                        <button
                            type="submit"
                            disabled={adding || !ticker.trim() || !entryPrice || !shares}
                            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50 hover:opacity-90 transition-opacity"
                        >
                            {adding ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                            Open Position
                        </button>
                        <button
                            type="button"
                            onClick={() => { reset(); setOpen(false); }}
                            className="px-3 py-2 rounded-lg border border-border text-sm text-muted-foreground hover:bg-accent transition-colors"
                        >
                            Cancel
                        </button>
                    </div>
                </form>
            )}
        </div>
    );
}

// ─── Inline Edit Row ───────────────────────────────────────────────────────────

function EditRow({ position, onSave, onCancel }) {
    const [stopLoss, setStopLoss]     = useState(position.stop_loss   ?? '');
    const [takeProfit, setTakeProfit] = useState(position.take_profit ?? '');
    const [notes, setNotes]           = useState(position.notes       ?? '');
    const [saving, setSaving]         = useState(false);
    const [err, setErr]               = useState(null);

    const save = async () => {
        setSaving(true);
        setErr(null);
        try {
            await portfolioApi.updatePosition(position.id, {
                stop_loss:   stopLoss   !== '' ? parseFloat(stopLoss)   : null,
                take_profit: takeProfit !== '' ? parseFloat(takeProfit) : null,
                notes:       notes      !== '' ? notes                  : null,
            });
            onSave();
        } catch (e) {
            setErr(e?.response?.data?.detail || 'Update failed.');
            setSaving(false);
        }
    };

    return (
        <tr className="bg-primary/5 border-b border-border">
            <td colSpan={10} className="px-4 py-3">
                <div className="flex flex-wrap items-end gap-3">
                    <div className="flex flex-col gap-1">
                        <label className="text-[10px] text-muted-foreground uppercase tracking-wide">Stop Loss</label>
                        <input
                            type="number"
                            step="any"
                            value={stopLoss}
                            onChange={e => setStopLoss(e.target.value)}
                            placeholder="—"
                            className="w-28 px-2 py-1.5 rounded-md border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                        />
                    </div>
                    <div className="flex flex-col gap-1">
                        <label className="text-[10px] text-muted-foreground uppercase tracking-wide">Take Profit</label>
                        <input
                            type="number"
                            step="any"
                            value={takeProfit}
                            onChange={e => setTakeProfit(e.target.value)}
                            placeholder="—"
                            className="w-28 px-2 py-1.5 rounded-md border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                        />
                    </div>
                    <div className="flex flex-col gap-1 flex-1 min-w-[160px]">
                        <label className="text-[10px] text-muted-foreground uppercase tracking-wide">Notes</label>
                        <input
                            type="text"
                            value={notes}
                            onChange={e => setNotes(e.target.value)}
                            placeholder="—"
                            className="px-2 py-1.5 rounded-md border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                        />
                    </div>
                    <div className="flex gap-2 pb-0.5">
                        <button
                            onClick={save}
                            disabled={saving}
                            className="flex items-center gap-1 px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-xs font-medium disabled:opacity-50 hover:opacity-90 transition-opacity"
                        >
                            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                            Save
                        </button>
                        <button
                            onClick={onCancel}
                            className="px-3 py-1.5 rounded-md border border-border text-xs text-muted-foreground hover:bg-accent transition-colors"
                        >
                            Cancel
                        </button>
                    </div>
                    {err && <p className="text-xs text-red-400 w-full">{err}</p>}
                </div>
            </td>
        </tr>
    );
}

// ─── Close Dialog ──────────────────────────────────────────────────────────────

function CloseDialog({ position, onClose, onCancel }) {
    const [exitPrice, setExitPrice] = useState(position.current_price ?? position.entry_price ?? '');
    const [exitReason, setExitReason] = useState('MANUAL');
    const [closing, setClosing]     = useState(false);
    const [err, setErr]             = useState(null);

    const pnl = exitPrice
        ? ((parseFloat(exitPrice) - position.entry_price) * position.shares).toFixed(2)
        : null;
    const pnlPct = exitPrice && position.entry_price
        ? ((parseFloat(exitPrice) / position.entry_price - 1) * 100).toFixed(2)
        : null;

    const submit = async (e) => {
        e.preventDefault();
        if (!exitPrice) return;
        setClosing(true);
        setErr(null);
        try {
            await portfolioApi.closePosition(position.id, {
                exit_price:  parseFloat(exitPrice),
                exit_reason: exitReason,
            });
            onClose();
        } catch (error) {
            setErr(error?.response?.data?.detail || 'Close failed.');
            setClosing(false);
        }
    };

    return (
        <tr className="bg-red-500/5 border-b border-border">
            <td colSpan={10} className="px-4 py-3">
                <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
                    <div className="text-sm font-medium text-red-400">
                        Close {position.ticker} ({position.shares} shares)
                    </div>
                    <div className="flex flex-col gap-1">
                        <label className="text-[10px] text-muted-foreground uppercase tracking-wide">Exit Price *</label>
                        <input
                            type="number"
                            required
                            step="any"
                            value={exitPrice}
                            onChange={e => setExitPrice(e.target.value)}
                            className="w-32 px-2 py-1.5 rounded-md border border-red-500/30 bg-background text-sm focus:outline-none focus:ring-2 focus:ring-red-500/30"
                        />
                    </div>
                    <div className="flex flex-col gap-1">
                        <label className="text-[10px] text-muted-foreground uppercase tracking-wide">Exit Reason</label>
                        <select
                            value={exitReason}
                            onChange={e => setExitReason(e.target.value)}
                            className="px-2 py-1.5 rounded-md border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                        >
                            <option value="MANUAL">Manual</option>
                            <option value="STOP">Stop Loss Hit</option>
                            <option value="TARGET">Take Profit Hit</option>
                            <option value="SIGNAL">Signal Change</option>
                        </select>
                    </div>
                    {pnl !== null && (
                        <div className={`text-sm font-semibold tabular-nums ${parseFloat(pnl) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            P&L: {parseFloat(pnl) >= 0 ? '+' : ''}{fmt$(Math.abs(parseFloat(pnl)))} ({parseFloat(pnlPct) >= 0 ? '+' : ''}{pnlPct}%)
                        </div>
                    )}
                    <div className="flex gap-2 pb-0.5">
                        <button
                            type="submit"
                            disabled={closing || !exitPrice}
                            className="flex items-center gap-1 px-3 py-1.5 rounded-md bg-red-600 text-white text-xs font-medium disabled:opacity-50 hover:opacity-90 transition-opacity"
                        >
                            {closing ? <Loader2 className="h-3 w-3 animate-spin" /> : <X className="h-3 w-3" />}
                            Confirm Close
                        </button>
                        <button
                            type="button"
                            onClick={onCancel}
                            className="px-3 py-1.5 rounded-md border border-border text-xs text-muted-foreground hover:bg-accent transition-colors"
                        >
                            Cancel
                        </button>
                    </div>
                    {err && <p className="text-xs text-red-400 w-full">{err}</p>}
                </form>
            </td>
        </tr>
    );
}

// ─── Mobile Position Card ──────────────────────────────────────────────────────

function MobilePositionCard({ pos, onNavigate, livePrices, onEdit, onClose }) {
    const lp = livePrices[pos.ticker];
    const livePrice = lp?.price ?? pos.current_price;
    const liveUnrealizedPct = pos.entry_price && livePrice != null
        ? ((livePrice - pos.entry_price) / pos.entry_price * 100)
        : pos.unrealized_pnl_pct;
    const liveUnrealizedPnl = pos.entry_price && pos.shares && livePrice != null
        ? (livePrice - pos.entry_price) * pos.shares
        : pos.unrealized_pnl;

    const isPositive = liveUnrealizedPnl != null && liveUnrealizedPnl >= 0;
    const isNegative = liveUnrealizedPnl != null && liveUnrealizedPnl < 0;

    return (
        <div className={`rounded-xl border p-3 ${
            isPositive ? 'border-emerald-500/20 bg-emerald-500/5' :
            isNegative ? 'border-red-500/20 bg-red-500/5' :
            'border-border bg-card/50'
        }`}>
            {/* Row 1: Ticker + country + signal + actions */}
            <div className="flex items-center justify-between gap-2 mb-2">
                <div className="flex items-center gap-2 min-w-0">
                    <button
                        onClick={() => onNavigate?.('hub', pos.ticker)}
                        className="font-bold text-sm text-foreground hover:text-primary transition-colors"
                    >
                        {pos.ticker}
                    </button>
                    {pos.country && (
                        <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold uppercase ${
                            pos.country === 'IN' ? 'bg-orange-500/10 text-orange-500' : 'bg-blue-500/10 text-blue-500'
                        }`}>
                            {pos.country}
                        </span>
                    )}
                    {pos.signal && <SignalBadge signal={pos.signal} size="sm" />}
                </div>
                <div className="flex items-center gap-1 shrink-0" onClick={e => e.stopPropagation()}>
                    <button
                        onClick={onEdit}
                        title="Edit stop/target"
                        className="p-1.5 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded transition-colors"
                    >
                        <Edit2 className="h-3.5 w-3.5" />
                    </button>
                    <button
                        onClick={onClose}
                        title="Close position"
                        className="p-1.5 text-muted-foreground hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                    >
                        <X className="h-3.5 w-3.5" />
                    </button>
                </div>
            </div>

            {/* Row 2: P&L + shares */}
            <div className="flex items-baseline justify-between mb-2">
                <div>
                    {liveUnrealizedPnl != null ? (
                        <span className={`text-base font-bold tabular-nums ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                            {isPositive ? '+' : '-'}{fmt$(Math.abs(liveUnrealizedPnl))}
                            <span className="text-xs ml-1 opacity-80">({isPositive ? '+' : ''}{liveUnrealizedPct?.toFixed(2)}%)</span>
                        </span>
                    ) : (
                        <span className="text-muted-foreground/50 text-sm">—</span>
                    )}
                </div>
                <span className="text-xs text-muted-foreground">{pos.shares} sh</span>
            </div>

            {/* Row 3: Entry → Current */}
            <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1.5">
                <span>Entry: <strong className="text-foreground tabular-nums">{fmt$(pos.entry_price)}</strong></span>
                <span className="text-muted-foreground/40">→</span>
                <span>Now: <strong className="text-foreground tabular-nums">
                    {livePrice != null ? fmt$(livePrice) : '—'}
                    {lp?.price != null && <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 ml-1 align-middle" />}
                </strong></span>
            </div>

            {/* Row 4: Stop + Target */}
            <div className="flex items-center gap-3 text-xs">
                <span className="text-muted-foreground">Stop: <strong className="text-red-400 tabular-nums">
                    {pos.stop_loss != null ? fmt$(pos.stop_loss) : '—'}
                </strong></span>
                <span className="text-muted-foreground">Target: <strong className="text-emerald-400 tabular-nums">
                    {pos.take_profit != null ? fmt$(pos.take_profit) : '—'}
                </strong></span>
                {pos.risk_pct != null && (
                    <span className="text-muted-foreground ml-auto">Risk: <strong className="text-red-400">{pos.risk_pct.toFixed(1)}%</strong></span>
                )}
            </div>
        </div>
    );
}

// ─── Open Positions Table ──────────────────────────────────────────────────────

function OpenPositionsTable({ positions, onRefresh, onNavigate, livePrices = {} }) {
    const [editingId, setEditingId] = useState(null);
    const [closingId, setClosingId] = useState(null);

    const handleSaved = () => {
        setEditingId(null);
        onRefresh();
    };

    const handleClosed = () => {
        setClosingId(null);
        onRefresh();
    };

    if (positions.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center h-40 text-muted-foreground space-y-2">
                <Briefcase className="h-8 w-8 opacity-20" />
                <p className="text-sm">No open positions. Add one above.</p>
            </div>
        );
    }

    return (
        <>
            {/* Mobile card list */}
            <div className="md:hidden space-y-3 p-3">
                {positions.map(pos => (
                    <React.Fragment key={pos.id}>
                        <MobilePositionCard
                            pos={pos}
                            onNavigate={onNavigate}
                            livePrices={livePrices}
                            onEdit={() => {
                                setClosingId(null);
                                setEditingId(id => id === pos.id ? null : pos.id);
                            }}
                            onClose={() => {
                                setEditingId(null);
                                setClosingId(id => id === pos.id ? null : pos.id);
                            }}
                        />
                        {editingId === pos.id && (
                            <div className="rounded-xl border border-primary/20 bg-primary/5 overflow-hidden">
                                <table className="w-full">
                                    <tbody>
                                        <EditRow
                                            position={pos}
                                            onSave={handleSaved}
                                            onCancel={() => setEditingId(null)}
                                        />
                                    </tbody>
                                </table>
                            </div>
                        )}
                        {closingId === pos.id && (
                            <div className="rounded-xl border border-red-500/20 bg-red-500/5 overflow-hidden">
                                <table className="w-full">
                                    <tbody>
                                        <CloseDialog
                                            position={pos}
                                            onClose={handleClosed}
                                            onCancel={() => setClosingId(null)}
                                        />
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </React.Fragment>
                ))}
            </div>

            {/* Desktop table */}
            <div className="hidden md:block overflow-x-auto">
                <table className="w-full text-sm">
                    <thead className="bg-muted/40 border-b border-border text-muted-foreground text-xs">
                        <tr>
                            <th className="text-left px-4 py-3 font-medium">Ticker</th>
                            <th className="text-left px-4 py-3 font-medium">Signal</th>
                            <th className="text-left px-4 py-3 font-medium">Entry Date</th>
                            <th className="text-right px-4 py-3 font-medium">Entry $</th>
                            <th className="text-right px-4 py-3 font-medium">Current $</th>
                            <th className="text-right px-4 py-3 font-medium">Unrealized P&L</th>
                            <th className="text-right px-4 py-3 font-medium">Stop</th>
                            <th className="text-right px-4 py-3 font-medium">Target</th>
                            <th className="text-left px-4 py-3 font-medium">Risk%</th>
                            <th className="text-right px-4 py-3 font-medium">Action</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-border/40">
                        {positions.map(pos => (
                            <React.Fragment key={pos.id}>
                                <tr
                                    className="hover:bg-muted/20 transition-colors cursor-pointer"
                                    onClick={() => onNavigate?.('hub', pos.ticker)}
                                >
                                    <td className="px-4 py-3">
                                        <div className="font-bold text-sm">{pos.ticker}</div>
                                        {pos.name && (
                                            <div className="text-[11px] text-muted-foreground truncate max-w-[140px]">{pos.name}</div>
                                        )}
                                        {pos.country && (
                                            <span className={`text-[9px] px-1.5 py-0.5 rounded-sm font-bold uppercase ${
                                                pos.country === 'IN' ? 'bg-orange-500/10 text-orange-500' : 'bg-blue-500/10 text-blue-500'
                                            }`}>
                                                {pos.country}
                                            </span>
                                        )}
                                    </td>
                                    <td className="px-4 py-3">
                                        {pos.signal
                                            ? <SignalBadge signal={pos.signal} size="sm" />
                                            : <span className="text-xs text-muted-foreground/50">—</span>
                                        }
                                    </td>
                                    <td className="px-4 py-3 text-xs text-muted-foreground">
                                        {fmtDate(pos.entry_date)}
                                    </td>
                                    <td className="px-4 py-3 text-right tabular-nums text-xs font-semibold">
                                        {fmt$(pos.entry_price)}
                                        <div className="text-[11px] text-muted-foreground">{pos.shares} sh</div>
                                    </td>
                                    <td className="px-4 py-3 text-right tabular-nums text-xs font-semibold">
                                        {(() => {
                                            const lp = livePrices[pos.ticker];
                                            const livePrice = lp?.price ?? pos.current_price;
                                            if (livePrice == null) return <span className="text-muted-foreground/50">—</span>;
                                            return (
                                                <span className="flex items-center justify-end gap-1">
                                                    {fmt$(livePrice)}
                                                    {lp?.price != null && (
                                                        <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" title="Live price" />
                                                    )}
                                                </span>
                                            );
                                        })()}
                                    </td>
                                    <td className="px-4 py-3 text-right">
                                        {(() => {
                                            const lp = livePrices[pos.ticker];
                                            const livePrice = lp?.price ?? pos.current_price;
                                            const liveUnrealizedPct = pos.entry_price
                                                ? ((livePrice - pos.entry_price) / pos.entry_price * 100)
                                                : pos.unrealized_pnl_pct;
                                            const liveUnrealizedPnl = pos.entry_price && pos.shares
                                                ? (livePrice - pos.entry_price) * pos.shares
                                                : pos.unrealized_pnl;
                                            return <PnlCell pnl={liveUnrealizedPnl} pnlPct={liveUnrealizedPct} />;
                                        })()}
                                    </td>
                                    <td className="px-4 py-3 text-right tabular-nums text-xs text-red-400">
                                        {pos.stop_loss != null ? fmt$(pos.stop_loss) : (
                                            <span className="text-muted-foreground/50">—</span>
                                        )}
                                    </td>
                                    <td className="px-4 py-3 text-right tabular-nums text-xs text-emerald-400">
                                        {pos.take_profit != null ? fmt$(pos.take_profit) : (
                                            <span className="text-muted-foreground/50">—</span>
                                        )}
                                    </td>
                                    <td className="px-4 py-3">
                                        <RiskBar riskPct={pos.risk_pct} />
                                    </td>
                                    <td className="px-4 py-3 text-right" onClick={e => e.stopPropagation()}>
                                        <div className="flex items-center gap-1 justify-end">
                                            <button
                                                onClick={() => {
                                                    setClosingId(null);
                                                    setEditingId(id => id === pos.id ? null : pos.id);
                                                }}
                                                title="Edit stop/target"
                                                className="p-1.5 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded transition-colors"
                                            >
                                                <Edit2 className="h-3.5 w-3.5" />
                                            </button>
                                            <button
                                                onClick={() => {
                                                    setEditingId(null);
                                                    setClosingId(id => id === pos.id ? null : pos.id);
                                                }}
                                                title="Close position"
                                                className="p-1.5 text-muted-foreground hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                                            >
                                                <X className="h-3.5 w-3.5" />
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                                {editingId === pos.id && (
                                    <EditRow
                                        position={pos}
                                        onSave={handleSaved}
                                        onCancel={() => setEditingId(null)}
                                    />
                                )}
                                {closingId === pos.id && (
                                    <CloseDialog
                                        position={pos}
                                        onClose={handleClosed}
                                        onCancel={() => setClosingId(null)}
                                    />
                                )}
                            </React.Fragment>
                        ))}
                    </tbody>
                </table>
            </div>
        </>
    );
}

// ─── Closed Positions Section ──────────────────────────────────────────────────

function ClosedPositionsSection() {
    const [open, setOpen]         = useState(false);
    const [items, setItems]       = useState([]);
    const [total, setTotal]       = useState(0);
    const [loading, setLoading]   = useState(false);
    const [error, setError]       = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await portfolioApi.getHistory(1, 20);
            setItems(res.data.items || []);
            setTotal(res.data.total || 0);
        } catch (e) {
            setError(e?.response?.data?.detail || 'Failed to load history.');
        } finally {
            setLoading(false);
        }
    }, []);

    const toggle = () => {
        if (!open && items.length === 0) load();
        setOpen(v => !v);
    };

    const EXIT_REASON_LABEL = {
        MANUAL: 'Manual',
        STOP:   'Stop Hit',
        TARGET: 'Target Hit',
        SIGNAL: 'Signal Change',
    };

    return (
        <div className="rounded-xl border border-border bg-card/50">
            <button
                onClick={toggle}
                className="w-full flex items-center justify-between px-4 py-3 text-sm font-semibold hover:bg-muted/20 transition-colors rounded-xl"
            >
                <span className="flex items-center gap-2">
                    <TrendingDown className="h-4 w-4 text-muted-foreground" />
                    Closed Positions
                    {total > 0 && (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-muted/60 text-muted-foreground border border-border">
                            {total}
                        </span>
                    )}
                </span>
                {open ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
            </button>

            {open && (
                <div className="border-t border-border">
                    {loading ? (
                        <div className="flex items-center justify-center h-24 gap-2 text-muted-foreground">
                            <Loader2 className="animate-spin h-4 w-4" /> Loading history…
                        </div>
                    ) : error ? (
                        <div className="flex flex-col items-center justify-center h-24 gap-2 text-red-400">
                            <p className="text-sm">{error}</p>
                            <button onClick={load} className="text-xs text-muted-foreground underline">Retry</button>
                        </div>
                    ) : items.length === 0 ? (
                        <div className="flex items-center justify-center h-24 text-muted-foreground text-sm">
                            No closed positions yet.
                        </div>
                    ) : (
                        <>
                            {/* Mobile card list */}
                            <div className="md:hidden divide-y divide-border/40">
                                {items.map(pos => {
                                    const pos_ret = pos.realized_pnl_pct;
                                    const isPos = pos.realized_pnl != null && pos.realized_pnl >= 0;
                                    const isNeg = pos.realized_pnl != null && pos.realized_pnl < 0;
                                    return (
                                        <div key={pos.id} className={`px-3 py-3 ${
                                            isPos ? 'bg-emerald-500/5' : isNeg ? 'bg-red-500/5' : ''
                                        }`}>
                                            <div className="flex items-center justify-between gap-2 mb-1">
                                                <div className="flex items-center gap-2">
                                                    <span className="font-bold text-sm">{pos.ticker}</span>
                                                    {pos.signal && <SignalBadge signal={pos.signal} size="sm" />}
                                                </div>
                                                <div className="text-right">
                                                    {pos.realized_pnl != null ? (
                                                        <span className={`text-sm font-bold tabular-nums ${isPos ? 'text-emerald-400' : 'text-red-400'}`}>
                                                            {isPos ? '+' : '-'}{fmt$(Math.abs(pos.realized_pnl))}
                                                        </span>
                                                    ) : (
                                                        <span className="text-muted-foreground/50">—</span>
                                                    )}
                                                </div>
                                            </div>
                                            <div className="flex items-center justify-between text-xs text-muted-foreground">
                                                <span>{fmtDate(pos.entry_date)} → {fmtDate(pos.exit_date)}</span>
                                                <div className="flex items-center gap-2">
                                                    <span className={`font-semibold tabular-nums ${pos_ret != null ? (pos_ret >= 0 ? 'text-emerald-400' : 'text-red-400') : ''}`}>
                                                        {pos_ret != null ? fmtPct(pos_ret) : '—'}
                                                    </span>
                                                    <span className="text-muted-foreground/60">{EXIT_REASON_LABEL[pos.exit_reason] || pos.exit_reason || '—'}</span>
                                                </div>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>

                            {/* Desktop table */}
                            <div className="hidden md:block overflow-x-auto">
                                <table className="w-full text-sm">
                                    <thead className="bg-muted/40 border-b border-border text-muted-foreground text-xs">
                                        <tr>
                                            <th className="text-left px-4 py-3 font-medium">Ticker</th>
                                            <th className="text-left px-4 py-3 font-medium">Signal</th>
                                            <th className="text-left px-4 py-3 font-medium">Entry → Exit</th>
                                            <th className="text-right px-4 py-3 font-medium">Return %</th>
                                            <th className="text-left px-4 py-3 font-medium">Exit Reason</th>
                                            <th className="text-right px-4 py-3 font-medium">Realized P&L</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-border/40">
                                        {items.map(pos => {
                                            const pos_ret = pos.realized_pnl_pct;
                                            return (
                                                <tr key={pos.id} className="hover:bg-muted/20 transition-colors">
                                                    <td className="px-4 py-3">
                                                        <div className="font-bold text-sm">{pos.ticker}</div>
                                                        {pos.name && (
                                                            <div className="text-[11px] text-muted-foreground truncate max-w-[130px]">{pos.name}</div>
                                                        )}
                                                    </td>
                                                    <td className="px-4 py-3">
                                                        {pos.signal
                                                            ? <SignalBadge signal={pos.signal} size="sm" />
                                                            : <span className="text-xs text-muted-foreground/50">—</span>
                                                        }
                                                    </td>
                                                    <td className="px-4 py-3 text-xs text-muted-foreground">
                                                        <div>{fmtDate(pos.entry_date)}</div>
                                                        <div className="text-[11px] opacity-70">→ {fmtDate(pos.exit_date)}</div>
                                                    </td>
                                                    <td className="px-4 py-3 text-right">
                                                        {pos_ret != null ? (
                                                            <span className={`tabular-nums text-sm font-semibold ${pos_ret >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                                                {fmtPct(pos_ret)}
                                                            </span>
                                                        ) : (
                                                            <span className="text-muted-foreground/50">—</span>
                                                        )}
                                                    </td>
                                                    <td className="px-4 py-3">
                                                        <span className="text-xs text-muted-foreground">
                                                            {EXIT_REASON_LABEL[pos.exit_reason] || pos.exit_reason || '—'}
                                                        </span>
                                                    </td>
                                                    <td className="px-4 py-3 text-right">
                                                        {pos.realized_pnl != null ? (
                                                            <span className={`tabular-nums text-sm font-semibold ${pos.realized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                                                {pos.realized_pnl >= 0 ? '+' : '-'}{fmt$(Math.abs(pos.realized_pnl))}
                                                            </span>
                                                        ) : (
                                                            <span className="text-muted-foreground/50">—</span>
                                                        )}
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                            {total > 20 && (
                                <div className="px-4 py-2 text-xs text-muted-foreground border-t border-border">
                                    Showing 20 of {total} closed positions.
                                </div>
                            )}
                        </>
                    )}
                </div>
            )}
        </div>
    );
}

// ─── Main Portfolio Component ──────────────────────────────────────────────────

export default function Portfolio({ onNavigate }) {
    const [positions, setPositions] = useState([]);
    const [summary, setSummary]     = useState(null);
    const [loading, setLoading]     = useState(true);
    const [error, setError]         = useState(null);

    const openTickers = positions.map(p => p.ticker);
    const { prices: livePrices } = useLivePrices(openTickers);

    const loadAll = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const [posRes, sumRes] = await Promise.all([
                portfolioApi.getPositions(),
                portfolioApi.getSummary(),
            ]);
            setPositions(posRes.data.items || []);
            setSummary(sumRes.data);
        } catch (e) {
            setError(e?.response?.data?.detail || 'Failed to load portfolio.');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { loadAll(); }, [loadAll]);

    const unrealizedPos = summary ? summary.total_unrealized_pnl >= 0 : null;
    const realizedPos   = summary ? summary.total_realized_pnl   >= 0 : null;

    return (
        <div className="space-y-5">

            {/* ── Header ── */}
            <div className="flex items-center justify-between flex-wrap gap-3">
                <div>
                    <h2 className="text-xl font-bold flex items-center gap-2">
                        <Briefcase className="h-5 w-5 text-primary" /> Portfolio P&L
                    </h2>
                    <p className="text-sm text-muted-foreground">
                        {summary ? `${summary.position_count} open position${summary.position_count !== 1 ? 's' : ''}` : 'Loading…'}
                    </p>
                </div>
                <button
                    onClick={loadAll}
                    disabled={loading}
                    className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground px-3 py-1.5 rounded-md border border-border hover:bg-accent transition-colors disabled:opacity-50"
                >
                    <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
                </button>
            </div>

            {/* ── Summary Cards ── */}
            {summary && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <SummaryCard
                        label="Total Invested"
                        value={fmt$(summary.total_invested)}
                        sub={`Current: ${fmt$(summary.total_current_value)}`}
                        icon={DollarSign}
                    />
                    <SummaryCard
                        label="Unrealized P&L"
                        value={
                            summary.total_unrealized_pnl != null
                                ? `${unrealizedPos ? '+' : '-'}${fmt$(Math.abs(summary.total_unrealized_pnl))}`
                                : '—'
                        }
                        sub={fmtPct(summary.total_unrealized_pnl_pct)}
                        positive={unrealizedPos === true}
                        negative={unrealizedPos === false}
                        icon={unrealizedPos ? TrendingUp : TrendingDown}
                    />
                    <SummaryCard
                        label="Realized P&L"
                        value={
                            summary.total_realized_pnl != null
                                ? `${realizedPos ? '+' : '-'}${fmt$(Math.abs(summary.total_realized_pnl))}`
                                : '—'
                        }
                        positive={realizedPos === true && summary.total_realized_pnl !== 0}
                        negative={realizedPos === false}
                        icon={DollarSign}
                    />
                    <SummaryCard
                        label="Open Positions"
                        value={summary.position_count}
                        sub={
                            summary.best_position
                                ? `Best: ${summary.best_position.ticker} (${fmtPct(summary.best_position.unrealized_pnl_pct)})`
                                : 'No positions'
                        }
                        icon={Briefcase}
                    />
                </div>
            )}

            {/* ── Add Position Form ── */}
            <AddPositionForm onAdd={loadAll} />

            {/* ── Open Positions Table ── */}
            <div className="rounded-xl border border-border overflow-hidden bg-card/50">
                <div className="px-4 py-3 border-b border-border flex items-center justify-between">
                    <h3 className="text-sm font-semibold flex items-center gap-2">
                        <TrendingUp className="h-4 w-4 text-emerald-400" /> Open Positions
                    </h3>
                    {positions.length > 0 && (
                        <span className="text-xs text-muted-foreground">{positions.length} position{positions.length !== 1 ? 's' : ''}</span>
                    )}
                </div>

                {loading ? (
                    <div className="flex items-center justify-center h-40 gap-2 text-muted-foreground">
                        <Loader2 className="animate-spin h-5 w-5" /> Loading positions…
                    </div>
                ) : error ? (
                    <div className="flex flex-col items-center justify-center h-40 gap-2 text-red-400">
                        <p className="text-sm">{error}</p>
                        <button onClick={loadAll} className="text-xs text-muted-foreground underline">Retry</button>
                    </div>
                ) : (
                    <OpenPositionsTable
                        positions={positions}
                        onRefresh={loadAll}
                        onNavigate={onNavigate}
                        livePrices={livePrices}
                    />
                )}
            </div>

            {/* ── Signal Breakdown ── */}
            {summary && Object.keys(summary.by_signal || {}).length > 0 && (
                <div className="rounded-xl border border-border bg-card/50 p-4">
                    <h3 className="text-sm font-semibold mb-3 text-muted-foreground">Open Positions by Signal</h3>
                    <div className="flex flex-wrap gap-2">
                        {Object.entries(summary.by_signal).map(([sig, data]) => (
                            <div key={sig} className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border bg-background">
                                <SignalBadge signal={sig} size="sm" />
                                <span className="text-xs text-muted-foreground">{data.count} pos · {fmt$(data.value)}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* ── Closed Positions ── */}
            <ClosedPositionsSection />

            <p className="text-xs text-muted-foreground px-1">
                Click any open position row to open the Intelligence Hub deep-dive for that ticker.
            </p>
        </div>
    );
}
