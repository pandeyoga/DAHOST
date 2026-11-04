import * as React from "react"
import * as TabsPrimitive from "@radix-ui/react-tabs"

import { cn } from "@/lib/utils"

const Tabs = TabsPrimitive.Root

/**
 * PANDUAN_UI G4 (2026-11-04): Tabs di DALAM tab hub tidak boleh tampil sebagai baris tab kedua.
 * HubTabs memasang konteks ini; TabsList/TabsTrigger di dalamnya tampil sebagai pil penyaring
 * (sama dengan FilterChips) dan className bawaan pemanggil diabaikan supaya gayanya seragam.
 */
export const NestedTabsContext = React.createContext(false)
export const CHIP_CLASS = "inline-flex h-8 items-center justify-center gap-1.5 whitespace-nowrap rounded-full border border-[var(--glass-border)] bg-[var(--card-surface)] px-3 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
export const CHIP_ACTIVE_CLASS = "border-transparent bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] hover:text-[hsl(var(--primary))]"

const TabsList = React.forwardRef(({ className, ...props }, ref) => {
  const nested = React.useContext(NestedTabsContext)
  return (
    <TabsPrimitive.List
      ref={ref}
      className={nested
        ? "inline-flex flex-wrap items-center gap-1.5"
        : cn("inline-flex h-9 items-center justify-center rounded-lg bg-muted p-1 text-muted-foreground", className)}
      {...props} />
  )
})
TabsList.displayName = TabsPrimitive.List.displayName

const TabsTrigger = React.forwardRef(({ className, ...props }, ref) => {
  const nested = React.useContext(NestedTabsContext)
  return (
    <TabsPrimitive.Trigger
      ref={ref}
      className={nested
        ? cn(CHIP_CLASS, "data-[state=active]:border-transparent data-[state=active]:bg-[hsl(var(--primary)/0.12)] data-[state=active]:text-[hsl(var(--primary))]")
        : cn(
          "inline-flex items-center justify-center whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow",
          className
        )}
      {...props} />
  )
})
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName

const TabsContent = React.forwardRef(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
      className
    )}
    {...props} />
))
TabsContent.displayName = TabsPrimitive.Content.displayName

export { Tabs, TabsList, TabsTrigger, TabsContent }
