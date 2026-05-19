import React, { useState } from 'react';
import { LayoutDashboard, Database, Activity, Settings, Globe, Zap, Bell, Award } from 'lucide-react';
import IngestionDashboard from './components/IngestionDashboard';
import StockUniverse from './components/StockUniverse';
import Dashboard from './components/Dashboard';
import MarketAnalysis from './components/MarketAnalysis';
import IntelligenceHub from './components/IntelligenceHub';
import Compounders from './components/Compounders';
import LiveJobsView from './components/LiveJobsView';

const TABS = [
    { id: 'dashboard', label: 'Executive Dashboard', icon: LayoutDashboard },
    { id: 'hub', label: 'Intelligence Hub', icon: Zap },
    { id: 'market', label: 'Market Analysis', icon: Activity },
    { id: 'compounders', label: 'Compounders', icon: Award },
    { id: 'data', label: 'Data Ingestion', icon: Database },
    { id: 'jobs', label: 'Active Jobs', icon: Activity }, // New Tab
    { id: 'universe', label: 'Stock Universe', icon: Globe },
];

const TAB_LABELS = Object.fromEntries(TABS.map(t => [t.id, t.label]));

function NavItem({ icon: Icon, label, active, onClick }) {
    return (
        <button
            onClick={onClick}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors ${active
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                }`}
        >
            <Icon size={18} />
            <span>{label}</span>
        </button>
    );
}

export default function App() {
    // tab + optional sub-state (e.g. pre-filled ticker for Hub)
    const [activeTab, setActiveTab] = useState('dashboard');
    const [hubTicker, setHubTicker] = useState(null);

    // Allow child components to navigate to a tab, optionally passing extra data
    const handleNavigate = (tab, extra = null) => {
        if (tab === 'hub' && extra) setHubTicker(extra);
        setActiveTab(tab);
    };

    return (
        <div className="flex h-screen bg-background text-foreground font-sans">

            {/* ── Sidebar ── */}
            <aside className="w-56 border-r border-border bg-card/50 backdrop-blur-sm p-4 hidden md:flex flex-col shrink-0">
                <div className="mb-8 px-2 flex items-center gap-2">
                    <Activity className="h-5 w-5 text-primary" />
                    <h1 className="text-lg font-bold tracking-tight">OmniTrader AI</h1>
                </div>

                <nav className="space-y-1 flex-1">
                    {TABS.filter(t => t.id !== 'settings').map(tab => (
                        <NavItem
                            key={tab.id}
                            icon={tab.icon}
                            label={tab.label}
                            active={activeTab === tab.id}
                            onClick={() => handleNavigate(tab.id)}
                        />
                    ))}
                </nav>

                <div className="mt-auto">
                    <NavItem
                        icon={Settings}
                        label="Settings"
                        active={activeTab === 'settings'}
                        onClick={() => handleNavigate('settings')}
                    />
                </div>
            </aside>

            {/* ── Main ── */}
            <main className="flex-1 overflow-auto min-w-0">
                <header className="h-14 border-b border-border flex items-center px-6 bg-card/50 backdrop-blur-sm sticky top-0 z-10">
                    <h2 className="text-base font-semibold">
                        {TAB_LABELS[activeTab] || 'Settings'}
                    </h2>
                </header>

                <div className="p-6">
                    {activeTab === 'dashboard' && (
                        <Dashboard onNavigate={handleNavigate} />
                    )}
                    {activeTab === 'hub' && (
                        <IntelligenceHub
                            key={hubTicker}           // re-mount when ticker changes
                            initialTicker={hubTicker}
                        />
                    )}
                    {activeTab === 'market' && (
                        <MarketAnalysis />
                    )}
                    {activeTab === 'compounders' && (
                        <Compounders />
                    )}
                    {activeTab === 'data' && (
                        <IngestionDashboard onNavigate={handleNavigate} />
                    )}
                    {activeTab === 'jobs' && (
                        <LiveJobsView />
                    )}
                    {activeTab === 'universe' && (
                        <StockUniverse onNavigate={handleNavigate} />
                    )}
                    {activeTab === 'settings' && (
                        <div className="flex items-center justify-center h-64 text-muted-foreground border border-dashed border-border rounded-lg text-sm">
                            Settings — coming soon
                        </div>
                    )}
                </div>
            </main>
        </div>
    );
}
