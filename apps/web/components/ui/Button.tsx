import { forwardRef, type ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "btn-gradient",
  secondary: "border border-line-strong bg-field text-foreground backdrop-blur hover:bg-surface-2",
  ghost: "text-foreground hover:bg-surface-2",
  danger: "border border-bad/50 bg-field text-bad hover:bg-bad/10",
};
const SIZE: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-xs",
  md: "h-9 px-4 text-sm",
  lg: "h-11 px-5 text-sm",
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
      className={`inline-flex shrink-0 items-center justify-center gap-2 rounded-xl font-medium transition-[background-color,opacity] duration-150 disabled:pointer-events-none disabled:opacity-50 ${VARIANT[variant]} ${SIZE[size]} ${className}`} />
  );
});

/** Icon-only button: `label` is required so it always has an accessible name. */
export const IconButton = forwardRef<HTMLButtonElement, Omit<ButtonProps, "children" | "size"> & { label: string; children: React.ReactNode }>(
  function IconButton({ label, children, variant = "ghost", className = "", type = "button", ...rest }, ref) {
    return (
      <button ref={ref} type={type} aria-label={label} title={label} {...rest}
        className={`inline-flex size-8 shrink-0 items-center justify-center rounded-lg transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50 ${VARIANT[variant]} ${className}`}>
        {children}
      </button>
    );
  },
);
