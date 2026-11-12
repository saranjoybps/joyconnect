import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement>;
const base = (p: P) => ({
  width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 1.75, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true, ...p,
});

export const PlusIcon = (p: P) => <svg {...base(p)}><path d="M12 5v14M5 12h14" /></svg>;
export const ChatIcon = (p: P) => <svg {...base(p)}><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z" /></svg>;
export const PlugIcon = (p: P) => <svg {...base(p)}><path d="M9 2v6M15 2v6M6 8h12v3a6 6 0 0 1-12 0V8ZM12 17v5" /></svg>;
export const FlowIcon = (p: P) => <svg {...base(p)}><rect x="3" y="3" width="6" height="6" rx="1" /><rect x="15" y="15" width="6" height="6" rx="1" /><path d="M9 6h4a2 2 0 0 1 2 2v7" /></svg>;
export const PlayIcon = (p: P) => <svg {...base(p)}><path d="M6 4l14 8-14 8V4Z" /></svg>;
export const BrainIcon = (p: P) => <svg {...base(p)}><path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V4a3 3 0 0 0-3 0ZM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1" /></svg>;
export const GearIcon = (p: P) => <svg {...base(p)}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" /></svg>;
export const SunIcon = (p: P) => <svg {...base(p)}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>;
export const MoonIcon = (p: P) => <svg {...base(p)}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" /></svg>;
export const SidebarIcon = (p: P) => <svg {...base(p)}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></svg>;
export const MenuIcon = (p: P) => <svg {...base(p)}><path d="M4 6h16M4 12h16M4 18h16" /></svg>;
export const SearchIcon = (p: P) => <svg {...base(p)}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>;
export const SendIcon = (p: P) => <svg {...base(p)}><path d="M12 19V5M5 12l7-7 7 7" /></svg>;
export const StopIcon = (p: P) => <svg {...base(p)} fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>;
export const CopyIcon = (p: P) => <svg {...base(p)}><rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h8" /></svg>;
export const CheckIcon = (p: P) => <svg {...base(p)}><path d="m5 12 5 5L20 7" /></svg>;
export const RefreshIcon = (p: P) => <svg {...base(p)}><path d="M20 11a8 8 0 0 0-14-4L4 9M4 4v5h5M4 13a8 8 0 0 0 14 4l2-2M20 20v-5h-5" /></svg>;
export const PencilIcon = (p: P) => <svg {...base(p)}><path d="M4 20h4L19 9l-4-4L4 16v4ZM14 6l4 4" /></svg>;
export const TrashIcon = (p: P) => <svg {...base(p)}><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></svg>;
export const ChevronIcon = (p: P) => <svg {...base(p)}><path d="m9 6 6 6-6 6" /></svg>;
export const ExternalIcon = (p: P) => <svg {...base(p)}><path d="M14 4h6v6M20 4 10 14M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></svg>;
export const CloseIcon = (p: P) => <svg {...base(p)}><path d="M6 6l12 12M18 6 6 18" /></svg>;
export const SparkIcon = (p: P) => <svg {...base(p)}><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3ZM19 16l.7 1.8L21.5 18.5l-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7L19 16Z" /></svg>;
export const LogoMark = (p: P) => <svg {...base({ width: 20, height: 20, ...p })}><circle cx="7" cy="12" r="3.5" /><circle cx="17" cy="12" r="3.5" /><path d="M10.5 12h3" /></svg>;
