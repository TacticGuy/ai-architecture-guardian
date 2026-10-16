import { Moon, Sun } from "lucide-react";
import { Link } from "react-router-dom";

import { Logo } from "@/components/Logo";
import { cn } from "@/lib/utils";
import { useTheme } from "@/lib/theme";

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  // Two 28px cells inside a 3px padding: the 28px knob sits exactly on the active icon's cell.
  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      onClick={toggle}
      className={cn(
        "relative grid h-9 w-16 shrink-0 grid-cols-2 items-center justify-items-center rounded-full border border-border bg-muted p-[3px] transition-colors hover:border-foreground/30 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        className,
      )}
    >
      <span
        className={cn(
          "absolute left-[3px] top-[3px] size-7 rounded-full bg-background shadow-sm ring-1 ring-border transition-transform duration-300 ease-out",
          dark && "translate-x-7",
        )}
      />
      <Sun className={cn("relative z-10 size-3.5 transition-colors", dark ? "text-muted-foreground" : "text-foreground")} />
      <Moon className={cn("relative z-10 size-3.5 transition-colors", dark ? "text-foreground" : "text-muted-foreground")} />
    </button>
  );
}

export function NavBar({ links }: { links?: { label: string; href: string }[] }) {
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link to="/" className="flex items-center gap-3 font-display text-sm font-bold uppercase tracking-tight sm:text-lg" aria-label="AI Architecture Guardian home">
          <Logo className="size-9 shrink-0 rounded-lg ring-1 ring-border sm:size-10" />
          <span className="leading-none">AI Architecture Guardian</span>
        </Link>
        <nav className="flex items-center gap-1 sm:gap-2">
          {links?.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="hidden rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:text-foreground md:block"
            >
              {link.label}
            </a>
          ))}
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}
