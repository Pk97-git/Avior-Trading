import React, { useState, useEffect, useCallback } from 'react';
import { Filter, Plus, X, Play, Save, ChevronDown, Search, Loader2, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { screenerApi } from '../api';

// ── Helpers ────────────────────────────────────────────────────────────────────

const SIGNAL_COLORS = {
    STRONG_BUY:     'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
    ACCUMULATE:     'bg-green-500/20 text-green-400 border-green-500/30',
    HOLD:           'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    PROACTIVE_SWING:'bg-blue-500/20 text-blue-400 border-blue-500/30',
    AVOID:          'bg-orange-500/20 text-orange-400 border-orange-500/30',
    DISTRIBUTION:   'bg-red-400/20 text-red-300 border-red-400/30',
    SELL:           'bg-red-600/20 text-red-400 border-red-600/30',
};

const NUM_OPERATORS = [
    { value: '>',       label: '>' },
    { value: '<',       label: '<' },
    { value: '>=',      label: '>=' },
    { value: '<=',      label: '<=' },
    { value: '=',       label: '=' },
    { value: 'between', label: 'between' },
];
const STR_OPERATORS = [
    { value: '=',        label: 'equals' },
    { value: 'in',       label: 'is one of' },
    { value: 'contains', label: 'contains' },
];
const ENUM_OPERATORS = [
    { value: '=',  label: 'equals' },
    { value: 'in', label: 'is one of' },
];

function getOperators(field) {
    if (!field) return NUM_OPERATORS;
    if (field.type === 'enum')   return ENUM_OPERATORS;
    if (field.type === 'string') return STR_OPERATORS;
    return NUM_OPERATORS;
}

function fmt(val, decimals = 2) {
    if (val == null) return '—';
    const n = parseFloat(val);
    if (isNaN(n)) return '—';
    return n.toFixed(decimals);
}

function pctColor(val) {
    if (val == null) return 'text-muted-foreground';
    const n = parseFloat(val);
    if (isNaN(n)) return 'text-muted-foreground';
    if (n > 0) return 'text-emerald-400';
    if (n < 0) return 'text-red-400';
    return 'text-muted-foreground';
}

function ScoreBar({ score }) {
    if (score == null) return <span className="text-muted-foreground text-xs">—</span>;
    const pct = Math.min(100, Math.max(0, score));
    const color = pct >= 70 ? 'bg-emerald-500' : pct >= 50 ? 'bg-yellow-500' : 'bg-red-500';
    return (
        <div className="flex items-center gap-2">
            <div className="w-16 bg-muted rounded-full h-1.5 overflow-hidden">
                <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
            </div>
            <span className="text-xs font-medium tabular-nums">{Math.round(pct)}</span>
        </div>
    );
}

// ── Condition Row ──────────────────────────────────────────────────────────────

function ConditionRow({ condition, index, fields, onChange, onRemove }) {
    const [fieldSearch, setFieldSearch] = useState('');
    const [showFieldDropdown, setShowFieldDropdown] = useState(false);

    const selectedField = fields.find(f => f.field === condition.field);
    const operators = getOperators(selectedField);

    const filteredFields = fields.filter(f =>
        !fieldSearch ||
        f.label.toLowerCase().includes(fieldSearch.toLowerCase()) ||
        f.field.toLowerCase().includes(fieldSearch.toLowerCase())
    );

    const groups = [...new Set(filteredFields.map(f => f.group))];

    function handleFieldSelect(field) {
        const ops = getOperators(field);
        onChange(index, {
            field:    field.field,
            operator: ops[0].value,
            value:    field.type === 'enum' ? field.options[0] : '',
        });
        setShowFieldDropdown(false);
        setFieldSearch('');
    }

    function handleOperatorChange(e) {
        const op = e.target.value;
        onChange(index, {
            ...condition,
            operator: op,
            value: op === 'between' ? ['', ''] : op === 'in' ? [] : '',
        });
    }

    function renderValueInput() {
        if (!selectedField) return null;

        if (condition.operator === 'between') {
            const vals = Array.isArray(condition.value) ? condition.value : ['', ''];
            return (
                <div className="flex items-center gap-1">
                    <input
                        type="number"
                        className="w-20 px-2 py-1 rounded bg-muted border border-border text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                        value={vals[0]}
                        placeholder="min"
                        onChange={e => onChange(index, { ...condition, value: [e.target.value, vals[1]] })}
                    />
                    <span className="text-muted-foreground text-xs">–</span>
                    <input
                        type="number"
                        className="w-20 px-2 py-1 rounded bg-muted border border-border text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                        value={vals[1]}
                        placeholder="max"
                        onChange={e => onChange(index, { ...condition, value: [vals[0], e.target.value] })}
                    />
                </div>
            );
        }

        if (selectedField.type === 'enum') {
            if (condition.operator === 'in') {
                const selected = Array.isArray(condition.value) ? condition.value : [];
                return (
                    <div className="flex flex-wrap gap-1">
                        {(selectedField.options || []).map(opt => (
                            <button
                                key={opt}
                                onClick={() => {
                                    const next = selected.includes(opt)
                                        ? selected.filter(v => v !== opt)
                                        : [...selected, opt];
                                    onChange(index, { ...condition, value: next });
                                }}
                                className={`px-2 py-0.5 rounded text-xs border transition-colors ${
                                    selected.includes(opt)
                                        ? 'bg-primary text-primary-foreground border-primary'
                                        : 'bg-muted border-border text-muted-foreground hover:border-primary/50'
                                }`}
                            >
                                {opt}
                            </button>
                        ))}
                    </div>
                );
            }
            return (
                <select
                    className="px-2 py-1 rounded bg-muted border border-border text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                    value={condition.value || ''}
                    onChange={e => onChange(index, { ...condition, value: e.target.value })}
                >
                    {(selectedField.options || []).map(opt => (
                        <option key={opt} value={opt}>{opt}</option>
                    ))}
                </select>
            );
        }

        if (selectedField.type === 'string' && condition.operator === 'in') {
            const vals = Array.isArray(condition.value) ? condition.value : [];
            return (
                <input
                    type="text"
                    className="w-40 px-2 py-1 rounded bg-muted border border-border text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                    placeholder="val1, val2, ..."
                    value={vals.join(', ')}
                    onChange={e => onChange(index, {
                        ...condition,
                        value: e.target.value.split(',').map(v => v.trim()).filter(Boolean),
                    })}
                />
            );
        }

        const inputType = selectedField.type === 'number' ? 'number' : 'text';
        return (
            <input
                type={inputType}
                className="w-28 px-2 py-1 rounded bg-muted border border-border text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                placeholder="value"
                value={condition.value ?? ''}
                onChange={e => onChange(index, { ...condition, value: e.target.value })}
            />
        );
    }

    return (
        <div className="flex items-center gap-2 flex-wrap">
            {/* Field selector */}
            <div className="relative">
                <button
                    onClick={() => setShowFieldDropdown(v => !v)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-muted border border-border text-sm hover:border-primary/50 transition-colors min-w-[140px]"
                >
                    <span className="flex-1 text-left truncate">
                        {selectedField ? selectedField.label : <span className="text-muted-foreground">Select field…</span>}
                    </span>
                    <ChevronDown size={12} className="text-muted-foreground shrink-0" />
                </button>

                {showFieldDropdown && (
                    <div className="absolute top-full left-0 mt-1 w-72 bg-card border border-border rounded-lg shadow-xl z-50 overflow-hidden">
                        <div className="p-2 border-b border-border">
                            <div className="flex items-center gap-2 px-2 py-1 rounded bg-muted">
                                <Search size={12} className="text-muted-foreground shrink-0" />
                                <input
                                    autoFocus
                                    type="text"
                                    placeholder="Search fields…"
                                    className="bg-transparent text-sm outline-none flex-1"
                                    value={fieldSearch}
                                    onChange={e => setFieldSearch(e.target.value)}
                                />
                            </div>
                        </div>
                        <div className="max-h-72 overflow-y-auto">
                            {groups.map(group => (
                                <div key={group}>
                                    <p className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60 bg-muted/30">
                                        {group}
                                    </p>
                                    {filteredFields.filter(f => f.group === group).map(f => (
                                        <button
                                            key={f.field}
                                            onClick={() => handleFieldSelect(f)}
                                            className={`w-full text-left px-3 py-2 text-sm hover:bg-accent transition-colors ${
                                                condition.field === f.field ? 'bg-primary/10 text-primary' : ''
                                            }`}
                                        >
                                            <div className="font-medium">{f.label}</div>
                                            {f.description && (
                                                <div className="text-xs text-muted-foreground truncate">{f.description}</div>
                                            )}
                                        </button>
                                    ))}
                                </div>
                            ))}
                            {filteredFields.length === 0 && (
                                <div className="px-3 py-4 text-sm text-muted-foreground text-center">No fields found</div>
                            )}
                        </div>
                    </div>
                )}
            </div>

            {/* Operator */}
            <select
                className="px-2 py-1.5 rounded bg-muted border border-border text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                value={condition.operator || ''}
                onChange={handleOperatorChange}
            >
                {operators.map(op => (
                    <option key={op.value} value={op.value}>{op.label}</option>
                ))}
            </select>

            {/* Value input */}
            <div className="flex-1 min-w-0">
                {renderValueInput()}
            </div>

            {/* Remove */}
            <button
                onClick={() => onRemove(index)}
                className="p-1.5 rounded hover:bg-destructive/20 hover:text-destructive text-muted-foreground transition-colors"
            >
                <X size={14} />
            </button>
        </div>
    );
}

// ── Save Modal ─────────────────────────────────────────────────────────────────

function SaveModal({ conditions, onSave, onClose }) {
    const [name, setName]   = useState('');
    const [desc, setDesc]   = useState('');
    const [saving, setSaving] = useState(false);

    async function handleSave() {
        if (!name.trim()) return;
        setSaving(true);
        try {
            await onSave({ name: name.trim(), description: desc.trim() || null, conditions });
            onClose();
        } finally {
            setSaving(false);
        }
    }

    return (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-md p-6">
                <h3 className="text-lg font-semibold mb-4">Save Screener</h3>
                <div className="space-y-3">
                    <div>
                        <label className="text-sm text-muted-foreground block mb-1">Name *</label>
                        <input
                            autoFocus
                            type="text"
                            className="w-full px-3 py-2 rounded bg-muted border border-border text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                            placeholder="My Screener"
                            value={name}
                            onChange={e => setName(e.target.value)}
                            onKeyDown={e => e.key === 'Enter' && handleSave()}
                        />
                    </div>
                    <div>
                        <label className="text-sm text-muted-foreground block mb-1">Description (optional)</label>
                        <input
                            type="text"
                            className="w-full px-3 py-2 rounded bg-muted border border-border text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                            placeholder="What does this screen look for?"
                            value={desc}
                            onChange={e => setDesc(e.target.value)}
                        />
                    </div>
                </div>
                <div className="flex gap-2 mt-5 justify-end">
                    <button onClick={onClose} className="px-4 py-2 rounded text-sm hover:bg-muted transition-colors">Cancel</button>
                    <button
                        onClick={handleSave}
                        disabled={!name.trim() || saving}
                        className="flex items-center gap-2 px-4 py-2 rounded bg-primary text-primary-foreground text-sm hover:bg-primary/90 disabled:opacity-50 transition-colors"
                    >
                        {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                        Save
                    </button>
                </div>
            </div>
        </div>
    );
}

// ── Results Table ──────────────────────────────────────────────────────────────

function ResultsTable({ results, onNavigate }) {
    return (
        <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
                <thead>
                    <tr className="border-b border-border bg-muted/50">
                        <th className="text-left px-3 py-2.5 font-medium text-muted-foreground whitespace-nowrap">Ticker</th>
                        <th className="text-left px-3 py-2.5 font-medium text-muted-foreground whitespace-nowrap">Company</th>
                        <th className="text-left px-3 py-2.5 font-medium text-muted-foreground whitespace-nowrap">Sector</th>
                        <th className="text-right px-3 py-2.5 font-medium text-muted-foreground whitespace-nowrap">AI Score</th>
                        <th className="text-left px-3 py-2.5 font-medium text-muted-foreground whitespace-nowrap">Signal</th>
                        <th className="text-right px-3 py-2.5 font-medium text-muted-foreground whitespace-nowrap">RSI</th>
                        <th className="text-right px-3 py-2.5 font-medium text-muted-foreground whitespace-nowrap">SMA50%</th>
                        <th className="text-right px-3 py-2.5 font-medium text-muted-foreground whitespace-nowrap">5d %</th>
                        <th className="text-right px-3 py-2.5 font-medium text-muted-foreground whitespace-nowrap">P/E</th>
                        <th className="text-right px-3 py-2.5 font-medium text-muted-foreground whitespace-nowrap">Vol Ratio</th>
                    </tr>
                </thead>
                <tbody>
                    {results.map((row, i) => (
                        <tr
                            key={row.ticker}
                            className={`border-b border-border/50 hover:bg-muted/30 cursor-pointer transition-colors ${i % 2 === 0 ? '' : 'bg-muted/10'}`}
                            onClick={() => onNavigate && onNavigate('hub', row.ticker)}
                        >
                            <td className="px-3 py-2.5">
                                <span className="font-mono font-semibold text-primary">{row.ticker}</span>
                            </td>
                            <td className="px-3 py-2.5 max-w-[160px]">
                                <span className="truncate block" title={row.name}>{row.name || '—'}</span>
                            </td>
                            <td className="px-3 py-2.5 text-muted-foreground text-xs">
                                <span className="truncate block max-w-[100px]" title={row.sector}>{row.sector || '—'}</span>
                            </td>
                            <td className="px-3 py-2.5">
                                <div className="flex justify-end">
                                    <ScoreBar score={row.ai_score} />
                                </div>
                            </td>
                            <td className="px-3 py-2.5">
                                {row.signal ? (
                                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${SIGNAL_COLORS[row.signal] || 'bg-muted text-muted-foreground border-border'}`}>
                                        {row.signal.replace(/_/g, ' ')}
                                    </span>
                                ) : <span className="text-muted-foreground">—</span>}
                            </td>
                            <td className="px-3 py-2.5 text-right tabular-nums">
                                {row.rsi_14 != null ? (
                                    <span className={
                                        row.rsi_14 < 30 ? 'text-emerald-400 font-medium' :
                                        row.rsi_14 > 70 ? 'text-red-400 font-medium' : ''
                                    }>
                                        {fmt(row.rsi_14, 1)}
                                    </span>
                                ) : '—'}
                            </td>
                            <td className={`px-3 py-2.5 text-right tabular-nums ${pctColor(row.sma50_pct)}`}>
                                {row.sma50_pct != null ? `${fmt(row.sma50_pct, 1)}%` : '—'}
                            </td>
                            <td className={`px-3 py-2.5 text-right tabular-nums ${pctColor(row.price_change_5d)}`}>
                                <div className="flex items-center justify-end gap-0.5">
                                    {row.price_change_5d != null && (
                                        <>
                                            {row.price_change_5d > 0 ? <TrendingUp size={12} /> : row.price_change_5d < 0 ? <TrendingDown size={12} /> : <Minus size={12} />}
                                            {fmt(row.price_change_5d, 1)}%
                                        </>
                                    )}
                                    {row.price_change_5d == null && '—'}
                                </div>
                            </td>
                            <td className="px-3 py-2.5 text-right tabular-nums text-muted-foreground">
                                {row.pe_ratio != null ? fmt(row.pe_ratio, 1) : '—'}
                            </td>
                            <td className="px-3 py-2.5 text-right tabular-nums text-muted-foreground">
                                {row.vol_ratio_20d != null ? (
                                    <span className={row.vol_ratio_20d > 1.5 ? 'text-blue-400 font-medium' : ''}>
                                        {fmt(row.vol_ratio_20d, 2)}x
                                    </span>
                                ) : '—'}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

// ── Main Component ─────────────────────────────────────────────────────────────

export default function Screener({ onNavigate }) {
    const [conditions,  setConditions]  = useState([]);
    const [results,     setResults]     = useState([]);
    const [fields,      setFields]      = useState([]);
    const [templates,   setTemplates]   = useState([]);
    const [savedScreeners, setSavedScreeners] = useState([]);
    const [loading,     setLoading]     = useState(false);
    const [ran,         setRan]         = useState(false);
    const [meta,        setMeta]        = useState(null);  // { total_scanned, matches, elapsed_ms }
    const [error,       setError]       = useState(null);
    const [showSave,    setShowSave]    = useState(false);
    const [activeGroup, setActiveGroup] = useState('built-in');  // 'built-in' | 'saved'

    // ── Load fields + templates on mount ─────────────────────────────────────
    useEffect(() => {
        screenerApi.getFields().then(r => setFields(r.data || [])).catch(() => {});
        screenerApi.getTemplates().then(r => setTemplates(r.data || [])).catch(() => {});
        screenerApi.getSaved().then(r => setSavedScreeners(r.data || [])).catch(() => {});
    }, []);

    // ── Condition management ──────────────────────────────────────────────────
    function addCondition() {
        setConditions(prev => [...prev, { field: '', operator: '>', value: '' }]);
    }

    function updateCondition(index, updated) {
        setConditions(prev => prev.map((c, i) => i === index ? updated : c));
    }

    function removeCondition(index) {
        setConditions(prev => prev.filter((_, i) => i !== index));
    }

    function clearAll() {
        setConditions([]);
        setResults([]);
        setRan(false);
        setMeta(null);
        setError(null);
    }

    function loadTemplate(template) {
        setConditions(template.conditions.map(c => ({ ...c })));
        setRan(false);
        setResults([]);
        setMeta(null);
        setError(null);
    }

    // ── Run screener ──────────────────────────────────────────────────────────
    const runScreener = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            // Prepare conditions — coerce numeric values
            const prepared = conditions
                .filter(c => c.field)
                .map(c => {
                    const field = fields.find(f => f.field === c.field);
                    let value = c.value;
                    if (field && field.type === 'number') {
                        if (c.operator === 'between' && Array.isArray(value)) {
                            value = value.map(v => parseFloat(v));
                        } else if (c.operator === 'in' && Array.isArray(value)) {
                            value = value.map(v => parseFloat(v));
                        } else if (typeof value === 'string') {
                            value = parseFloat(value);
                        }
                    }
                    return { field: c.field, operator: c.operator, value };
                });

            const res = await screenerApi.run({ conditions: prepared, limit: 100 });
            const data = res.data;
            setResults(data.results || []);
            setMeta({
                total_scanned:      data.total_scanned,
                matches:            data.matches,
                elapsed_ms:         data.elapsed_ms,
                conditions_applied: data.conditions_applied,
            });
            setRan(true);
        } catch (err) {
            setError(err?.response?.data?.detail || err.message || 'Screener failed');
        } finally {
            setLoading(false);
        }
    }, [conditions, fields]);

    // ── Save screener ─────────────────────────────────────────────────────────
    async function handleSave({ name, description }) {
        await screenerApi.save({ name, description, conditions });
        const saved = await screenerApi.getSaved();
        setSavedScreeners(saved.data || []);
    }

    const displayTemplates = activeGroup === 'saved' ? savedScreeners : templates;

    // ── Render ────────────────────────────────────────────────────────────────
    return (
        <div className="flex gap-4 h-full min-h-0">

            {/* ── Sidebar: Templates ── */}
            <aside className="w-52 shrink-0 space-y-3">
                <div className="bg-card border border-border rounded-xl overflow-hidden">
                    {/* Tab toggle */}
                    <div className="flex border-b border-border">
                        {['built-in', 'saved'].map(g => (
                            <button
                                key={g}
                                onClick={() => setActiveGroup(g)}
                                className={`flex-1 py-2 text-xs font-medium transition-colors ${
                                    activeGroup === g
                                        ? 'bg-primary/10 text-primary border-b-2 border-primary'
                                        : 'text-muted-foreground hover:text-foreground'
                                }`}
                            >
                                {g === 'built-in' ? 'Templates' : 'Saved'}
                            </button>
                        ))}
                    </div>

                    <div className="p-2 space-y-1">
                        {displayTemplates.length === 0 && (
                            <p className="text-xs text-muted-foreground text-center py-4 px-2">
                                {activeGroup === 'saved' ? 'No saved screeners yet' : 'No templates available'}
                            </p>
                        )}
                        {displayTemplates.map((t, i) => (
                            <button
                                key={i}
                                onClick={() => loadTemplate(t)}
                                className="w-full text-left px-2.5 py-2 rounded hover:bg-muted transition-colors group"
                            >
                                <div className="text-xs font-medium leading-tight group-hover:text-primary transition-colors">
                                    {t.name}
                                </div>
                                {t.description && (
                                    <div className="text-[10px] text-muted-foreground leading-tight mt-0.5 line-clamp-2">
                                        {t.description}
                                    </div>
                                )}
                            </button>
                        ))}
                    </div>
                </div>

                {/* Save button */}
                {conditions.length > 0 && (
                    <button
                        onClick={() => setShowSave(true)}
                        className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border border-border text-sm hover:bg-muted transition-colors"
                    >
                        <Save size={13} />
                        Save Screener
                    </button>
                )}
            </aside>

            {/* ── Main content ── */}
            <div className="flex-1 min-w-0 space-y-4">

                {/* ── Header ── */}
                <div className="flex items-center justify-between gap-4">
                    <div>
                        <h2 className="text-lg font-semibold flex items-center gap-2">
                            <Filter size={18} className="text-primary" />
                            Custom Screener
                        </h2>
                        <p className="text-sm text-muted-foreground mt-0.5">
                            Build filters to find exactly what you're looking for
                        </p>
                    </div>
                    <button
                        onClick={runScreener}
                        disabled={loading}
                        className="flex items-center gap-2 px-5 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
                    >
                        {loading
                            ? <Loader2 size={15} className="animate-spin" />
                            : <Play size={15} />
                        }
                        {loading ? 'Running…' : 'Run Screen'}
                    </button>
                </div>

                {/* ── Condition builder ── */}
                <div className="bg-card border border-border rounded-xl p-4 space-y-3">
                    <div className="flex items-center justify-between mb-1">
                        <span className="text-sm font-medium">
                            Conditions
                            {conditions.length > 0 && (
                                <span className="ml-2 text-xs text-muted-foreground">
                                    ({conditions.length} filter{conditions.length !== 1 ? 's' : ''}, AND logic)
                                </span>
                            )}
                        </span>
                        {conditions.length > 0 && (
                            <button
                                onClick={clearAll}
                                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                            >
                                Clear all
                            </button>
                        )}
                    </div>

                    {conditions.length === 0 && (
                        <div className="py-6 text-center text-sm text-muted-foreground border border-dashed border-border rounded-lg">
                            No conditions yet. Add a filter or select a template.
                        </div>
                    )}

                    <div className="space-y-2">
                        {conditions.map((cond, i) => (
                            <div key={i} className="flex items-start gap-2">
                                {i > 0 && (
                                    <span className="text-[10px] font-semibold text-muted-foreground/50 uppercase mt-2.5 w-6 text-right shrink-0">
                                        AND
                                    </span>
                                )}
                                {i === 0 && <div className="w-6 shrink-0" />}
                                <div className="flex-1">
                                    <ConditionRow
                                        condition={cond}
                                        index={i}
                                        fields={fields}
                                        onChange={updateCondition}
                                        onRemove={removeCondition}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>

                    <button
                        onClick={addCondition}
                        className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-primary transition-colors mt-2"
                    >
                        <Plus size={14} />
                        Add Condition
                    </button>
                </div>

                {/* ── Error ── */}
                {error && (
                    <div className="px-4 py-3 rounded-lg bg-destructive/10 border border-destructive/30 text-destructive text-sm">
                        {error}
                    </div>
                )}

                {/* ── Results ── */}
                {ran && (
                    <div className="space-y-3">
                        <div className="flex items-center justify-between">
                            <div className="text-sm">
                                <span className="font-semibold text-primary">{meta?.matches ?? results.length}</span>
                                <span className="text-muted-foreground">
                                    {' '}stock{results.length !== 1 ? 's' : ''} matched
                                    {meta?.total_scanned ? ` out of ${meta.total_scanned.toLocaleString()} scanned` : ''}
                                </span>
                            </div>
                            {meta?.elapsed_ms != null && (
                                <span className="text-xs text-muted-foreground">
                                    {meta.elapsed_ms < 1000
                                        ? `${Math.round(meta.elapsed_ms)}ms`
                                        : `${(meta.elapsed_ms / 1000).toFixed(1)}s`
                                    }
                                </span>
                            )}
                        </div>

                        {results.length === 0 ? (
                            <div className="py-12 text-center text-sm text-muted-foreground border border-border rounded-xl bg-card">
                                No stocks match your current filters. Try relaxing some conditions.
                            </div>
                        ) : (
                            <ResultsTable results={results} onNavigate={onNavigate} />
                        )}
                    </div>
                )}
            </div>

            {/* ── Save Modal ── */}
            {showSave && (
                <SaveModal
                    conditions={conditions}
                    onSave={handleSave}
                    onClose={() => setShowSave(false)}
                />
            )}
        </div>
    );
}
