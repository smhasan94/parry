import { UserButton } from "@clerk/clerk-react";
import { Eye } from "lucide-react";
import { useRole } from "@/hooks/useRole";

interface HeaderProps {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}

export function Header({ title, description, actions }: HeaderProps) {
  const { role } = useRole();
  return (
    <header className="flex h-14 items-center justify-between border-b border-border px-6">
      <div>
        <h1 className="text-lg font-semibold">{title}</h1>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </div>
      <div className="flex items-center gap-4">
        {role === "viewer" && (
          <span
            className="inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground"
            title="You have read-only access. Contact an admin to make changes."
          >
            <Eye className="h-3 w-3" />
            Read-only
          </span>
        )}
        {actions}
        <UserButton afterSignOutUrl="/" />
      </div>
    </header>
  );
}
