import React, { useEffect, useState, useCallback } from 'react';
import { agentsApi } from '../api';
import { Loader2, RefreshCw, CheckCircle2, XCircle, Clock, Database, Key, Bell } from 'lucide-react';

function StatusDot({ ok }) {
    return ok
        ? <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
        : <XCircle className="h-4 w-4 text-red-400 shrink-0" />;
}

function fmt(n) {
    if (n == null) return '—';
    return Number(n).toLocaleString();
}

function fmtDate(d) {
    if (!d) return 'Never';
    try { return new Date(d).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }); }
    catch { return String(d); }
}

export default function Settings() {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await agentsApi.getSystemStatus();
            setData(res.data);
        } catch (e) {
            setError(e?.response?.data?.detail || 'Failed to load system status.');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    if (loading) return (
        <div className="flex items-center justify-center h-64 text-muted-foreground gap-2">
            <Loader2 className="animate-spin h-5 w-5" /> Loading system status…
        </div>
    );

    if (error) return (
        <div className="flex flex-col items-center justify-center h-64 gap-2 text-red-400">
            <p>{error}</p>
            <button onClick={load} className="text-sm text-muted-foreground underline">Retry</button>
        </div>
    );

    const apiKeys   = data?.api_keys || {};
    const counts    = data?.table_counts || {};
    const lastRuns  = data?.last_runs || {};
    const universe  = data?.universe_breakdown || {};

    const API_KEY_LABELS = {
        groq:      'Groq (LLM thesis + sentiment)',
        anthropic: 'Anthropic (Vision agent)',
        openai:    'OpenAI (optional fallback)',
        gemini:    'Gemini (optional fallback)',
        fred:      'FRED (macro data)',
    };

    const TABLE_LABELS = {
        stocks:              'Stock universe',
        stock_prices:        'OHLCV price rows',
        company_financials:  'Financial statements',
        macro_data:          'Macro indicators',
        news_sentiment:      'News sentiment records',
        institutional_flows: 'Institutional flow records',
        promoter_holdings:   'Promoter holding records',
        ai_analysis:         'AI analysis records',
        alerts:              'Alerts generated',
        watchlist:           'Watchlist entries',
    };

    return (
        <div className="space-y-6 max-w-4xl">

            {/* ── Header ── */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-xl font-bold">System Settings & Status</h2>
                    <p className="text-sm text-muted-foreground">API key health, data coverage, last run times</p>
                </div>
                <button
                    onClick={load}
                    className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground px-3 py-1.5 rounded-md border border-border hover:bg-accent transition-colors"
                >
                    <RefreshCw className="h-4 w-4" /> Refresh
                </button>
            </div>

            {/* ── API Keys ── */}
            <div className="rounded-xl border border-border bg-card/50 p-5">
                <h3 className="font-semibold text-sm mb-4 flex items-center gap-2">
                    <Key className="h-4 w-4 text-muted-foreground" /> API Key Status
                </h3>
                <div className="space-y-2.5">
                    {Object.entries(API_KEY_LABELS).map(([key, label]) => (
                        <div key={key} className="flex items-center justify-between text-sm">
                            <div className="flex items-center gap-2">
                                <StatusDot ok={apiKeys[key]} />
                                <span className="font-medium">{label}</span>
                            </div>
                            <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                                apiKeys[key]
                                    ? 'bg-emerald-500/10 text-emerald-400'
                                    : 'bg-muted text-muted-foreground'
                            }`}>
                                {apiKeys[key] ? 'Configured' : 'Not set'}
                            </span>
                        </div>
                    ))}
                </div>
                <p className="text-xs text-muted-foreground mt-4 bg-muted/20 p-3 rounded-lg">
                    Set API keys via environment variables: <code className="font-mono bg-background px-1 rounded">GROQ_API_KEY</code>,{' '}
                    <code className="font-mono bg-background px-1 rounded">ANTHROPIC_API_KEY</code>,{' '}
                    <code className="font-mono bg-background px-1 rounded">FRED_API_KEY</code>.
                    Without Groq, the system falls back to rule-based sentiment scoring.
                    Without Anthropic, the Vision agent returns a neutral score of 50.
                </p>
            </div>

            {/* ── Last Run Times ── */}
            <div className="rounded-xl border border-border bg-card/50 p-5">
                <h3 className="font-semibold text-sm mb-4 flex items-center gap-2">
                    <Clock className="h-4 w-4 text-muted-foreground" /> Last Run Times
                </h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {[
                        { label: 'Last AI Analysis', key: 'last_analysis' },
                        { label: 'Last Alert Generated', key: 'last_alert' },
                        { label: 'Last Price Update', key: 'last_price_update' },
                        { label: 'Last Macro Update', key: 'last_macro_update' },
                    ].map(({ label, key }) => (
                        <div key={key} className="bg-muted/20 rounded-lg p-3">
                            <p className="text-xs text-muted-foreground">{label}</p>
                            <p className={`text-sm font-semibold mt-0.5 ${lastRuns[key] ? 'text-foreground' : 'text-muted-foreground/50'}`}>
                                {fmtDate(lastRuns[key])}
                            </p>
                        </div>
                    ))}
                </div>
            </div>

            {/* ── Universe + DB Counts ── */}
            <div className="rounded-xl border border-border bg-card/50 p-5">
                <h3 className="font-semibold text-sm mb-4 flex items-center gap-2">
                    <Database className="h-4 w-4 text-muted-foreground" /> Database Coverage
                </h3>

                {/* Universe breakdown */}
                {Object.keys(universe).length > 0 && (
                    <div className="flex gap-3 mb-4 flex-wrap">
                        {Object.entries(universe).map(([country, n]) => (
                            <div key={country} className={`rounded-lg px-4 py-2 text-center border ${
                                country === 'IN' ? 'bg-orange-500/10 border-orange-500/20' : 'bg-blue-500/10 border-blue-500/20'
                            }`}>
                                <p className={`text-lg font-bold ${country === 'IN' ? 'text-orange-400' : 'text-blue-400'}`}>
                                    {fmt(n)}
                                </p>
                                <p className="text-xs text-muted-foreground">{country} stocks</p>
                            </div>
                        ))}
                    </div>
                )}

                {/* Table row counts */}
                <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-border text-muted-foreground text-xs">
                                <th className="text-left py-2 font-medium">Table</th>
                                <th className="text-right py-2 font-medium">Row Count</th>
                                <th className="text-right py-2 font-medium">Status</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border/30">
                            {Object.entries(TABLE_LABELS).map(([key, label]) => {
                                const count = counts[key];
                                const hasData = count != null && count > 0;
                                return (
                                    <tr key={key} className="hover:bg-muted/10">
                                        <td className="py-2 text-sm">{label}</td>
                                        <td className="py-2 text-right tabular-nums font-mono text-xs">
                                            {fmt(count)}
                                        </td>
                                        <td className="py-2 text-right">
                                            <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-semibold ${
                                                hasData
                                                    ? 'bg-emerald-500/10 text-emerald-400'
                                                    : 'bg-muted text-muted-foreground/60'
                                            }`}>
                                                {hasData ? 'Has data' : 'Empty'}
                                            </span>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* ── Notification Configuration ── */}
            <div className="rounded-xl border border-border bg-card/50 p-5">
                <h3 className="font-semibold text-sm mb-4 flex items-center gap-2">
                    <Bell className="h-4 w-4 text-muted-foreground" /> Notification Configuration
                </h3>
                <div className="space-y-2.5 mb-4">
                    <div className="flex items-center justify-between text-sm">
                        <div className="flex items-center gap-2">
                            <StatusDot ok={data?.notification_channels?.slack} />
                            <span className="font-medium">Slack</span>
                        </div>
                        <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                            data?.notification_channels?.slack
                                ? 'bg-emerald-500/10 text-emerald-400'
                                : 'bg-muted text-muted-foreground'
                        }`}>
                            {data?.notification_channels?.slack ? 'Configured' : 'Not set'}
                        </span>
                    </div>
                    <div className="flex items-center justify-between text-sm">
                        <div className="flex items-center gap-2">
                            <StatusDot ok={data?.notification_channels?.email} />
                            <span className="font-medium">Email (SMTP)</span>
                        </div>
                        <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                            data?.notification_channels?.email
                                ? 'bg-emerald-500/10 text-emerald-400'
                                : 'bg-muted text-muted-foreground'
                        }`}>
                            {data?.notification_channels?.email ? 'Configured' : 'Not set'}
                        </span>
                    </div>
                </div>
                <div className="text-xs text-muted-foreground mt-4 bg-muted/20 p-3 rounded-lg space-y-1">
                    <p className="mb-2">Set these environment variables to enable notifications:</p>
                    <div><code className="font-mono bg-background px-1 rounded">SLACK_WEBHOOK_URL</code> — Slack incoming webhook URL</div>
                    <div><code className="font-mono bg-background px-1 rounded">ALERT_EMAIL_TO</code> — recipient email address</div>
                    <div><code className="font-mono bg-background px-1 rounded">SMTP_HOST</code> / <code className="font-mono bg-background px-1 rounded">SMTP_PORT</code> / <code className="font-mono bg-background px-1 rounded">SMTP_USER</code> / <code className="font-mono bg-background px-1 rounded">SMTP_PASS</code> — SMTP server config</div>
                </div>
            </div>

            {/* ── Scheduled Jobs Info ── */}
            <div className="rounded-xl border border-border bg-card/50 p-5">
                <h3 className="font-semibold text-sm mb-4">Scheduled Jobs (UTC)</h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs text-muted-foreground">
                    {[
                        ['Intraday prices', '6:30, 8:00, 14:00, 17:30, 20:30 (weekdays)'],
                        ['India EOD',       '10:45 weekdays (45 min after NSE close)'],
                        ['US EOD',          '21:00 weekdays (30 min after NYSE close)'],
                        ['Nightly gap fill','00:00 daily (auto-backfills data gaps)'],
                        ['Daily ingest',    '22:00 weekdays (macro, sentiment, institutional)'],
                        ['Agent scoring',   '23:00 weekdays (full universe batch scoring)'],
                        ['Swing screener',  '00:30 weekdays (proactive swing setups)'],
                        ['Weekly refresh',  'Sunday 02:00 (fundamentals, macro, SEC 13F)'],
                        ['Walk-forward',    'Sunday 03:00 (signal accuracy backtesting)'],
                        ['Monthly 13F',     '1st of month 03:00 (13F, promoter holdings)'],
                    ].map(([job, schedule]) => (
                        <div key={job} className="flex justify-between bg-muted/20 rounded px-3 py-2 gap-2">
                            <span className="font-medium text-foreground/80">{job}</span>
                            <span className="text-right">{schedule}</span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
