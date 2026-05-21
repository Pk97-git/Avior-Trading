import React, { useEffect, useState, useCallback } from 'react';
import {
    Bell, Mail, MessageCircle, CheckCircle2, XCircle, Loader2,
    Send, Eye, ChevronDown, ChevronUp, Info,
} from 'lucide-react';
import { notificationsApi } from '../api';

function Toggle({ checked, onChange, disabled }) {
    return (
        <button
            onClick={() => !disabled && onChange(!checked)}
            disabled={disabled}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors
                ${checked ? 'bg-sky-500' : 'bg-slate-700'}
                ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
        >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform
                ${checked ? 'translate-x-6' : 'translate-x-1'}`} />
        </button>
    );
}

function Field({ label, hint, children }) {
    return (
        <div className="space-y-1">
            <label className="text-xs font-medium text-slate-400 uppercase tracking-wide">{label}</label>
            {children}
            {hint && <p className="text-xs text-slate-600">{hint}</p>}
        </div>
    );
}

function StatusBadge({ status }) {
    if (!status) return null;
    const map = {
        sent:           { color: 'text-emerald-400', icon: <CheckCircle2 className="h-4 w-4" />, label: 'Sent!' },
        partial:        { color: 'text-yellow-400',  icon: <CheckCircle2 className="h-4 w-4" />, label: 'Partial delivery' },
        no_channels:    { color: 'text-red-400',     icon: <XCircle className="h-4 w-4" />,      label: 'No channels configured' },
        no_opportunity: { color: 'text-slate-400',   icon: <Info className="h-4 w-4" />,         label: 'No trade found today — run trade scan first' },
        error:          { color: 'text-red-400',     icon: <XCircle className="h-4 w-4" />,      label: 'Error — check console' },
    };
    const s = map[status] || map.error;
    return (
        <span className={`flex items-center gap-1.5 text-sm ${s.color}`}>
            {s.icon} {s.label}
        </span>
    );
}

export default function NotificationSettings() {
    const [prefs, setPrefs]       = useState(null);
    const [smtpOk, setSmtpOk]     = useState(false);
    const [loading, setLoading]   = useState(true);
    const [saving, setSaving]     = useState(false);
    const [testing, setTesting]   = useState(false);
    const [testStatus, setTestStatus] = useState(null);
    const [preview, setPreview]   = useState(null);
    const [showPreview, setShowPreview] = useState(false);
    const [error, setError]       = useState(null);
    const [tgExpanded, setTgExpanded] = useState(false);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const res = await notificationsApi.getPreferences();
            setPrefs(res.data.prefs);
            setSmtpOk(res.data.smtp_configured);
        } catch (e) {
            setError('Failed to load notification settings.');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const save = async () => {
        if (!prefs) return;
        setSaving(true);
        try {
            await notificationsApi.savePreferences(prefs);
        } catch (e) {
            setError(e?.response?.data?.detail || 'Save failed.');
        } finally {
            setSaving(false);
        }
    };

    const sendTest = async () => {
        setTesting(true);
        setTestStatus(null);
        // Save first
        try { await notificationsApi.savePreferences(prefs); } catch {}
        try {
            const res = await notificationsApi.sendTest();
            setTestStatus(res.data.status);
        } catch (e) {
            const detail = e?.response?.data?.detail || '';
            if (detail.includes('No qualifying trade')) setTestStatus('no_opportunity');
            else if (detail.includes('No channels'))    setTestStatus('no_channels');
            else setTestStatus('error');
        } finally {
            setTesting(false);
        }
    };

    const loadPreview = async () => {
        try {
            const res = await notificationsApi.preview();
            setPreview(res.data);
            setShowPreview(true);
        } catch (e) {
            const detail = e?.response?.data?.detail || 'No trade found.';
            setError(detail);
        }
    };

    if (loading) return (
        <div className="flex items-center gap-2 text-slate-400 p-6">
            <Loader2 className="animate-spin h-4 w-4" /> Loading notification settings…
        </div>
    );

    if (!prefs) return (
        <div className="text-red-400 p-6">{error || 'Could not load settings.'}</div>
    );

    const update = (key, val) => setPrefs(p => ({ ...p, [key]: val }));

    return (
        <div className="space-y-5 max-w-lg">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <Bell className="h-5 w-5 text-sky-400" />
                    <h3 className="font-semibold text-slate-100">Morning Brief</h3>
                    <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded-full">
                        7:00 AM IST · Mon–Fri
                    </span>
                </div>
                <Toggle checked={prefs.enabled} onChange={v => update('enabled', v)} />
            </div>

            <p className="text-sm text-slate-400 leading-relaxed">
                Every weekday morning you'll receive the <strong className="text-slate-200">#1 trade idea</strong> with
                entry price, stop loss, target, and the reasoning behind it — so your only job is to say yes or no.
            </p>

            {/* Minimum score */}
            <div className="bg-slate-800/60 rounded-xl p-4 space-y-3">
                <Field
                    label="Minimum Score"
                    hint={`Only notify when the top trade scores ≥ ${prefs.min_score}/100. Raise to get fewer, higher-conviction alerts.`}
                >
                    <div className="flex items-center gap-3">
                        <input
                            type="range" min={50} max={90} step={5}
                            value={prefs.min_score}
                            onChange={e => update('min_score', parseInt(e.target.value))}
                            className="flex-1 accent-sky-500"
                        />
                        <span className="text-sky-400 font-bold w-12 text-right">{prefs.min_score}/100</span>
                    </div>
                </Field>
            </div>

            {/* Email */}
            <div className="bg-slate-800/60 rounded-xl p-4 space-y-3">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <Mail className="h-4 w-4 text-slate-400" />
                        <span className="text-sm font-medium text-slate-200">Email</span>
                        {!smtpOk && (
                            <span className="text-xs text-yellow-500 bg-yellow-500/10 px-2 py-0.5 rounded-full">
                                SMTP not configured
                            </span>
                        )}
                    </div>
                    <Toggle
                        checked={prefs.email_enabled}
                        onChange={v => update('email_enabled', v)}
                        disabled={!smtpOk}
                    />
                </div>

                {prefs.email_enabled && (
                    <Field label="Email Address" hint="Where to send the morning brief.">
                        <input
                            type="email"
                            value={prefs.email_address || ''}
                            onChange={e => update('email_address', e.target.value)}
                            placeholder="you@example.com"
                            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2
                                       text-sm text-slate-100 placeholder-slate-600 focus:outline-none
                                       focus:border-sky-500"
                        />
                    </Field>
                )}

                {!smtpOk && (
                    <p className="text-xs text-slate-600">
                        Set <code className="text-sky-600">SMTP_HOST</code>,{' '}
                        <code className="text-sky-600">SMTP_USER</code>, and{' '}
                        <code className="text-sky-600">SMTP_PASS</code> in your{' '}
                        <code className="text-sky-600">.env</code> file to enable email.
                    </p>
                )}
            </div>

            {/* Telegram */}
            <div className="bg-slate-800/60 rounded-xl p-4 space-y-3">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <MessageCircle className="h-4 w-4 text-slate-400" />
                        <span className="text-sm font-medium text-slate-200">Telegram</span>
                        <span className="text-xs text-emerald-500 bg-emerald-500/10 px-2 py-0.5 rounded-full">
                            Recommended
                        </span>
                    </div>
                    <Toggle
                        checked={prefs.telegram_enabled}
                        onChange={v => { update('telegram_enabled', v); if (v) setTgExpanded(true); }}
                    />
                </div>

                {prefs.telegram_enabled && (
                    <div className="space-y-3">
                        <Field label="Bot Token" hint="From @BotFather on Telegram.">
                            <input
                                type="password"
                                value={prefs.telegram_bot_token || ''}
                                onChange={e => update('telegram_bot_token', e.target.value)}
                                placeholder="110201543:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
                                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2
                                           text-sm text-slate-100 placeholder-slate-600 focus:outline-none
                                           focus:border-sky-500 font-mono"
                            />
                        </Field>
                        <Field label="Chat ID" hint="Your personal chat ID (use @userinfobot to find it).">
                            <input
                                type="text"
                                value={prefs.telegram_chat_id || ''}
                                onChange={e => update('telegram_chat_id', e.target.value)}
                                placeholder="123456789"
                                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2
                                           text-sm text-slate-100 placeholder-slate-600 focus:outline-none
                                           focus:border-sky-500"
                            />
                        </Field>

                        <button
                            onClick={() => setTgExpanded(x => !x)}
                            className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300"
                        >
                            {tgExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                            How to set up Telegram in 60 seconds
                        </button>

                        {tgExpanded && (
                            <ol className="text-xs text-slate-500 space-y-1 list-decimal list-inside
                                           bg-slate-900/60 rounded-lg p-3">
                                <li>Open Telegram, search <strong className="text-slate-300">@BotFather</strong></li>
                                <li>Send <code className="text-sky-500">/newbot</code> → give it any name</li>
                                <li>Copy the <strong className="text-slate-300">token</strong> BotFather gives you</li>
                                <li>Search <strong className="text-slate-300">@userinfobot</strong>, send any message → copy your ID</li>
                                <li>Paste both above and click Save + Test</li>
                            </ol>
                        )}
                    </div>
                )}
            </div>

            {/* Actions */}
            <div className="flex items-center gap-3 flex-wrap">
                <button
                    onClick={save}
                    disabled={saving}
                    className="flex items-center gap-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-50
                               text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
                >
                    {saving ? <Loader2 className="animate-spin h-4 w-4" /> : null}
                    Save Settings
                </button>

                <button
                    onClick={sendTest}
                    disabled={testing || (!prefs.email_enabled && !prefs.telegram_enabled)}
                    className="flex items-center gap-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-40
                               text-slate-200 text-sm font-medium px-4 py-2 rounded-lg transition-colors"
                >
                    {testing ? <Loader2 className="animate-spin h-4 w-4" /> : <Send className="h-4 w-4" />}
                    Send Test Now
                </button>

                <button
                    onClick={loadPreview}
                    className="flex items-center gap-2 text-slate-400 hover:text-slate-200
                               text-sm px-3 py-2 rounded-lg transition-colors"
                >
                    <Eye className="h-4 w-4" /> Preview
                </button>

                {testStatus && <StatusBadge status={testStatus} />}
            </div>

            {error && (
                <p className="text-xs text-red-400 bg-red-400/10 rounded-lg px-3 py-2">{error}</p>
            )}

            {/* Preview panel */}
            {showPreview && preview && (
                <div className="bg-slate-900 border border-slate-700 rounded-xl p-4 space-y-3">
                    <div className="flex items-center justify-between">
                        <span className="text-xs font-medium text-slate-400 uppercase tracking-wide">
                            Preview — {preview.brief?.ticker}
                        </span>
                        <button onClick={() => setShowPreview(false)}
                            className="text-slate-600 hover:text-slate-400 text-xs">
                            Close
                        </button>
                    </div>
                    <pre className="text-xs text-slate-300 whitespace-pre-wrap font-mono leading-relaxed
                                    bg-slate-950 rounded-lg p-3 overflow-auto max-h-72">
                        {preview.plain_text}
                    </pre>
                </div>
            )}
        </div>
    );
}
