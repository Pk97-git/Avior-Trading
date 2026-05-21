import React, { useState, useCallback } from 'react';
import { Calculator, X, Info, TrendingUp, TrendingDown, AlertTriangle, CheckCircle } from 'lucide-react';
import { positionSizingApi } from '../api';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(n, digits = 2) {
    if (n == null) return '—';
    return Number(n).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function fmtCcy(n, symbol = '₹') {
    if (n == null) return '—';
    if (Math.abs(n) >= 1_00_000) return `${symbol}${(n / 1_00_000).toFixed(2)}L`;
    if (Math.abs(n) >= 1_000) return `${symbol}${(n / 1_000).toFixed(1)}K`;
    return `${symbol}${fmt(n)}`;
}

// ─── Comparison Table Row ────────────────────────────────────────────────────

function SizingRow({ label, shares, capital, pctPortfolio, maxLoss, highlight, currencySymbol = '₹' }) {
    return (
        <tr className={`border-b border-border/40 ${highlight ? 'bg-primary/10' : 'hover:bg-muted/20'}`}>
            <td className={`py-2 pl-2 text-sm font-medium ${highlight ? 'text-primary' : 'text-foreground'}`}>
                {highlight && <span className="inline-block w-1.5 h-1.5 rounded-full bg-primary mr-2 mb-0.5" />}
                {label}
            </td>
            <td className="py-2 text-right text-sm font-mono">{shares != null ? shares.toLocaleString() : '—'}</td>
            <td className="py-2 text-right text-sm font-mono">{fmtCcy(capital, currencySymbol)}</td>
            <td className="py-2 text-right text-sm">{pctPortfolio != null ? `${fmt(pctPortfolio)}%` : '—'}</td>
            <td className={`py-2 pr-2 text-right text-sm ${highlight ? 'text-red-400' : 'text-muted-foreground'}`}>
                {maxLoss != null ? `−${fmtCcy(maxLoss, currencySymbol)}` : '—'}
            </td>
        </tr>
    );
}

// ─── Main PositionSizer Component ────────────────────────────────────────────

function PositionSizer({ prefill = {}, onClose }) {
    const [form, setForm] = useState({
        portfolio_value: '',
        entry_price: prefill.entry || '',
        stop_loss: prefill.stop || '',
        take_profit: prefill.target || '',
        win_rate: 0.55,
        max_risk_pct: 2.0,
        country: 'IN',
    });
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const currencySymbol = form.country === 'IN' ? '₹' : '$';

    const handleChange = (key, value) => {
        setForm(f => ({ ...f, [key]: value }));
        setResult(null);
        setError(null);
    };

    const handleCalculate = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const payload = {
                portfolio_value: parseFloat(form.portfolio_value),
                entry_price:     parseFloat(form.entry_price),
                stop_loss:       parseFloat(form.stop_loss),
                take_profit:     parseFloat(form.take_profit),
                win_rate:        parseFloat(form.win_rate),
                max_risk_pct:    parseFloat(form.max_risk_pct),
                country:         form.country,
            };
            const res = await positionSizingApi.calculate(payload);
            setResult(res.data);
        } catch (e) {
            setError(e?.response?.data?.detail || 'Calculation failed');
        } finally {
            setLoading(false);
        }
    }, [form]);

    const isFormValid = form.portfolio_value && form.entry_price && form.stop_loss && form.take_profit;

    const inputClass = "w-full bg-muted/40 border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary";

    return (
        <div className="space-y-5">
            {/* Summary banner */}
            {result && (
                <div className="rounded-lg border border-primary/30 bg-primary/5 p-4">
                    <p className="text-sm font-semibold text-primary mb-1">
                        Recommended Position
                    </p>
                    <p className="text-base font-bold">
                        {result.recommended_shares.toLocaleString()} shares — {fmtCcy(result.recommended_capital, currencySymbol)} ({fmt(result.recommended_pct_portfolio)}% of portfolio)
                    </p>
                    <p className="text-sm text-muted-foreground mt-1">
                        Max loss if stopped: <span className="text-red-400 font-medium">−{fmtCcy(result.max_loss_if_stopped, currencySymbol)}</span>
                        {' · '}
                        Max gain if target: <span className="text-green-400 font-medium">+{fmtCcy(result.max_gain_if_target, currencySymbol)}</span>
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">{result.method_used}</p>
                </div>
            )}

            {/* Input form */}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <div>
                    <label className="block text-xs text-muted-foreground mb-1">Portfolio Value ({currencySymbol})</label>
                    <input
                        type="number"
                        className={inputClass}
                        placeholder="e.g. 500000"
                        value={form.portfolio_value}
                        onChange={e => handleChange('portfolio_value', e.target.value)}
                    />
                </div>
                <div>
                    <label className="block text-xs text-muted-foreground mb-1">Entry Price</label>
                    <input
                        type="number"
                        className={inputClass}
                        placeholder="e.g. 1200"
                        value={form.entry_price}
                        onChange={e => handleChange('entry_price', e.target.value)}
                    />
                </div>
                <div>
                    <label className="block text-xs text-muted-foreground mb-1">Stop Loss</label>
                    <input
                        type="number"
                        className={inputClass}
                        placeholder="e.g. 1140"
                        value={form.stop_loss}
                        onChange={e => handleChange('stop_loss', e.target.value)}
                    />
                </div>
                <div>
                    <label className="block text-xs text-muted-foreground mb-1">Take Profit</label>
                    <input
                        type="number"
                        className={inputClass}
                        placeholder="e.g. 1380"
                        value={form.take_profit}
                        onChange={e => handleChange('take_profit', e.target.value)}
                    />
                </div>
                <div>
                    <label className="block text-xs text-muted-foreground mb-1">
                        Win Rate: <span className="font-semibold text-foreground">{Math.round(form.win_rate * 100)}%</span>
                    </label>
                    <input
                        type="range"
                        min="0.30" max="0.80" step="0.01"
                        className="w-full mt-1 accent-primary"
                        value={form.win_rate}
                        onChange={e => handleChange('win_rate', e.target.value)}
                    />
                    <div className="flex justify-between text-[10px] text-muted-foreground">
                        <span>30%</span><span>55%</span><span>80%</span>
                    </div>
                </div>
                <div>
                    <label className="block text-xs text-muted-foreground mb-1">
                        Max Risk %: <span className="font-semibold text-foreground">{form.max_risk_pct}%</span>
                    </label>
                    <input
                        type="range"
                        min="0.5" max="5.0" step="0.5"
                        className="w-full mt-1 accent-primary"
                        value={form.max_risk_pct}
                        onChange={e => handleChange('max_risk_pct', e.target.value)}
                    />
                    <div className="flex justify-between text-[10px] text-muted-foreground">
                        <span>0.5%</span><span>2%</span><span>5%</span>
                    </div>
                </div>
            </div>

            {/* Country + Calculate */}
            <div className="flex items-center gap-3 flex-wrap">
                <div className="flex gap-2">
                    {['IN', 'US'].map(c => (
                        <button
                            key={c}
                            onClick={() => handleChange('country', c)}
                            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                                form.country === c
                                    ? 'bg-primary text-primary-foreground'
                                    : 'bg-muted text-muted-foreground hover:bg-accent'
                            }`}
                        >
                            {c === 'IN' ? '🇮🇳 India' : '🇺🇸 US'}
                        </button>
                    ))}
                </div>
                <button
                    onClick={handleCalculate}
                    disabled={!isFormValid || loading}
                    className="ml-auto px-5 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-semibold hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center gap-2"
                >
                    <Calculator size={15} />
                    {loading ? 'Calculating…' : 'Calculate Size'}
                </button>
            </div>

            {error && (
                <p className="text-sm text-red-400 flex items-center gap-2">
                    <AlertTriangle size={14} /> {error}
                </p>
            )}

            {/* Results comparison table */}
            {result && (
                <div className="space-y-4">
                    {/* Key metrics */}
                    <div className="grid grid-cols-3 gap-3">
                        <div className="rounded-lg border border-border bg-card p-3 text-center">
                            <p className="text-xs text-muted-foreground mb-1">R/R Ratio</p>
                            <p className={`text-xl font-bold ${result.risk_reward_ratio >= 2 ? 'text-green-400' : result.risk_reward_ratio >= 1.5 ? 'text-yellow-400' : 'text-red-400'}`}>
                                {fmt(result.risk_reward_ratio, 1)}:1
                            </p>
                        </div>
                        <div className="rounded-lg border border-border bg-card p-3 text-center">
                            <p className="text-xs text-muted-foreground mb-1">Expected Value</p>
                            <p className={`text-xl font-bold ${result.expected_value > 0 ? 'text-green-400' : 'text-red-400'}`}>
                                {result.expected_value >= 0 ? '+' : ''}{fmt(result.expected_value, 2)}x
                            </p>
                        </div>
                        <div className="rounded-lg border border-border bg-card p-3 text-center">
                            <p className="text-xs text-muted-foreground mb-1">Risk per Share</p>
                            <p className="text-xl font-bold">{currencySymbol}{fmt(result.risk_per_share)}</p>
                        </div>
                    </div>

                    {/* Comparison table */}
                    <div className="rounded-lg border border-border overflow-hidden">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-border bg-muted/30">
                                    <th className="text-left py-2 pl-2 text-xs text-muted-foreground uppercase tracking-wide">Method</th>
                                    <th className="text-right py-2 text-xs text-muted-foreground uppercase tracking-wide">Shares</th>
                                    <th className="text-right py-2 text-xs text-muted-foreground uppercase tracking-wide">Capital</th>
                                    <th className="text-right py-2 text-xs text-muted-foreground uppercase tracking-wide">% Portfolio</th>
                                    <th className="text-right py-2 pr-2 text-xs text-muted-foreground uppercase tracking-wide">Max Loss</th>
                                </tr>
                            </thead>
                            <tbody>
                                <SizingRow
                                    label="Recommended"
                                    shares={result.recommended_shares}
                                    capital={result.recommended_capital}
                                    pctPortfolio={result.recommended_pct_portfolio}
                                    maxLoss={result.max_loss_if_stopped}
                                    highlight={true}
                                    currencySymbol={currencySymbol}
                                />
                                <SizingRow
                                    label="Half Kelly"
                                    shares={result.half_kelly_shares}
                                    capital={result.half_kelly_capital}
                                    pctPortfolio={result.half_kelly_pct}
                                    maxLoss={result.half_kelly_shares * result.risk_per_share}
                                    currencySymbol={currencySymbol}
                                />
                                <SizingRow
                                    label="Fixed 2% Risk"
                                    shares={result.fixed_2pct_shares}
                                    capital={result.fixed_2pct_capital}
                                    pctPortfolio={result.fixed_2pct_capital > 0 ? (result.fixed_2pct_capital / parseFloat(form.portfolio_value) * 100) : null}
                                    maxLoss={result.fixed_2pct_shares * result.risk_per_share}
                                    currencySymbol={currencySymbol}
                                />
                                <SizingRow
                                    label="Fixed 1% Risk"
                                    shares={result.fixed_1pct_shares}
                                    capital={result.fixed_1pct_capital}
                                    pctPortfolio={result.fixed_1pct_capital > 0 ? (result.fixed_1pct_capital / parseFloat(form.portfolio_value) * 100) : null}
                                    maxLoss={result.fixed_1pct_shares * result.risk_per_share}
                                    currencySymbol={currencySymbol}
                                />
                                <SizingRow
                                    label="Full Kelly (aggressive)"
                                    shares={result.full_kelly_shares}
                                    capital={result.full_kelly_capital}
                                    pctPortfolio={result.full_kelly_pct}
                                    maxLoss={result.full_kelly_shares * result.risk_per_share}
                                    currencySymbol={currencySymbol}
                                />
                            </tbody>
                        </table>
                    </div>

                    {/* Notes */}
                    {result.notes?.length > 0 && (
                        <div className="space-y-2">
                            {result.notes.map((note, i) => {
                                const isPositive = note.includes('Strong expected') || note.includes('good mathematical');
                                const isWarning  = note.includes('Negative Kelly') || note.includes('Do not trade') || note.includes('below 1.5');
                                return (
                                    <div key={i} className={`flex items-start gap-2 p-2.5 rounded-lg text-xs ${
                                        isWarning  ? 'bg-red-500/10 border border-red-500/20 text-red-400' :
                                        isPositive ? 'bg-green-500/10 border border-green-500/20 text-green-400' :
                                                     'bg-yellow-500/10 border border-yellow-500/20 text-yellow-400'
                                    }`}>
                                        {isWarning  ? <AlertTriangle size={13} className="mt-0.5 shrink-0" /> :
                                         isPositive ? <CheckCircle size={13} className="mt-0.5 shrink-0" /> :
                                                      <Info size={13} className="mt-0.5 shrink-0" />}
                                        {note}
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

// ─── Modal Wrapper ────────────────────────────────────────────────────────────

export function PositionSizerModal({ isOpen, onClose, prefill = {} }) {
    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
            <div className="relative z-10 w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-xl border border-border bg-card shadow-2xl">
                <div className="sticky top-0 flex items-center justify-between px-5 py-4 border-b border-border bg-card z-10">
                    <div className="flex items-center gap-2">
                        <Calculator size={18} className="text-primary" />
                        <h2 className="text-base font-bold">Position Sizer</h2>
                        <span className="text-xs text-muted-foreground">Kelly Criterion + Fixed Risk</span>
                    </div>
                    <button onClick={onClose} className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors">
                        <X size={16} />
                    </button>
                </div>
                <div className="p-5">
                    <PositionSizer prefill={prefill} onClose={onClose} />
                </div>
            </div>
        </div>
    );
}

// ─── Standalone Panel Export ──────────────────────────────────────────────────

export default function PositionSizerPanel() {
    return (
        <div className="space-y-4 max-w-screen-lg">
            <div className="flex items-center gap-2">
                <Calculator size={20} className="text-primary" />
                <h2 className="text-lg font-bold text-foreground">Position Sizer</h2>
                <span className="text-xs text-muted-foreground">Kelly Criterion + Fixed Risk Rules</span>
            </div>
            <p className="text-sm text-muted-foreground">
                Enter your trade setup to get the optimal position size. We compute Kelly Criterion and fixed risk rules, then recommend the conservative minimum to protect your capital.
            </p>
            <div className="rounded-xl border border-border bg-card p-5">
                <PositionSizer />
            </div>
        </div>
    );
}
