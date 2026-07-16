# apps/web

Next.js frontend for Nexus — dashboard, unified search, multi-provider chat,
Today/Goals, handoff composer, sources & keys settings.

Stack: Next.js (App Router) · React · Tailwind CSS v4 · shadcn/ui.

## Development

```bash
npm install
npm run dev        # http://localhost:3000
```

## Checks

```bash
npm run lint          # ESLint
npm run typecheck     # tsc --noEmit
npm run format:check  # Prettier (format with `npm run format`)
npm run build         # production build
```

shadcn/ui components live in `src/components/ui/` (generated — excluded from
Prettier). Add more with `npx shadcn@latest add <component>`.
