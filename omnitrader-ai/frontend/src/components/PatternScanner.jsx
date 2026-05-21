import React, { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Loader2, TrendingUp, X, ChevronRight, Star } from 'lucide-react';
import { patternsApi } from '../api';

// ── helpers ────────────────────────────────────────────────────────────────

const CATEGORY_STYLES = {
    SINGLE:    'bg-slate-700/60 text-slate-300',
    DOUBLE:    'bg-blue-900/60 text-blue-300',
    TRIPLE:    'bg-purple-900/60 text-purple-300',
    COMPLEX:   'bg-amber-900/60 text-amber-300',
    STRUCTURE: 'bg-emerald-900/60 text-emerald-300',
};

const BIAS_STYLES = {
    BULLISH: 'bg-green-500/20 text-green-400 border border-green-500/30',
    BEARISH: 'bg-red-500/20 text-red-400 border border-red-500/30',
    NEUTRAL: 'bg-slate-700/40 text-slate-400 border border-slate-600/30',
};

const COUNTRY_FLAG = { IN: '🇮🇳', US: '🇺🇸' };

function Stars({ value, max = 5 }) {
    return (
        <span className="inline-flex gap-0.5">
            {Array.from({ length: max }, (_, i) => (
                <span key={i} className={i < value ? 'text-yellow-400' : 'text-slate-700'}>★</span>
            ))}
        </span>
    );
}

function ContextBar({ score }) {
    const pct = Math.round((score ?? 0) * 100);
    let color = 'bg-red-500';
    if (score >= 0.7) color = 'bg-green-500';
    else if (score >= 0.4) color = 'bg-yellow-500';
    return (
        <div className="flex items-center gap-1.5 group relative">
            <div className="w-16 h-1.5 rounded-full bg-slate-700/60 overflow-hidden">
                <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
            </div>
            <span className="text-xs text-slate-500">{pct}%</span>
        </div>
    );
}

function formatDate(dateStr) {
    if (!dateStr) return '—';
    const d = new Date(dateStr);
    const now = new Date();
    const diff = Math.floor((now - d) / 86400000);
    if (diff === 0) return 'Today';
    if (diff === 1) return 'Yesterday';
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

// ── Side panel ─────────────────────────────────────────────────────────────

function PatternSidePanel({ pattern, onClose, onNavigate, onBacktest }) {
    if (!pattern) return null;
    const notes = pattern.context_notes
        ? (Array.isArray(pattern.context_notes) ? pattern.context_notes : [pattern.context_notes])
        : [];

    return (
        <div className="w-[360px] shrink-0 flex flex-col border-l border-slate-700/60 bg-slate-900/80 backdrop-blur-sm overflow-y-auto">
            {/* Header */}
            <div className="flex items-start justify-between p-4 border-b border-slate-700/60">
                <div>
                    <div className="flex items-center gap-2 mb-1">
                        <span className="text-lg font-bold text-slate-100">
                            {COUNTRY_FLAG[pattern.country] || ''} {pattern.ticker}
                        </span>
                        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${BIAS_STYLES[pattern.bias] || BIAS_STYLES.NEUTRAL}`}>
                            {pattern.bias}
                        </span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="text-slate-300 font-medium">{pattern.pattern_name}</span>
                        <span className={`px-1.5 py-0.5 rounded text-xs ${CATEGORY_STYLES[pattern.category] || CATEGORY_STYLES.SINGLE}`}>
                            {pattern.category}
                        </span>
                    </div>
                </div>
                <button onClick={onClose} className="p-1 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors">
                    <X size={16} />
                </button>
            </div>

            {/* Body */}
            <div className="flex-1 p-4 space-y-4 text-sm">
                {/* Strength + reliability */}
                <div className="flex items-center gap-4">
                    <div>
                        <div className="text-xs text-slate-500 mb-1">Strength</div>
                        <Stars value={pattern.strength} />
                    </div>
                    <div>
                        <div className="text-xs text-slate-500 mb-1">Reliability</div>
                        <span className="text-slate-300">{pattern.reliability_pct ?? '—'}%</span>
                    </div>
                    <div>
                        <div className="text-xs text-slate-500 mb-1">Volume</div>
                        <span className={pattern.volume_confirmed ? 'text-green-400' : 'text-slate-500'}>
                            {pattern.volume_confirmed ? '✓ Confirmed' : '—'}
                        </span>
                    </div>
                </div>

                {/* Description */}
                {pattern.description && (
                    <div>
                        <div className="text-xs text-slate-500 mb-1 uppercase tracking-wide">Description</div>
                        <p className="text-slate-300 leading-relaxed">{pattern.description}</p>
                    </div>
                )}

                {/* Entry / Stop */}
                <div className="grid grid-cols-2 gap-3">
                    {pattern.entry_suggestion != null && (
                        <div className="bg-slate-800/60 rounded-lg p-3 border border-slate-700/40">
                            <div className="text-xs text-slate-500 mb-1">Entry Suggestion</div>
                            <div className="text-yellow-400 font-mono font-semibold">{pattern.entry_suggestion}</div>
                        </div>
                    )}
                    {pattern.stop_suggestion != null && (
                        <div className="bg-slate-800/60 rounded-lg p-3 border border-slate-700/40">
                            <div className="text-xs text-slate-500 mb-1">Stop Suggestion</div>
                            <div className="text-red-400 font-mono font-semibold">{pattern.stop_suggestion}</div>
                        </div>
                    )}
                </div>

                {/* Context score */}
                {pattern.context_score != null && (
                    <div>
                        <div className="text-xs text-slate-500 mb-2 uppercase tracking-wide">Context Score</div>
                        <ContextBar score={pattern.context_score} />
                    </div>
                )}

                {/* Context notes */}
                {notes.length > 0 && (
                    <div>
                        <div className="text-xs text-slate-500 mb-2 uppercase tracking-wide">Context Notes</div>
                        <ul className="space-y-1">
                            {notes.map((note, i) => (
                                <li key={i} className="flex items-start gap-2 text-slate-400">
                                    <span className="text-blue-500 mt-0.5 shrink-0">•</span>
                                    <span>{note}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </div>

            {/* Actions */}
            <div className="p-4 border-t border-slate-700/60 space-y-2">
                <button
                    onClick={() => onNavigate('hub', pattern.ticker)}
                    className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium transition-colors"
                >
                    <TrendingUp size={14} />
                    View in Intelligence Hub
                </button>
                <button
                    onClick={() => onBacktest(pattern)}
                    className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg text-sm font-medium transition-colors"
                >
                    <Star size={14} />
                    Backtest this pattern
                </button>
            </div>
        </div>
    );
}

// ── Main component ─────────────────────────────────────────────────────────

export default function PatternScanner({ onNavigate }) {
    const [results, setResults] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [biasFilter, setBiasFilter] = useState('ALL');
    const [countryFilter, setCountryFilter] = useState('ALL');
    const [minStrength, setMinStrength] = useState(3);
    const [selectedPattern, setSelectedPattern] = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = { min_strength: minStrength, limit: 50 };
            if (biasFilter !== 'ALL') params.bias = biasFilter;
            if (countryFilter !== 'ALL') params.country = countryFilter;
            const res = await patternsApi.scanToday(params);
            setResults(res.data.results ?? res.data ?? []);
        } catch (e) {
            setError(e?.response?.data?.detail || 'Failed to load pattern scan results.');
        } finally {
            setLoading(false);
        }
    }, [biasFilter, countryFilter, minStrength]);

    useEffect(() => { load(); }, [load]);

    const handleBacktest = (pattern) => {
        if (onNavigate) onNavigate('backtest', pattern.ticker);
    };

    // Summary counts
    const bullishCount = results.filter(r => r.bias === 'BULLISH').length;
    const bearishCount = results.filter(r => r.bias === 'BEARISH').length;
    const neutralCount = results.filter(r => r.bias === 'NEUTRAL').length;

    return (
        <div className="flex h-full bg-slate-900 text-slate-100 min-h-0">
            {/* Main panel */}
            <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
                {/* Header */}
                <div className="px-6 pt-5 pb-4 border-b border-slate-700/60">
                    <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                            <TrendingUp className="text-blue-400" size={20} />
                            <h1 className="text-xl font-bold text-slate-100">Pattern Scanner</h1>
                        </div>
                        <button
                            onClick={load}
                            disabled={loading}
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm text-slate-200 transition-colors disabled:opacity-50"
                        >
                            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                            Refresh
                        </button>
                    </div>
                    <p className="text-slate-500 text-sm">Today's candlestick formations across the universe</p>
                </div>

                {/* Filters */}
                <div className="px-6 py-3 border-b border-slate-700/60 flex flex-wrap items-center gap-4">
                    {/* Bias filter */}
                    <div className="flex rounded-lg overflow-hidden border border-slate-700/60">
                        {['ALL', 'BULLISH', 'BEARISH'].map(b => (
                            <button
                                key={b}
                                onClick={() => setBiasFilter(b)}
                                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                                    biasFilter === b
                                        ? b === 'BULLISH' ? 'bg-green-500/20 text-green-400'
                                            : b === 'BEARISH' ? 'bg-red-500/20 text-red-400'
                                            : 'bg-slate-700 text-slate-200'
                                        : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800'
                                }`}
                            >{b}</button>
                        ))}
                    </div>

                    {/* Country filter */}
                    <div className="flex items-center gap-1.5">
                        <span className="text-xs text-slate-500">Country:</span>
                        <div className="flex rounded-lg overflow-hidden border border-slate-700/60">
                            {['ALL', 'IN', 'US'].map(c => (
                                <button
                                    key={c}
                                    onClick={() => setCountryFilter(c)}
                                    className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                                        countryFilter === c
                                            ? 'bg-slate-700 text-slate-200'
                                            : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800'
                                    }`}
                                >
                                    {c === 'IN' ? '🇮🇳 IN' : c === 'US' ? '🇺🇸 US' : c}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Strength slider */}
                    <div className="flex items-center gap-2">
                        <span className="text-xs text-slate-500">Min Strength:</span>
                        <Stars value={minStrength} />
                        <input
                            type="range"
                            min={1}
                            max={5}
                            value={minStrength}
                            onChange={e => setMinStrength(Number(e.target.value))}
                            className="w-20 accent-yellow-400"
                        />
                        <span className="text-xs text-slate-400 w-4">{minStrength}</span>
                    </div>
                </div>

                {/* Summary chips */}
                {!loading && !error && results.length > 0 && (
                    <div className="px-6 py-2.5 border-b border-slate-700/60 flex items-center gap-3 flex-wrap">
                        <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-green-500/10 border border-green-500/20 text-green-400 text-xs font-medium">
                            <span className="w-2 h-2 rounded-full bg-green-500 inline-block" />
                            {bullishCount} Bullish
                        </span>
                        <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-red-500/10 border border-red-500/20 text-red-400 text-xs font-medium">
                            <span className="w-2 h-2 rounded-full bg-red-500 inline-block" />
                            {bearishCount} Bearish
                        </span>
                        {neutralCount > 0 && (
                            <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-700/40 border border-slate-600/30 text-slate-400 text-xs font-medium">
                                <span className="w-2 h-2 rounded-full bg-slate-500 inline-block" />
                                {neutralCount} Neutral
                            </span>
                        )}
                        <span className="text-slate-600 text-xs ml-auto">{results.length} total</span>
                    </div>
                )}

                {/* Content */}
                <div className="flex-1 overflow-auto">
                    {loading && (
                        <div className="flex items-center justify-center h-64 gap-3 text-slate-500">
                            <Loader2 className="animate-spin" size={24} />
                            <span>Scanning for patterns...</span>
                        </div>
                    )}

                    {!loading && error && (
                        <div className="flex flex-col items-center justify-center h-64 gap-3">
                            <p className="text-red-400 text-sm">{error}</p>
                            <button onClick={load} className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm text-slate-200 transition-colors">
                                Retry
                            </button>
                        </div>
                    )}

                    {!loading && !error && results.length === 0 && (
                        <div className="flex flex-col items-center justify-center h-64 gap-2 text-slate-500">
                            <TrendingUp size={32} className="text-slate-700" />
                            <p className="text-sm">No patterns detected today matching your filters.</p>
                            <p className="text-xs text-slate-600">Try lowering the minimum strength.</p>
                        </div>
                    )}

                    {!loading && !error && results.length > 0 && (
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="border-b border-slate-700/60 bg-slate-800/40">
                                        <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Ticker</th>
                                        <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Pattern</th>
                                        <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Bias</th>
                                        <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Strength</th>
                                        <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Context</th>
                                        <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Volume</th>
                                        <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Date</th>
                                        <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Reliability</th>
                                        <th className="px-4 py-3" />
                                    </tr>
                                </thead>
                                <tbody>
                                    {results.map((row, i) => {
                                        const isSelected = selectedPattern?.ticker === row.ticker && selectedPattern?.pattern_name === row.pattern_name && selectedPattern?.detected_at === row.detected_at;
                                        return (
                                            <tr
                                                key={i}
                                                onClick={() => setSelectedPattern(isSelected ? null : row)}
                                                className={`border-b border-slate-800/60 cursor-pointer transition-colors ${
                                                    isSelected
                                                        ? 'bg-blue-500/10 border-blue-500/20'
                                                        : 'hover:bg-slate-800/40'
                                                }`}
                                            >
                                                {/* Ticker */}
                                                <td className="px-4 py-3">
                                                    <span className="font-bold text-slate-100">{COUNTRY_FLAG[row.country] || ''} {row.ticker}</span>
                                                </td>

                                                {/* Pattern name + category badge */}
                                                <td className="px-4 py-3">
                                                    <div className="flex flex-col gap-0.5">
                                                        <span className="text-slate-200 font-medium">{row.pattern_name}</span>
                                                        {row.category && (
                                                            <span className={`self-start px-1.5 py-0.5 rounded text-xs font-medium ${CATEGORY_STYLES[row.category] || CATEGORY_STYLES.SINGLE}`}>
                                                                {row.category}
                                                            </span>
                                                        )}
                                                    </div>
                                                </td>

                                                {/* Bias pill */}
                                                <td className="px-4 py-3">
                                                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${BIAS_STYLES[row.bias] || BIAS_STYLES.NEUTRAL}`}>
                                                        {row.bias}
                                                    </span>
                                                </td>

                                                {/* Strength stars */}
                                                <td className="px-4 py-3">
                                                    <Stars value={row.strength} />
                                                </td>

                                                {/* Context bar */}
                                                <td className="px-4 py-3">
                                                    <div className="relative group">
                                                        <ContextBar score={row.context_score} />
                                                        {row.context_notes && (
                                                            <div className="absolute bottom-full left-0 mb-1 w-52 bg-slate-800 border border-slate-700 rounded-lg p-2 text-xs text-slate-300 shadow-xl z-20 hidden group-hover:block">
                                                                {Array.isArray(row.context_notes)
                                                                    ? row.context_notes.map((n, j) => <p key={j} className="mb-0.5">• {n}</p>)
                                                                    : <p>{row.context_notes}</p>
                                                                }
                                                            </div>
                                                        )}
                                                    </div>
                                                </td>

                                                {/* Volume confirmed */}
                                                <td className="px-4 py-3 text-center">
                                                    {row.volume_confirmed
                                                        ? <span className="text-green-400 text-base">✓</span>
                                                        : <span className="text-slate-600">—</span>
                                                    }
                                                </td>

                                                {/* Date */}
                                                <td className="px-4 py-3 text-slate-400 whitespace-nowrap">
                                                    {formatDate(row.detected_at || row.date)}
                                                </td>

                                                {/* Reliability */}
                                                <td className="px-4 py-3 text-slate-500 text-xs">
                                                    {row.reliability_pct != null ? `${row.reliability_pct}%` : '—'}
                                                </td>

                                                {/* Action */}
                                                <td className="px-4 py-3">
                                                    <button
                                                        onClick={(e) => { e.stopPropagation(); onNavigate('hub', row.ticker); }}
                                                        className="flex items-center gap-1 px-2.5 py-1 bg-blue-600/20 hover:bg-blue-600/40 border border-blue-500/30 text-blue-400 rounded text-xs font-medium transition-colors whitespace-nowrap"
                                                    >
                                                        View Chart <ChevronRight size={12} />
                                                    </button>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </div>

            {/* Side panel */}
            {selectedPattern && (
                <PatternSidePanel
                    pattern={selectedPattern}
                    onClose={() => setSelectedPattern(null)}
                    onNavigate={onNavigate}
                    onBacktest={handleBacktest}
                />
            )}
        </div>
    );
}
