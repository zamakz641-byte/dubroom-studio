export function PageHeader({
  kicker,
  title,
  description,
  actions,
}: {
  kicker: string;
  title: string;
  description: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="flex min-h-24 items-end justify-between gap-8 border-b border-line px-8 py-5 max-[1100px]:items-center max-[1100px]:gap-4 max-[1100px]:px-5">
      <div className="min-w-0 flex-1">
        <span className="ui-kicker">{kicker}</span>
        <div className="mt-1 flex min-w-0 flex-wrap items-baseline gap-x-4 gap-y-1">
          <h1 className="shrink-0 whitespace-nowrap text-[26px] font-semibold leading-tight tracking-[-0.025em] text-foreground">
            {title}
          </h1>
          <p className="min-w-60 max-w-3xl flex-1 text-[12px] leading-5 text-copy">
            {description}
          </p>
        </div>
      </div>
      {actions && (
        <div className="flex shrink-0 items-center gap-2">{actions}</div>
      )}
    </header>
  );
}
