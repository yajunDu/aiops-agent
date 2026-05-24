import { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface StatCardProps {
  label: string;
  value: string | number;
  unit?: string;
  trend?: string;
  trendDirection?: "up" | "down" | "stable";
  icon: LucideIcon;
  variant?: "default" | "success" | "warning" | "danger";
}

export default function StatCard({
  label, value, unit, trend, trendDirection, icon: Icon, variant = "default"
}: StatCardProps) {
  const variantStyles = {
    default: "border-zinc-200 bg-white",
    success: "border-emerald-200 bg-emerald-50/40",
    warning: "border-amber-200 bg-amber-50/40",
    danger: "border-red-200 bg-red-50/40",
  };
  const iconBgs = {
    default: "bg-blue-50 text-blue-600",
    success: "bg-emerald-50 text-emerald-600",
    warning: "bg-amber-50 text-amber-600",
    danger: "bg-red-50 text-red-600",
  };

  return (
    <div className={cn(
      "rounded-lg border p-4 transition-all hover:shadow-sm",
      variantStyles[variant]
    )}>
      <div className="flex items-start justify-between mb-3">
        <div className={cn("p-2 rounded-md", iconBgs[variant])}>
          <Icon className="w-4 h-4" strokeWidth={2.2} />
        </div>
        {trend && (
          <span className={cn(
            "text-xs font-mono px-1.5 py-0.5 rounded font-medium",
            trendDirection === "down" ? "text-emerald-700 bg-emerald-100" :
            trendDirection === "up" ? "text-red-700 bg-red-100" :
            "text-zinc-600 bg-zinc-100"
          )}>
            {trend}
          </span>
        )}
      </div>
      <p className="text-xs text-zinc-500 mb-1">{label}</p>
      <div className="flex items-baseline gap-1">
        <p className="text-2xl font-bold text-zinc-900 font-mono">{value}</p>
        {unit && <span className="text-sm text-zinc-500">{unit}</span>}
      </div>
    </div>
  );
}
