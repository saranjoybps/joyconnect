import { forwardRef, type InputHTMLAttributes, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

const BASE =
  "w-full rounded-xl border border-line-strong bg-field px-3 text-sm text-foreground placeholder:text-muted transition-colors duration-150 hover:border-muted focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/30 disabled:opacity-50 aria-[invalid=true]:border-bad";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className = "", ...rest }, ref,
) {
  return <input ref={ref} {...rest} className={`h-9 ${BASE} ${className}`} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className = "", ...rest }, ref,
) {
  return <textarea ref={ref} {...rest} className={`py-2 ${BASE} ${className}`} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className = "", ...rest }, ref,
) {
  return <select ref={ref} {...rest} className={`h-9 ${BASE} ${className}`} />;
});

export function Label({ htmlFor, children, hint }: { htmlFor: string; children: React.ReactNode; hint?: string }) {
  return (
    <label htmlFor={htmlFor} className="mb-1.5 block text-sm font-medium">
      {children}
      {hint && <span className="ml-1 font-normal text-muted">{hint}</span>}
    </label>
  );
}
