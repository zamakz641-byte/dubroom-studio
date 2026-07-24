import * as React from "react";
import { cn } from "@/lib/utils";

export function Slider({
  className,
  value,
  onValueChange,
  min = 0,
  max = 100
}: {
  className?: string;
  value: number[];
  onValueChange: (value: number[]) => void;
  min?: number;
  max?: number;
}) {
  return (
    <input
      className={cn("w-full accent-primary", className)}
      max={max}
      min={min}
      type="range"
      value={value[0] ?? min}
      onChange={(event) => onValueChange([Number(event.target.value)])}
    />
  );
}

