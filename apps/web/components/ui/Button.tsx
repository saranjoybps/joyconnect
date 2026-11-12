import { forwardRef, type ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

// Pill buttons. Primary is solid near-black (white in dark mode).
const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-m-ink text-m-ink-fg hover:opacity-90",
  secondary: "border border-m-line-strong bg-m-panel text-m-text hover:bg-m-soft",
  ghost: "text-m-muted hover:bg-m-soft hover:text-m-text",
  danger: "border border-m-bad/40 bg-m-panel text-m-bad hover:bg-m-bad/10",
};
const SIZE: Record<ButtonSize, string> = {
  sm: "h-7 px-3 text-xs",
  md: "h-9 px-4 text-[13px]",
  lg: "h-10 px-5 text-sm",
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", className = "", type = "button", ...rest }, ref,
) {
  return (
    <button ref={ref} type={type} {...rest}
      className={`inline-flex shrink-0 items-center justify-center gap-2 rounded-full font-medium transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50 ${VARIANT[variant]} ${SIZE[size]} ${className}`} />
  );
});

/** Icon-only button: `label` is required so it always has an accessible name. */
export const IconButton = forwardRef<HTMLButtonElement, Omit<ButtonProps, "children" | "size"> & { label: string; children: React.ReactNode }>(
  function IconButton({ label, children, variant = "ghost", className = "", type = "button", ...rest }, ref) {
    return (
      <button ref={ref} type={type} aria-label={label} title={label} {...rest}
        className={`inline-flex size-8 shrink-0 items-center justify-center rounded-full transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50 ${VARIANT[variant]} ${className}`}>
        {children}
      </button>
    );
  },
);
