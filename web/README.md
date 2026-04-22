# Research Harness — Web Dashboard

Next.js 16 / React 19 front end for the Research Harness FastAPI backend. Browse topics, papers, projects, artifacts, and provenance stats; trigger ingestion, gap detection, claim extraction, outline generation, and section drafting via the dashboard.

## Prerequisites

- Node 20+ (or 22+) and `npm`
- Running Research Harness HTTP API (default `http://localhost:8000`)

Start the backend first:

```bash
# From the repo root
pip install -e "packages/research_harness_mcp[api]"
python -m research_harness_mcp.http_api
```

## Development

```bash
cd web
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Configuration

```bash
# Override the API base URL (defaults to http://localhost:8000)
export NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Production build

```bash
npm run build
npm run start
```

## Project structure

```
src/
├── app/                  <- Next.js App Router pages
│   ├── page.tsx          <- Dashboard home
│   ├── library/          <- Paper library
│   └── projects/         <- Projects list + detail
├── components/
│   ├── ui/               <- shadcn/ui primitives
│   ├── layout/           <- sidebar, etc.
│   └── project/          <- Analysis, paper search, action toolbar
└── lib/
    ├── api.ts            <- Typed fetchers for the FastAPI backend
    └── types.ts          <- Shared response types
```

## License

Same as the monorepo — [PolyForm Noncommercial 1.0.0](../LICENSE).
