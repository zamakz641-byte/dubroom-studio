import * as React from "react";
import { cn } from "@/lib/utils";

export function Switch({
  checked,
  className,
  onCheckedChange
}: {
  checked: boolean;
  className?: string;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <button
      aria-checked={checked}
      className={cn(
        "relative h-5 w-9 rounded-full bg-muted transition-colors data-[checked=true]:bg-primary",
        className
      )}
      data-checked={checked}
      role="switch"
      type="button"
      onClick={() => onCheckedChange(!checked)}
    >
      <span
        className={cn(
          "absolute left-0.5 top-0.5 size-4 rounded-full bg-background shadow transition-transform",
          checked && "translate-x-4"
        )}
      />
    </button>
  );
}

