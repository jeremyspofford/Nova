interface BadgeProps {
  type: "status" | "priority" | "risk" | "label"
  value: string
}

export function Badge({ type, value }: BadgeProps) {
  return (
    <span className={`badge badge--${type} badge--${value.replace(/_/g, "-")}`}>
      {value}
    </span>
  )
}
