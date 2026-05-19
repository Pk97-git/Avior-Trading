import React from 'react';

const SIGNAL_CONFIG = {
    STRONG_BUY: { label: 'Strong Buy', bg: 'bg-emerald-500/15', text: 'text-emerald-400', border: 'border-emerald-500/30', bar: 'bg-emerald-500' },
    ACCUMULATE: { label: 'Accumulate', bg: 'bg-blue-500/15', text: 'text-blue-400', border: 'border-blue-500/30', bar: 'bg-blue-500' },
    PROACTIVE_SWING: { label: 'Swing Setup', bg: 'bg-purple-500/15', text: 'text-purple-400', border: 'border-purple-500/30', bar: 'bg-purple-500' },
    AVOID: { label: 'Avoid', bg: 'bg-yellow-500/15', text: 'text-yellow-400', border: 'border-yellow-500/30', bar: 'bg-yellow-500' },
    DISTRIBUTION: { label: 'Distribution', bg: 'bg-red-500/15', text: 'text-red-400', border: 'border-red-500/30', bar: 'bg-red-500' },
};

const DEFAULT_CFG = { label: '—', bg: 'bg-muted/30', text: 'text-muted-foreground', border: 'border-border', bar: 'bg-muted' };

export function SignalBadge({ signal, size = 'sm' }) {
    const cfg = SIGNAL_CONFIG[signal] || DEFAULT_CFG;
    const px = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm';
    return (
        <span className={`inline-flex items-center rounded-full font-semibold ${px} ${cfg.bg} ${cfg.text} border ${cfg.border}`}>
            {cfg.label}
        </span>
    );
}

export function ScoreBar({ score, signal }) {
    const cfg = SIGNAL_CONFIG[signal] || DEFAULT_CFG;
    const pct = Math.max(0, Math.min(100, score || 0));
    return (
        <div className="flex items-center gap-2">
            <div className="flex-1 h-1.5 bg-muted/50 rounded-full overflow-hidden">
                <div className={`h-full rounded-full transition-all ${cfg.bar}`} style={{ width: `${pct}%` }} />
            </div>
            <span className="text-xs text-muted-foreground tabular-nums w-8 text-right">{pct}</span>
        </div>
    );
}

export function AgentScoreRow({ label, score }) {
    if (score == null) return null;
    const pct = Math.max(0, Math.min(100, score));
    const color = pct >= 65 ? 'bg-emerald-500' : pct >= 45 ? 'bg-blue-500' : 'bg-red-500';
    return (
        <div className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground w-24 shrink-0">{label}</span>
            <div className="flex-1 h-1 bg-muted/40 rounded-full overflow-hidden">
                <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
            </div>
            <span className="text-muted-foreground tabular-nums w-6 text-right">{pct}</span>
        </div>
    );
}

/**
 * SignalCard — compact card showing one ticker's full signal.
 *
 * Props:
 *   ticker, name, sector, country
 *   signal, final_score
 *   fundamental_score, technical_score, macro_score, institutional_score, sentiment_score
 *   signal_thesis  — list[str]
 *   onClick        — optional click handler
 */
export default function SignalCard({
    ticker, name, sector, country,
    signal, final_score,
    fundamental_score, technical_score, macro_score, institutional_score, sentiment_score,
    signal_thesis,
    onClick,
}) {
    const cfg = SIGNAL_CONFIG[signal] || DEFAULT_CFG;
    const top3 = (signal_thesis || []).slice(0, 3);

    return (
        <div
            onClick={onClick}
            className={`rounded-xl border p-4 flex flex-col gap-3 cursor-pointer transition-all
                hover:shadow-md hover:border-opacity-60 ${cfg.border} ${cfg.bg}`}
        >
            {/* Header */}
            <div className="flex items-start justify-between gap-2">
                <div>
                    <div className="flex items-center gap-2">
                        <span className="font-bold text-sm">{ticker}</span>
                        <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${country === 'IN' ? 'bg-orange-500/20 text-orange-400' : 'bg-blue-500/20 text-blue-400'}`}>
                            {country || 'US'}
                        </span>
                    </div>
                    {name && <p className="text-xs text-muted-foreground mt-0.5 truncate max-w-[160px]">{name}</p>}
                    {sector && <p className="text-xs text-muted-foreground/70">{sector}</p>}
                </div>
                <SignalBadge signal={signal} size="sm" />
            </div>

            {/* Composite score bar */}
            <ScoreBar score={final_score} signal={signal} />

            {/* Agent score breakdown */}
            <div className="flex flex-col gap-1.5">
                <AgentScoreRow label="Fundamentals" score={fundamental_score} />
                <AgentScoreRow label="Technical" score={technical_score} />
                <AgentScoreRow label="Macro" score={macro_score} />
                <AgentScoreRow label="Institutional" score={institutional_score} />
                <AgentScoreRow label="Sentiment" score={sentiment_score} />
            </div>

            {/* Top thesis bullets */}
            {top3.length > 0 && (
                <ul className="text-xs text-muted-foreground space-y-1 mt-1 border-t border-border/40 pt-2">
                    {top3.map((t, i) => (
                        <li key={i} className="flex gap-1.5">
                            <span className="mt-0.5 shrink-0">•</span>
                            <span>{t}</span>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}
