import React, { useEffect, useState, useCallback } from 'react';
import { agentsApi } from '../api';
import { Loader2, RefreshCw, BarChart2, TrendingUp, TrendingDown } from 'lucide-react';
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
    ResponsiveContainer, Cell, ReferenceLine,
} from 'recharts';

const SIGNAL_COLORS = {
    STRONG_BUY:   '#10b981',
    ACCUMULATE:   '#3b82f6',
    AVOID:        '#eab308',
    DISTRIBUTION: '#ef4444',
};

const SIGNAL_LABELS = {
    STRONG_BUY:   'Strong Buy',
    ACCUMULATE:   'Accumulate',
    AVOID:        'Avoid',
    DISTRIBUTION: 'Distribution',
};

const LOOKBACK_OPTIONS = [30, 60, 90, 180, 365];

function MetricCard({ label, value, sub, color, icon: Icon }) {
    return (
        <div className="rounded-xl border border-border bg-card/50 p-4">
            <div className="flex items-center gap-1.5 text-muted-foreground text-xs font-medium mb-1">
                {Icon && <Icon className="h-3.5 w-3.5" />}
                {label}
            </div>
            <p className={`text-2xl font-bold tabular-nums ${color || 'text-foreground'}`}>{value ?? '—'}</p>
            {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
        </div>
    );
}

function HitRateBar({ signal, hitRate, total }) {
    if (hitRate == null) return null;
    const color = SIGNAL_COLORS[signal] || '#888';
    const label = SIGNAL_LABELS[signal] || signal;
    return (
        <div className="space-y-1">
            <div className="flex items-center justify-between text-xs">
                <span className="font-medium" style={{ color }}>{label}</span>
                <span className="text-muted-foreground">
                    {hitRate.toFixed(1)}% ({total} signals)
                </span>
            </div>
            <div className="h-2 bg-muted/40 rounded-full overflow-hidden">
                <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{ width: `${Math.min(hitRate, 100)}%`, backgroundColor: color }}
                />
            </div>
        </div>
    );
}

export default function SignalPerformance() {
    const [data, setData]       = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError]     = useState(null);
    const [days, setDays]       = useState(90);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await agentsApi.getSignalPerformance(days);
            setData(res.data);
        } catch (e) {
            setError(e?.response?.data?.detail || 'Failed to load performance data.');
        } finally {
            setLoading(false);
        }
    }, [days]);

    useEffect(() => { load(); }, [load]);

    const bySignal = data?.by_signal || [];

    // Summary metrics
    const buySignals   = bySignal.filter(s => ['STRONG_BUY', 'ACCUMULATE'].includes(s.signal));
    const avgBuyReturn = buySignals.length
        ? buySignals.reduce((sum, s) => sum + (s.avg_return_30d || 0) * (s.with_outcome || 0), 0)
          / Math.max(1, buySignals.reduce((sum, s) => sum + (s.with_outcome || 0), 0))
        : null;

    const strongBuy = bySignal.find(s => s.signal === 'STRONG_BUY');
    const dist      = bySignal.find(s => s.signal === 'DISTRIBUTION');

    const chartData = bySignal
        .filter(s => s.avg_return_30d != null)
        .map(s => ({
            signal:  SIGNAL_LABELS[s.signal] || s.signal,
            key:     s.signal,
            return:  s.avg_return_30d,
            signals: s.with_outcome,
        }));

    return (
        <div className="space-y-6">

            {/* ── Header ── */}
            <div className="flex items-center justify-between flex-wrap gap-3">
                <div>
                    <h2 className="text-xl font-bold flex items-center gap-2">
                        <BarChart2 className="h-5 w-5 text-primary" /> Signal Performance
                    </h2>
                    <p className="text-sm text-muted-foreground">
                        Historical accuracy of AI-generated signals vs actual 30-day forward returns
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    {/* Lookback selector */}
                    <div className="flex rounded-md border border-border overflow-hidden text-xs">
                        {LOOKBACK_OPTIONS.map(d => (
                            <button
                                key={d}
                                onClick={() => setDays(d)}
                                className={`px-2.5 py-1.5 font-medium transition-colors ${
                                    days === d
                                        ? 'bg-primary text-primary-foreground'
                                        : 'hover:bg-accent text-muted-foreground'
                                }`}
                            >
                                {d}d
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

            {loading ? (
                <div className="flex items-center justify-center h-64 text-muted-foreground gap-2">
                    <Loader2 className="animate-spin h-5 w-5" /> Calculating performance…
                </div>
            ) : error ? (
                <div className="flex flex-col items-center justify-center h-64 gap-2 text-red-400">
                    <p>{error}</p>
                    <button onClick={load} className="text-sm text-muted-foreground underline">Retry</button>
                </div>
            ) : bySignal.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-64 text-muted-foreground space-y-3 border border-dashed border-border rounded-xl">
                    <BarChart2 className="h-10 w-10 opacity-20" />
                    <p className="text-sm font-medium">No historical signal data yet.</p>
                    <p className="text-xs">Run the agent scoring pipeline for at least 30 days to see performance stats.</p>
                </div>
            ) : (
                <>
                    {/* ── Summary cards ── */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <MetricCard
                            icon={BarChart2}
                            label="Total Analyses"
                            value={data?.total_analyses?.toLocaleString()}
                            sub={`past ${days} days`}
                        />
                        <MetricCard
                            icon={TrendingUp}
                            label="Avg Buy Return (30d)"
                            value={avgBuyReturn != null ? `${avgBuyReturn >= 0 ? '+' : ''}${avgBuyReturn.toFixed(1)}%` : '—'}
                            sub="STRONG_BUY + ACCUMULATE"
                            color={avgBuyReturn != null ? (avgBuyReturn >= 0 ? 'text-emerald-400' : 'text-red-400') : undefined}
                        />
                        <MetricCard
                            label="Strong Buy Hit Rate"
                            value={strongBuy?.hit_rate_pct != null ? `${strongBuy.hit_rate_pct}%` : '—'}
                            sub={strongBuy ? `${strongBuy.with_outcome} signals with outcome` : 'No data'}
                            color={strongBuy?.hit_rate_pct >= 55 ? 'text-emerald-400' : strongBuy?.hit_rate_pct != null ? 'text-yellow-400' : undefined}
                        />
                        <MetricCard
                            icon={TrendingDown}
                            label="Distribution Hit Rate"
                            value={dist?.hit_rate_pct != null ? `${dist.hit_rate_pct}%` : '—'}
                            sub={dist ? `${dist.with_outcome} signals with outcome` : 'No data'}
                            color={dist?.hit_rate_pct >= 55 ? 'text-emerald-400' : dist?.hit_rate_pct != null ? 'text-yellow-400' : undefined}
                        />
                    </div>

                    {/* ── Return chart ── */}
                    {chartData.length > 0 && (
                        <div className="rounded-xl border border-border bg-card/50 p-5">
                            <h3 className="font-semibold text-sm mb-4">Average 30-Day Forward Return by Signal</h3>
                            <ResponsiveContainer width="100%" height={200}>
                                <BarChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                                    <XAxis dataKey="signal" tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} />
                                    <YAxis
                                        tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                                        tickFormatter={v => `${v}%`}
                                        width={40}
                                    />
                                    <ReferenceLine y={0} stroke="hsl(var(--border))" />
                                    <Tooltip
                                        contentStyle={{
                                            background: 'hsl(var(--card))',
                                            border: '1px solid hsl(var(--border))',
                                            borderRadius: 8,
                                            fontSize: 12,
                                        }}
                                        formatter={(val, name) => [`${val >= 0 ? '+' : ''}${val}%`, 'Avg 30d return']}
                                    />
                                    <Bar dataKey="return" radius={[4, 4, 0, 0]}>
                                        {chartData.map((entry) => (
                                            <Cell
                                                key={entry.key}
                                                fill={SIGNAL_COLORS[entry.key] || '#888'}
                                                fillOpacity={0.85}
                                            />
                                        ))}
                                    </Bar>
                                </BarChart>
                            </ResponsiveContainer>
                        </div>
                    )}

                    {/* ── Hit rate bars ── */}
                    <div className="rounded-xl border border-border bg-card/50 p-5">
                        <h3 className="font-semibold text-sm mb-4">Directional Accuracy (Hit Rate)</h3>
                        <div className="space-y-4">
                            {bySignal
                                .filter(s => s.hit_rate_pct != null)
                                .map(s => (
                                    <HitRateBar
                                        key={s.signal}
                                        signal={s.signal}
                                        hitRate={s.hit_rate_pct}
                                        total={s.total_signals}
                                    />
                                ))
                            }
                            {bySignal.every(s => s.hit_rate_pct == null) && (
                                <p className="text-sm text-muted-foreground text-center py-4">
                                    Hit rate data requires at least 30 days of forward price history after signal generation.
                                </p>
                            )}
                        </div>
                    </div>

                    {/* ── Detailed table ── */}
                    <div className="rounded-xl border border-border overflow-hidden bg-card/50">
                        <table className="w-full text-sm">
                            <thead className="bg-muted/40 border-b border-border text-muted-foreground text-xs">
                                <tr>
                                    <th className="text-left px-4 py-3 font-medium">Signal</th>
                                    <th className="text-right px-4 py-3 font-medium">Total</th>
                                    <th className="text-right px-4 py-3 font-medium">With Outcome</th>
                                    <th className="text-right px-4 py-3 font-medium">Pending</th>
                                    <th className="text-right px-4 py-3 font-medium">Avg Score</th>
                                    <th className="text-right px-4 py-3 font-medium">Avg 30d Return</th>
                                    <th className="text-right px-4 py-3 font-medium">Hit Rate</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border/40">
                                {bySignal.map(s => (
                                    <tr key={s.signal} className="hover:bg-muted/20">
                                        <td className="px-4 py-3">
                                            <span
                                                className="font-semibold text-xs px-2 py-0.5 rounded"
                                                style={{
                                                    color: SIGNAL_COLORS[s.signal],
                                                    background: SIGNAL_COLORS[s.signal] + '1a',
                                                }}
                                            >
                                                {SIGNAL_LABELS[s.signal] || s.signal}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3 text-right tabular-nums text-xs">{s.total_signals}</td>
                                        <td className="px-4 py-3 text-right tabular-nums text-xs">{s.with_outcome}</td>
                                        <td className="px-4 py-3 text-right tabular-nums text-xs text-muted-foreground">{s.pending}</td>
                                        <td className="px-4 py-3 text-right tabular-nums text-xs">
                                            {s.avg_score != null ? s.avg_score.toFixed(1) : '—'}
                                        </td>
                                        <td className={`px-4 py-3 text-right tabular-nums text-xs font-semibold ${
                                            s.avg_return_30d == null ? 'text-muted-foreground/50' :
                                            s.avg_return_30d >= 0 ? 'text-emerald-400' : 'text-red-400'
                                        }`}>
                                            {s.avg_return_30d != null
                                                ? `${s.avg_return_30d >= 0 ? '+' : ''}${s.avg_return_30d.toFixed(2)}%`
                                                : '—'}
                                        </td>
                                        <td className={`px-4 py-3 text-right tabular-nums text-xs font-semibold ${
                                            s.hit_rate_pct == null ? 'text-muted-foreground/50' :
                                            s.hit_rate_pct >= 55 ? 'text-emerald-400' : 'text-yellow-400'
                                        }`}>
                                            {s.hit_rate_pct != null ? `${s.hit_rate_pct}%` : '—'}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>

                    <p className="text-xs text-muted-foreground px-1">
                        Hit rate = % of buy signals where price was higher 30 days later (or % of DISTRIBUTION signals where price was lower).
                        Signals with insufficient forward price data are shown as pending.
                    </p>
                </>
            )}
        </div>
    );
}
