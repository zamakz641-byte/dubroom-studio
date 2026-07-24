import { useEffect } from "react";

const regions =
  ".page,.onboarding-stage,.stage-content,.engine-drawer,.notification-feed,.activity-feed,.profile-creator,.voice-profile-panel,.engine-variant-panel,.engine-variant-list,.rvc-model-list,.import-hub main";

function canScroll(node: HTMLElement, delta: number) {
  if (node.scrollHeight <= node.clientHeight + 1) return false;
  return delta > 0
    ? node.scrollTop + node.clientHeight < node.scrollHeight - 1
    : node.scrollTop > 1;
}

function scrollRegionFrom(target: HTMLElement | null, delta: number) {
  let node: HTMLElement | null = target;
  while (node && node !== document.body) {
    const style = getComputedStyle(node);
    if (/auto|scroll/.test(style.overflowY) && canScroll(node, delta))
      return node;
    node = node.parentElement;
  }
  const candidates = [
    ...(document.querySelectorAll(regions) as NodeListOf<HTMLElement>),
  ];
  return (
    candidates.find(
      (candidate) =>
        candidate.offsetParent !== null && canScroll(candidate, delta),
    ) || null
  );
}

export function ScrollBridge() {
  useEffect(() => {
    const onWheel = (event: WheelEvent) => {
      if (event.ctrlKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("select,input[type=range]")) return;
      if (
        target?.closest('[data-testid="timeline-scroll"]') &&
        Math.abs(event.deltaX) > Math.abs(event.deltaY)
      )
        return;
      const rawDelta =
        Math.abs(event.deltaY) >= Math.abs(event.deltaX)
          ? event.deltaY
          : event.deltaX;
      if (Math.abs(rawDelta) < 0.1) return;
      const probe = rawDelta > 0 ? 1 : -1;
      const region = scrollRegionFrom(target, probe);
      if (!region) return;
      const factor =
        event.deltaMode === WheelEvent.DOM_DELTA_LINE
          ? 20
          : event.deltaMode === WheelEvent.DOM_DELTA_PAGE
            ? region.clientHeight
            : 1;
      const delta = rawDelta * factor;
      const before = region.scrollTop;
      region.scrollTop = Math.max(
        0,
        Math.min(region.scrollHeight - region.clientHeight, before + delta),
      );
      if (Math.abs(region.scrollTop - before) < 0.1) return;
      event.preventDefault();
    };
    const onKey = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented ||
        event.ctrlKey ||
        event.metaKey ||
        event.altKey
      )
        return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input,textarea,select,[contenteditable=true]"))
        return;
      const amount =
        event.key === "PageDown"
          ? window.innerHeight * 0.75
          : event.key === "PageUp"
            ? -window.innerHeight * 0.75
            : event.key === "ArrowDown"
              ? 72
              : event.key === "ArrowUp"
                ? -72
                : event.key === " "
                  ? event.shiftKey
                    ? -window.innerHeight * 0.75
                    : window.innerHeight * 0.75
                  : 0;
      if (!amount) return;
      const region = scrollRegionFrom(target, amount > 0 ? 1 : -1);
      if (!region) return;
      const before = region.scrollTop;
      region.scrollTop = Math.max(
        0,
        Math.min(region.scrollHeight - region.clientHeight, before + amount),
      );
      if (Math.abs(region.scrollTop - before) < 0.1) return;
      event.preventDefault();
    };
    window.addEventListener("wheel", onWheel, {
      capture: true,
      passive: false,
    });
    window.addEventListener("keydown", onKey, { capture: true });
    return () => {
      window.removeEventListener("wheel", onWheel, { capture: true });
      window.removeEventListener("keydown", onKey, { capture: true });
    };
  }, []);
  return null;
}
