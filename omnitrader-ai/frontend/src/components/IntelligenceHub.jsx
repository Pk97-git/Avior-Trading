import React, { useEffect, useState, useCallback } from 'react';
import { agentsApi, watchlistApi } from '../api';
import { Filter, Loader2, ChevronLeft, ChevronRight, RefreshCw, Search, Zap, X, Brain, Star, StarOff, TrendingUp, TrendingDown, Target } from 'lucide-react';
import { SignalBadge } from './shared/SignalCard';

const SIGNAL_TYPES = ['ALL', 'STRONG_BUY', 'ACCUMULATE', 'PROACTIVE_SWING', 'AVOID', 'DISTRIBUTION'];
const COUNTRY_TYPES = ['ALL', 'US', 'IN'];
const SIGNAL_LABELS = {
    STRONG_BUY: 'Strong Buy',
    ACCUMULATE: 'Accumulate',
    PROACTIVE_SWING: 'Swing Setup',
    AVOID: 'Avoid',
    DISTRIBUTION: 'Distribution',
};

function FilterToggle({ options, active, onChange, label }) {
    return (
        <div className="flex items-center gap-1.5">
            {label && <span className="text-xs text-muted-foreground">{label}:</span>}
            <div className="flex rounded-md border border-border overflow-hidden text-xs">
                {options.map(opt => (
                    <button
                        key={opt}
                        onClick={() => onChange(opt)}
                        className={`px-2.5 py-1.5 font-medium transition-colors ${active === opt
                            ? 'bg-primary text-primary-foreground'
                            : 'hover:bg-accent text-muted-foreground'
                            }`}
                    >
                        {opt === 'ALL' ? 'All' : (SIGNAL_LABELS[opt] || opt)}
                    </button>
                ))}
            </div>
        </div>
    );
}

function DiagnosticCard({ label, score, bullets }) {
    if (score == null && (!bullets || bullets.length === 0)) return null;
    return (
        <div className="border border-border rounded-xl bg-card shadow-sm overflow-hidden mb-4">
            <div className="flex items-center justify-between p-3 border-b border-border/50 bg-muted/20">
                <span className="font-semibold text-sm">{label}</span>
                {score != null && (
                    <span className={`px-2.5 py-1 rounded text-xs font-bold ${score >= 70 ? 'bg-emerald-500/15 text-emerald-500' :
                        score >= 50 ? 'bg-blue-500/15 text-blue-500' :
                            'bg-yellow-500/15 text-yellow-600'
                        }`}>
                        Score: {score}/100
                    </span>
                )}
            </div>
            {bullets && bullets.length > 0 && (
                <div className="p-4 bg-muted/5">
                    <ul className="space-y-2">
                        {bullets.map((b, i) => (
                            <li key={i} className="flex gap-2.5 text-sm text-foreground/80 leading-relaxed">
                                <span className="mt-1.5 shrink-0 text-primary/60 text-[8px]">■</span>
                                <div>{b}</div>
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    );
}

// ── Factor scores mini-bar ────────────────────────────────────────────────────
function FactorBar({ label, z }) {
    if (z == null) return null;
    const pct = Math.round(Math.max(0, Math.min(100, 50 + z * 22.5)));
    const color = pct >= 65 ? 'bg-emerald-500' : pct >= 40 ? 'bg-blue-500' : 'bg-red-500';
    return (
        <div className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground w-20 shrink-0 capitalize">{label}</span>
            <div className="flex-1 h-1.5 bg-muted/40 rounded-full overflow-hidden">
                <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
            </div>
            <span className="text-muted-foreground tabular-nums w-12 text-right">{z >= 0 ? '+' : ''}{z?.toFixed(2)}</span>
        </div>
    );
}

// ── Analog row ────────────────────────────────────────────────────────────────
function AnalogRow({ analog }) {
    const { date, similarity, forward_30d_pct, forward_60d_pct } = analog;
    const color = forward_30d_pct == null ? 'text-muted-foreground'
        : forward_30d_pct > 3 ? 'text-emerald-400'
        : forward_30d_pct < -3 ? 'text-red-400'
        : 'text-yellow-400';
    return (
        <div className="flex items-center justify-between text-xs py-1.5 border-b border-border/30 last:border-0">
            <span className="text-muted-foreground">{date}</span>
            <span className="text-muted-foreground">sim {(similarity * 100).toFixed(0)}%</span>
            <span className={`font-semibold tabular-nums ${color}`}>
                {forward_30d_pct != null ? `${forward_30d_pct > 0 ? '+' : ''}${forward_30d_pct}%` : '—'} / 30d
            </span>
            <span className="text-muted-foreground tabular-nums">
                {forward_60d_pct != null ? `${forward_60d_pct > 0 ? '+' : ''}${forward_60d_pct}%` : '—'} / 60d
            </span>
        </div>
    );
}

function SlideOverPanel({ ticker, alertItem, onClose, onRefresh }) {
    const [analysis, setAnalysis] = useState(null);
    const [loading, setLoading] = useState(true);
    const [runningFresh, setRunningFresh] = useState(false);
    const [error, setError] = useState(null);
    const [watchlisted, setWatchlisted] = useState(false);
    const [watchlistBusy, setWatchlistBusy] = useState(false);

    const fetchAnalysis = useCallback(async (t) => {
        setLoading(true);
        setError(null);
        try {
            const res = await agentsApi.getAnalysis(t);
            setAnalysis(res.data);
        } catch (e) {
            setError(e?.response?.data?.detail || `No detailed analysis found for ${t}. Trigger a fresh run via the button above to generate one.`);
            setAnalysis(null);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (ticker) fetchAnalysis(ticker);
    }, [ticker, fetchAnalysis]);

    const runFreshAnalysis = async () => {
        setRunningFresh(true);
        setError(null);
        try {
            const res = await agentsApi.triggerAnalysis(ticker);
            setAnalysis(res.data);
            if (onRefresh) onRefresh();
        } catch (e) {
            setError(e?.response?.data?.detail || `Failed to run fresh analysis for ${ticker}`);
        } finally {
            setRunningFresh(false);
        }
    };

    const toggleWatchlist = async () => {
        setWatchlistBusy(true);
        try {
            if (watchlisted) {
                await watchlistApi.removeTicker(ticker);
                setWatchlisted(false);
            } else {
                await watchlistApi.addTicker(ticker);
                setWatchlisted(true);
            }
        } catch (e) {
            console.error('Watchlist toggle failed:', e?.response?.data?.detail || e);
        } finally {
            setWatchlistBusy(false);
        }
    };

    const factorScores = analysis?.factor_scores || {};
    const hasFactors = Object.keys(factorScores).length > 0;
    const analogs = analysis?.analogs || [];
    const hasMemory = analogs.length > 0;
    const maxPositionPct = analysis?.max_position_pct;
    const calibratedProb = analysis?.calibrated_prob;
    const executionNote = analysis?.execution_note;
    const volatilityNote = analysis?.volatility_note;
    const entryPrice  = analysis?.entry_price;
    const stopLoss    = analysis?.stop_loss;
    const takeProfit  = analysis?.take_profit;
    const atr14       = analysis?.atr_14;
    const hasLevels   = entryPrice || stopLoss || takeProfit;

    return (
        <div className="fixed inset-y-0 right-0 w-full md:w-[620px] lg:w-[860px] bg-background border-l border-border shadow-2xl z-50 flex flex-col transform transition-transform duration-300">
            {/* Header */}
            <div className="flex flex-wrap items-center justify-between px-6 py-4 border-b border-border bg-card/50">
                <div className="flex items-center gap-3">
                    <h2 className="text-xl font-bold">{ticker}</h2>
                    {analysis?.signal ? (
                        <SignalBadge signal={analysis.signal} size="md" />
                    ) : alertItem?.signal ? (
                        <SignalBadge signal={alertItem.signal} size="md" />
                    ) : null}
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={toggleWatchlist}
                        disabled={watchlistBusy}
                        title={watchlisted ? 'Remove from watchlist' : 'Add to watchlist'}
                        className={`p-1.5 rounded-md border transition-colors disabled:opacity-50 ${
                            watchlisted
                                ? 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400 hover:bg-yellow-500/20'
                                : 'border-border text-muted-foreground hover:bg-accent'
                        }`}
                    >
                        {watchlistBusy
                            ? <Loader2 className="h-4 w-4 animate-spin" />
                            : watchlisted ? <Star className="h-4 w-4 fill-current" /> : <Star className="h-4 w-4" />
                        }
                    </button>
                    <button
                        onClick={runFreshAnalysis}
                        disabled={runningFresh || loading}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-border hover:bg-accent disabled:opacity-50 transition-colors text-muted-foreground"
                    >
                        {runningFresh ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                        {runningFresh ? 'Running...' : 'Run Fresh AI Analysis'}
                    </button>
                    <button onClick={onClose} className="p-1.5 text-muted-foreground hover:bg-accent rounded-md transition-colors">
                        <X className="h-5 w-5" />
                    </button>
                </div>
            </div>

            {/* Content Container */}
            <div className="flex-1 overflow-y-auto p-6 flex flex-col lg:flex-row gap-6">
                {/* Left Side: Analysis & Scores */}
                <div className="flex-1 min-w-0 space-y-4">
                    {loading ? (
                        <div className="flex flex-col items-center gap-3 text-sm text-muted-foreground h-32 justify-center">
                            <Loader2 className="animate-spin h-5 w-5 text-primary" />
                            <span>Fetching latest AI insights for {ticker}...</span>
                        </div>
                    ) : error ? (
                        <div className="bg-red-500/10 border border-red-500/20 text-red-400 p-4 rounded-lg text-sm flex flex-col gap-2">
                            <p className="font-semibold">Analysis Not Found</p>
                            <p>{error}</p>
                        </div>
                    ) : analysis ? (
                        <>
                            {/* Score Overview & Executive Thesis */}
                            <div className="p-5 bg-card border border-border rounded-xl shadow-sm">
                                <div className="flex justify-between items-start mb-4 border-b border-border/50 pb-4">
                                    <div>
                                        <p className="text-xs text-muted-foreground uppercase tracking-wider font-semibold mb-1">Final Conviction</p>
                                        <p className="text-4xl font-bold tabular-nums text-foreground">
                                            {analysis.final_score}
                                            <span className="text-xl text-muted-foreground/40 font-medium">/100</span>
                                        </p>
                                    </div>
                                    <div className="text-right">
                                        <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1">Macro Regime</p>
                                        <p className="font-semibold text-sm bg-accent px-3 py-1 rounded text-accent-foreground inline-block">
                                            {analysis.regime || '—'}
                                        </p>
                                    </div>
                                </div>

                                {(analysis.signal_thesis && analysis.signal_thesis.length > 0) && (
                                    <div>
                                        <h3 className="font-bold text-sm mb-3 flex items-center gap-2">
                                            <Zap className="h-4 w-4 text-emerald-500" />
                                            Executive Summary
                                        </h3>
                                        <div className="space-y-2 text-sm text-foreground/90 leading-relaxed">
                                            {analysis.signal_thesis.map((t, i) => (
                                                <p key={i}>{t}</p>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>

                            {/* ── Position Sizing Block ── */}
                            {(maxPositionPct != null || calibratedProb != null) && (
                                <div className="p-4 bg-card border border-border rounded-xl shadow-sm">
                                    <h3 className="font-bold text-sm mb-3 flex items-center gap-2 text-yellow-400">
                                        <span className="text-base">⚖️</span> Position Sizing
                                    </h3>
                                    <div className="grid grid-cols-2 gap-3 mb-3">
                                        {maxPositionPct != null && (
                                            <div className="bg-muted/30 rounded-lg p-3 text-center">
                                                <p className="text-xs text-muted-foreground mb-1">Max Position Size</p>
                                                <p className="text-2xl font-bold tabular-nums text-yellow-400">{maxPositionPct}%</p>
                                                <p className="text-[10px] text-muted-foreground">of portfolio (Half-Kelly)</p>
                                            </div>
                                        )}
                                        {calibratedProb != null && (
                                            <div className="bg-muted/30 rounded-lg p-3 text-center">
                                                <p className="text-xs text-muted-foreground mb-1">Win Probability</p>
                                                <p className="text-2xl font-bold tabular-nums text-blue-400">
                                                    {Math.round(calibratedProb * 100)}%
                                                </p>
                                                <p className="text-[10px] text-muted-foreground">calibrated (Platt scaling)</p>
                                            </div>
                                        )}
                                    </div>
                                    {volatilityNote && (
                                        <p className="text-xs text-muted-foreground bg-muted/20 p-2 rounded mb-2">{volatilityNote}</p>
                                    )}
                                    {executionNote && (
                                        <p className="text-xs text-muted-foreground bg-muted/20 p-2 rounded">{executionNote}</p>
                                    )}
                                </div>
                            )}

                            {/* ── Trade Levels ── */}
                            {hasLevels && (
                                <div className="p-4 bg-card border border-border rounded-xl shadow-sm">
                                    <h3 className="font-bold text-sm mb-3 flex items-center gap-2 text-blue-400">
                                        <Target className="h-4 w-4" /> Trade Levels (ATR-Based)
                                    </h3>
                                    <div className="grid grid-cols-3 gap-3 mb-2">
                                        {entryPrice != null && (
                                            <div className="bg-muted/30 rounded-lg p-3 text-center">
                                                <p className="text-xs text-muted-foreground mb-1">Entry Price</p>
                                                <p className="text-lg font-bold tabular-nums text-foreground">
                                                    ${entryPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                                </p>
                                                <p className="text-[10px] text-muted-foreground">latest close</p>
                                            </div>
                                        )}
                                        {stopLoss != null && (
                                            <div className="bg-red-500/5 border border-red-500/20 rounded-lg p-3 text-center">
                                                <p className="text-xs text-muted-foreground mb-1 flex items-center justify-center gap-1">
                                                    <TrendingDown className="h-3 w-3 text-red-400" /> Stop Loss
                                                </p>
                                                <p className="text-lg font-bold tabular-nums text-red-400">
                                                    ${stopLoss.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                                </p>
                                                <p className="text-[10px] text-muted-foreground">2× ATR below entry</p>
                                            </div>
                                        )}
                                        {takeProfit != null && (
                                            <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-lg p-3 text-center">
                                                <p className="text-xs text-muted-foreground mb-1 flex items-center justify-center gap-1">
                                                    <TrendingUp className="h-3 w-3 text-emerald-400" /> Take Profit
                                                </p>
                                                <p className="text-lg font-bold tabular-nums text-emerald-400">
                                                    ${takeProfit.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                                </p>
                                                <p className="text-[10px] text-muted-foreground">6× ATR (3:1 R/R)</p>
                                            </div>
                                        )}
                                    </div>
                                    {atr14 != null && entryPrice != null && (
                                        <p className="text-xs text-muted-foreground bg-muted/20 p-2 rounded">
                                            14d ATR: ${atr14.toFixed(2)} ({((atr14 / entryPrice) * 100).toFixed(1)}% of price)
                                            {stopLoss != null && takeProfit != null && (
                                                <> · Risk ${(entryPrice - stopLoss).toFixed(2)} → Reward ${(takeProfit - entryPrice).toFixed(2)}</>
                                            )}
                                        </p>
                                    )}
                                </div>
                            )}

                            {/* ── All 7 Agent Diagnostic Cards ── */}
                            <div>
                                <h3 className="font-bold text-sm mb-3 flex items-center gap-2 text-muted-foreground">
                                    <Brain className="h-4 w-4" />
                                    Agent Diagnostics (7 of 7)
                                </h3>

                                <DiagnosticCard label="Fundamental Agent" score={analysis.fundamental_score} bullets={analysis.fundamental_thesis} />
                                <DiagnosticCard label="Technical Agent" score={analysis.technical_score} bullets={analysis.technical_thesis} />
                                <DiagnosticCard label="Macro Agent" score={analysis.macro_score} bullets={analysis.macro_thesis} />
                                <DiagnosticCard label="Institutional Agent" score={analysis.institutional_score} bullets={analysis.institutional_thesis} />
                                <DiagnosticCard label="Sentiment Agent" score={analysis.sentiment_score} bullets={analysis.sentiment_thesis} />

                                {/* Vision Agent */}
                                {(analysis.vision_score != null || (analysis.vision_thesis && analysis.vision_thesis.length > 0)) && (
                                    <DiagnosticCard
                                        label="Vision Agent (Chart Pattern)"
                                        score={analysis.vision_score}
                                        bullets={analysis.vision_thesis}
                                    />
                                )}

                                {/* Memory Agent */}
                                {analysis.memory_confidence != null && (
                                    <div className="border border-border rounded-xl bg-card shadow-sm overflow-hidden mb-4">
                                        <div className="flex items-center justify-between p-3 border-b border-border/50 bg-muted/20">
                                            <span className="font-semibold text-sm">Historical Memory Agent</span>
                                            <span className="px-2.5 py-1 rounded text-xs font-bold bg-purple-500/15 text-purple-400">
                                                Confidence: {Math.round(analysis.memory_confidence * 100)}%
                                            </span>
                                        </div>
                                        <div className="p-4 bg-muted/5 space-y-3">
                                            {analysis.memory_thesis && analysis.memory_thesis.map((b, i) => (
                                                <p key={i} className="text-sm text-foreground/80 leading-relaxed flex gap-2">
                                                    <span className="mt-1.5 shrink-0 text-primary/60 text-[8px]">■</span>
                                                    {b}
                                                </p>
                                            ))}
                                            {hasMemory && (
                                                <div className="mt-3 border-t border-border/40 pt-3">
                                                    <p className="text-xs text-muted-foreground font-semibold mb-2 uppercase tracking-wide">
                                                        Top {analogs.length} Historical Analogs
                                                    </p>
                                                    {analogs.map((a, i) => <AnalogRow key={i} analog={a} />)}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                )}

                                {/* Factor Decomposition */}
                                {hasFactors && (
                                    <div className="border border-border rounded-xl bg-card shadow-sm overflow-hidden mb-4">
                                        <div className="p-3 border-b border-border/50 bg-muted/20">
                                            <span className="font-semibold text-sm">Factor Decomposition</span>
                                            <span className="text-xs text-muted-foreground ml-2">(z-score vs universe)</span>
                                        </div>
                                        <div className="p-4 bg-muted/5 space-y-2.5">
                                            {Object.entries(factorScores).map(([k, v]) => (
                                                <FactorBar key={k} label={k} z={v} />
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </>
                    ) : null}
                </div>

                {/* Right Side: Swing Chart + Thesis */}
                {(alertItem?.image_url || alertItem?.thesis?.length > 0) && (
                    <div className="w-full lg:w-[300px] xl:w-[360px] shrink-0 space-y-4">
                        <h3 className="font-bold text-sm flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full bg-purple-500"></span>
                            Swing Trade Setup
                        </h3>
                        {alertItem.image_url && (
                            <div className="rounded-xl overflow-hidden border border-border shadow-sm bg-muted/10 p-1">
                                <img
                                    src={alertItem.image_url}
                                    alt={`${ticker} setup chart`}
                                    className="w-full h-auto rounded-lg"
                                />
                            </div>
                        )}
                        {alertItem.thesis && alertItem.thesis.length > 0 && (
                            <div className="text-xs text-muted-foreground bg-muted/30 p-4 rounded-xl border border-border/50 shadow-inner">
                                {alertItem.thesis.map((t, i) => (
                                    <div key={i} className="mb-3 last:mb-0 space-y-2">
                                        {t.split('\n').map((para, idx) => (
                                            para.trim() ? <p key={idx}>{para}</p> : null
                                        ))}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}

export default function IntelligenceHub({ initialTicker }) {
    const [items, setItems] = useState([]);
    const [total, setTotal] = useState(0);
    const [pages, setPages] = useState(1);
    const [page, setPage] = useState(1);
    const [signal, setSignal] = useState('ALL');
    const [country, setCountry] = useState('ALL');
    const [loading, setLoading] = useState(true);

    // Slide over state
    const [selectedTicker, setSelectedTicker] = useState(initialTicker || null);
    const [selectedAlert, setSelectedAlert] = useState(null);
    const [searchInput, setSearchInput] = useState('');

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const params = { page, limit: 50 };
            if (signal !== 'ALL') params.signal = signal;
            if (country !== 'ALL') params.country = country;
            const res = await agentsApi.getSignals(params);
            setItems(res.data.items || []);
            setTotal(res.data.total || 0);
            setPages(res.data.pages || 1);
        } catch {
            setItems([]);
            setTotal(0);
        } finally {
            setLoading(false);
        }
    }, [page, signal, country]);

    // Reset to page 1 whenever filters change
    useEffect(() => { setPage(1); }, [signal, country]);
    useEffect(() => { load(); }, [load]);

    // Direct initial search mapping
    useEffect(() => {
        if (initialTicker) {
            setSelectedTicker(initialTicker);
            setSelectedAlert(null);
        }
    }, [initialTicker]);

    const handleRowClick = (item) => {
        setSelectedAlert(item);
        setSelectedTicker(item.ticker);
    };

    const handleSearchSubmit = (e) => {
        e.preventDefault();
        const t = searchInput.trim().toUpperCase();
        if (t) {
            setSelectedAlert(null);
            setSelectedTicker(t);
            setSearchInput('');
        }
    };

    return (
        <div className="space-y-5 relative">
            {/* Slide Over Overlay background */}
            {selectedTicker && (
                <div
                    className="fixed inset-0 bg-background/80 backdrop-blur-sm z-40 transition-opacity"
                    onClick={() => setSelectedTicker(null)}
                />
            )}

            {/* Slide Over Panel */}
            {selectedTicker && (
                <SlideOverPanel
                    ticker={selectedTicker}
                    alertItem={selectedAlert}
                    onClose={() => setSelectedTicker(null)}
                    onRefresh={load}
                />
            )}

            {/* ── Header + Top Bar ── */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-card/40 p-5 rounded-2xl border border-border shadow-sm">
                <div>
                    <h2 className="text-2xl font-bold flex items-center gap-2">
                        <Zap className="h-5 w-5 text-primary" /> Intelligence Hub
                    </h2>
                    <p className="text-sm text-muted-foreground mt-1">
                        Explore {total.toLocaleString()} market signals and deep-dive into AI agent logs.
                    </p>
                </div>

                <div className="flex items-center gap-3 w-full md:w-auto">
                    <form onSubmit={handleSearchSubmit} className="relative flex-1 min-w-[200px] md:w-72">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                        <input
                            type="text"
                            placeholder="Enter ticker (e.g. AAPL) to deep dive..."
                            value={searchInput}
                            onChange={e => setSearchInput(e.target.value)}
                            className="w-full pl-9 pr-3 py-2 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/40 shadow-inner"
                        />
                    </form>
                    <button
                        onClick={load}
                        className="flex items-center gap-1.5 text-xs font-medium text-foreground bg-accent hover:bg-accent/80 px-4 py-2 rounded-xl border border-border transition-colors shrink-0"
                    >
                        <RefreshCw className="h-4 w-4" /> Refresh
                    </button>
                </div>
            </div>

            {/* ── Filters ── */}
            <div className="flex flex-wrap items-center gap-3 px-1">
                <Filter className="h-4 w-4 text-muted-foreground shrink-0" />
                <FilterToggle
                    options={SIGNAL_TYPES}
                    active={signal}
                    onChange={setSignal}
                />
                <div className="w-px h-6 bg-border mx-1"></div>
                <FilterToggle
                    options={COUNTRY_TYPES}
                    active={country}
                    onChange={setCountry}
                    label="Region"
                />
            </div>

            {/* ── Table ── */}
            <div className="rounded-2xl border border-border overflow-hidden bg-card/60 shadow-sm">
                {loading ? (
                    <div className="flex flex-col items-center justify-center h-[400px] gap-3 text-muted-foreground">
                        <Loader2 className="animate-spin h-8 w-8 text-primary/70" />
                        <span className="text-sm font-medium">Scanning intelligence feed...</span>
                    </div>
                ) : items.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-[400px] text-muted-foreground space-y-2">
                        <Search className="h-8 w-8 opacity-20" />
                        <span className="text-sm font-medium">No signals match the current filters.</span>
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead className="bg-muted/40 border-b border-border text-muted-foreground text-[10px] uppercase tracking-wider">
                                <tr>
                                    <th className="text-left px-5 py-3 font-semibold">Asset</th>
                                    <th className="text-left px-5 py-3 font-semibold">Signal</th>
                                    <th className="text-right px-5 py-3 font-semibold">Price</th>
                                    <th className="text-right px-5 py-3 font-semibold">Conviction</th>
                                    <th className="text-left px-5 py-3 font-semibold hidden md:table-cell">Headline Analysis</th>
                                    <th className="text-right px-5 py-3 font-semibold hidden lg:table-cell">Generated</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border/40">
                                {items.map(item => (
                                    <tr
                                        key={item.id}
                                        onClick={() => handleRowClick(item)}
                                        className="hover:bg-muted/30 cursor-pointer transition-colors group"
                                    >
                                        <td className="px-5 py-4">
                                            <div className="font-bold text-sm flex items-center gap-2">
                                                {item.ticker}
                                                {item.country && (
                                                    <span className={`text-[9px] px-1.5 py-0.5 rounded-sm font-bold uppercase ${item.country === 'IN'
                                                        ? 'bg-orange-500/10 text-orange-500 border border-orange-500/20'
                                                        : 'bg-blue-500/10 text-blue-500 border border-blue-500/20'
                                                        }`}>
                                                        {item.country}
                                                    </span>
                                                )}
                                            </div>
                                            {item.name && (
                                                <div className="text-[11px] text-muted-foreground truncate max-w-[180px] mt-0.5">
                                                    {item.name}
                                                </div>
                                            )}
                                        </td>
                                        <td className="px-5 py-4">
                                            <div className="flex flex-col items-start gap-1.5">
                                                <SignalBadge signal={item.signal} size="sm" />
                                                {item.previous_signal && item.previous_signal !== item.signal && (
                                                    <span className="text-[10px] text-muted-foreground/60 font-medium">
                                                        was {item.previous_signal}
                                                    </span>
                                                )}
                                            </div>
                                        </td>
                                        <td className="px-5 py-4 text-right tabular-nums text-xs font-semibold">
                                            {item.current_price != null
                                                ? `$${item.current_price.toLocaleString()}`
                                                : <span className="text-muted-foreground/40">—</span>
                                            }
                                        </td>
                                        <td className="px-5 py-4 text-right tabular-nums">
                                            {item.final_score != null ? (
                                                <span className={`inline-flex items-center justify-center min-w-[2rem] px-2 h-8 rounded-full text-xs font-bold ${item.final_score >= 70 ? 'bg-emerald-500/15 text-emerald-500' :
                                                    item.final_score >= 50 ? 'bg-blue-500/15 text-blue-500' :
                                                        'bg-yellow-500/15 text-yellow-600'
                                                    }`}>
                                                    {item.final_score}
                                                </span>
                                            ) : '—'}
                                        </td>
                                        <td className="px-5 py-4 text-xs text-muted-foreground hidden md:table-cell max-w-[350px]">
                                            <div className="truncate group-hover:text-foreground/90 transition-colors">
                                                {item.headline || '—'}
                                            </div>
                                        </td>
                                        <td className="px-5 py-4 text-right text-[11px] text-muted-foreground whitespace-nowrap hidden lg:table-cell">
                                            {item.generated_at
                                                ? new Date(item.generated_at).toLocaleString('en-US', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
                                                : '—'
                                            }
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {/* ── Pagination ── */}
            {!loading && pages > 1 && (
                <div className="flex items-center justify-between px-2 pt-2 border-t border-border/50">
                    <p className="text-xs text-muted-foreground font-medium">
                        Page {page} of {pages}
                    </p>
                    <div className="flex gap-2">
                        <button
                            onClick={() => setPage(p => Math.max(1, p - 1))}
                            disabled={page === 1}
                            className="px-4 py-2 rounded-lg border border-border bg-card text-xs font-semibold disabled:opacity-40 hover:bg-accent hover:text-foreground transition-colors flex items-center gap-1.5"
                        >
                            <ChevronLeft className="h-3.5 w-3.5 -ml-1" /> Prev
                        </button>
                        <button
                            onClick={() => setPage(p => Math.min(pages, p + 1))}
                            disabled={page === pages}
                            className="px-4 py-2 rounded-lg border border-border bg-card text-xs font-semibold disabled:opacity-40 hover:bg-accent hover:text-foreground transition-colors flex items-center gap-1.5"
                        >
                            Next <ChevronRight className="h-3.5 w-3.5 -mr-1" />
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}
