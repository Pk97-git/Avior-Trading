import React, { useState, useEffect, useCallback } from 'react';
import {
    ShoppingCart, RefreshCw, X, CheckCircle, Clock, AlertCircle,
    XCircle, DollarSign, TrendingUp, Send, ChevronLeft, ChevronRight,
    Wallet, BarChart2,
} from 'lucide-react';
import { ordersApi } from '../api';

// ─── Helpers ─────────────────────────────────────────────────────────────────

const STATUS_STYLE = {
    PENDING:   { color: 'text-yellow-400', bg: 'bg-yellow-400/10', icon: Clock },
    FILLED:    { color: 'text-green-400',  bg: 'bg-green-400/10',  icon: CheckCircle },
    CANCELLED: { color: 'text-slate-400',  bg: 'bg-slate-400/10',  icon: XCircle },
    REJECTED:  { color: 'text-red-400',    bg: 'bg-red-400/10',    icon: AlertCircle },
};

function StatusBadge({ status }) {
    const s = STATUS_STYLE[status] || STATUS_STYLE.PENDING;
    const Icon = s.icon;
    return (
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${s.color} ${s.bg}`}>
            <Icon size={11} />
            {status}
        </span>
    );
}

function fmt(n, digits = 2) {
    if (n == null) return '—';
    return Number(n).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function fmtCcy(n, currency = 'USD') {
    if (n == null) return '—';
    return new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: 2 }).format(n);
}

function fmtDate(d) {
    if (!d) return '—';
    return new Date(d).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
}

// ─── Broker Balance Card ──────────────────────────────────────────────────────

function BrokerBalanceCard({ country }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        setLoading(true);
        ordersApi.getBrokerBalance(country)
            .then(r => setData(r.data))
            .catch(() => setData(null))
            .finally(() => setLoading(false));
    }, [country]);

    return (
        <div className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-center gap-2 mb-3 text-muted-foreground text-xs font-medium uppercase tracking-wide">
                <Wallet size={14} />
                {loading ? 'Loading…' : `${data?.broker || 'Broker'} · ${country}`}
            </div>
            {loading ? (
                <div className="h-12 animate-pulse bg-muted rounded" />
            ) : data ? (
                <div className="grid grid-cols-3 gap-4">
                    <div>
                        <p className="text-xs text-muted-foreground">Cash</p>
                        <p className="text-lg font-semibold">{fmtCcy(data.cash, data.currency)}</p>
                    </div>
                    <div>
                        <p className="text-xs text-muted-foreground">Portfolio Value</p>
                        <p className="text-lg font-semibold">{fmtCcy(data.portfolio_value, data.currency)}</p>
                    </div>
                    <div>
                        <p className="text-xs text-muted-foreground">Buying Power</p>
                        <p className="text-lg font-semibold">{fmtCcy(data.buying_power, data.currency)}</p>
                    </div>
                </div>
            ) : (
                <p className="text-sm text-muted-foreground">Could not load balance.</p>
            )}
        </div>
    );
}

// ─── Quick Order Form ─────────────────────────────────────────────────────────

function QuickOrderForm({ onSuccess }) {
    const [form, setForm] = useState({
        ticker: '', side: 'BUY', qty: '', order_type: 'MARKET', limit_price: '', notes: '',
    });
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState(null);

    const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

    async function handleSubmit(e) {
        e.preventDefault();
        if (!form.ticker || !form.qty) return;
        setSubmitting(true);
        setError(null);
        try {
            const body = {
                ticker:      form.ticker.toUpperCase(),
                side:        form.side,
                qty:         parseFloat(form.qty),
                order_type:  form.order_type,
                limit_price: form.order_type === 'LIMIT' && form.limit_price ? parseFloat(form.limit_price) : null,
                notes:       form.notes || null,
            };
            await ordersApi.submitManual(body);
            setForm({ ticker: '', side: 'BUY', qty: '', order_type: 'MARKET', limit_price: '', notes: '' });
            onSuccess?.();
        } catch (err) {
            setError(err?.response?.data?.detail || 'Order failed.');
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-card p-4">
            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                <Send size={14} className="text-primary" />
                Quick Order
            </h3>

            <div className="grid grid-cols-2 md:grid-cols-6 gap-2 items-end">
                <div className="col-span-1 md:col-span-2">
                    <label className="text-xs text-muted-foreground">Ticker</label>
                    <input
                        className="w-full mt-1 bg-background border border-border rounded px-2 py-1.5 text-sm uppercase placeholder:normal-case"
                        placeholder="AAPL"
                        value={form.ticker}
                        onChange={e => set('ticker', e.target.value)}
                        required
                    />
                </div>

                <div>
                    <label className="text-xs text-muted-foreground">Side</label>
                    <select
                        className="w-full mt-1 bg-background border border-border rounded px-2 py-1.5 text-sm"
                        value={form.side}
                        onChange={e => set('side', e.target.value)}
                    >
                        <option>BUY</option>
                        <option>SELL</option>
                    </select>
                </div>

                <div>
                    <label className="text-xs text-muted-foreground">Qty</label>
                    <input
                        type="number" min="0.001" step="any"
                        className="w-full mt-1 bg-background border border-border rounded px-2 py-1.5 text-sm"
                        placeholder="10"
                        value={form.qty}
                        onChange={e => set('qty', e.target.value)}
                        required
                    />
                </div>

                <div>
                    <label className="text-xs text-muted-foreground">Type</label>
                    <select
                        className="w-full mt-1 bg-background border border-border rounded px-2 py-1.5 text-sm"
                        value={form.order_type}
                        onChange={e => set('order_type', e.target.value)}
                    >
                        <option>MARKET</option>
                        <option>LIMIT</option>
                    </select>
                </div>

                {form.order_type === 'LIMIT' ? (
                    <div>
                        <label className="text-xs text-muted-foreground">Limit $</label>
                        <input
                            type="number" min="0" step="0.01"
                            className="w-full mt-1 bg-background border border-border rounded px-2 py-1.5 text-sm"
                            placeholder="150.00"
                            value={form.limit_price}
                            onChange={e => set('limit_price', e.target.value)}
                        />
                    </div>
                ) : <div />}

                <div className="flex items-end">
                    <button
                        type="submit"
                        disabled={submitting}
                        className="w-full bg-primary text-primary-foreground rounded px-3 py-1.5 text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
                    >
                        {submitting ? 'Placing…' : 'Place Order'}
                    </button>
                </div>
            </div>

            {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
        </form>
    );
}

// ─── Signal Submit ─────────────────────────────────────────────────────────────

function SignalOrderForm({ onSuccess }) {
    const [ticker, setTicker] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState(null);
    const [result, setResult] = useState(null);

    async function handleSubmit(e) {
        e.preventDefault();
        if (!ticker) return;
        setSubmitting(true);
        setError(null);
        setResult(null);
        try {
            const r = await ordersApi.submitFromAnalysis(ticker);
            setResult(r.data);
            setTicker('');
            onSuccess?.();
        } catch (err) {
            setError(err?.response?.data?.detail || 'Failed to submit AI-driven order.');
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-card p-4">
            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                <TrendingUp size={14} className="text-green-400" />
                Trade from AI Signal
            </h3>

            <div className="flex gap-2 items-end">
                <div className="flex-1">
                    <label className="text-xs text-muted-foreground">Ticker (uses latest AI analysis)</label>
                    <input
                        className="w-full mt-1 bg-background border border-border rounded px-2 py-1.5 text-sm uppercase placeholder:normal-case"
                        placeholder="TSLA"
                        value={ticker}
                        onChange={e => setTicker(e.target.value)}
                        required
                    />
                </div>
                <button
                    type="submit"
                    disabled={submitting}
                    className="bg-green-600 text-white rounded px-4 py-1.5 text-sm font-medium hover:bg-green-500 disabled:opacity-50 transition-colors"
                >
                    {submitting ? 'Submitting…' : 'Auto-Size & Buy'}
                </button>
            </div>

            {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
            {result && (
                <p className="mt-2 text-xs text-green-400">
                    Order placed — {result.broker} · {result.order?.status || 'submitted'}
                </p>
            )}
        </form>
    );
}

// ─── Orders Table ─────────────────────────────────────────────────────────────

function OrdersTable({ orders, onCancel, onRefresh }) {
    return (
        <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
                <thead>
                    <tr className="border-b border-border bg-muted/30 text-xs text-muted-foreground uppercase tracking-wide">
                        <th className="text-left px-3 py-2">ID</th>
                        <th className="text-left px-3 py-2">Time</th>
                        <th className="text-left px-3 py-2">Ticker</th>
                        <th className="text-left px-3 py-2">Side</th>
                        <th className="text-left px-3 py-2">Type</th>
                        <th className="text-right px-3 py-2">Qty</th>
                        <th className="text-right px-3 py-2">Limit $</th>
                        <th className="text-right px-3 py-2">Fill $</th>
                        <th className="text-left px-3 py-2">Broker</th>
                        <th className="text-left px-3 py-2">Signal</th>
                        <th className="text-left px-3 py-2">Status</th>
                        <th className="px-3 py-2" />
                    </tr>
                </thead>
                <tbody>
                    {orders.length === 0 ? (
                        <tr>
                            <td colSpan={12} className="text-center py-10 text-muted-foreground text-sm">
                                No orders yet.
                            </td>
                        </tr>
                    ) : orders.map(o => (
                        <tr key={o.id} className="border-b border-border/50 hover:bg-muted/20 transition-colors">
                            <td className="px-3 py-2 text-muted-foreground">#{o.id}</td>
                            <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">{fmtDate(o.created_at)}</td>
                            <td className="px-3 py-2 font-semibold">{o.ticker}</td>
                            <td className="px-3 py-2">
                                <span className={o.side === 'BUY' ? 'text-green-400' : 'text-red-400'}>
                                    {o.side}
                                </span>
                            </td>
                            <td className="px-3 py-2 text-xs">{o.order_type}</td>
                            <td className="px-3 py-2 text-right">{fmt(o.qty, 4)}</td>
                            <td className="px-3 py-2 text-right">{o.limit_price ? fmt(o.limit_price) : '—'}</td>
                            <td className="px-3 py-2 text-right">{o.filled_price ? fmt(o.filled_price) : '—'}</td>
                            <td className="px-3 py-2 text-xs">{o.broker}</td>
                            <td className="px-3 py-2 text-xs">{o.signal || '—'}</td>
                            <td className="px-3 py-2"><StatusBadge status={o.status} /></td>
                            <td className="px-3 py-2">
                                {o.status === 'PENDING' && (
                                    <button
                                        onClick={() => onCancel(o.id)}
                                        className="text-red-400 hover:text-red-300 transition-colors"
                                        title="Cancel order"
                                    >
                                        <X size={14} />
                                    </button>
                                )}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function Orders({ onNavigate }) {
    const [orders, setOrders]       = useState([]);
    const [total, setTotal]         = useState(0);
    const [page, setPage]           = useState(1);
    const [statusFilter, setStatus] = useState('');
    const [loading, setLoading]     = useState(true);
    const [syncing, setSyncing]     = useState(false);
    const [country, setCountry]     = useState('US');

    const LIMIT = 50;

    const fetchOrders = useCallback(async () => {
        setLoading(true);
        try {
            const params = { page, limit: LIMIT };
            if (statusFilter) params.status = statusFilter;
            const r = await ordersApi.listOrders(params);
            setOrders(r.data.items || []);
            setTotal(r.data.total || 0);
        } catch {
            setOrders([]);
        } finally {
            setLoading(false);
        }
    }, [page, statusFilter]);

    useEffect(() => { fetchOrders(); }, [fetchOrders]);

    async function handleCancel(id) {
        if (!window.confirm(`Cancel order #${id}?`)) return;
        try {
            await ordersApi.cancelOrder(id);
            fetchOrders();
        } catch (err) {
            alert(err?.response?.data?.detail || 'Cancel failed.');
        }
    }

    async function handleSync() {
        setSyncing(true);
        try {
            await ordersApi.syncBroker();
            fetchOrders();
        } finally {
            setSyncing(false);
        }
    }

    const totalPages = Math.ceil(total / LIMIT);

    return (
        <div className="space-y-5 max-w-screen-xl">

            {/* ── Header ── */}
            <div className="flex items-center justify-between flex-wrap gap-3">
                <div>
                    <h2 className="text-xl font-bold flex items-center gap-2">
                        <ShoppingCart size={20} className="text-primary" />
                        Order Management
                    </h2>
                    <p className="text-sm text-muted-foreground mt-0.5">
                        Paper / Zerodha / Alpaca order log — {total.toLocaleString()} total
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <select
                        value={country}
                        onChange={e => setCountry(e.target.value)}
                        className="bg-background border border-border rounded px-2 py-1.5 text-xs"
                    >
                        <option value="US">US (Alpaca)</option>
                        <option value="IN">IN (Zerodha)</option>
                    </select>
                    <button
                        onClick={handleSync}
                        disabled={syncing}
                        className="flex items-center gap-1.5 bg-background border border-border text-xs px-3 py-1.5 rounded hover:bg-accent transition-colors disabled:opacity-50"
                    >
                        <RefreshCw size={13} className={syncing ? 'animate-spin' : ''} />
                        Sync Broker
                    </button>
                    <button
                        onClick={fetchOrders}
                        className="flex items-center gap-1.5 bg-background border border-border text-xs px-3 py-1.5 rounded hover:bg-accent transition-colors"
                    >
                        <RefreshCw size={13} />
                        Refresh
                    </button>
                </div>
            </div>

            {/* ── Broker Balance ── */}
            <BrokerBalanceCard country={country} />

            {/* ── Order Forms ── */}
            <div className="grid md:grid-cols-2 gap-4">
                <SignalOrderForm onSuccess={fetchOrders} />
                <QuickOrderForm onSuccess={fetchOrders} />
            </div>

            {/* ── Filters + Table ── */}
            <div className="space-y-3">
                <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs text-muted-foreground font-medium">Filter:</span>
                    {['', 'PENDING', 'FILLED', 'CANCELLED', 'REJECTED'].map(s => (
                        <button
                            key={s}
                            onClick={() => { setStatus(s); setPage(1); }}
                            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                                statusFilter === s
                                    ? 'bg-primary text-primary-foreground'
                                    : 'bg-muted text-muted-foreground hover:bg-accent'
                            }`}
                        >
                            {s || 'All'}
                        </button>
                    ))}
                </div>

                {loading ? (
                    <div className="rounded-lg border border-border p-8 text-center text-muted-foreground text-sm animate-pulse">
                        Loading orders…
                    </div>
                ) : (
                    <OrdersTable orders={orders} onCancel={handleCancel} onRefresh={fetchOrders} />
                )}

                {/* ── Pagination ── */}
                {totalPages > 1 && (
                    <div className="flex items-center justify-center gap-2">
                        <button
                            disabled={page <= 1}
                            onClick={() => setPage(p => p - 1)}
                            className="p-1.5 rounded border border-border hover:bg-accent disabled:opacity-40 transition-colors"
                        >
                            <ChevronLeft size={14} />
                        </button>
                        <span className="text-xs text-muted-foreground">
                            Page {page} / {totalPages}
                        </span>
                        <button
                            disabled={page >= totalPages}
                            onClick={() => setPage(p => p + 1)}
                            className="p-1.5 rounded border border-border hover:bg-accent disabled:opacity-40 transition-colors"
                        >
                            <ChevronRight size={14} />
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}
