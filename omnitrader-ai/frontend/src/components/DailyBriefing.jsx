import React, { useState, useEffect, useCallback } from 'react';
import {
    Newspaper, RefreshCw, TrendingUp, TrendingDown, AlertTriangle,
    ShieldAlert, ChevronDown, ChevronUp, Target, StopCircle,
    DollarSign, Activity, Zap, BarChart2, Calendar, Layers, Users,
    CheckCircle, XCircle, MinusCircle, ArrowRight, Clock,
} from 'lucide-react';
import { briefingApi } from '../api';

// ─── Constants ────────────────────────────────────────────────────────────────

const SIGNAL_STYLE = {
    STRONG_BUY:      { bg: 'bg-green-500/15',  border: 'border-green-500/40',  text: 'text-green-400',  badge: 'bg-green-500/20 text-green-400',  label: 'Strong Buy',    icon: TrendingUp },
    ACCUMULATE:      { bg: 'bg-blue-500/15',   border: 'border-blue-500/40',   text: 'text-blue-400',   badge: 'bg-blue-500/20 text-blue-400',    label: 'Accumulate',    icon: TrendingUp },
    PROACTIVE_SWING: { bg: 'bg-purple-500/15', border: 'border-purple-500/40', text: 'text-purple-400', badge: 'bg-purple-500/20 text-purple-400', label: 'Swing Setup',   icon: Zap },
    AVOID:           { bg: 'bg-yellow-500/10', border: 'border-yellow-500/30', text: 'text-yellow-400', badge: 'bg-yellow-500/20 text-yellow-400', label: 'Avoid',         icon: MinusCircle },
    DISTRIBUTION:    { bg: 'bg-red-500/10',    border: 'border-red-500/30',    text: 'text-red-400',    badge: 'bg-red-500/20 text-red-400',       label: 'Sell / Exit',   icon: TrendingDown },
};

const CB_STYLE = {
    CLEAR:   { color: 'text-green-400',  bg: 'bg-green-500/10',  icon: CheckCircle,  label: 'Market Clear — Trading Enabled' },
    CAUTION: { color: 'text-yellow-400', bg: 'bg-yellow-500/10', icon: AlertTriangle, label: 'Caution — Reduce Position Size' },
    HALT:    { color: 'text-red-400',    bg: 'bg-red-500/10',    icon: ShieldAlert,   label: 'Trading Halted — Circuit Breaker Active' },
    UNKNOWN: { color: 'text-slate-400',  bg: 'bg-slate-500/10',  icon: MinusCircle,   label: 'Status Unknown' },
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(n, d = 2) {
    if (n == null) return '—';
    return Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
}

function fmtPct(n) {
    if (n == null) return '—';
    return `${n >= 0 ? '+' : ''}${fmt(n)}%`;
}

function fmtPrice(n) {
    if (n == null) return '—';
    return `$${fmt(n)}`;
}

function sentimentColor(s) {
    if (s == null) return 'text-muted-foreground';
    if (s > 0.2)  return 'text-green-400';
    if (s < -0.2) return 'text-red-400';
    return 'text-yellow-400';
}

function ScoreBar({ label, value, color = 'bg-primary' }) {
    const pct = Math.max(0, Math.min(100, value || 0));
    return (
        <div className="flex items-center gap-2 text-xs">
            <span className="w-20 text-muted-foreground shrink-0">{label}</span>
            <div className="flex-1 bg-muted rounded-full h-1.5">
                <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
            </div>
            <span className="w-8 text-right font-medium">{value ?? '—'}</span>
        </div>
    );
}

function scoreColor(v) {
    if (v == null) return 'bg-muted';
    if (v >= 70) return 'bg-green-500';
    if (v >= 50) return 'bg-blue-500';
    if (v >= 35) return 'bg-yellow-500';
    return 'bg-red-500';
}

// ─── Macro Banner ─────────────────────────────────────────────────────────────

function MacroBanner({ macro, cb }) {
    const cbStyle = CB_STYLE[cb?.status] || CB_STYLE.UNKNOWN;
    const CbIcon  = cbStyle.icon;
    const vix     = macro?.vix;

    return (
        <div className={`rounded-lg border px-4 py-3 flex flex-wrap items-center gap-4 ${cbStyle.bg} border-border`}>
            <div className={`flex items-center gap-2 font-semibold text-sm ${cbStyle.color}`}>
                <CbIcon size={16} />
                {cbStyle.label}
            </div>
            {cb?.reasons?.length > 0 && (
                <span className="text-xs text-muted-foreground">
                    {cb.reasons.join(' · ')}
                </span>
            )}
            <div className="ml-auto flex items-center gap-5 text-xs text-muted-foreground">
                {vix != null && (
                    <span>VIX <strong className={vix > 25 ? 'text-red-400' : 'text-foreground'}>{fmt(vix)}</strong></span>
                )}
                {macro?.yield_spread != null && (
                    <span>10Y-2Y <strong className={macro.yield_inverted ? 'text-red-400' : 'text-foreground'}>{fmt(macro.yield_spread, 3)}%</strong></span>
                )}
                {macro?.indicators?.SP500 != null && (
                    <span>SPX <strong>{fmt(macro.indicators.SP500, 0)}</strong></span>
                )}
            </div>
        </div>
    );
}

// ─── Sector Chips ─────────────────────────────────────────────────────────────

function SectorChips({ sectors }) {
    if (!sectors?.length) return null;
    const top    = sectors.filter(s => s.rank_4w <= 3 && s.change_4w != null);
    const bottom = sectors.slice(-3).filter(s => s.change_4w != null);

    return (
        <div className="flex flex-wrap gap-2 items-center text-xs">
            <span className="text-muted-foreground font-medium">Sectors:</span>
            {top.map(s => (
                <span key={s.etf} className="px-2 py-0.5 rounded-full bg-green-500/15 text-green-400 border border-green-500/20">
                    ↑ {s.sector} ({fmtPct(s.change_4w)} 4W)
                </span>
            ))}
            {bottom.map(s => (
                <span key={s.etf} className="px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 border border-red-500/20">
                    ↓ {s.sector} ({fmtPct(s.change_4w)} 4W)
                </span>
            ))}
        </div>
    );
}

// ─── Stock Card ───────────────────────────────────────────────────────────────

function ThesisList({ items, color }) {
    if (!items?.length) return null;
    return (
        <ul className="space-y-1">
            {items.map((t, i) => (
                <li key={i} className="flex items-start gap-2 text-xs text-muted-foreground leading-relaxed">
                    <ArrowRight size={10} className={`mt-0.5 shrink-0 ${color}`} />
                    <span>{t}</span>
                </li>
            ))}
        </ul>
    );
}

function StockCard({ stock, onDeepDive }) {
    const [expanded, setExpanded] = useState(false);
    const style = SIGNAL_STYLE[stock.signal] || SIGNAL_STYLE.AVOID;
    const SignalIcon = style.icon;

    const r = stock.reasoning || {};
    const allTheses = [
        { label: 'Decision', items: r.executive,     color: style.text },
        { label: 'Technical',   items: r.technical,     color: 'text-blue-400' },
        { label: 'Fundamental', items: r.fundamental,   color: 'text-emerald-400' },
        { label: 'Macro',       items: r.macro,         color: 'text-purple-400' },
        { label: 'Sentiment',   items: r.sentiment,     color: 'text-yellow-400' },
        { label: 'Institutional', items: r.institutional, color: 'text-orange-400' },
        { label: 'Memory',      items: r.memory,        color: 'text-slate-400' },
    ].filter(t => t.items?.length);

    return (
        <div className={`rounded-lg border ${style.border} ${style.bg} overflow-hidden`}>

            {/* ── Card Header ── */}
            <div className="p-4">
                <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                        {/* Ticker + signal badge */}
                        <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-lg font-bold tracking-tight">{stock.ticker}</span>
                            <span className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${style.badge}`}>
                                <SignalIcon size={11} />
                                {stock.signal_label}
                            </span>
                            {stock.country && (
                                <span className="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground">{stock.country}</span>
                            )}
                            {/* Insider signal badge */}
                            {stock.insider_signal === 'CLUSTER_BUY' && (
                                <span className="text-xs px-2 py-0.5 rounded-full bg-orange-500/20 text-orange-400 border border-orange-500/30 font-semibold animate-pulse">
                                    🔥 Cluster Buy
                                </span>
                            )}
                            {stock.insider_signal === 'INSIDER_BUY' && (
                                <span className="text-xs px-2 py-0.5 rounded-full bg-orange-500/10 text-orange-400 font-medium">
                                    👤 Insider Buy
                                </span>
                            )}
                            {/* Analyst signal badge */}
                            {stock.analyst_signal?.signal === 'BULLISH' && (
                                <span className="text-xs px-2 py-0.5 rounded-full bg-blue-500/15 text-blue-400 border border-blue-500/20 font-medium">
                                    ↑ {stock.analyst_signal.upgrades} Upgrade{stock.analyst_signal.upgrades > 1 ? 's' : ''}
                                </span>
                            )}
                            {stock.analyst_signal?.signal === 'BEARISH' && (
                                <span className="text-xs px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 text-[10px]">
                                    ↓ Downgraded
                                </span>
                            )}
                        </div>
                        <p className="text-xs text-muted-foreground mt-0.5 truncate">{stock.name} · {stock.sector}</p>

                        {/* Headline */}
                        {stock.headline && (
                            <p className={`text-sm font-medium mt-2 leading-snug ${style.text}`}>
                                {stock.headline}
                            </p>
                        )}
                    </div>

                    {/* Score donut */}
                    <div className="text-center shrink-0">
                        <div className={`w-12 h-12 rounded-full flex items-center justify-center text-lg font-bold border-2 ${style.border}`}>
                            {stock.final_score ?? '—'}
                        </div>
                        <p className="text-[10px] text-muted-foreground mt-0.5">Score</p>
                    </div>
                </div>

                {/* ── Trade Levels ── */}
                {stock.entry_price && (
                    <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                        <div className="rounded bg-background/60 px-2 py-1.5">
                            <p className="text-muted-foreground flex items-center gap-1"><DollarSign size={10} />Entry</p>
                            <p className="font-semibold mt-0.5">{fmtPrice(stock.entry_price)}</p>
                        </div>
                        <div className="rounded bg-background/60 px-2 py-1.5">
                            <p className="text-muted-foreground flex items-center gap-1"><StopCircle size={10} />Stop</p>
                            <p className="font-semibold mt-0.5 text-red-400">{fmtPrice(stock.stop_loss)}</p>
                            {stock.downside_pct != null && <p className="text-[10px] text-red-400/70">{fmtPct(stock.downside_pct)}</p>}
                        </div>
                        <div className="rounded bg-background/60 px-2 py-1.5">
                            <p className="text-muted-foreground flex items-center gap-1"><Target size={10} />Target</p>
                            <p className="font-semibold mt-0.5 text-green-400">{fmtPrice(stock.take_profit)}</p>
                            {stock.upside_pct != null && <p className="text-[10px] text-green-400/70">{fmtPct(stock.upside_pct)}</p>}
                        </div>
                    </div>
                )}

                {/* R:R + Win Prob */}
                {(stock.risk_reward != null || stock.calibrated_prob != null) && (
                    <div className="mt-2 flex items-center gap-4 text-xs text-muted-foreground">
                        {stock.risk_reward != null && (
                            <span>R:R <strong className="text-foreground">{stock.risk_reward}:1</strong></span>
                        )}
                        {stock.calibrated_prob != null && (
                            <span>Win Prob <strong className="text-foreground">{Math.round(stock.calibrated_prob * 100)}%</strong></span>
                        )}
                        {stock.max_position_pct != null && (
                            <span>Max Size <strong className="text-foreground">{fmt(stock.max_position_pct)}%</strong></span>
                        )}
                        {stock.sector_rank != null && (
                            <span>Sector Rank <strong className="text-foreground">#{stock.sector_rank}</strong></span>
                        )}
                    </div>
                )}

                {/* Scores mini bars */}
                <div className="mt-3 space-y-1">
                    {[
                        ['Technical',    stock.scores?.technical],
                        ['Fundamental',  stock.scores?.fundamental],
                        ['Macro',        stock.scores?.macro],
                        ['Sentiment',    stock.scores?.sentiment],
                        ['Institutional', stock.scores?.institutional],
                    ].map(([label, val]) => (
                        <ScoreBar key={label} label={label} value={val} color={scoreColor(val)} />
                    ))}
                </div>

                {/* Recent news snippets */}
                {stock.recent_news?.length > 0 && (
                    <div className="mt-3 space-y-1">
                        {stock.recent_news.slice(0, 2).map((n, i) => (
                            <div key={i} className="flex items-start gap-1.5 text-xs">
                                <span className={`shrink-0 mt-0.5 ${sentimentColor(n.sentiment_score)}`}>●</span>
                                <span className="text-muted-foreground line-clamp-1">{n.headline}</span>
                            </div>
                        ))}
                    </div>
                )}

                {/* Expand / Action row */}
                <div className="mt-3 flex items-center gap-2">
                    <button
                        onClick={() => setExpanded(e => !e)}
                        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                    >
                        {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                        {expanded ? 'Hide' : 'Full Analysis'}
                    </button>
                    {onDeepDive && (
                        <button
                            onClick={() => onDeepDive(stock.ticker)}
                            className="ml-auto text-xs text-primary hover:text-primary/80 flex items-center gap-1 transition-colors"
                        >
                            Deep Dive <ArrowRight size={11} />
                        </button>
                    )}
                </div>
            </div>

            {/* ── Expanded Thesis ── */}
            {expanded && (
                <div className="border-t border-border/40 px-4 py-3 space-y-3 bg-background/30">
                    {allTheses.map(section => (
                        section.items?.length > 0 && (
                            <div key={section.label}>
                                <p className={`text-[10px] uppercase tracking-wider font-semibold mb-1 ${section.color}`}>
                                    {section.label}
                                </p>
                                <ThesisList items={section.items} color={section.color} />
                            </div>
                        )
                    ))}

                    {/* Historical analogs */}
                    {stock.analogs?.length > 0 && (
                        <div>
                            <p className="text-[10px] uppercase tracking-wider font-semibold mb-1 text-slate-400">Historical Analogs</p>
                            <div className="flex gap-2 flex-wrap">
                                {stock.analogs.slice(0, 3).map((a, i) => (
                                    <span key={i} className="text-xs px-2 py-0.5 rounded bg-muted text-muted-foreground">
                                        {a.date ? new Date(a.date).toLocaleDateString('en', {month:'short', year:'2-digit'}) : '—'}
                                        {a.forward_return != null && ` → ${fmtPct(a.forward_return * 100)}`}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Cross-asset sensitivity */}
                    {stock.cross_asset_sensitivity && Object.keys(stock.cross_asset_sensitivity).length > 0 && (
                        <div>
                            <p className="text-[10px] uppercase tracking-wider font-semibold mb-1 text-slate-400">Cross-Asset Sensitivity (β)</p>
                            <div className="flex gap-3 flex-wrap text-xs text-muted-foreground">
                                {Object.entries(stock.cross_asset_sensitivity).map(([k, v]) => (
                                    <span key={k}>{k}: <strong className={v > 0 ? 'text-green-400' : 'text-red-400'}>{fmt(v, 3)}</strong></span>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

// ─── Section Header ───────────────────────────────────────────────────────────

function SectionHeader({ icon: Icon, label, count, color, subtitle }) {
    return (
        <div className="flex items-center gap-3 mb-4">
            <div className={`p-2 rounded-lg ${color}`}>
                <Icon size={16} />
            </div>
            <div>
                <h3 className="font-semibold flex items-center gap-2">
                    {label}
                    {count != null && (
                        <span className="text-xs px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground font-normal">
                            {count} stocks
                        </span>
                    )}
                </h3>
                {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
            </div>
        </div>
    );
}

// ─── Summary Row ──────────────────────────────────────────────────────────────

function SummaryRow({ summary, totalAnalyzed }) {
    return (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
                { label: 'Analyzed',  value: totalAnalyzed,       color: 'text-foreground' },
                { label: 'Buy Signals',  value: summary?.buy_count,   color: 'text-green-400' },
                { label: 'Sell Signals', value: summary?.sell_count,  color: 'text-red-400' },
                { label: 'Regime',    value: summary?.regime || '—', color: 'text-blue-400', small: true },
            ].map(item => (
                <div key={item.label} className="rounded-lg border border-border bg-card px-4 py-3">
                    <p className="text-xs text-muted-foreground">{item.label}</p>
                    <p className={`text-xl font-bold mt-0.5 ${item.color} ${item.small ? 'text-sm' : ''}`}>
                        {item.value ?? '—'}
                    </p>
                </div>
            ))}
        </div>
    );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function DailyBriefing({ onNavigate }) {
    const [data, setData]           = useState(null);
    const [loading, setLoading]     = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [error, setError]         = useState(null);
    const [showSells, setShowSells] = useState(true);

    const load = useCallback(async (force = false) => {
        force ? setRefreshing(true) : setLoading(true);
        setError(null);
        try {
            const r = await briefingApi.getDaily(force);
            setData(r.data);
        } catch (err) {
            setError(err?.response?.data?.detail || 'Failed to load briefing.');
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    function handleDeepDive(ticker) {
        onNavigate?.('hub', ticker);
    }

    if (loading) {
        return (
            <div className="space-y-4 max-w-screen-xl">
                <div className="h-10 w-64 rounded animate-pulse bg-muted" />
                <div className="h-14 rounded animate-pulse bg-muted" />
                <div className="grid md:grid-cols-2 gap-4">
                    {[1,2,3,4].map(i => <div key={i} className="h-48 rounded-lg animate-pulse bg-muted" />)}
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-6 text-center max-w-lg mx-auto">
                <XCircle size={32} className="mx-auto text-red-400 mb-2" />
                <p className="text-red-400 font-medium">{error}</p>
                <button onClick={() => load()} className="mt-3 text-sm text-primary hover:underline">Retry</button>
            </div>
        );
    }

    if (!data?.has_data) {
        return (
            <div className="rounded-lg border border-border bg-card p-10 text-center max-w-lg mx-auto">
                <Newspaper size={40} className="mx-auto text-muted-foreground opacity-40 mb-3" />
                <p className="text-muted-foreground">{data?.message || 'No analysis data yet.'}</p>
                <p className="text-xs text-muted-foreground mt-2">Run the agent batch from Data Ingestion to generate signals.</p>
            </div>
        );
    }

    const buys  = data.top_buys  || [];
    const sells = data.top_sells || [];

    return (
        <div className="space-y-6 max-w-screen-xl">

            {/* ── Header ── */}
            <div className="flex items-center justify-between flex-wrap gap-3">
                <div>
                    <h2 className="text-xl font-bold flex items-center gap-2">
                        <Newspaper size={20} className="text-primary" />
                        Daily Intelligence Briefing
                    </h2>
                    <p className="text-sm text-muted-foreground mt-0.5 flex items-center gap-1.5">
                        <Clock size={12} />
                        {data.cached ? 'Cached' : 'Fresh'} · Generated {new Date(data.generated_at).toLocaleTimeString()} ·{' '}
                        {data.total_analyzed} stocks analyzed
                    </p>
                </div>
                <button
                    onClick={() => load(true)}
                    disabled={refreshing}
                    className="flex items-center gap-2 bg-primary text-primary-foreground text-sm px-4 py-2 rounded-lg hover:bg-primary/90 disabled:opacity-50 transition-colors"
                >
                    <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
                    {refreshing ? 'Refreshing…' : 'Refresh Report'}
                </button>
            </div>

            {/* ── Blackout warning ── */}
            {data.is_blackout && data.next_event && (
                <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 flex items-center gap-3">
                    <AlertTriangle size={16} className="text-red-400 shrink-0" />
                    <div>
                        <span className="text-sm font-semibold text-red-400">High-Impact Event in next 24h: </span>
                        <span className="text-sm text-red-300">{data.next_event.event}</span>
                        <span className="text-xs text-red-400/70 ml-2">— consider reducing new positions</span>
                    </div>
                </div>
            )}

            {/* ── Macro + CB Banner ── */}
            <MacroBanner macro={data.macro_context} cb={data.circuit_breaker} />

            {/* ── Summary Stats ── */}
            <SummaryRow summary={data.summary} totalAnalyzed={data.total_analyzed} />

            {/* ── Sector Positioning ── */}
            <SectorChips sectors={data.sector_advice} />

            {/* ── Upcoming Events Strip ── */}
            {data.upcoming_events?.length > 0 && (
                <div className="flex items-center gap-2 flex-wrap text-xs">
                    <span className="text-muted-foreground font-medium flex items-center gap-1">
                        <Calendar size={12} />
                        Events:
                    </span>
                    {data.upcoming_events.slice(0, 4).map((evt, i) => (
                        <span key={i} className={`px-2 py-0.5 rounded border font-medium ${
                            evt.days_until <= 3
                                ? 'bg-red-500/15 text-red-400 border-red-500/30'
                                : 'bg-muted text-muted-foreground border-border'
                        }`}>
                            {evt.days_until === 0 ? 'Today' : evt.days_until === 1 ? 'Tomorrow' : `${evt.days_until}d`} · {evt.event}
                        </span>
                    ))}
                </div>
            )}

            {/* ── BUY + SELL columns ── */}
            <div className="grid md:grid-cols-2 gap-6">

                {/* BUYs */}
                <div>
                    <SectionHeader
                        icon={TrendingUp}
                        label="Buy Opportunities"
                        count={buys.length}
                        color="bg-green-500/15 text-green-400"
                        subtitle="Strong Buy · Accumulate · Swing Setups — ranked by conviction score"
                    />
                    {buys.length === 0 ? (
                        <div className="rounded-lg border border-border bg-card p-6 text-center text-muted-foreground text-sm">
                            No buy signals in the current analysis window.
                        </div>
                    ) : (
                        <div className="space-y-4">
                            {buys.map(s => (
                                <StockCard key={s.ticker} stock={s} onDeepDive={handleDeepDive} />
                            ))}
                        </div>
                    )}
                </div>

                {/* SELLs */}
                <div>
                    <div className="flex items-center justify-between mb-4">
                        <div className="flex items-center gap-3">
                            <div className="p-2 rounded-lg bg-red-500/10 text-red-400">
                                <TrendingDown size={16} />
                            </div>
                            <div>
                                <h3 className="font-semibold flex items-center gap-2">
                                    Sell / Avoid
                                    <span className="text-xs px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground font-normal">
                                        {sells.length} stocks
                                    </span>
                                </h3>
                                <p className="text-xs text-muted-foreground">Distribution · Avoid — weakest conviction</p>
                            </div>
                        </div>
                        <button
                            onClick={() => setShowSells(v => !v)}
                            className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
                        >
                            {showSells ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                            {showSells ? 'Hide' : 'Show'}
                        </button>
                    </div>

                    {showSells && (
                        sells.length === 0 ? (
                            <div className="rounded-lg border border-border bg-card p-6 text-center text-muted-foreground text-sm">
                                No sell signals in the current window.
                            </div>
                        ) : (
                            <div className="space-y-4">
                                {sells.map(s => (
                                    <StockCard key={s.ticker} stock={s} onDeepDive={handleDeepDive} />
                                ))}
                            </div>
                        )
                    )}
                </div>
            </div>

            {/* ── Disclaimer ── */}
            <p className="text-[11px] text-muted-foreground/60 text-center pb-2">
                AI-generated analysis for research purposes only. Not financial advice.
                Verify all data before making trading decisions. Past performance does not guarantee future results.
            </p>
        </div>
    );
}
