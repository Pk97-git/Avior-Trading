import React, { useEffect, useState } from 'react';
import { ingestionApi } from '../api';
import { Loader2, Activity, CheckCircle2, XCircle, Clock } from 'lucide-react';

export default function LiveJobsView() {
    const [jobs, setJobs] = useState([]);
    const [history, setHistory] = useState([]);
    const [loading, setLoading] = useState(true);

    // Poll for active jobs
    useEffect(() => {
        let interval;
        const fetchJobs = async () => {
            try {
                const res = await ingestionApi.getLiveJobs();
                setJobs(res.data.active_jobs || []);
                setHistory(res.data.job_history || []);
            } catch (err) {
                console.error("Failed to fetch jobs:", err);
            } finally {
                setLoading(false);
            }
        };

        fetchJobs();
        interval = setInterval(fetchJobs, 5000); // Check every 5s

        return () => clearInterval(interval);
    }, []);

    if (loading) {
        return (
            <div className="flex -mt-20 items-center justify-center h-full min-h-[500px] text-muted-foreground w-full">
                <Loader2 className="animate-spin mr-2 h-5 w-5" /> Checking server jobs...
            </div>
        );
    }

    if (jobs.length === 0 && history.length === 0) {
        return (
            <div className="flex flex-col -mt-20 items-center justify-center h-full min-h-[500px] text-muted-foreground w-full">
                <Activity className="h-10 w-10 text-muted-foreground/30 mb-4" />
                <h3 className="font-medium text-foreground">No Background Jobs</h3>
                <p className="text-sm mt-1">Both the historical backfiller and the daily catch-up data pipelines are currently idle, and no log history was found.</p>
            </div>
        );
    }

    return (
        <div className="space-y-6 animate-in fade-in duration-500 max-w-4xl">
            <div className="flex items-center justify-between mb-8">
                <div>
                    <h2 className="text-2xl font-semibold tracking-tight">Active Background Jobs</h2>
                    <p className="text-sm text-muted-foreground mt-1">Live streaming terminal progress from the backend Python ingestion pipelines.</p>
                </div>
            </div>

            <div className="space-y-4">
                {jobs.length === 0 && (
                    <div className="p-4 rounded-lg border border-dashed border-border bg-card/50 text-center text-muted-foreground text-sm flex items-center justify-center gap-2">
                        <Activity className="h-4 w-4" />
                        No jobs currently running
                    </div>
                )}

                {jobs.map((job, idx) => (
                    <div key={idx} className="rounded-lg border border-primary/30 bg-primary/5 shadow-sm p-6 overflow-hidden">
                        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
                            <div className="space-y-2">
                                <div className="font-semibold text-lg flex items-center gap-2 text-primary">
                                    <Loader2 className="h-5 w-5 animate-spin" />
                                    {job.name}
                                    <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-600 text-xs font-bold tracking-wider uppercase ml-2">
                                        {job.status}
                                    </span>
                                </div>
                                <div className="text-sm text-muted-foreground">{job.progress_text}</div>
                            </div>
                            {job.progress_pct !== null && (
                                <div className="w-full md:w-96 p-4 rounded-md border border-border bg-card">
                                    <div className="flex justify-between text-xs font-medium mb-2">
                                        <span>Overall Progress</span>
                                        <span className="text-primary">{job.progress_pct}%</span>
                                    </div>
                                    <div className="h-2 rounded-full bg-muted overflow-hidden">
                                        <div
                                            className="h-full bg-primary transition-all duration-1000 origin-left"
                                            style={{ width: `${job.progress_pct}%` }}
                                        />
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                ))}
            </div>

            {/* Completed Job History section */}
            {history.length > 0 && (
                <div className="pt-8 mt-12 border-t border-border">
                    <h3 className="text-lg font-semibold tracking-tight mb-6 flex items-center gap-2">
                        <Clock className="h-5 w-5 text-muted-foreground" />
                        Completed Job History
                    </h3>
                    <div className="space-y-3">
                        {history.map((h, idx) => (
                            <div key={idx} className="flex flex-col sm:flex-row sm:items-center justify-between p-4 rounded-md border border-border bg-card hover:bg-muted/30 transition-colors">
                                <div className="space-y-1 w-full">
                                    <div className="flex items-center gap-2">
                                        {h.status === "COMPLETED" ? (
                                            <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                                        ) : (
                                            <XCircle className="h-4 w-4 text-destructive shrink-0" />
                                        )}
                                        <span className="font-medium text-sm text-foreground">{h.job_name}</span>
                                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ml-2 
                                            ${h.status === 'COMPLETED' ? 'bg-emerald-500/10 text-emerald-600' : 'bg-destructive/10 text-destructive'}
                                        `}>
                                            {h.status}
                                        </span>
                                        <span className="text-xs text-muted-foreground ml-auto whitespace-nowrap hidden sm:inline-block font-mono">
                                            {h.ended_at}
                                        </span>
                                    </div>
                                    <div className="text-xs text-muted-foreground pl-6 font-mono leading-relaxed mt-1">
                                        {h.summary}
                                    </div>
                                </div>

                                <span className="text-xs text-muted-foreground sm:hidden font-mono mt-2 pl-6">
                                    {h.ended_at}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}
