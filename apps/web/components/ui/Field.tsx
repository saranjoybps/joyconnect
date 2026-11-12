import { forwardRef, type InputHTMLAttributes, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

const BASE =
  "w-full rounded-xl border border-m-line-strong bg-m-panel px-3 text-[13px] text-m-text placeholder:text-m-muted transition-colors duration-150 hover:border-m-muted focus-visible:border-m-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-m-accent/25 disabled:opacity-50 aria-[invalid=true]:border-m-bad";

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
    <label htmlFor={htmlFor} className="mb-1.5 block text-[13px] font-medium">
      {children}
      {hint && <span className="ml-1 font-normal text-m-muted">{hint}</span>}
    </label>
  );
}
