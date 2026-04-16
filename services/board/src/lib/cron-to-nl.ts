/**
 * Convert common cron expressions to human-readable English.
 * Covers the 80% case; returns raw expression for anything else.
 */
export function cronToHuman(cron: string): string {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return cron
  const [minute, hour, dom, month, dow] = parts

  if (cron === "* * * * *") return "every minute"

  const everyNMin = minute.match(/^\*\/(\d+)$/)
  if (everyNMin && hour === "*" && dom === "*" && month === "*" && dow === "*") {
    return `every ${everyNMin[1]} minutes`
  }

  // daily at HH:MM
  if (/^\d+$/.test(minute) && /^\d+$/.test(hour) && dom === "*" && month === "*" && dow === "*") {
    const hh = hour.padStart(2, "0")
    const mm = minute.padStart(2, "0")
    return `every day at ${hh}:${mm} UTC`
  }

  // weekdays at HH:MM
  if (/^\d+$/.test(minute) && /^\d+$/.test(hour) && dom === "*" && month === "*" && dow === "1-5") {
    return `every weekday at ${hour.padStart(2, "0")}:${minute.padStart(2, "0")} UTC`
  }

  // hourly at :MM
  if (/^\d+$/.test(minute) && hour === "*" && dom === "*" && month === "*" && dow === "*") {
    return `every hour at :${minute.padStart(2, "0")}`
  }

  return cron
}
