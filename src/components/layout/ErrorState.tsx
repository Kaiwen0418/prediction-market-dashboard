type ErrorStateProps = {
  title?: string;
  detail: string;
};

export function ErrorState({ title = "Market data unavailable", detail }: ErrorStateProps) {
  return (
    <main className="mx-auto flex min-h-screen max-w-7xl items-center justify-center px-6 py-12">
      <div className="panel max-w-2xl px-8 py-8 text-center">
        <p className="metric-label">Service notice</p>
        <h1 className="mt-3 text-2xl font-semibold text-slate-900">{title}</h1>
        <p className="mt-3 text-base leading-7 text-slate-600">{detail}</p>
      </div>
    </main>
  );
}
