type LoadingStateProps = {
  label?: string;
};

export function LoadingState({ label = "Loading market information..." }: LoadingStateProps) {
  return (
    <main className="mx-auto flex min-h-screen max-w-7xl items-center justify-center px-6 py-12">
      <div className="panel px-8 py-8 text-center">
        <p className="metric-label">Loading</p>
        <p className="mt-3 text-lg text-slate-700">{label}</p>
      </div>
    </main>
  );
}
