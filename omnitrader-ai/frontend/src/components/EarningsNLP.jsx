import React, { useState, useEffect } from 'react';
import { earningsNlpApi } from '../api';
import {
    TrendingUp, TrendingDown, Minus, AlertTriangle, ChevronDown,
    ChevronUp, Search, RefreshCw, Loader2, MessageSquare,
} from 'lucide-react';

// ── Tone config ────────────────────────────────────────────────────────────────

const TONE_CONFIG = {
    BULLISH_TONE:   { label: 'Bullish',   bg: 'bg-emerald-500/20', text: 'text-emerald-400', border: 'border-emerald-500/40', dot: 'bg-emerald-400' },
    CAUTIOUS_TONE:  { label: 'Cautious',  bg: 'bg-amber-500/20',   text: 'text-amber-400',   border: 'border-amber-500/40',   dot: 'bg-amber-400' },
    BEARISH_TONE:   { label: 'Bearish',   bg: 'bg-red-500/20',     text: 'text-red-400',     border: 'border-red-500/40',     dot: 'bg-red-400' },
    NEUTRAL_TONE:   { label: 'Neutral',   bg: 'bg-slate-500/20',   text: 'text-slate-400',   border: 'border-slate-500/40',   dot: 'bg-slate-400' },
};

const GUIDANCE_ICON = {
    UP:      <TrendingUp  className="h-4 w-4 text-emerald-400" />,
    FLAT:    <Minus       className="h-4 w-4 text-slate-400"   />,
    DOWN:    <TrendingDown className="h-4 w-4 text-red-400"    />,
    UNKNOWN: <Minus       className="h-4 w-4 text-slate-500"   />,
};

const SURPRISE_STYLE = {
    BEAT:    { label: 'Beat',    cls: 'text-emerald-400 bg-emerald-500/10 border border-emerald-500/30' },
    MISS:    { label: 'Miss',    cls: 'text-red-400 bg-red-500/10 border border-red-500/30' },
    IN_LINE: { label: 'In Line', cls: 'text-slate-400 bg-slate-500/10 border border-slate-500/30' },
    UNKNOWN: { label: 'Unknown', cls: 'text-slate-500 bg-slate-800 border border-slate-700' },
};

const ANALYST_STYLE = {
    UPGRADED:    'text-emerald-400 bg-emerald-500/10 border border-emerald-500/30',
    DOWNGRADED:  'text-red-400 bg-red-500/10 border border-red-500/30',
    NEUTRAL:     'text-slate-400 bg-slate-500/10 border border-slate-500/30',
    UNKNOWN:     'text-slate-500 bg-slate-800 border border-slate-700',
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function ToneBadge({ tone, large = false }) {
    const cfg = TONE_CONFIG[tone] || TONE_CONFIG.NEUTRAL_TONE;
    return (
        <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full border font-semibold
            ${cfg.bg} ${cfg.text} ${cfg.border} ${large ? 'text-base' : 'text-xs'}`}>
            <span className={`h-2 w-2 rounded-full ${cfg.dot}`} />
            {cfg.label}
        </span>
    );
}

function MoverCard({ mover, onSelect, selected }) {
    const cfg = TONE_CONFIG[mover.tone_estimate] || TONE_CONFIG.NEUTRAL_TONE;
    return (
        <button
            onClick={() => onSelect(mover.ticker)}
            className={`w-full text-left p-3 rounded-lg border transition-all
                ${selected
                    ? 'border-primary bg-primary/10'
                    : 'border-border hover:border-border/80 bg-card hover:bg-accent/30'
                }`}
        >
            <div className="flex items-center justify-between gap-2 mb-1">
                <span className="font-bold text-sm">{mover.ticker}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${cfg.bg} ${cfg.text} ${cfg.border}`}>
                    {cfg.label}
                </span>
            </div>
            <p className="text-xs text-muted-foreground truncate">{mover.name}</p>
            <div className="flex items-center gap-2 mt-1.5 text-xs text-muted-foreground">
                <span className="bg-muted px-1.5 py-0.5 rounded">{mover.news_count} news</span>
                {mover.sector && <span className="truncate">{mover.sector}</span>}
            </div>
        </button>
    );
}

function AnalysisResult({ data }) {
    const cfg  = TONE_CONFIG[data.tone] || TONE_CONFIG.NEUTRAL_TONE;
    const surp = SURPRISE_STYLE[data.surprise_sentiment] || SURPRISE_STYLE.UNKNOWN;

    return (
        <div className="space-y-4">
            {/* Proxy notice */}
            {!data.llm_used && (
                <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400 text-sm">
                    <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                    <span>Using sentiment proxy — Groq API key not configured for deep NLP analysis.</span>
                </div>
            )}

            {/* Tone header */}
            <div className={`p-4 rounded-xl border ${cfg.bg} ${cfg.border}`}>
                <div className="flex flex-wrap items-center gap-3 mb-3">
                    <ToneBadge tone={data.tone} large />
                    <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                        Confidence: <span className="font-semibold text-foreground">{Math.round((data.confidence || 0) * 100)}%</span>
                    </div>
                    <div className="text-xs text-muted-foreground ml-auto">{data.news_count} articles analysed</div>
                </div>

                <div className="flex flex-wrap gap-3">
                    {/* Guidance */}
                    <div className="flex items-center gap-1.5 text-sm">
                        <span className="text-muted-foreground">Guidance:</span>
                        {GUIDANCE_ICON[data.guidance_direction]}
                        <span className="font-medium">{data.guidance_direction?.replace('_', ' ')}</span>
                    </div>

                    {/* EPS Surprise */}
                    <div className="flex items-center gap-1.5 text-sm">
                        <span className="text-muted-foreground">EPS:</span>
                        <span className={`px-2 py-0.5 rounded text-xs font-semibold ${surp.cls}`}>
                            {surp.label}
                        </span>
                    </div>

                    {/* Analyst reaction */}
                    <div className="flex items-center gap-1.5 text-sm">
                        <span className="text-muted-foreground">Analysts:</span>
                        <span className={`px-2 py-0.5 rounded text-xs font-semibold ${ANALYST_STYLE[data.analyst_reaction] || ANALYST_STYLE.UNKNOWN}`}>
                            {data.analyst_reaction?.replace('_', ' ')}
                        </span>
                    </div>
                </div>
            </div>

            {/* Summary */}
            {data.summary && (
                <div className="p-4 rounded-lg bg-card border border-border">
                    <p className="text-sm text-foreground leading-relaxed">{data.summary}</p>
                </div>
            )}

            {/* Key phrases */}
            {data.key_phrases?.length > 0 && (
                <div className="p-4 rounded-lg bg-card border border-border">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">Key Phrases</h4>
                    <ul className="space-y-1.5">
                        {data.key_phrases.map((phrase, i) => (
                            <li key={i} className="text-sm italic text-foreground/80 pl-3 border-l-2 border-primary/40">
                                "{phrase}"
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {/* Risk flags */}
            {data.risk_flags?.length > 0 && (
                <div className="p-4 rounded-lg bg-amber-500/5 border border-amber-500/30">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-amber-400 mb-2 flex items-center gap-1.5">
                        <AlertTriangle className="h-3.5 w-3.5" /> Risk Flags
                    </h4>
                    <ul className="space-y-1">
                        {data.risk_flags.map((flag, i) => (
                            <li key={i} className="text-sm text-amber-300/80 flex items-start gap-1.5">
                                <span className="text-amber-500 mt-0.5">•</span>{flag}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    );
}

// ── Explainer ─────────────────────────────────────────────────────────────────

function Explainer() {
    const [open, setOpen] = useState(false);
    return (
        <div className="rounded-lg border border-border bg-card/50 overflow-hidden">
            <button
                onClick={() => setOpen(o => !o)}
                className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
                <span className="flex items-center gap-2">
                    <MessageSquare className="h-4 w-4" />
                    What is Earnings Tone Analysis?
                </span>
                {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
            {open && (
                <div className="px-4 pb-4 text-sm text-muted-foreground leading-relaxed border-t border-border pt-3">
                    Hedge funds pay thousands per month for earnings call transcripts. We analyse the news coverage and
                    management language to estimate tone — is management sounding confident or nervous? Did analysts upgrade
                    or downgrade after the call? A bullish tone with raised guidance and analyst upgrades is a strong forward
                    indicator. Cautious or nervous language often precedes guidance cuts and sell-offs.
                </div>
            )}
        </div>
    );
}

// ── Main Component ─────────────────────────────────────────────────────────────

export default function EarningsNLP() {
    const [movers,         setMovers]         = useState([]);
    const [moversLoading,  setMoversLoading]  = useState(true);
    const [moversError,    setMoversError]    = useState(null);
    const [country,        setCountry]        = useState('ALL');

    const [searchTicker,   setSearchTicker]   = useState('');
    const [activeTicker,   setActiveTicker]   = useState(null);
    const [analysis,       setAnalysis]       = useState(null);
    const [analysisLoading, setAnalysisLoading] = useState(false);
    const [analysisError,  setAnalysisError]  = useState(null);

    // Load movers on mount / country change
    useEffect(() => {
        setMoversLoading(true);
        setMoversError(null);
        earningsNlpApi.getMovers({ country })
            .then(r => setMovers(r.data.movers || []))
            .catch(e => setMoversError(e.response?.data?.detail || e.message))
            .finally(() => setMoversLoading(false));
    }, [country]);

    const loadAnalysis = (ticker) => {
        if (!ticker) return;
        setActiveTicker(ticker.toUpperCase());
        setAnalysis(null);
        setAnalysisError(null);
        setAnalysisLoading(true);
        earningsNlpApi.getTicker(ticker)
            .then(r => setAnalysis(r.data))
            .catch(e => setAnalysisError(e.response?.data?.detail || e.message))
            .finally(() => setAnalysisLoading(false));
    };

    const handleSearch = (e) => {
        e.preventDefault();
        if (searchTicker.trim()) loadAnalysis(searchTicker.trim());
    };

    return (
        <div className="space-y-4">
            <Explainer />

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                {/* ── Left panel: Movers ── */}
                <div className="lg:col-span-1 space-y-3">
                    <div className="flex items-center justify-between">
                        <h3 className="text-sm font-semibold">Earnings Movers</h3>
                        <select
                            value={country}
                            onChange={e => setCountry(e.target.value)}
                            className="text-xs bg-muted border border-border rounded px-2 py-1"
                        >
                            <option value="ALL">All</option>
                            <option value="IN">India</option>
                            <option value="US">US</option>
                        </select>
                    </div>

                    {moversLoading && (
                        <div className="flex items-center justify-center py-8 text-muted-foreground text-sm gap-2">
                            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
                        </div>
                    )}
                    {moversError && (
                        <div className="text-red-400 text-sm p-3 bg-red-500/10 rounded-lg border border-red-500/30">
                            {moversError}
                        </div>
                    )}
                    {!moversLoading && !moversError && movers.length === 0 && (
                        <p className="text-muted-foreground text-sm text-center py-8">
                            No earnings movers found in the last 30 days.
                        </p>
                    )}
                    <div className="space-y-2">
                        {movers.map(m => (
                            <MoverCard
                                key={m.ticker}
                                mover={m}
                                onSelect={loadAnalysis}
                                selected={activeTicker === m.ticker}
                            />
                        ))}
                    </div>
                </div>

                {/* ── Right panel: Analysis ── */}
                <div className="lg:col-span-2 space-y-3">
                    {/* Search box */}
                    <form onSubmit={handleSearch} className="flex gap-2">
                        <div className="relative flex-1">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                            <input
                                type="text"
                                value={searchTicker}
                                onChange={e => setSearchTicker(e.target.value.toUpperCase())}
                                placeholder="Enter ticker (e.g. AAPL, RELIANCE.NS)"
                                className="w-full pl-9 pr-3 py-2 bg-muted border border-border rounded-lg text-sm focus:outline-none focus:border-primary"
                            />
                        </div>
                        <button
                            type="submit"
                            disabled={!searchTicker.trim() || analysisLoading}
                            className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium
                                       hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                        >
                            {analysisLoading
                                ? <><Loader2 className="h-4 w-4 animate-spin" /> Analysing…</>
                                : <><RefreshCw className="h-4 w-4" /> Analyse</>
                            }
                        </button>
                    </form>

                    {/* Loading state */}
                    {analysisLoading && (
                        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-3">
                            <Loader2 className="h-8 w-8 animate-spin text-primary" />
                            <p className="text-sm">Asking AI to read the room…</p>
                            <p className="text-xs text-muted-foreground/60">Analysing earnings news and management tone</p>
                        </div>
                    )}

                    {/* Error */}
                    {analysisError && !analysisLoading && (
                        <div className="text-red-400 text-sm p-4 bg-red-500/10 rounded-lg border border-red-500/30">
                            {analysisError}
                        </div>
                    )}

                    {/* Result */}
                    {analysis && !analysisLoading && (
                        <div>
                            <div className="flex items-center gap-2 mb-3">
                                <h3 className="font-bold text-base">{analysis.ticker}</h3>
                                <span className="text-xs text-muted-foreground">Earnings Tone Analysis</span>
                            </div>
                            <AnalysisResult data={analysis} />
                        </div>
                    )}

                    {/* Empty state */}
                    {!analysis && !analysisLoading && !analysisError && (
                        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-2">
                            <MessageSquare className="h-10 w-10 text-muted-foreground/30" />
                            <p className="text-sm">Select a stock from the movers list or search for a ticker</p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
