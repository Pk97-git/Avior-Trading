import React, { useState, useCallback } from 'react';
import { backtestApi } from '../api';
import { Loader2, FlaskConical, TrendingUp, TrendingDown, BarChart2, RefreshCw } from 'lucide-react';
import {
    LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
    ResponsiveContainer, ReferenceLine,
} from 'recharts';

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(v, decimals = 2) {
    if (v == null) return '—';
    return Number(v).toFixed(decimals);
}

function fmtPct(v) {
    if (v == null) return '—';
    const n = Number(v);
    return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}

function MetricCard({ label, value, sub, color }) {
    return (
        <div className="rounded-xl border border-border bg-card/50 p-4">
            <p className="text-xs text-muted-foreground font-medium mb-1">{label}</p>
            <p className={`text-2xl font-bold tabular-nums ${color || 'text-foreground'}`}>{value}</p>
            {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
        </div>
    );
}

const EXIT_COLORS = {
    TARGET: 'text-emerald-400',
    STOP:   'text-red-400',
    TIME:   'text-muted-foreground',
    SIGNAL: 'text-yellow-400',
};

const SIGNAL_COLORS = {
    STRONG_BUY:      '#10b981',
    ACCUMULATE:      '#3b82f6',
    PROACTIVE_SWING: '#8b5cf6',
    AVOID:           '#eab308',
    DISTRIBUTION:    '#ef4444',
};

// ── Main Component ────────────────────────────────────────────────────────────

export default function Backtest() {
    const today = new Date().toISOString().slice(0, 10);
    const oneYearAgo = new Date(Date.now() - 365 * 86400000).toISOString().slice(0, 10);

    const [form, setForm] = useState({
        start_date:      oneYearAgo,
        end_date:        today,
        initial_capital: 100000,
        max_positions:   10,
        max_hold_days:   30,
        use_kelly:       true,
        signal_filter:   ['STRONG_BUY', 'ACCUMULATE'],
        country:         '',
    });

    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError]   = useState(null);

    const toggleSignal = (sig) => {
        setForm(f => ({
            ...f,
            signal_filter: f.signal_filter.includes(sig)
                ? f.signal_filter.filter(s => s !== sig)
                : [...f.signal_filter, sig],
        }));
    };

    const run = useCallback(async () => {
        if (!form.start_date || !form.end_date) return;
        setLoading(true);
        setError(null);
        setResult(null);
        try {
            const payload = {
                ...form,
                initial_capital: Number(form.initial_capital),
                max_positions:   Number(form.max_positions),
                max_hold_days:   Number(form.max_hold_days),
                country: form.country || null,
            };
            const res = await backtestApi.run(payload);
            setResult(res.data);
        } catch (e) {
            setError(e?.response?.data?.detail || 'Backtest failed. Check date range and ensure signal data exists.');
        } finally {
            setLoading(false);
        }
    }, [form]);

    const m = result?.metrics;
    const equityCurve = (result?.equity_curve || []).map(p => ({
        date:      p.date,
        value:     p.value,
        drawdown:  p.drawdown_pct,
    }));

    const trades = result?.trades || [];
    const monthly = result?.monthly_returns
        ? Object.entries(result.monthly_returns).sort(([a], [b]) => a.localeCompare(b))
        : [];

    return (
        <div className="space-y-6 max-w-7xl">

            {/* ── Header ── */}
            <div>
                <h2 className="text-xl font-bold flex items-center gap-2">
                    <FlaskConical className="h-5 w-5 text-primary" /> Backtest Engine
                </h2>
                <p className="text-sm text-muted-foreground">
                    Replay historical AI signals against actual price data to measure strategy performance.
                </p>
            </div>

            {/* ── Config Panel ── */}
            <div className="rounded-xl border border-border bg-card/50 p-5 space-y-4">
                <h3 className="font-semibold text-sm">Configuration</h3>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div>
                        <label className="text-xs text-muted-foreground block mb-1">Start Date</label>
                        <input type="date" value={form.start_date}
                            onChange={e => setForm(f => ({ ...f, start_date: e.target.value }))}
                            className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40" />
                    </div>
                    <div>
                        <label className="text-xs text-muted-foreground block mb-1">End Date</label>
                        <input type="date" value={form.end_date}
                            onChange={e => setForm(f => ({ ...f, end_date: e.target.value }))}
                            className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40" />
                    </div>
                    <div>
                        <label className="text-xs text-muted-foreground block mb-1">Initial Capital ($)</label>
                        <input type="number" value={form.initial_capital} min={1000} step={10000}
                            onChange={e => setForm(f => ({ ...f, initial_capital: e.target.value }))}
                            className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40" />
                    </div>
                    <div>
                        <label className="text-xs text-muted-foreground block mb-1">Max Positions</label>
                        <input type="number" value={form.max_positions} min={1} max={50}
                            onChange={e => setForm(f => ({ ...f, max_positions: e.target.value }))}
                            className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40" />
                    </div>
                    <div>
                        <label className="text-xs text-muted-foreground block mb-1">Max Hold Days</label>
                        <input type="number" value={form.max_hold_days} min={1} max={365}
                            onChange={e => setForm(f => ({ ...f, max_hold_days: e.target.value }))}
                            className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40" />
                    </div>
                    <div>
                        <label className="text-xs text-muted-foreground block mb-1">Region</label>
                        <select value={form.country}
                            onChange={e => setForm(f => ({ ...f, country: e.target.value }))}
                            className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40">
                            <option value="">All Markets</option>
                            <option value="US">US Only</option>
                            <option value="IN">India Only</option>
                        </select>
                    </div>
                    <div className="flex items-end gap-2">
                        <label className="flex items-center gap-2 text-sm cursor-pointer">
                            <input type="checkbox" checked={form.use_kelly}
                                onChange={e => setForm(f => ({ ...f, use_kelly: e.target.checked }))}
                                className="rounded" />
                            Use Half-Kelly Sizing
                        </label>
                    </div>
                </div>

                {/* Signal filter */}
                <div>
                    <label className="text-xs text-muted-foreground block mb-2">Entry Signals</label>
                    <div className="flex flex-wrap gap-2">
                        {['STRONG_BUY', 'ACCUMULATE', 'PROACTIVE_SWING'].map(sig => (
                            <button key={sig}
                                onClick={() => toggleSignal(sig)}
                                className={`px-3 py-1 rounded-full text-xs font-semibold border transition-colors ${
                                    form.signal_filter.includes(sig)
                                        ? 'border-transparent text-white'
                                        : 'border-border text-muted-foreground bg-transparent'
                                }`}
                                style={form.signal_filter.includes(sig) ? { backgroundColor: SIGNAL_COLORS[sig] } : {}}
                            >
                                {sig.replace('_', ' ')}
                            </button>
                        ))}
                    </div>
                </div>

                <button
                    onClick={run}
                    disabled={loading || form.signal_filter.length === 0}
                    className="flex items-center gap-2 px-5 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50 hover:opacity-90 transition-opacity"
                >
                    {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FlaskConical className="h-4 w-4" />}
                    {loading ? 'Running Backtest…' : 'Run Backtest'}
                </button>
            </div>

            {/* ── Error ── */}
            {error && (
                <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-4 text-red-400 text-sm">
                    {error}
                </div>
            )}

            {/* ── Results ── */}
            {result && m && (
                <>
                    {/* Summary metrics */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <MetricCard
                            label="Total Return"
                            value={fmtPct(m.total_return_pct)}
                            sub={`CAGR ${fmtPct(m.cagr_pct)}`}
                            color={m.total_return_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}
                        />
                        <MetricCard
                            label="Sharpe Ratio"
                            value={fmt(m.sharpe_ratio)}
                            sub={`Sortino ${fmt(m.sortino_ratio)}`}
                            color={m.sharpe_ratio >= 1 ? 'text-emerald-400' : m.sharpe_ratio >= 0 ? 'text-yellow-400' : 'text-red-400'}
                        />
                        <MetricCard
                            label="Max Drawdown"
                            value={fmtPct(m.max_drawdown_pct)}
                            sub="peak-to-trough"
                            color="text-red-400"
                        />
                        <MetricCard
                            label="Win Rate"
                            value={m.win_rate_pct != null ? `${fmt(m.win_rate_pct, 1)}%` : '—'}
                            sub={`${m.winning_trades}W / ${m.losing_trades}L of ${m.total_trades} trades`}
                            color={m.win_rate_pct >= 55 ? 'text-emerald-400' : 'text-yellow-400'}
                        />
                        <MetricCard
                            label="Profit Factor"
                            value={fmt(m.profit_factor)}
                            sub="gross profit / gross loss"
                            color={m.profit_factor >= 1.5 ? 'text-emerald-400' : m.profit_factor >= 1 ? 'text-yellow-400' : 'text-red-400'}
                        />
                        <MetricCard
                            label="Avg Hold"
                            value={m.avg_hold_days != null ? `${fmt(m.avg_hold_days, 1)}d` : '—'}
                            sub="average trade duration"
                        />
                        <MetricCard
                            label="Final Portfolio"
                            value={`$${(result.config.initial_capital * (1 + (m.total_return_pct || 0) / 100)).toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
                            sub={`from $${Number(result.config.initial_capital).toLocaleString()}`}
                        />
                        <MetricCard
                            label="Period"
                            value={`${result.config.start_date} → ${result.config.end_date}`}
                            sub={`${m.total_trades} trades simulated`}
                        />
                    </div>

                    {/* Equity curve */}
                    {equityCurve.length > 1 && (
                        <div className="rounded-xl border border-border bg-card/50 p-5">
                            <h3 className="font-semibold text-sm mb-4 flex items-center gap-2">
                                <TrendingUp className="h-4 w-4 text-emerald-400" /> Portfolio Equity Curve
                            </h3>
                            <ResponsiveContainer width="100%" height={240}>
                                <LineChart data={equityCurve} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                                    <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                                        tickFormatter={v => v.slice(5)} interval="preserveStartEnd" />
                                    <YAxis tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                                        tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} width={48} />
                                    <ReferenceLine y={result.config.initial_capital} stroke="hsl(var(--border))" strokeDasharray="4 4" />
                                    <Tooltip
                                        contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                                        formatter={(val, name) => [
                                            name === 'value' ? `$${val.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : `${val.toFixed(2)}%`,
                                            name === 'value' ? 'Portfolio' : 'Drawdown',
                                        ]}
                                    />
                                    <Line type="monotone" dataKey="value" stroke="#10b981" strokeWidth={2} dot={false} />
                                </LineChart>
                            </ResponsiveContainer>
                        </div>
                    )}

                    {/* Monthly returns */}
                    {monthly.length > 0 && (
                        <div className="rounded-xl border border-border bg-card/50 p-5">
                            <h3 className="font-semibold text-sm mb-4">Monthly Returns</h3>
                            <div className="flex flex-wrap gap-2">
                                {monthly.map(([month, ret]) => (
                                    <div key={month} className={`rounded-lg px-3 py-2 text-center min-w-[80px] ${
                                        ret >= 3 ? 'bg-emerald-500/20 text-emerald-400' :
                                        ret >= 0 ? 'bg-emerald-500/10 text-emerald-500' :
                                        ret >= -3 ? 'bg-red-500/10 text-red-400' :
                                        'bg-red-500/20 text-red-400'
                                    }`}>
                                        <p className="text-[10px] text-muted-foreground">{month}</p>
                                        <p className="text-sm font-bold tabular-nums">{fmtPct(ret)}</p>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Trade log */}
                    {trades.length > 0 && (
                        <div className="rounded-xl border border-border overflow-hidden bg-card/50">
                            <div className="p-4 border-b border-border flex items-center justify-between">
                                <h3 className="font-semibold text-sm flex items-center gap-2">
                                    <BarChart2 className="h-4 w-4" /> Trade Log ({trades.length} trades)
                                </h3>
                            </div>
                            <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
                                <table className="w-full text-xs">
                                    <thead className="bg-muted/40 border-b border-border text-muted-foreground sticky top-0">
                                        <tr>
                                            <th className="text-left px-4 py-2 font-medium">Ticker</th>
                                            <th className="text-left px-4 py-2 font-medium">Signal</th>
                                            <th className="text-left px-4 py-2 font-medium">Entry</th>
                                            <th className="text-left px-4 py-2 font-medium">Exit</th>
                                            <th className="text-right px-4 py-2 font-medium">Entry $</th>
                                            <th className="text-right px-4 py-2 font-medium">Exit $</th>
                                            <th className="text-right px-4 py-2 font-medium">Return</th>
                                            <th className="text-right px-4 py-2 font-medium">Days</th>
                                            <th className="text-left px-4 py-2 font-medium">Exit Reason</th>
                                            <th className="text-left px-4 py-2 font-medium">Regime</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-border/40">
                                        {trades.map((t, i) => (
                                            <tr key={i} className="hover:bg-muted/20">
                                                <td className="px-4 py-2 font-bold">{t.ticker}</td>
                                                <td className="px-4 py-2">
                                                    <span className="text-[10px] px-1.5 py-0.5 rounded font-semibold"
                                                        style={{ color: SIGNAL_COLORS[t.signal], background: (SIGNAL_COLORS[t.signal] || '#888') + '1a' }}>
                                                        {t.signal?.replace('_', ' ')}
                                                    </span>
                                                </td>
                                                <td className="px-4 py-2 text-muted-foreground">{t.entry_date?.slice(0, 10)}</td>
                                                <td className="px-4 py-2 text-muted-foreground">{t.exit_date?.slice(0, 10)}</td>
                                                <td className="px-4 py-2 text-right tabular-nums">${fmt(t.entry_price)}</td>
                                                <td className="px-4 py-2 text-right tabular-nums">${fmt(t.exit_price)}</td>
                                                <td className={`px-4 py-2 text-right tabular-nums font-semibold ${t.return_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                                    {fmtPct(t.return_pct)}
                                                </td>
                                                <td className="px-4 py-2 text-right text-muted-foreground">{t.hold_days}</td>
                                                <td className={`px-4 py-2 font-semibold ${EXIT_COLORS[t.exit_reason] || ''}`}>{t.exit_reason}</td>
                                                <td className="px-4 py-2 text-muted-foreground text-[10px]">{t.regime || '—'}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}

                    {/* Return by regime */}
                    {result.metrics?.return_by_regime && Object.keys(result.metrics.return_by_regime).length > 0 && (
                        <div className="rounded-xl border border-border bg-card/50 p-5">
                            <h3 className="font-semibold text-sm mb-3">Return by Macro Regime</h3>
                            <div className="flex flex-wrap gap-3">
                                {Object.entries(result.metrics.return_by_regime).map(([regime, ret]) => (
                                    <div key={regime} className="bg-muted/20 rounded-lg px-4 py-2 text-center">
                                        <p className="text-xs text-muted-foreground">{regime}</p>
                                        <p className={`text-sm font-bold tabular-nums ${ret >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                                            {fmtPct(ret)}
                                        </p>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    <p className="text-xs text-muted-foreground px-1">
                        Entry at next-day close after signal. Exit on stop-loss, take-profit (ATR-based), max hold, or adverse signal.
                        Sizing via half-Kelly (capped 20%) when enabled. Past performance does not guarantee future results.
                    </p>
                </>
            )}
        </div>
    );
}
