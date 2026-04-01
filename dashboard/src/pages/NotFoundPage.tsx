import { Link } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { Shield } from "lucide-react";

export function NotFoundPage() {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center space-y-4">
        <Shield className="mx-auto h-12 w-12 text-muted-foreground" />
        <h1 className="text-4xl font-bold">404</h1>
        <p className="text-sm text-muted-foreground">Page not found.</p>
        <Link to="/dashboard">
          <Button variant="outline">Back to Dashboard</Button>
        </Link>
      </div>
    </div>
  );
}
