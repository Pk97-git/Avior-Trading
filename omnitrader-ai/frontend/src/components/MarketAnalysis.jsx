import React, { useEffect, useState, useCallback } from 'react';
import { agentsApi } from '../api';
import { RefreshCw, Loader2, TrendingUp, TrendingDown } from 'lucide-react';
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
    ResponsiveContainer, Cell,
} from 'recharts';

const REGIME_COLORS = {
    'Risk-On':             { bg: 'bg-emerald-500/10', border: 'border-emerald-500/40', text: 'text-emerald-400', dot: 'bg-emerald-400' },
    'Liquidity Expansion': { bg: 'bg-blue-500/10',    border: 'border-blue-500/40',    text: 'text-blue-400',    dot: 'bg-blue-400'    },
    'Tightening':          { bg: 'bg-yellow-500/10',  border: 'border-yellow-500/40',  text: 'text-yellow-400',  dot: 'bg-yellow-400'  },
    'Risk-Off':            { bg: 'bg-red-500/10',     border: 'border-red-500/40',     text: 'text-red-400',     dot: 'bg-red-400'     },
    'Recession Risk':      { bg: 'bg-orange-500/10',  border: 'border-orange-500/40',  text: 'text-orange-400',  dot: 'bg-orange-400'  },
};
const DEFAULT_REGIME_COLOR = { bg: 'bg-muted/10', border: 'border-border', text: 'text-muted-foreground', dot: 'bg-muted' };

const BANNER_INDICATORS = [
    { label: 'VIX',       key: 'VIX',      fmt: v => v?.toFixed(1)              },
    { label: 'US 10Y',    key: 'US10Y',    fmt: v => v ? v.toFixed(2) + '%' : '—' },
    { label: 'Fed Funds', key: 'FEDFUNDS', fmt: v => v ? v.toFixed(2) + '%' : '—' },
    { label: 'CPI',       key: 'CPI',      fmt: v => v ? v.toFixed(1) + '%' : '—' },
    { label: 'DXY',       key: 'DXY',      fmt: v => v?.toFixed(1)              },
    { label: 'INR/USD',   key: 'INR=X',    fmt: v => v?.toFixed(2)              },
];

function pctColor(v) {
    if (v == null) return 'text-muted-foreground';
    return v >= 0 ? 'text-emerald-400' : 'text-red-400';
}

function pctFmt(v) {
    if (v == null) return '—';
    return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
}

function fmtXAxis(d) {
    // d is "YYYY-MM-DD" → show "DD Mon"
    try {
        const date = new Date(d);
        return date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
    } catch {
        return d;
    }
}

export default function MarketAnalysis() {
    const [data, setData]       = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError]     = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await agentsApi.getMarketAnalysis();
            setData(res.data);
        } catch (e) {
            setError(e?.response?.data?.detail || 'Failed to load market analysis.');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    if (loading) return (
        <div className="flex items-center justify-center h-64 text-muted-foreground gap-2">
            <Loader2 className="animate-spin h-5 w-5" /> Loading market analysis…
        </div>
    );

    if (error) return (
        <div className="flex flex-col items-center justify-center h-64 gap-2 text-red-400">
            <p>{error}</p>
            <button onClick={load} className="text-sm text-muted-foreground underline">Retry</button>
        </div>
    );

    const regime      = data?.regime || {};
    const regimeCfg   = REGIME_COLORS[regime.regime] || DEFAULT_REGIME_COLOR;
    const indicators  = regime.indicators || {};
    const sectors     = data?.sectors     || [];
    const fiiDii      = data?.fii_dii     || [];
    const crossAssets = data?.cross_assets || [];

    const shownIndicators = BANNER_INDICATORS.filter(ind => indicators[ind.key] != null);

    return (
        <div className="space-y-6">

            {/* ── Header ── */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-xl font-bold">Market Analysis</h2>
                    <p className="text-sm text-muted-foreground">Macro regime · Sector rotation · FII/DII flows</p>
                </div>
                <button
                    onClick={load}
                    className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground px-3 py-1.5 rounded-md border border-border hover:bg-accent transition-colors"
                >
                    <RefreshCw className="h-4 w-4" /> Refresh
                </button>
            </div>

            {/* ── Regime banner ── */}
            <div className={`rounded-xl border p-5 ${regimeCfg.bg} ${regimeCfg.border}`}>
                <div className="flex items-center gap-3 mb-4">
                    <span className={`h-3 w-3 rounded-full shrink-0 ${regimeCfg.dot}`} />
                    <h3 className={`text-lg font-bold ${regimeCfg.text}`}>{regime.regime || 'Unknown'}</h3>
                    {regime.confidence != null && (
                        <span className="text-xs text-muted-foreground px-2 py-0.5 rounded-full bg-background/50 border border-border/60">
                            {Math.round(regime.confidence * 100)}% confidence
                        </span>
                    )}
                </div>
                {shownIndicators.length > 0 && (
                    <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
                        {shownIndicators.map(ind => (
                            <div key={ind.key} className="bg-background/50 rounded-lg p-2.5 border border-border/40">
                                <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{ind.label}</p>
                                <p className="text-sm font-semibold mt-0.5">{ind.fmt(indicators[ind.key]) ?? '—'}</p>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* ── Sector rotation + Cross assets ── */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

                {/* Sector rotation table */}
                <div className="rounded-xl border border-border bg-card/50 p-4">
                    <h3 className="font-semibold text-sm mb-3">Sector Rotation (SPDR ETFs)</h3>
                    {sectors.length === 0 ? (
                        <p className="text-sm text-muted-foreground py-6 text-center">No sector data available.</p>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full text-xs">
                                <thead>
                                    <tr className="text-muted-foreground border-b border-border">
                                        <th className="text-left py-2 font-medium w-7">#</th>
                                        <th className="text-left py-2 font-medium">ETF</th>
                                        <th className="text-left py-2 font-medium">Sector</th>
                                        <th className="text-right py-2 font-medium">4W</th>
                                        <th className="text-right py-2 font-medium">12W</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-border/40">
                                    {sectors.map((s, i) => (
                                        <tr key={s.etf} className="hover:bg-muted/20 transition-colors">
                                            <td className="py-2 text-muted-foreground/60">{i + 1}</td>
                                            <td className="py-2 font-mono font-semibold">{s.etf}</td>
                                            <td className="py-2 text-muted-foreground truncate max-w-[130px]">{s.sector}</td>
                                            <td className={`py-2 text-right tabular-nums font-semibold ${pctColor(s.change_4w_pct)}`}>
                                                {pctFmt(s.change_4w_pct)}
                                            </td>
                                            <td className={`py-2 text-right tabular-nums ${pctColor(s.change_12w_pct)}`}>
                                                {pctFmt(s.change_12w_pct)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>

                {/* Cross-assets grid */}
                <div className="rounded-xl border border-border bg-card/50 p-4">
                    <h3 className="font-semibold text-sm mb-3">Cross-Assets</h3>
                    {crossAssets.length === 0 ? (
                        <p className="text-sm text-muted-foreground py-6 text-center">No cross-asset data available.</p>
                    ) : (
                        <div className="grid grid-cols-2 gap-3">
                            {crossAssets.map(a => (
                                <div key={a.label} className="rounded-lg border border-border/60 bg-background/50 p-3">
                                    <p className="text-xs text-muted-foreground">{a.label}</p>
                                    <p className="text-lg font-bold tabular-nums mt-0.5">{a.value?.toLocaleString()}</p>
                                    <div className="flex items-center gap-1 mt-1">
                                        {(a.change_1w_pct ?? 0) >= 0
                                            ? <TrendingUp  className="h-3 w-3 text-emerald-400" />
                                            : <TrendingDown className="h-3 w-3 text-red-400" />
                                        }
                                        <span className={`text-xs font-semibold ${pctColor(a.change_1w_pct)}`}>
                                            {pctFmt(a.change_1w_pct)} 1W
                                        </span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>

            {/* ── FII / DII chart ── */}
            {fiiDii.length > 0 && (
                <div className="rounded-xl border border-border bg-card/50 p-4">
                    <h3 className="font-semibold text-sm mb-4">FII / DII Net Flows — India (₹ Cr, 30 days)</h3>
                    <ResponsiveContainer width="100%" height={220}>
                        <BarChart data={fiiDii} margin={{ top: 4, right: 8, left: 0, bottom: 4 }} barGap={2}>
                            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                            <XAxis
                                dataKey="date"
                                tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                                tickFormatter={fmtXAxis}
                                interval="preserveStartEnd"
                            />
                            <YAxis
                                tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                                tickFormatter={v => `${(v / 1000).toFixed(0)}k`}
                                width={42}
                            />
                            <Tooltip
                                contentStyle={{
                                    background: 'hsl(var(--card))',
                                    border: '1px solid hsl(var(--border))',
                                    borderRadius: 8,
                                    fontSize: 12,
                                }}
                                formatter={(val, name) => [
                                    `₹${val?.toLocaleString()} Cr`,
                                    name === 'fii_net' ? 'FII' : 'DII',
                                ]}
                                labelFormatter={fmtXAxis}
                            />
                            <Bar dataKey="fii_net" name="FII" radius={[2, 2, 0, 0]}>
                                {fiiDii.map((entry, i) => (
                                    <Cell key={i} fill={entry.fii_net >= 0 ? '#10b981' : '#ef4444'} fillOpacity={0.85} />
                                ))}
                            </Bar>
                            <Bar dataKey="dii_net" name="DII" radius={[2, 2, 0, 0]}>
                                {fiiDii.map((entry, i) => (
                                    <Cell key={i} fill={entry.dii_net >= 0 ? '#3b82f6' : '#f97316'} fillOpacity={0.75} />
                                ))}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>

                    <div className="flex gap-4 mt-3 justify-center">
                        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                            <span className="h-2.5 w-4 rounded-sm bg-emerald-500 opacity-85 inline-block" /> FII (net)
                        </div>
                        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                            <span className="h-2.5 w-4 rounded-sm bg-blue-500 opacity-75 inline-block" /> DII (net)
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
