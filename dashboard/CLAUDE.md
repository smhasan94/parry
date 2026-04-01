# Dashboard — React frontend

## Stack specifics
- React 18 + TypeScript strict mode
- Tailwind CSS (no custom CSS files — utility classes only)
- shadcn/ui for components (import from `@/components/ui/`)
- TanStack Query v5 for all server state
- TanStack Router for routing (file-based routes in `src/routes/`)
- Zustand for client-only state (auth, UI state)
- Recharts for charts (agent activity, detection trends)
- Clerk React SDK for auth (`useAuth`, `useOrganization`)

## Component conventions
- Functional components with TypeScript, no class components
- Props interfaces defined inline above the component: `interface Props { ... }`
- `export default` for page components, named exports for shared components
- Co-locate component-specific hooks in same file if under ~50 lines, else `hooks/` folder

## Data fetching
- All API calls go through `src/lib/api.ts` — never `fetch()` directly in components
- Use TanStack Query hooks — `useQuery`, `useMutation`, `useInfiniteQuery`
- Query keys: `['agents', orgId]`, `['events', agentId, filters]`, `['incidents', orgId]`
- Optimistic updates for policy changes

## Key pages
- `/dashboard` — org overview, agent grid, live event feed
- `/agents/:agentId` — per-agent detail: timeline, baseline, incidents
- `/incidents` — incident list with severity filter
- `/policies` — policy editor (what tools/domains each agent can use)
- `/settings` — org settings, API keys, billing (Stripe portal link)

## Real-time
- Agent event feed uses SSE (Server-Sent Events), not WebSockets
- Hook: `useAgentEventStream(agentId)` in `src/hooks/useEventStream.ts`

## Run commands
```bash
npm run dev       # :5173
npm run build
npm run lint
npm test
```
