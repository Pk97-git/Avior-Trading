import React, { useEffect, useState, useCallback } from 'react';
import { agentsApi, circuitBreakerApi } from '../api';
import { TrendingUp, Zap, Globe2, Bell, RefreshCw, Loader2, ChevronRight, AlertTriangle, ShieldAlert } from 'lucide-react';
import SignalCard, { SignalBadge } from './shared/SignalCard';

const REGIME_COLORS = {
    'Risk-On': { text: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30' },
    'Liquidity Expansion': { text: 'text-blue-400', bg: 'bg-blue-500/10', border: 'border-blue-500/30' },
    'Tightening': { text: 'text-yellow-400', bg: 'bg-yellow-500/10', border: 'border-yellow-500/30' },
    'Risk-Off': { text: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/30' },
    'Recession Risk': { text: 'text-orange-400', bg: 'bg-orange-500/10', border: 'border-orange-500/30' },
};
const DEFAULT_REGIME_CFG = { text: 'text-muted-foreground', bg: 'bg-muted/10', border: 'border-border' };

const SIGNAL_PILLS = [
    { key: 'STRONG_BUY', label: 'Strong Buy', cls: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30' },
    { key: 'ACCUMULATE', label: 'Accumulate', cls: 'text-blue-400 bg-blue-500/10 border-blue-500/30' },
    { key: 'PROACTIVE_SWING', label: 'Swing Setup', cls: 'text-purple-400 bg-purple-500/10 border-purple-500/30' },
    { key: 'AVOID', label: 'Avoid', cls: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30' },
    { key: 'DISTRIBUTION', label: 'Distribution', cls: 'text-red-400 bg-red-500/10 border-red-500/30' },
];

function StatCard({ icon, label, value, sub, color }) {
    return (
        <div className="rounded-xl border border-border bg-card/50 p-4 flex flex-col gap-1">
            <div className="flex items-center gap-1.5 text-muted-foreground text-xs font-medium mb-1">
                {icon}
                {label}
            </div>
            <p className={`text-2xl font-bold tabular-nums ${color || 'text-foreground'}`}>{value ?? '—'}</p>
            {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
        </div>
    );
}

function AlertRow({ alert }) {
    const { ticker, name, country, signal, previous_signal, final_score, headline, generated_at, image_url } = alert;
    return (
        <div className="flex items-start gap-3 py-3 border-b border-border/40 last:border-0 hover:bg-muted/10 transition-colors p-2 rounded-lg -mx-2">
            {image_url && (
                <div className="shrink-0 w-12 h-12 bg-muted rounded overflow-hidden border border-border">
                    <img src={image_url} alt="Chart" className="w-full h-full object-cover" loading="lazy" />
                </div>
            )}
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-bold text-xs">{ticker}</span>
                    {name && <span className="text-muted-foreground text-xs truncate max-w-[120px]">{name}</span>}
                    {country && (
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${country === 'IN' ? 'bg-orange-500/20 text-orange-400' : 'bg-blue-500/20 text-blue-400'}`}>
                            {country}
                        </span>
                    )}
                    <SignalBadge signal={signal} size="sm" />
                    {previous_signal && previous_signal !== signal && (
                        <span className="text-[10px] text-muted-foreground/60">← {previous_signal}</span>
                    )}
                </div>
                {headline && <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">{headline}</p>}
            </div>
            <div className="text-right shrink-0">
                {final_score != null && (
                    <span className="text-sm font-bold tabular-nums">{final_score}</span>
                )}
                <p className="text-[10px] text-muted-foreground/60 mt-0.5">
                    {generated_at ? new Date(generated_at).toLocaleDateString() : ''}
                </p>
            </div>
        </div>
    );
}

export default function Dashboard({ onNavigate }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [markingRead, setMarkingRead] = useState(false);

    // ── Circuit Breaker status ──────────────────────────────────────────────────
    const [cbStatus, setCbStatus] = useState(null); // { status, reasons }

    useEffect(() => {
        let cancelled = false;
        const fetchCB = async () => {
            try {
                const res = await circuitBreakerApi.getStatus();
                if (!cancelled) setCbStatus(res.data);
            } catch {
                // silently ignore — don't block dashboard on CB failure
            }
        };
        fetchCB();
        const interval = setInterval(fetchCB, 5 * 60 * 1000); // every 5 min
        return () => { cancelled = true; clearInterval(interval); };
    }, []);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await agentsApi.getDashboard();
            setData(res.data);
        } catch (e) {
            setError(e?.response?.data?.detail || 'Failed to load dashboard.');
        } finally {
            setLoading(false);
        }
    }, []);

    const markAllRead = useCallback(async () => {
        setMarkingRead(true);
        try {
            await agentsApi.markAlertsRead([]);
            // Refresh unread count without full reload
            setData(prev => prev ? { ...prev, unread_alerts: 0 } : prev);
        } finally {
            setMarkingRead(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    if (loading) return (
        <div className="flex items-center justify-center h-64 text-muted-foreground gap-2">
            <Loader2 className="animate-spin h-5 w-5" /> Loading dashboard…
        </div>
    );

    if (error) return (
        <div className="flex flex-col items-center justify-center h-64 gap-2 text-red-400">
            <p>{error}</p>
            <button onClick={load} className="text-sm text-muted-foreground underline">Retry</button>
        </div>
    );

    const sc = data?.signal_counts || {};
    const buyCount = (sc.STRONG_BUY || 0) + (sc.ACCUMULATE || 0);
    const regimeCfg = REGIME_COLORS[data?.regime] || DEFAULT_REGIME_CFG;
    const topSignals = data?.top_signals || [];
    const recentAlerts = data?.recent_alerts || [];

    return (
        <div className="space-y-6">

            {/* ── Header ── */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-xl font-bold">Executive Dashboard</h2>
                    <p className="text-sm text-muted-foreground">Today's signal summary</p>
                </div>
                <button
                    onClick={load}
                    className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground px-3 py-1.5 rounded-md border border-border hover:bg-accent transition-colors"
                >
                    <RefreshCw className="h-4 w-4" /> Refresh
                </button>
            </div>

            {/* ── Circuit Breaker Banner ── */}
            {cbStatus && cbStatus.status !== 'CLEAR' && (
                <div className={`w-full rounded-xl px-5 py-4 flex flex-col gap-2 border ${
                    cbStatus.status === 'HALT'
                        ? 'bg-red-500/10 border-red-500/30 text-red-300'
                        : 'bg-yellow-500/10 border-yellow-500/30 text-yellow-300'
                }`}>
                    <div className="flex items-center gap-2 font-semibold text-sm">
                        {cbStatus.status === 'HALT'
                            ? <ShieldAlert className="h-4 w-4 shrink-0" />
                            : <AlertTriangle className="h-4 w-4 shrink-0" />
                        }
                        Circuit Breaker: {cbStatus.status}
                    </div>
                    {Array.isArray(cbStatus.reasons) && cbStatus.reasons.length > 0 && (
                        <ul className="list-disc list-inside text-xs space-y-0.5 opacity-90">
                            {cbStatus.reasons.map((r, i) => <li key={i}>{r}</li>)}
                        </ul>
                    )}
                </div>
            )}

            {/* ── Stats ── */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <StatCard
                    icon={<TrendingUp className="h-3.5 w-3.5" />}
                    label="Buy Signals Today"
                    value={buyCount}
                    sub={`${sc.STRONG_BUY || 0} strong · ${sc.ACCUMULATE || 0} accumulate`}
                    color="text-emerald-400"
                />
                <StatCard
                    icon={<Zap className="h-3.5 w-3.5" />}
                    label="Avg Score"
                    value={data?.avg_score != null ? String(data.avg_score) : '—'}
                    sub="across tickers analysed today"
                />
                <StatCard
                    icon={<Globe2 className="h-3.5 w-3.5" />}
                    label="Macro Regime"
                    value={data?.regime || '—'}
                    sub={data?.regime_confidence != null
                        ? `${Math.round(data.regime_confidence * 100)}% confidence`
                        : ''}
                    color={regimeCfg.text}
                />
                <StatCard
                    icon={<Bell className="h-3.5 w-3.5" />}
                    label="Unread Alerts"
                    value={data?.unread_alerts ?? '—'}
                    sub="new signal changes"
                    color={data?.unread_alerts > 0 ? 'text-yellow-400' : undefined}
                />
            </div>

            {/* ── Signal distribution pills ── */}
            <div className="flex gap-2 flex-wrap">
                {SIGNAL_PILLS.map(({ key, label, cls }) => (
                    <span key={key} className={`px-3 py-1 rounded-full text-xs font-semibold border ${cls}`}>
                        {sc[key] || 0} {label}
                    </span>
                ))}
            </div>

            {/* ── Top Signals grid ── */}
            <div>
                <div className="flex items-center justify-between mb-3">
                    <h3 className="font-semibold text-sm">Top Signals</h3>
                    <button
                        onClick={() => onNavigate?.('hub')}
                        className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
                    >
                        View all <ChevronRight className="h-3 w-3" />
                    </button>
                </div>

                {topSignals.length === 0 ? (
                    <div className="text-center text-sm text-muted-foreground py-8 border border-dashed border-border rounded-xl">
                        No signals generated today. Run agents to generate signals.
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {topSignals.map(s => (
                            <SignalCard
                                key={s.ticker}
                                ticker={s.ticker}
                                name={s.name}
                                sector={s.sector}
                                country={s.country}
                                signal={s.signal}
                                final_score={s.final_score}
                                fundamental_score={s.fundamental_score}
                                technical_score={s.technical_score}
                                macro_score={s.macro_score}
                                institutional_score={s.institutional_score}
                                sentiment_score={s.sentiment_score}
                                signal_thesis={s.signal_thesis}
                                onClick={() => onNavigate?.('hub', s.ticker)}
                            />
                        ))}
                    </div>
                )}
            </div>

            {/* ── Recent Alerts ── */}
            <div>
                <div className="flex items-center justify-between mb-3">
                    <h3 className="font-semibold text-sm">Recent Alerts</h3>
                    <div className="flex items-center gap-3">
                        {(data?.unread_alerts > 0) && (
                            <button
                                onClick={markAllRead}
                                disabled={markingRead}
                                className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1 disabled:opacity-50"
                            >
                                {markingRead
                                    ? <Loader2 className="h-3 w-3 animate-spin" />
                                    : <Bell className="h-3 w-3" />
                                }
                                Mark all read
                            </button>
                        )}
                        <button
                            onClick={() => onNavigate?.('hub')}
                            className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
                        >
                            View all <ChevronRight className="h-3 w-3" />
                        </button>
                    </div>
                </div>
                <div className="rounded-xl border border-border bg-card/50 p-4">
                    {recentAlerts.length === 0 ? (
                        <p className="text-center text-sm text-muted-foreground py-4">No alerts yet.</p>
                    ) : (
                        recentAlerts.map((a, i) => <AlertRow key={i} alert={a} />)
                    )}
                </div>
            </div>
        </div>
    );
}
